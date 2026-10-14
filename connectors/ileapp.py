"""Phone data through iLEAPP (github.com/abrignoni/iLEAPP, MIT license), the open-source iOS artifact parser
maintained by the forensics community, plus an adapter from its output to our records.

    python3 connectors/ileapp.py              # run iLEAPP on the latest Finder backup, then import its results
    python3 connectors/ileapp.py --skip-run   # re-import the last run
    python3 connectors/ileapp.py --install    # (re)install iLEAPP's packages from the bundled wheels

Why: ~450 modules covering iOS versions and apps beyond this phone, with bugs reported and fixed upstream.
What we add: a profile that leaves out secrets and modules the corpus doesn't need (EXCLUDE_MODULES), our own
modules for apps it misses (connectors/ileapp_modules/, in iLEAPP's format so they can go upstream), and this
adapter. Upstream bugs and gaps we've hit are tracked in connectors/ILEAPP.md.

Offline: iLEAPP comes with the app (connectors/vendor/iLEAPP, the pinned release minus its tests and the modules
we never run) and so do its packages (connectors/vendor/ileapp-wheels). Installing makes a virtualenv from those
with pip --no-index: nothing is downloaded, ever. vendor/update_ileapp.sh rebuilds both, deliberately.

Run: iLEAPP reads our decrypted mirror (iphone_backup.py), not the encrypted backup: build_view() lays the
mirror out as hard links in the phone's own layout (private/var/mobile/..., the mapping iLEAPP's iTunes reader
uses) and iLEAPP runs with -t fs on that view. Its own iTunes decryption cuts files to the manifest's Size,
which truncates databases that grew during the backup (see iphone_backup.py); reading the mirror avoids that,
avoids decrypting 18 GB twice, and keeps the backup password away from iLEAPP's command line and logs. It writes
to ~/Library/Application Support/q1_user_model/ileapp/<backup>/ (outside iCloud). Only the LAVA database
(_lava_artifacts.db, one table per artifact) and _lava_data.lava (per-artifact metadata: category, column types,
chat column roles) are kept; iLEAPP's copies of extracted files and media, and its HTML/TSV/timeline reports
(~20 GB for this phone), are deleted. The backup password is never passed to this process.

Import: one source per iLEAPP module, named phone_<module>. Tables with a "conversation" data view become
messages (thread, text, direction, sender, time and media come from the columns the module declares); every
other table becomes dated records whose text is the row's fields. Media references resolve to files in our
decrypted mirror (corpus/raw/iphone/files), not to iLEAPP's copies. Modules our own parsers cover better
(OWNED: iMessage, calls, Health, contacts), secrets, other people's data and stores with nothing about the person
are left out (PRIVATE_*, OTHER_PEOPLE_NAMES, NO_INFO_CATEGORIES); everything else is imported, phone internals
tagged meta.tier = "device". Every left-out artifact is listed with its reason in manifest.json _ileapp_left_out.
"""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import iphone_backup
import os
import plistlib

from common import CORPUS, HOME, IPHONE, MANIFEST, NORM, Writer

ILEAPP_VERSION = "v2026.4.4"  # the vendored release; bump with vendor/update_ileapp.sh and re-check ILEAPP.md
VENDOR = Path(__file__).resolve().parent / "vendor"
ILEAPP = VENDOR / "iLEAPP"
WHEELS = VENDOR / "ileapp-wheels"
REQUIREMENTS = VENDOR / "ileapp-requirements.txt"
BASE = HOME / "Library/Application Support/q1_user_model"
TOOLS = BASE / "tools"
VENV_PY = TOOLS / f"ileapp-venv-{ILEAPP_VERSION}/bin/python"
OUT = BASE / "ileapp"
CUSTOM = Path(__file__).resolve().parent / "ileapp_modules"
MIN_FREE = 15e9  # iLEAPP's working files for this backup peaked near 10 GB (vendored copy, 2026-10-12)

# Left out of every run: Ph* = Photos.sqlite analysis (slow, memory-heavy, killed the first run; the Mac's
# photos connector reads the same iCloud library), keychain = saved passwords, imeiImsi = SIM identifiers.
# Not even run: keychain, SIM identifiers, and appCookies (it parses every app's cookie values into iLEAPP's own
# database, which is kept next to the import; they are live sessions, not data about the person).
EXCLUDE_MODULES = r"^(Ph\d|keychain$|imeiImsi$|appCookies$)"
# Covered by our own parsers, which merge the Mac's copy (imessage.py, calls.py, contacts.py) or clean the
# data (health.py: duplicate samples, glitches, non-Watch sleep). Health achievements have no equivalent.
OWNED = {"sms", "SMSmissingROWIDs", "callHistory", "callHistoryGroupCall", "callHistoryTransactions",
         "addressBook"}
OWNED_NAMES = r"^Health - (?!Achievements)|^interactionC Call History"
# What stays out. Only three reasons: privacy/security, other people's data, nothing about the person at all.
PRIVATE_CATEGORIES = {"Cookies", "SIM Info", "Cellular"}
# voice-triggers: Siri voice samples (voice biometrics). Left out for good: they aren't needed (decided 2026-10-09).
PRIVATE_NAMES = r"secure store|token|password|credential|cookie|subscriber|voice-triggers"
OTHER_PEOPLE_NAMES = r"^Bluetooth Other LE|cached images"  # strangers' devices nearby; other people's posts
NO_INFO_CATEGORIES = {"Control Center", "React Native", "Mobile Backup Plist", "Realm"}
# Kept but tagged meta.tier = "device": phone internals that still say something about the person (Wi-Fi networks
# with dates, paired devices, alarms, home screen, app use, files, shares, recovered app records).
DEVICE_CATEGORIES = {"WiFi Connections", "Bluetooth", "Clock", "CarPlay", "iOS Screens", "Home Screen",
                     "App Permissions", "Device Usage", "Device Information", "OS Updates", "Files App", "Cloudkit",
                     "MMKV", "Database Metadata", "AI Provenance", "Images", "Identifiers", "Accounts", "IOS Build",
                     "Installed Apps", "Location"}
DEVICE_NAMES = r"metric|application state|network observ|preferences|^LSC - |account$|accounts$|profiles?$"
# Fields that never leave the LAVA database, whatever the artifact (account data, app preferences).
SECRET_FIELDS = (r"token|secret|password|passcode|cookie|(^|[\W_])auth([\W_]|$)|authorization|session.?(id|key|token)|"
                 r"api.?key|credential|private.?key")
# The phone's Photos.sqlite is the same iCloud library as the Mac's; import it only when the Mac's isn't there.
DUPLICATE_OF = {"Photos": "photos"}
KINDS = [(r"conversation", "message"), (r"InteractionC", "interaction"), (r"^Notes$", "note"), (r"Calendar (Events|Birthdays)", "event"),
         (r"^Reminders", "reminder"), (r"Safari Browser - History$", "visit"),
         (r"Search|Searches", "search"), (r"^Voice Memos", "voice_memo"), (r"App Usage|Recent App", "app_usage"),
         (r"Contacts|Users|Blocked", "contact"), (r"Transactions|Expenses|Balances", "transaction"),
         (r"Trips|Boarding|PNR|Booking", "trip"), (r"Tabs|Bookmarks|Playback|Continue Watching|Titles", "media")]
ID_COLUMNS = r"(^|_)(guid|uuid|message_id|expense_id|visit_id|transaction_id|id)$"
# Chat views for message artifacts that don't declare one (column names as stored in LAVA).
CONVERSATIONS = {
    "weChatMessages": {"conversationDiscriminatorColumn": "chat_partner", "conversationLabelColumn": "chat_partner_name",
                       "textColumn": "message", "directionColumn": "direction_as_stored", "directionSentValue": "0",
                       "timeColumn": "sent", "typeColumn": "type_as_stored"},
}
# WeChat message types (MM.sqlite Type); WCDB compresses newer bodies with zstd and a dictionary iLEAPP doesn't
# apply, so those keep only their type label.
WECHAT_TYPES = {"1": "text", "3": "image", "34": "voice message", "42": "contact card", "43": "video",
                "47": "sticker", "48": "location", "49": "link/file/mini-program", "50": "call", "62": "short video",
                "10000": "system message", "10002": "recalled message"}
# Exact duplicate rows are collapsed (iLEAPP joins can repeat a row, e.g. Airbnb ~3x), except where the module
# exposes no message id and distinct messages can look identical (WhatsApp photo bursts in the same second).
KEEP_DUPLICATES = {"whatsAppMessages"}
# Rows that aren't the user's: Venmo's cached public and friends feeds are other people's payments.
# Venmo's cached users are everyone who appeared in any feed; keep friends and requests (people the user paid are
# named in their own transactions).
SKIP_ROWS = {"venmo_transactions": lambda r, f: (f or "").rsplit("/", 1)[-1] in ("PublicFeed", "FriendsFeed"),
             "venmo_users": lambda r, f: not str(r.get("friend_status") or "").startswith(("friend", "request"))}
EARLIEST = 946684800  # 2000-01-01: earlier record times are zero or unit errors
# Modules whose datetimes come out scaled wrong (tracked in ILEAPP.md): multiply before converting.
TIME_SCALE = {"uberClient": 1000}  # 1692981 = 2023-08-25 in kiloseconds
VOLATILE = r"read|delivered|count|status|updated|last_|modified"
PATH_COLUMNS = r"source_file|source_path|local_path|storage_folder"

# iLEAPP's virtual paths for backup domains (scripts/search_files.py `domains`), reversed.
ROOTS = [("private/var/mobile/Containers/Data/Application/", "AppDomain-"),
         ("private/var/mobile/Containers/Shared/AppGroup/", "AppDomainGroup-"),
         ("private/var/mobile/Containers/Data/PluginKitPlugin/", "AppDomainPlugin-"),
         ("private/var/containers/Data/System/", "SysContainerDomain-"),
         ("private/var/containers/Shared/SystemGroup/", "SysSharedContainerDomain-")]
MOBILE = ("HomeDomain", "MediaDomain", "CameraRollDomain", "HealthDomain", "KeyboardDomain", "HomeKitDomain",
          "TonesDomain")
FIXED = {"private/var/db/": "DatabaseDomain", "private/var/installd/": "InstallDomain",
         "private/var/Managed Preferences/": "ManagedPreferencesDomain", "private/var/MobileDevice/": "MobileDeviceDomain",
         "private/var/networkd/": "NetworkDomain", "private/var/protected/": "ProtectedDomain",
         "private/var/root/": "RootDomain", "private/var/preferences/": "SystemPreferencesDomain",
         "private/var/wireless/": "WirelessDomain"}


# ---------------------------------------------------------------------------------------------- running

def install():
    """A virtualenv with iLEAPP's packages, from the wheels that come with the app: --no-index, so pip never looks
    online. Wheels are built for one Python (vendor/update_ileapp.sh); another one is told so, not served a download."""
    if not (ILEAPP / "ileapp.py").exists():
        sys.exit(f"[ileapp] the bundled iLEAPP is missing ({ILEAPP})")
    TOOLS.mkdir(parents=True, exist_ok=True)
    if not VENV_PY.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV_PY.parent.parent)], check=True)
    r = subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--no-index", "--find-links", str(WHEELS),
                        "-r", str(REQUIREMENTS)], capture_output=True, text=True,
                       env={**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    if r.returncode:
        shutil.rmtree(VENV_PY.parent.parent, ignore_errors=True)
        sys.exit(f"[ileapp] iLEAPP's bundled packages don't fit Python {sys.version_info.major}.{sys.version_info.minor} "
                 f"on this Mac: {(r.stderr.strip().splitlines() or ['pip failed'])[-1]}")


def installed_version():
    return ILEAPP_VERSION


def write_profile(path):
    """Every plugin of the installed iLEAPP (and our custom modules) except EXCLUDE_MODULES, so plugins added in
    newer iLEAPP versions are picked up without editing a list."""
    script = ("import sys, re, json; sys.path.insert(0, '.'); from pathlib import Path\n"
              "from scripts.plugin_loader import PluginLoader\n"
              "paths = [Path('scripts/artifacts')] + [Path(p) for p in sys.argv[3:]]\n"
              "names = [p.name for p in PluginLoader(paths).plugins if not re.match(sys.argv[2], p.module_name)]\n"
              "json.dump({'leapp': 'ileapp', 'format_version': 1, 'plugins': names}, open(sys.argv[1], 'w'))\n"
              "print(len(names))")
    extra = [str(CUSTOM)] if any(CUSTOM.glob("*.py")) else []
    r = subprocess.run([str(VENV_PY), "-c", script, str(path), EXCLUDE_MODULES, *extra], cwd=ILEAPP,
                       capture_output=True, text=True, check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return int(r.stdout.strip().splitlines()[-1])


def domain_root(domain):
    """Backup domain -> its directory on the phone, as iLEAPP names it."""
    for root, prefix in ROOTS:
        if domain.startswith(prefix):
            return root + domain[len(prefix):]
    if domain in MOBILE:
        return "private/var/mobile"
    return next((root.rstrip("/") for root, d in FIXED.items() if d == domain), None)


def build_view(view):
    """Hard-link every mirrored file into `view` at its on-phone path (no extra space; rebuilt each run because
    iphone_backup.py replaces files rather than rewriting them in place)."""
    shutil.rmtree(view, ignore_errors=True)
    n = 0
    for domain_dir in IPHONE.iterdir():
        root = domain_root(domain_dir.name)
        if not root:
            continue
        for dirpath, _, files in os.walk(domain_dir):
            rel = os.path.relpath(dirpath, domain_dir)
            target = view / root / rel
            target.mkdir(parents=True, exist_ok=True)
            for f in files:
                try:
                    os.link(os.path.join(dirpath, f), target / f)
                    n += 1
                except FileExistsError:
                    pass
    # iLEAPP learns the iOS version from LastBuildInfo.plist, which backups don't contain (in -t itunes mode it reads
    # the backup's Info.plist instead); without it, version-dependent modules fail on an empty version string.
    info = IPHONE.parent / "Info.plist"
    if info.exists():
        d = plistlib.loads(info.read_bytes())
        lb = view / "private/var/installd/Library/MobileInstallation/LastBuildInfo.plist"
        lb.parent.mkdir(parents=True, exist_ok=True)
        lb.write_bytes(plistlib.dumps({"ProductName": "iPhone OS", "ProductVersion": d.get("Product Version", ""),
                                       "ProductBuildVersion": d.get("Build Version", "")}))
    return n


def run(backup=None, force=False):
    if not (ILEAPP / "ileapp.py").exists() or not VENV_PY.exists():
        install()
    bk = iphone_backup.Backup(backup)
    free = shutil.disk_usage(BASE).free
    if free < MIN_FREE and not force:
        sys.exit(f"[ileapp] only {free / 1e9:.0f} GB free; iLEAPP needs ~{MIN_FREE / 1e9:.0f} GB while it runs "
                 f"(--force to try anyway)")
    dest = OUT / bk.dir.name
    work = dest / "run"
    shutil.rmtree(work, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    profile = dest / "corpus.ilprofile"
    n = write_profile(profile)
    view = IPHONE.parent / "ileapp_view"
    linked = build_view(view)
    print(f"[ileapp] iLEAPP {installed_version()}, {n} plugins, {linked:,} files from the mirror of {bk.describe()}")
    cmd = [str(VENV_PY), "-u", "ileapp.py", "-t", "fs", "-i", str(view), "-o", str(dest),
           "--custom_output_folder", "run", "-m", str(profile)]
    if any(CUSTOM.glob("*.py")):
        cmd += ["--custom_artifacts_path", str(CUSTOM)]
    t = time.time()
    p = subprocess.run(cmd, cwd=ILEAPP, capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    shutil.rmtree(view, ignore_errors=True)
    log = p.stdout + p.stderr
    failed = re.findall(r"^(\S+) \[(\S+)\] artifact failed", log, re.M)
    (dest / "ileapp.log").write_text(log)
    if p.returncode or "Processes completed" not in log:
        sys.exit(f"[ileapp] iLEAPP exited {p.returncode} after {time.time() - t:.0f}s; see {dest / 'ileapp.log'}")
    keep = dest / "latest"
    shutil.rmtree(keep, ignore_errors=True)
    keep.mkdir()
    for name in ("_lava_artifacts.db", "_lava_data.lava"):
        shutil.move(str(work / name), str(keep / name))
    shutil.rmtree(work)
    (keep / "run.json").write_text(json.dumps({
        "ileapp": installed_version(), "plugins": n, "backup": bk.dir.name, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seconds": round(time.time() - t), "failed_artifacts": [f"{m}/{a}" for a, m in failed]}, indent=1))
    print(f"[ileapp] done in {time.time() - t:.0f}s; {len(failed)} artifacts failed: "
          f"{', '.join(m for _, m in failed) or 'none'}")
    return keep


# ---------------------------------------------------------------------------------------------- importing

def mirror_path(virtual):
    """iLEAPP's path for a phone file -> repo-relative path of our decrypted copy, if present."""
    v = virtual[virtual.find("private/var/"):] if "private/var/" in virtual else virtual.lstrip("/")
    candidates = []
    for root, prefix in ROOTS:
        if v.startswith(root):
            bundle, _, rel = v[len(root):].partition("/")
            candidates = [(prefix + bundle, rel)]
    for root, domain in FIXED.items():
        if v.startswith(root):
            candidates = [(domain, v[len(root):])]
    if not candidates and v.startswith("private/var/mobile/"):
        candidates = [(d, v[len("private/var/mobile/"):]) for d in MOBILE]
    for domain, rel in candidates:
        f = IPHONE / domain / rel
        if f.exists():
            return str(f.relative_to(CORPUS.parent))
    return None


def kind_for(name, conversation):
    for pattern, kind in KINDS:
        if re.search(pattern, "conversation" if conversation else name):
            return kind
    return "record"


def left_out(category, artifact):
    """The reason an artifact isn't imported, or None."""
    name = artifact["name"]
    if artifact["module"] in OWNED or re.search(OWNED_NAMES, name):
        return "covered by our own parser"
    if category in PRIVATE_CATEGORIES or re.search(PRIVATE_NAMES, name, re.I):
        return "privacy or security"
    if re.search(OTHER_PEOPLE_NAMES, name, re.I):
        return "other people's data"
    if category in NO_INFO_CATEGORIES:
        return "nothing about the person"
    dup = DUPLICATE_OF.get(category)
    if dup and (NORM / f"{dup}.jsonl").exists() and (NORM / f"{dup}.jsonl").stat().st_size:
        return f"same data as the {dup} source"
    return None


def tier(category, name):
    return "device" if category in DEVICE_CATEGORIES or re.search(DEVICE_NAMES, name, re.I) else None


def iso(v, plausible=False):
    try:
        t = float(v)
    except (TypeError, ValueError):
        return None
    if plausible and t < EARLIEST:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    except (OverflowError, OSError, ValueError):
        return None


NESTED_SECRET = re.compile(r'(\\?"[^"\\]*(?:token|password|passcode|secret|cookie|api.?key|credential)[^"\\]*\\?"\s*:\s*)'
                           r'(\\?"[^"\\]*\\?"|[^,}\s]+)', re.I)


def text_value(v):
    """LAVA cells are text, numbers or blobs; blobs become text when they are UTF-8, else a size label. Values of
    secret-looking keys inside embedded JSON (recovered app records) are redacted."""
    if isinstance(v, bytes):
        try:
            v = v.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(v)} bytes>"
    if isinstance(v, str) and ":" in v:
        v = NESTED_SECRET.sub(lambda m: m.group(1) + '"[redacted]"', v)
    return v


def wechat_message(r, conv, nicknames):
    """(sender or None, text) for a WeChat row: group messages from others start with '<wxid>:\n'."""
    kind = WECHAT_TYPES.get(str(r.get(conv["typeColumn"])), f"type {r.get(conv['typeColumn'])}")
    body = r.get(conv["textColumn"])
    if isinstance(body, bytes):
        body = None if body[:4] == b"\x28\xb5\x2f\xfd" else text_value(body)  # zstd, see WECHAT_TYPES
    sender = None
    m = re.match(r"^([\w-]+):\n", body or "")
    if m and str(r.get(conv["conversationDiscriminatorColumn"], "")).endswith("@chatroom"):
        sender, body = nicknames.get(m.group(1), m.group(1)), body[m.end():]
    if kind != "text":
        return sender, f"[{kind}]"
    return sender, body or "[text, compressed]"


def write_module(module, artifacts, con, media, version, nicknames, names):
    """All artifacts (tables) of one iLEAPP module -> source phone_<module>."""
    avenue = (f"iPhone backup → iLEAPP {version} scripts/artifacts/{module}.py → LAVA database → "
              f"connectors/ileapp.py")
    with Writer(f"phone_{module.lower()}", avenue,
                parser=f"iLEAPP {version}:scripts/artifacts/{module}.py + connectors/ileapp.py:write_module") as w:
        w.notes = {"artifacts": {}, "implausible_times": 0}
        for category, a in artifacts:
            labels = dict(a["column_map"])
            types = {c["name"]: c["type"] for c in a.get("object_columns") or []}
            cols = [r[1] for r in con.execute(f'pragma table_info("{a["tablename"]}")')]
            conv = (a.get("data_views") or {}).get("conversation") or CONVERSATIONS.get(a["artifact_key"])
            kind = kind_for(a["name"], bool(conv))
            times = [c for c in cols if types.get(c) == "datetime"]
            rows = [dict(zip(cols, r)) for r in con.execute(f'select * from "{a["tablename"]}"')]
            if module in TIME_SCALE:
                for r in rows:
                    for c in times:
                        if isinstance(r[c], (int, float)) and 0 < r[c] < EARLIEST:
                            r[c] *= TIME_SCALE[module]
            id_col = next((c for c in cols if re.search(ID_COLUMNS, c) and
                           len({r[c] for r in rows}) == len(rows) and all(r[c] not in (None, "") for r in rows)), None)
            n, seen = 0, {}
            for r in rows:
                files = [m for c in cols if types.get(c) == "media" and r[c] for m in [media.get(r[c])] if m]
                fields, shown, source_file = {}, [], None
                for c in cols:
                    v, label = text_value(r[c]), labels.get(c, c)
                    if v in (None, "") or types.get(c) == "media" or re.search(SECRET_FIELDS, f"{c} {label}", re.I):
                        continue
                    if re.search(PATH_COLUMNS, c):
                        source_file = source_file or v
                        continue
                    if isinstance(v, str) and v.startswith("Unknown (") and v[9:-1] in names:
                        v = names[v[9:-1]]  # iLEAPP leaves App Store ids it can't name as "Unknown (<id>)"
                    if re.search(SECRET_FIELDS, f"{c} {label}", re.I):
                        continue  # never import credentials, whatever the artifact
                    fields[label] = iso(v) if types.get(c) == "datetime" else v
                    if types.get(c) != "datetime":
                        shown.append(f"{label}: {v}")
                if id_col:
                    rid = f"{a['artifact_key']}:{r[id_col]}"
                else:
                    stable = {c: r[c] for c in cols if not re.search(VOLATILE, c)}
                    rid = f"{a['artifact_key']}:" + hashlib.sha1(
                        json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()[:16]
                if a["artifact_key"] in KEEP_DUPLICATES:
                    seen[rid] = seen.get(rid, 0) + 1
                    rid += f"#{seen[rid]}" if seen[rid] > 1 else ""
                if w.has(rid):
                    continue  # an exact repeat of a row (joins in the iLEAPP module)
                if a["artifact_key"] in SKIP_ROWS and SKIP_ROWS[a["artifact_key"]](r, source_file):
                    w.notes["other_peoples_rows"] = w.notes.get("other_peoples_rows", 0) + 1
                    continue
                meta = {k: v for k, v in (("artifact", a["name"]), ("category", category), ("files", files),
                                          ("fields", fields), ("source_file", source_file),
                                          ("tier", tier(category, a["name"]))) if v}
                if conv:
                    sent = str(r.get(conv.get("directionColumn"))) == str(conv.get("directionSentValue"))
                    if a["artifact_key"] == "weChatMessages":
                        sender, text = wechat_message(r, conv, nicknames)
                    else:
                        sender, text = r.get(conv.get("senderColumn")), text_value(r.get(conv.get("textColumn"))) or ""
                    if files and not text:
                        text = f"[{len(files)} attachment{'s' * (len(files) > 1)}]"
                    w.add(id=rid, kind="message", ts=iso(r.get(conv.get("timeColumn")), plausible=True), is_me=sent,
                          author="me" if sent else sender,
                          thread=str(r.get(conv.get("conversationDiscriminatorColumn")) or "") or None,
                          thread_name=r.get(conv.get("conversationLabelColumn")) or nicknames.get(
                              r.get(conv.get("conversationDiscriminatorColumn"))), text=str(text), meta=meta)
                else:
                    title = next((str(r[c]) for c in cols if re.search(r"title|^name$|description", c) and r[c]), None)
                    ts = next((iso(r[c]) for c in times if iso(r[c])), None)
                    # End time: an "end" column (events), or for editable content the last edit, which is when the
                    # text shown was written (notes keep only their latest version).
                    end_col = next((c for c in times if re.search(r"(^|_)end", c)), None) or (
                        next((c for c in times if re.search(r"modif|updated|last_edit", c)), None) if kind == "note" else None)
                    if ts and not iso(next(r[c] for c in times if iso(r[c])), plausible=True):
                        ts, w.notes["implausible_times"] = None, w.notes["implausible_times"] + 1
                    w.add(id=rid, kind=kind, ts=ts, ts_end=iso(r[end_col], plausible=True) if end_col else None,
                          title=title, text=f"{a['name']}: " + "; ".join(shown), meta=meta)
                n += 1
            w.notes["artifacts"][a["name"]] = n


def app_names():
    """App Store id -> app name, from the backup's Info.plist (iTunesMetadata of each installed app)."""
    info = IPHONE.parent / "Info.plist"
    if not info.exists():
        return {}, []
    apps = []
    for bundle, v in plistlib.loads(info.read_bytes()).get("Applications", {}).items():
        try:
            md = plistlib.loads(v["iTunesMetadata"]) if "iTunesMetadata" in v else {}
        except Exception:
            md = {}
        apps.append({"bundle": bundle, "id": md.get("itemId"), "name": md.get("itemName") or bundle,
                     "developer": md.get("artistName"), "genre": md.get("genre"), "released": md.get("releaseDate")})
    return {str(a["id"]): a["name"] for a in apps if a["id"]}, apps


def installed_apps(apps):
    """Apps installed on the phone at backup time (Info.plist; iLEAPP reads it only in -t itunes mode)."""
    if not apps:
        return
    with Writer("phone_installed_apps", "iPhone backup Info.plist (Applications → iTunesMetadata) → connectors/ileapp.py",
                accumulate=False) as w:
        for a in apps:
            w.add(id=a["bundle"], kind="app", title=a["name"],
                  text=f"Installed app: {a['name']}" + "".join(f"; {k}: {a[k]}" for k in ("developer", "genre", "bundle") if a[k]),
                  meta={k: a[k] for k in ("bundle", "id", "developer", "genre", "released") if a[k]})


def import_latest(latest=None):
    latest = Path(latest) if latest else max(OUT.glob("*/latest"), key=lambda p: p.stat().st_mtime, default=None)
    if not latest or not (latest / "_lava_artifacts.db").exists():
        print(f"[ileapp] no iLEAPP results under {OUT}; run connectors/ileapp.py first")
        return
    meta = json.loads((latest / "_lava_data.lava").read_text())
    version = json.loads((latest / "run.json").read_text())["ileapp"] if (latest / "run.json").exists() \
        else meta["parser_info"]["leapp_version"]
    con = sqlite3.connect(f"file:{latest / '_lava_artifacts.db'}?mode=ro", uri=True)
    media = {ref: mirror_path(src) for ref, src in con.execute(
        "select r.id, i.source_path from _lava_media_references r join _lava_media_items i on i.id = r.media_item_id")}
    by_module, ledger = {}, {}
    for category, arts in meta["artifacts"].items():
        for a in arts:
            if not a.get("record_count"):
                continue
            why = left_out(category, a)
            if why:
                ledger.setdefault(why, {})[a["name"]] = a["record_count"]
                continue
            by_module.setdefault(a["module"], []).append((category, a))
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    manifest["_ileapp_left_out"] = ledger
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    names, apps = app_names()
    installed_apps(apps)
    nicknames = {}
    if con.execute("select 1 from sqlite_master where name = 'wechatcontacts'").fetchone():
        nicknames = {i: n for i, n in con.execute("select wechat_id, nickname from wechatcontacts") if n}
    for module, arts in sorted(by_module.items()):
        write_module(module, arts, con, media, version, nicknames, names)
    print(f"[ileapp] imported {sum(len(v) for v in by_module.values())} artifacts from {len(by_module)} modules; left out: "
          + "; ".join(f"{why} {sum(d.values()):,} rows" for why, d in ledger.items()) + " (manifest.json _ileapp_left_out)")


def main(argv=()):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-run", action="store_true", help="import the last iLEAPP run only")
    ap.add_argument("--install", action="store_true", help="(re)install the pinned iLEAPP and its dependencies")
    ap.add_argument("--backup", help="backup folder (default: the most recent finished one)")
    ap.add_argument("--force", action="store_true", help="run even if disk space looks short")
    a = ap.parse_args(argv)
    if a.install:
        install()
    latest = None if a.skip_run else run(a.backup, force=a.force)  # decrypt first: iphone_backup.py
    import_latest(latest)


if __name__ == "__main__":
    main(sys.argv[1:])
