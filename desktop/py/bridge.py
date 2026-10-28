#!/usr/bin/env python3
"""The desktop app's only way into the connectors. Every command prints JSON, so the app never parses
free text it didn't write.

    bridge.py probe                     what's on this Mac: permissions, sources, iPhone backups, settings
    bridge.py stats                     the corpus manifest plus records per source per year (for gap checks)
    bridge.py identify <path>...        which export each downloaded file or folder is
    bridge.py run <connector>... [--no-index]
                                        run connectors, then rebuild the index; one JSON event per line
    bridge.py iphone [--password-stdin] decrypt and read the latest iPhone backup (connectors/iphone.py)
    bridge.py index                     rebuild corpus/corpus.db only
    bridge.py write-identity            JSON on stdin -> corpus/identity.json
    bridge.py exclude-icloud            move the corpus to <name>.nosync and leave a symlink, so iCloud stops syncing it
    bridge.py forget-phone              take what was read from the iPhone backup out of the library (not your phone)
    bridge.py index --forget-phone      the same, then rebuild the index; one JSON event per line (the app's queue runs it)

Paths: UMP_REPO (default: two levels up) holds connectors/; CORPUS_DIR overrides the corpus folder, as it
does for the connectors themselves; HOME decides whose Library is read. Tests add fake connector modules
with UMP_EXTRA_PYPATH and swap the iPhone pipeline with UMP_IPHONE_MODULE.
"""

import collections
import contextlib
import ctypes
import datetime as dt
import fcntl
import hashlib
import io
import itertools
import json
import os
import plistlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
import traceback
import tarfile
import zipfile
import zlib
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

REPO = Path(os.environ.get("UMP_REPO") or Path(__file__).resolve().parents[2])
CONNECTORS = REPO / "connectors"
sys.path.insert(0, str(CONNECTORS))
for extra in filter(None, os.environ.get("UMP_EXTRA_PYPATH", "").split(os.pathsep)):
    sys.path.insert(0, extra)
from library_paths import photos_libraries
import common  # noqa: E402 - connectors/common.py: how zips are read, as imports.py reads them

HOME = Path.home()
LIB = HOME / "Library"
CORPUS = Path(os.environ.get("CORPUS_DIR") or REPO / "corpus")
BACKUPS = LIB / "Application Support/MobileSync/Backup"
KEYCHAIN_ITEM = "q1_user_model iPhone backup"
SF_DATALESS = 0x40000000  # st_flags bit for iCloud files that are only in the cloud

# Where each Mac connector reads from. A source is present if any path is readable.
MAC_PATHS = {
    "contacts": [LIB / "Application Support/AddressBook"],
    "imessage": [LIB / "Messages/chat.db"],
    "whatsapp": [LIB / "Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"],
    "signal_desktop": [LIB / "Application Support/Signal/sql/db.sqlite"],
    "mail_app": [LIB / "Mail"],
    "apple_notes": [LIB / "Group Containers/group.com.apple.notes/NoteStore.sqlite"],
    "calendar_events": [LIB / "Group Containers/group.com.apple.calendar/Calendar.sqlitedb"],
    "reminders": [LIB / "Group Containers/group.com.apple.reminders/Container_v1/Stores"],
    "calls": [LIB / "Application Support/CallHistoryDB/CallHistory.storedata"],
    "browser_history": [LIB / "Safari/History.db"],  # and every other browser's history files (browsers.py), at probe time
    "app_usage": [LIB / "Biome/streams/restricted"],
    "ai_coding": [HOME / ".claude/projects", HOME / ".codex/sessions", LIB / "Application Support/Cursor/User/globalStorage/state.vscdb",
                  LIB / "Application Support/Code/User/workspaceStorage"],
    "editor_history": [LIB / f"Application Support/{e}/User/History" for e in ("Code", "Cursor", "VSCodium", "Windsurf")],
    "setup": [HOME / ".zshrc", HOME / ".gitconfig", HOME / ".claude/settings.json", HOME / ".config", HOME / "Library/LaunchAgents"],
    "shell_history": [HOME / ".zsh_history", HOME / ".zsh_sessions", HOME / ".bash_history", HOME / ".local/share/fish/fish_history"],
    "podcasts": [LIB / "Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"],
    "books": [LIB / "Containers/com.apple.iBooksX/Data/Documents/BKLibrary", LIB / "Containers/com.apple.iBooksX/Data/Documents/AEAnnotation"],
    "photos": [p / "database/Photos.sqlite" for p in photos_libraries(HOME)],
    "apple_maps": [LIB / "Containers/com.apple.Maps/Data/Maps/MapsSync_0.0.1"],
    "voice_memos": [LIB / "Group Containers/group.com.apple.VoiceMemos.shared/Recordings"],
    "notion_local": [LIB / "Application Support/Notion/notion.db"],
    "zotero": [HOME / "Zotero/zotero.sqlite"],  # or wherever its prefs.js says (zotero.py)
    # and Obsidian vaults wherever they are, read with these (not looked for alone: see PROTECTED)
    "documents": [HOME / "Documents", HOME / "Desktop", LIB / "Mobile Documents", LIB / "CloudStorage", HOME / "Dropbox"],
    "git_commits": [HOME / "Documents", HOME / "Desktop", LIB / "Mobile Documents/com~apple~CloudDocs",
                    *(HOME / d for d in ("Developer", "Code", "code", "Projects", "projects", "src", "dev", "git", "repos", "workspace"))],
}
# Files only Full Disk Access can read. The first one that exists decides.
FDA_PROBES = [LIB / "Messages/chat.db", LIB / "Safari/History.db", LIB / "Mail",
              LIB / "Group Containers/group.com.apple.notes/NoteStore.sqlite",
              LIB / "Application Support/CallHistoryDB/CallHistory.storedata", BACKUPS,
              LIB / "Application Support/com.apple.TCC/TCC.db"]


def out(obj):
    sys.stdout.write(json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def access(path):
    """'ok' if readable, 'blocked' if macOS refuses (no Full Disk Access), 'absent' if it isn't there."""
    try:
        st = os.stat(path)
        if stat.S_ISDIR(st.st_mode):
            os.listdir(path)
        else:
            with open(path, "rb") as f:
                f.read(1)
        return "ok"
    except FileNotFoundError:
        return "absent"
    except (PermissionError, OSError) as e:
        return "blocked" if isinstance(e, PermissionError) or getattr(e, "errno", None) in (1, 13) else "absent"


def full_disk_access():
    for p in FDA_PROBES:
        a = access(p)
        if a == "ok":
            return True, str(p)
        if a == "blocked":
            return False, str(p)
    return None, None


def read_plist(path):
    try:
        return plistlib.loads(Path(path).read_bytes())
    except Exception:
        return None


def pref(domain_file, key, defaults_domain=None):
    """{"readable": bool, "value": ...} for a preference: from the plist file under HOME (so tests can fake
    it), else `defaults read` for the real user. readable with value None means the key isn't set (the
    app's default applies)."""
    d = read_plist(domain_file)
    if d is not None:
        return {"readable": True, "value": d.get(key)}
    if defaults_domain and HOME == Path(os.path.expanduser("~" + os.environ.get("USER", ""))):
        r = subprocess.run(["defaults", "read", defaults_domain, key], capture_output=True, text=True)
        if r.returncode == 0:
            v = r.stdout.strip()
            return {"readable": True, "value": int(v) if v.lstrip("-").isdigit() else v}
    return {"readable": False, "value": None}


def in_icloud(path):
    """True if path is inside iCloud Drive (Desktop & Documents sync puts ~/Documents there)."""
    p = Path(path).resolve()
    if ".nosync" in "".join(p.parts):
        return False
    if str(p).startswith(str(LIB / "Mobile Documents")):
        return True
    while True:
        r = subprocess.run(["xattr", "-p", "com.apple.file-provider-domain-id", str(p)], capture_output=True, text=True)
        if r.returncode == 0 and "CloudDocs" in r.stdout:
            return True
        if p.parent == p or p == HOME:
            return False
        p = p.parent


def backups():
    found = []
    if access(BACKUPS) != "ok":
        return found
    for d in sorted(BACKUPS.iterdir()):
        if not d.is_dir():
            continue
        info, manifest, status = read_plist(d / "Info.plist"), read_plist(d / "Manifest.plist"), read_plist(d / "Status.plist")
        snapshot = (status or {}).get("SnapshotState")
        date = (info or {}).get("Last Backup Date") or (status or {}).get("Date")
        found.append({
            "dir": str(d), "id": d.name,
            # Which device: the same one's backups (an archived copy is a folder of its own) share it.
            "udid": (info or {}).get("Target Identifier") or (info or {}).get("Unique Identifier") or d.name,
            "device": (info or {}).get("Device Name"), "product": (info or {}).get("Product Type"),
            "ios": (info or {}).get("Product Version"),
            "date": date.replace(tzinfo=dt.timezone.utc).isoformat() if isinstance(date, dt.datetime) else None,
            "encrypted": bool((manifest or {}).get("IsEncrypted")),
            "finished": bool(info) and (d / "Manifest.db").exists() and snapshot in (None, "finished"),
            "in_progress": snapshot not in (None, "finished"),
        })
    return found


def mirror():
    """What iphone_backup.py last decrypted (corpus/raw/iphone/backup.json)."""
    p = CORPUS / "raw/iphone/backup.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def keychain_has_password():
    if HOME != Path(os.path.expanduser("~" + os.environ.get("USER", ""))):
        return False  # a test HOME has no Keychain
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_ITEM], capture_output=True)
    return r.returncode == 0


def has_module(name):
    r = subprocess.run([sys.executable, "-c", f"import {name}"], capture_output=True)
    return r.returncode == 0


def python_modules():
    """Whether this Python has cryptography and pypdf. The app looks once per launch (and on Check Again) and says
    what it found in UMP_PYTHON_MODULES, so a probe a minute doesn't start two Pythons to ask again."""
    try:
        known = json.loads(os.environ.get("UMP_PYTHON_MODULES") or "{}")
    except ValueError:
        known = {}
    if known.get("path") == sys.executable and all(isinstance(known.get(m), bool) for m in ("cryptography", "pypdf")):
        return {m: known[m] for m in ("cryptography", "pypdf")}
    return {m: has_module(m) for m in ("cryptography", "pypdf")}


def identity():
    p = CORPUS / "identity.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def suggest_identity():
    """The Contacts "me" card, as a starting point for identity.json."""
    try:
        from contacts import load_contacts
        for c in load_contacts():
            if c.get("is_me"):
                return {"names": [c["name"]] if c.get("name") else [], "emails": [v for _, v in c.get("emails", [])],
                        "phones": [v for _, v in c.get("phones", [])], "usernames": []}
    except Exception:
        pass
    return None


def mailbox_sources():
    """Folders under corpus/imports/ holding mailbox exports (.mbox, Outlook's .olm, at the top or a folder down): each is its
    own source, named as imports.py names it (hotmail; mail_mail for one in imports/mail/, which isn't Mail's)."""
    root = CORPUS / "imports"
    found, marks = [], ("*.mbox", "*/*.mbox", "*.olm", "*/*.olm")
    if root.exists():
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith((".", "takeout")) and any(x for m in marks for x in d.glob(m)):
                found.append(d.name)
    if not found:
        return []
    import imports
    return [imports.mail_source(n) for n in found]


def mail_accounts():
    """The accounts Mail on this Mac holds mail for (their address or name), or [] without Mail or Full Disk Access."""
    try:
        import mail_app
        root = mail_app.mail_root()
        if not root:
            return []
        names = mail_app.account_names()
        return sorted({names.get(p.name) or "an account" for p in root.iterdir() if p.is_dir() and p.name != "MailData" and any(p.glob("*.mbox/**/Messages/*.emlx"))})
    except OSError:
        return []


def claude_retention():
    p = HOME / ".claude/settings.json"
    if not (HOME / ".claude").exists():
        return {"present": False}
    try:
        days = json.loads(p.read_text()).get("cleanupPeriodDays") if p.exists() else None
    except ValueError:
        days = "unreadable"
    return {"present": True, "days": days, "path": str(p)}


ZSH_KEEP = "# Added by Homecoming: keep every Terminal command, with its time."
ZSH_KEEP_BEFORE = ("# Added by User Model: keep every Terminal command, with its time.",)  # the app's earlier name


def ours_in(text):
    return any(m in text for m in (ZSH_KEEP, *ZSH_KEEP_BEFORE))


def shell_retention():
    """How much history zsh keeps, from its startup files (read, never run: running .zshrc has side effects).
    Last assignment wins; oh-my-zsh sets 10,000 with times; a history file already holding ': <time>:' lines
    means EXTENDED_HISTORY is on whatever the files say."""
    shell = os.path.basename(os.environ.get("SHELL") or "")
    if shell != "zsh":
        return {"shell": shell or None}
    savehist, extended = None, False
    rc = HOME / ".zshrc"
    for f in (Path("/etc/zshenv"), Path("/etc/zshrc"), HOME / ".zshenv", HOME / ".zprofile", rc):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if m := re.match(r"^(?:export\s+)?SAVEHIST=(\d+)$", line):
                savehist = int(m.group(1))
            if re.match(r"^(?:source|\.)\s.*oh-my-zsh\.sh", line):
                savehist, extended = max(savehist or 0, 10000), True
            if re.match(r"^setopt\b", line, re.I) and re.search(r"extended_?history", line, re.I):
                extended = True
            if re.match(r"^unsetopt\b", line, re.I) and re.search(r"extended_?history", line, re.I):
                extended = False
    try:
        with open(HOME / ".zsh_history", "rb") as h:
            extended = extended or bool(re.search(rb"^: \d{9,11}:\d+;", h.read(65536), re.M))
    except OSError:
        pass
    return {"shell": "zsh", "savehist": savehist, "extended": extended, "rc": str(rc),
            "ours": rc.exists() and ours_in(rc.read_text(errors="replace"))}


def fix_shell_retention():
    """Append a block to ~/.zshrc that keeps every command with its time. Later lines win, so it goes last."""
    rc = HOME / ".zshrc"
    text = rc.read_text(errors="replace") if rc.exists() else ""
    if not ours_in(text):
        block = f"{ZSH_KEEP}\nsetopt EXTENDED_HISTORY\nHISTSIZE=1000000\nSAVEHIST=1000000\n"
        rc.write_text(text + ("" if not text or text.endswith("\n") else "\n") + ("\n" if text else "") + block)
    return shell_retention()


# Folders macOS asks about one by one without Full Disk Access. Before the Setup Assistant is past that step
# (UMP_DEFER_FOLDERS=1, from the app), they're left for later, so no question comes before anything says why. Cloud
# drives' folders and other apps' own data can be asked about too (macOS 14 and later), so they wait the same way.
PROTECTED = [HOME / "Documents", HOME / "Desktop", HOME / "Downloads", LIB / "Mobile Documents", LIB / "CloudStorage",
             HOME / "Dropbox", LIB / "Group Containers/group.net.whatsapp.WhatsApp.shared",
             LIB / "Containers/com.apple.Maps", LIB / "Containers/com.apple.iBooksX"]
DOWNLOADS = Path(os.environ.get("UMP_DOWNLOADS") or HOME / "Downloads")


def _protected(p):
    p = Path(p)
    return any(p == q or q in p.parents for q in PROTECTED)


def probe():
    fda, fda_path = full_disk_access()
    defer = os.environ.get("UMP_DEFER_FOLDERS") == "1" and fda is not True
    look = lambda p: "later" if defer and _protected(p) else access(p)
    sources = {}
    import browsers
    import phones
    found_browsers = browsers.found()
    histories = [p for b in found_browsers if b["id"] != "safari" for _, p in browsers.history_files(b["id"])]
    for name, paths in MAC_PATHS.items():
        states = [look(p) for p in [*paths, *(histories if name == "browser_history" else [])]]
        sources[name] = "ok" if "ok" in states else "blocked" if "blocked" in states else "absent"
    from common import git_bin
    if not git_bin():  # commits can't be read without git
        sources["git_commits"] = "absent"
    corpus_parent = CORPUS if CORPUS.exists() else CORPUS.parent
    usage = shutil.disk_usage(corpus_parent if corpus_parent.exists() else HOME)
    ident = identity()
    # Looking in Mail or notifications turned off in General: the copy kept for it goes too.
    for name, off in (("notifications", "UMP_READY_NOTIFICATIONS"), ("mail", "UMP_READY_MAIL")):
        if os.environ.get(off) == "0":
            drop_copy(name)
    return {
        "time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "home": str(HOME), "repo": str(REPO),
        "python": {"path": sys.executable, "version": sys.version.split()[0], **python_modules()},
        "fda": fda, "fda_path": fda_path,
        # Whether the Downloads folder can be looked in (exports land there): "later" until it's asked.
        "downloads": look(DOWNLOADS),
        "sources": sources,
        "corpus": {"path": str(CORPUS), "exists": CORPUS.exists(), "real_path": str(CORPUS.resolve()),
                   "in_icloud": in_icloud(CORPUS) if CORPUS.exists() else in_icloud(CORPUS.parent),
                   "free_bytes": usage.free, "total_bytes": usage.total},
        "identity": ident, "identity_suggestion": None if ident else suggest_identity(),
        "backups": backups(), "mirror": mirror(), "keychain_password": keychain_has_password(),
        "ileapp_installed": any((HOME / "Library/Application Support/q1_user_model/tools").glob("ileapp-venv-*/bin/python")),
        "mailbox_sources": mailbox_sources(),
        "notifications": notification_access(),
        # Your Setup: what was found here, for the person to change.
        "browsers": found_browsers, "phone": phones.info(), "mail_accounts": mail_accounts(),
        "retention": {
            "claude": claude_retention(),
            "shell": shell_retention(),
            "messages": pref(LIB / "Preferences/com.apple.MobileSMS.plist", "KeepMessageForDays", "com.apple.MobileSMS"),
            "safari": pref(LIB / "Containers/com.apple.Safari/Data/Library/Preferences/com.apple.Safari.plist",
                                        "HistoryAgeInDaysLimit"),
            # The iPhone's own "Keep Messages", from the decrypted backup (absent until a backup is read).
            "iphone_messages": pref(CORPUS / "raw/iphone/files/HomeDomain/Library/Preferences/com.apple.MobileSMS.plist", "KeepMessageForDays"),
            # Codex keeps every session in ~/.codex/sessions until you delete it; nothing to change, just whether it's here.
            "codex": {"present": (HOME / ".codex/sessions").exists()},
        },
    }


# The field that splits each Mac source by what it holds: service, browser, device... (stats -> facets).
FACETS = {
    "imessage": "json_extract(meta, '$.service')",
    "calls": "json_extract(meta, '$.type')",
    "browser_history": "substr(id, 1, instr(id, ':') - 1)",  # safari:..., chrome:...
    "app_usage": "json_extract(meta, '$.device')",
    "ai_coding": "json_extract(meta, '$.tool')",
    "editor_history": "json_extract(meta, '$.editor')",
    "shell_history": "json_extract(meta, '$.shell')",
    "setup": "json_extract(meta, '$.group')",
    # Documents in an export land in imported_documents; split them by the export's folder (a service you added).
    "imported_documents": "substr(json_extract(meta, '$.origin'), 1, instr(json_extract(meta, '$.origin') || '/', '/') - 1)",
    "photos": "json_extract(meta, '$.type')",
    "shared_photos": "json_extract(meta, '$.shared')",
    "documents": "json_extract(meta, '$.root')",
    "mail": "json_extract(meta, '$.account')",
}


def stats():
    manifest_path = CORPUS / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text())
    except Exception:
        manifest = {}
    years, copies, device, facets = {}, {}, [], {}
    db = CORPUS / "corpus.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) if db.exists() else None
    if con:
        try:
            for source, year, n in con.execute(
                    "select source, substr(ts, 1, 4), count(*) from records where ts is not null group by 1, 2"):
                if year and year.isdigit():
                    years.setdefault(source, {})[year] = n
        except sqlite3.Error as e:
            years = {"_error": str(e)}
        try:
            # What's inside each Mac source, by one field (shared/contents.ts says it in words). Sources merged
            # from the Mac and the iPhone also note which copy each record came from (meta.copy).
            for source, expr in FACETS.items():
                for copy, value, n in con.execute(f"select json_extract(meta, '$.copy'), {expr}, count(*) from records "
                                                  "where source = ? group by 1, 2", (source,)):
                    if copy:
                        copies.setdefault(source, {})[copy] = copies.get(source, {}).get(copy, 0) + n
                    if value:
                        facets.setdefault(source, {})[value] = facets.get(source, {}).get(value, 0) + n
            repos = con.execute("select count(distinct json_extract(meta, '$.repo')) from records where source = 'git_commits'").fetchone()[0]
            if repos:
                facets["git_commits"] = {"repositories": repos}
            # Phone sources that are mostly phone internals (ileapp.py tags them meta.tier = "device"), from a sample.
            for source in (k for k in manifest if k.startswith("phone_")):
                tiers = [t for (t,) in con.execute("select json_extract(meta, '$.tier') from records where source = ? limit 200", (source,))]
                if tiers.count("device") * 2 > len(tiers):
                    device.append(source)
        except sqlite3.Error:
            pass  # an index from before records had meta
        con.close()
    return {"manifest": manifest, "years": years, "copies": copies, "device": sorted(device), "facets": facets,
            "db_mtime": db.stat().st_mtime if db.exists() else None,
            "manifest_mtime": manifest_path.stat().st_mtime if manifest_path.exists() else None}


# ---------------------------------------------------------------- exports in formats no parser knows

ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHAPE_DEPTH, SHAPE_KEYS = 6, 60


def _leaf(v):
    """What kind of value this is, without the value."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true/false"
    if isinstance(v, (int, float)):
        if isinstance(v, int) and 9e8 < v < 4e9:
            return "number (looks like a Unix time in seconds)"
        if isinstance(v, int) and 9e11 < v < 4e12:
            return "number (looks like a Unix time in milliseconds)"
        return "number"
    s = str(v)
    if ISO_TIME.match(s):
        return "date and time"
    if ISO_DATE.match(s):
        return "date"
    if re.match(r"^https?://", s):
        return "link"
    if re.match(r"^[^@\s]+@[^@\s]+\.\w+$", s):
        return "email address"
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return "number as text"
    if re.fullmatch(r"[0-9a-fA-F-]{16,}", s):
        return "id"
    return "text"


def _shape(values, depth=0, examples=False):
    """The merged shape of a list of values: {key: shape} for objects, [n] of shape for lists, else the leaf
    kind with the longest text length seen (and one example when asked)."""
    values = [v for v in values if v is not None][:200]
    if not values:
        return "null"
    if depth > SHAPE_DEPTH:
        return "…"
    if all(isinstance(v, dict) for v in values):
        keys = []
        for v in values:
            keys += [k for k in v if k not in keys]
        if _map_like(keys):  # a lookup table keyed by ids or names: say so, without the keys
            kind = "numbers" if all(re.fullmatch(r"\d+", str(k)) for k in keys) else "ids or names"
            return {"map with keys": f"{len(keys):,} {kind}", "each value": _shape([x for v in values for x in v.values()], depth + 1, examples)}
        out = {}
        for k in keys[:SHAPE_KEYS]:
            out[k] = _shape([v.get(k) for v in values], depth + 1, examples)
        if len(keys) > SHAPE_KEYS:
            out["…"] = f"{len(keys) - SHAPE_KEYS} more fields"
        return out
    if all(isinstance(v, list) for v in values):
        items = [x for v in values for x in v]
        return {"list of": _shape(items, depth + 1, examples), "count": f"up to {max(len(v) for v in values):,}"}
    kinds = {_leaf(v) for v in values}
    kind = " or ".join(sorted(kinds))
    if kinds == {"text"}:
        n = max(len(str(v)) for v in values)
        kind = f"text (up to {n:,} character{'' if n == 1 else 's'})"
    if examples:
        ex = next((str(v) for v in values if str(v).strip()), "")
        if ex:
            kind += f', e.g. "{ex[:60]}{"…" if len(ex) > 60 else ""}"'
    return kind


def _export_entries(folder):
    import imports as im
    return [e for e in im.entries() if (Path(e.origin).parts[:1] == (folder,) if e.origin else False)]


def _datalike(name):
    """A file or folder name that is itself data: a title, a person's name, an id. Never sent as is."""
    stem = name.rsplit(".", 1)[0] if "." in name[1:] else name
    return bool(re.search(r"\s|@|[^\x00-\x7f]|\d{6,}|[0-9a-f]{12,}", stem, re.I))


def _path_patterns(paths):
    """{path: pattern}: names that are data become *, so the request names no person, page, thread or id.
    A folder is one of many instances (a conversation, a channel, a page) when at least 4 siblings hold the same
    kinds of files; numbers in file names are counters (message_1.json -> message_*.json)."""
    def gen_file(name):
        stem, dot, ext = name.rpartition(".") if "." in name[1:] else (name, "", "")
        stem = "*" if _datalike(stem) else re.sub(r"\d+", "*", stem)
        return f"{stem}.{ext}" if dot else stem
    kids = collections.defaultdict(set)    # folder -> child folder names
    sig = collections.defaultdict(set)     # folder -> generalized names of the files directly in it
    for p in paths:
        parts = p.split("/")
        for i in range(len(parts) - 1):
            kids["/".join(parts[:i])].add(parts[i])
        sig["/".join(parts[:-1])].add(gen_file(parts[-1]))
    instance = set()
    for parent, names in kids.items():
        counts = collections.Counter(frozenset(sig[f"{parent}/{n}" if parent else n]) for n in names)
        common, n = counts.most_common(1)[0] if counts else (None, 0)
        for name in names:
            path = f"{parent}/{name}" if parent else name
            if _datalike(name) or (n >= 4 and frozenset(sig[path]) == common):
                instance.add(path)
    out = {}
    for p in paths:
        parts = p.split("/")
        segs = ["*" if "/".join(parts[:i + 1]) in instance else parts[i] for i in range(len(parts) - 1)]
        out[p] = "/".join(segs + [gen_file(parts[-1])])
    return out


def _map_like(keys):
    """An object whose keys are data (ids, addresses, names) rather than field names. One id, address or link is
    enough; keys in another script only when most are (field names in Chinese or Japanese exports aren't data)."""
    if len(keys) > 40 or any(re.fullmatch(r"\d{4,}|[0-9a-f-]{12,}", str(k), re.I) or re.search(r"@|://", str(k)) for k in keys):
        return True
    return len(keys) >= 4 and sum(1 for k in keys if re.search(r"[^\x00-\x7f]", str(k))) * 2 > len(keys)


PROMPT_BUDGET = 60_000  # characters of structure in one request


def describe_export(folder, examples=False, service=None):
    """The structure of corpus/imports/<folder>/ as Claude would see it: its files, grouped into patterns (no
    names that are data: people, pages, threads, ids), and the shape of each JSON/CSV/JS pattern's fields (names
    and kinds of values, never the values unless examples=True), within PROMPT_BUDGET."""
    import mapped_exports as mx
    entries = sorted(_export_entries(folder), key=lambda e: e.path)
    pattern = _path_patterns([e.path for e in entries])
    groups = {}
    for e in entries:
        g = groups.setdefault(pattern[e.path], {"files": 0, "bytes": 0, "ext": Path(e.path).suffix.lower(), "samples": []})
        g["files"] += 1
        g["bytes"] += e.size or 0
        if g["ext"] in (".json", ".csv", ".js") and len(g["samples"]) < 5 and e.size and e.size <= 50 * 2**20:
            try:
                g["samples"].append(mx.parse(e))
            except (ValueError, UnicodeDecodeError):
                pass
    blocks = []
    for pat, g in groups.items():
        what = {".json": "JSON", ".js": "JSON", ".csv": "CSV", ".html": "HTML, kept as a document", ".htm": "HTML, kept as a document",
                ".pdf": "PDF, kept as a document", ".txt": "text, kept as a document"}.get(
            g["ext"], "media, kept as a file" if g["ext"] in (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov", ".mp3", ".m4a", ".heic", ".webp") else "other")
        head = f"{pat}  ({g['files']:,} file{'s' if g['files'] != 1 else ''}, {what}, {g['bytes']:,} bytes)"
        shape = None
        if g["samples"]:
            lists = [x for x in g["samples"] if isinstance(x, list)]
            shape = {"list of": _shape([i for x in lists for i in x], examples=examples), "count": f"up to {max(len(x) for x in lists):,}"} \
                if lists and len(lists) == len(g["samples"]) else _shape([x for x in g["samples"] if isinstance(x, dict)], examples=examples)
        blocks.append((bool(shape), g["files"], head + (f"\n{json.dumps(shape, indent=2, ensure_ascii=False)}" if shape else "")))
    blocks.sort(key=lambda b: (not b[0], -b[1]))
    shown, used = [], 0
    for _, _, b in blocks:
        if used + len(b) > PROMPT_BUDGET and shown:
            break
        shown.append(b)
        used += len(b)
    left = len(blocks) - len(shown)
    structure = "\n\n".join(shown) + (f"\n\n… and {left:,} more file pattern{'s' if left != 1 else ''} not shown, to keep this short." if left else "")
    name = service or folder
    prompt = MAPPING_PROMPT.format(service=name, values=" and an example value for each field" if examples else "",
                                   content="A few example values are included." if examples else
                                   "No values are included, only field names and the kinds of values; file and folder names that are themselves data are shown as *.",
                                   kinds=", ".join(sorted(mx.KINDS)), structure=structure or "(no files)")
    return {"folder": folder, "files": [{"path": e.path, "bytes": e.size} for e in entries], "patterns": len(groups),
            "structured": sum(1 for g in groups.values() if g["samples"]), "prompt": prompt}


MAPPING_PROMPT = "\n".join([
    "You are writing a mapping for a personal-data export from {service}, so that its contents can be read as records: posts, "
    "messages, comments, purchases and so on. Below is the export's structure: its files, and for each JSON or CSV file the "
    "names of its fields and the kinds of values they hold{values}. {content}",
    "",
    "Reply with only a JSON object, no prose, in this form:",
    '{{"service": "{service}", "version": 1, "items": [{{"describe": "...", "file": "...", "path": "...", "kind": "...", "time": "...", '
    '"title": "...", "text": ["..."], "author": "...", "thread": "...", "thread_name": "...", "url": "...", "id": "..."}}]}}',
    "",
    "- One item per kind of thing in the export. A file can have several (e.g. stories, and their comments).",
    '- file: a glob matched against a file\'s path as shown below, e.g. "stories.json" or "messages/*.json".',
    '- path: dot path to the list of items inside the file (e.g. "data.stories"); "" when the file itself is the list. CSV files '
    'are always lists of rows: use "".',
    "- kind: one of {kinds}.",
    "- time: the field saying when the thing happened (written, sent, watched, bought), not when the export was made.",
    "- text: the fields holding what was written or done, most important first.",
    "- title, thread (what it belongs to: a conversation, a story), thread_name, url, id: when there is a field for it.",
    '- author: the field naming who made it, or "me" when everything in that list was made by the account\'s owner.',
    '- Every field name can be a dot path into nested objects ("user.name"). Leave out a field rather than guess.',
    "- Leave out settings, devices, sessions, logins, ads and other account plumbing.",
    '- describe: a few plain words a person would recognize, e.g. "Stories you wrote", "Comments on your stories".',
    "",
    "Structure:",
    "",
    "{structure}",
    "",
])


def try_mapping(folder, mapping):
    """Run a mapping over the whole export without writing anything: what each item finds, a few samples,
    and which structured files nothing reads."""
    import mapped_exports as mx
    from imports import fitbit_reads, leftover_time
    m = mx.validate(mapping)
    es = _export_entries(folder)
    stats = [{"describe": r["describe"], "kind": r["kind"], "file": r["file"], "files": set(), "items": 0, "timed": 0,
              "first": None, "last": None, "sample": [], "repeats": 0} for r in m["items"]]
    ids = set()
    for i, e, rec in mx.records(m, es, when=leftover_time):
        s = stats[i]
        s["files"].add(e.path)
        # An id another item has too (the mapping's id field isn't unique): kept once when it's used, so said here.
        # With overlap it's the same item in another file (two bank downloads' dates overlap): only counted once.
        if rec["id"] in ids:
            s["repeats"] += 0 if m["items"][i].get("overlap") else 1
            continue
        ids.add(rec["id"])
        s["items"] += 1
        if rec.get("ts"):
            s["timed"] += 1
            s["first"] = min(s["first"] or rec["ts"], rec["ts"])
            s["last"] = max(s["last"] or rec["ts"], rec["ts"])
        if len(s["sample"]) < 3:
            s["sample"].append({k: (rec.get(k)[:240] if isinstance(rec.get(k), str) else rec.get(k)) for k in ("ts", "title", "text", "author")})
    # Fitbit's series by the reading (a record a day) and routes (a record each) are read whatever the mapping says
    # (imports.fitbit_days).
    structured = [e.path for e in es if Path(e.path).suffix.lower() in (".json", ".csv", ".js") and not fitbit_reads(e.path)]
    mapped = set().union(*[s["files"] for s in stats]) if stats else set()
    for s in stats:
        s["files"] = len(s["files"])
    return {"mapping": m, "rules": stats, "structured": len(structured), "mapped": len(mapped),
            "unmapped": [p for p in structured if p not in mapped][:50]}


def save_mapping(folder, mapping):
    """corpus/mappings/<folder>.json, on this Mac only: the mappings that come with the app (data/mappings/) are
    part of a release and never written to from here. A mapping holds field names, none of the export's data."""
    import mapped_exports as mx
    d = CORPUS / "mappings"
    if mapping is None:
        (d / f"{folder}.json").unlink(missing_ok=True)
        return {"removed": folder}
    m = mx.validate(mapping)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{folder}.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    return {"saved": str(d / f"{folder}.json"), "mapping": m}


# ---------------------------------------------------------------- your other accounts, found in your data

SERVICES = Path(__file__).resolve().parents[1] / "data/services.json"  # scripts/build_services.py
TWO_LEVEL = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.jp", "ne.jp", "or.jp", "com.br",
             "com.cn", "com.mx", "co.in", "co.kr", "co.nz", "com.sg", "com.tr", "com.tw", "com.hk", "co.za", "com.ar",
             "co.il", "com.my", "com.ph", "co.id", "qc.ca", "on.ca", "bc.ca", "ab.ca"}
# Hosts that give every customer their own subdomain (the Public Suffix List's private section, in part): each site
# under them is its own. Without this, Matrix (whose directory entry lists two github.io pages) took every visit to
# any GitHub Pages site.
SHARED_HOSTS = {"github.io", "gitlab.io", "netlify.app", "vercel.app", "herokuapp.com", "pages.dev", "workers.dev", "web.app",
                "firebaseapp.com", "appspot.com", "blogspot.com", "azurewebsites.net", "cloudfront.net", "amazonaws.com",
                "readthedocs.io", "glitch.me", "fly.dev", "onrender.com", "surge.sh", "notion.site", "wixsite.com", "carrd.co",
                "neocities.org", "ngrok.io", "ngrok-free.app", "replit.app", "repl.co"}
# Mail and web hosts, not services that hold your data beyond the mail itself (the mailboxes are read anyway).
NOT_SERVICES = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com",
                "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com",
                "qq.com", "163.com", "126.com", "naver.com", "yandex.ru", "fastmail.com", "zoho.com", "hey.com",
                "amazonses.com", "sendgrid.net", "mailchimp.com", "mailgun.org", "mandrillapp.com", "mcsv.net",
                "rsgsv.net", "list-manage.com", "exacttarget.com", "sparkpostmail.com", "postmarkapp.com",
                "edu", "localhost"}
CORP = re.compile(r",?\s+(inc|llc|ltd|limited|corp|corporation|co|gmbh|s\.a|plc|pty|ag|bv|sa)\.?$", re.I)


def registrable(h):
    """mail.wattpad.com -> wattpad.com; shop.example.co.uk -> example.co.uk (and any com.xx, co.xx, org.xx);
    docs.someone.github.io -> someone.github.io."""
    parts = (h or "").lower().strip(".").split(".")
    if len(parts) >= 3 and (".".join(parts[-2:]) in TWO_LEVEL or ".".join(parts[-2:]) in SHARED_HOSTS or
                            (len(parts[-1]) == 2 and parts[-2] in ("com", "co", "net", "org", "ac", "gov", "edu", "ne", "or"))):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _norm_name(n):
    """Name for matching apps to services; too short (or not in Latin letters) to match on means None."""
    n = re.sub(r"[^a-z0-9]", "", CORP.sub("", (n or "").strip()).lower())
    return n if len(n) >= 3 else None


# ---------------------------------------------------------------- notifications
# macOS keeps the notifications still in Notification Center in one database; once cleared, they're gone. The app
# looks there for a service saying your data is ready. Only the matches for exports you asked for leave here.

MAC_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
# Words of a data request, not just "ready": a chat in the service's own app saying "is it ready?" isn't one.
READY = re.compile(r"\b(download|archive|your (\w+ )?(data|information|files)|copy of your|data (package|export|request)|"
                   r"export(ed)?|request (is |has been )?(complete|completed|processed|fulfilled))\b", re.I)
# "We got your request" isn't "it's ready": the confirmation a service sends when you ask (Google's "Archive of Google
# data requested") says so, and says nothing about being ready.
PENDING = re.compile(r"\b(requested|received your request|we('ve| have) received|preparing|being prepared|in progress|"
                     r"we('ll| will) (email|let you know|notify|send))\b", re.I)
READY_NOW = re.compile(r"\b(ready|available|is here|can now download|now download|has (been )?(completed?|finished|processed))\b", re.I)
ready_text = lambda t: bool(READY.search(t)) and not (PENDING.search(t) and not READY_NOW.search(t))
APP_NAMES = {"com.apple.mail": "Mail", "com.apple.mobilesms": "Messages", "com.apple.safari": "Safari",
             "com.google.chrome": "Chrome", "com.microsoft.outlook": "Outlook", "com.readdle.smartemail-mac": "Spark"}


# Notification Center's database and Mail's index are read from a copy: their apps keep writing to them. The copy is
# kept (in ~/Library/Caches, which Time Machine leaves out) and made again only once the files have changed; on APFS
# it's a clone, which shares the original's blocks instead of copying a gigabyte of mail index every few minutes.
COPIES = Path(os.environ.get("UMP_CACHE_DIR") or LIB / "Caches/Homecoming") / "copies"


def _clone(src, dst):
    """dst as an APFS clone of src (instant, and no space until one of them changes), else a plain copy."""
    try:
        if ctypes.CDLL(None).clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
            return
    except (OSError, AttributeError):
        pass
    shutil.copy2(src, dst)


@contextlib.contextmanager
def db_copy(db, name):
    """The path of a copy of SQLite database `db` (with its -wal and -shm) to read while in the block. Made again
    when any of them changed (size or time) since; one bridge at a time. Raises OSError if `db` can't be read (no
    Full Disk Access), and then the copy goes too: what can't be read there isn't kept here."""
    d = COPIES / name
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(COPIES, 0o700)
    with open(d / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(db, "rb") as f:  # as macOS sees it now, not as a copy remembers it
                f.read(1)
        except OSError:
            for s in ("", "-wal", "-shm", ".json"):
                (d / f"db{s}").unlink(missing_ok=True)
            raise
        stamp = {"db": str(db), "files": [[s, st.st_size, st.st_mtime_ns] for s in ("", "-wal", "-shm")
                                          for st in [_stat(f"{db}{s}")] if st]}
        try:
            same = json.loads((d / "db.json").read_text()) == stamp and (d / "db").exists()
        except (OSError, ValueError):
            same = False
        if not same:
            for s in (".json", "", "-wal", "-shm"):  # one the database no longer has mustn't be read with the new copy
                (d / f"db{s}").unlink(missing_ok=True)
            for s, *_ in stamp["files"]:
                _clone(f"{db}{s}", d / f"db{s}")
            (d / "db.json").write_text(json.dumps(stamp))  # as it was before the copy: changed during it, copied again
        yield d / "db"


def _stat(p):
    try:
        return os.stat(p)
    except FileNotFoundError:
        return None


def _readable(p):
    """Whether this app may read the file (Full Disk Access), asked of the file itself: nothing is copied for it."""
    try:
        with open(p, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


def drop_copy(name):
    """The copy kept for a place that's no longer looked in (turned off in General): gone, once no bridge is reading
    it (db_copy's lock)."""
    d = COPIES / name
    if not d.exists():
        return
    with open(d / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for p in d.iterdir():
            if p.name != "lock":
                p.unlink(missing_ok=True)
        (d / "lock").unlink(missing_ok=True)
    try:
        d.rmdir()
    except OSError:
        pass


def _read_only(p):
    return f"file:{quote(str(p))}?mode=ro"


def notification_db():
    if os.environ.get("UMP_NOTIFICATIONS_DB"):
        return Path(os.environ["UMP_NOTIFICATIONS_DB"])
    new = LIB / "Group Containers/group.com.apple.usernoted/db2/db"  # macOS 15 and later
    if new.exists():
        return new
    try:  # before macOS 15
        d = subprocess.run(["getconf", "DARWIN_USER_DIR"], capture_output=True, text=True, timeout=5).stdout.strip()
        return Path(d) / "com.apple.notificationcenter/db2/db"
    except (OSError, subprocess.SubprocessError):
        return new


def notifications(since):
    """(when, app id, title, subtitle, body) of each notification delivered since `since`, or None if the
    database can't be read (no Full Disk Access). Read from a copy: Notification Center keeps writing to it."""
    db = notification_db()
    try:
        with db_copy(db, "notifications") as copy:
            con = sqlite3.connect(_read_only(copy), uri=True)
            try:
                rows = con.execute("select a.identifier, r.delivered_date, r.data from record r join app a on a.app_id = r.app_id "
                                   "where r.delivered_date >= ?", ((since - MAC_EPOCH).total_seconds(),)).fetchall()
            finally:
                con.close()
    except (OSError, sqlite3.Error):
        return None
    out = []
    for ident, when, data in rows:
        try:
            req = plistlib.loads(data).get("req") or {}
        except Exception:
            continue
        out.append((MAC_EPOCH + dt.timedelta(seconds=when or 0), ident or "", _text(req.get("titl")), _text(req.get("subt")),
                    _text(req.get("body"))))
    return out


def notification_shown(title, since):
    """Whether a notification with this title, posted since `since` (ISO), reached Notification Center, and whether
    macOS put it on screen: it can keep one without showing it (the app's notifications allowed, but delivered quietly
    or set to None). {"readable": False} without Full Disk Access."""
    db = notification_db()
    try:
        with db_copy(db, "notifications") as copy:
            con = sqlite3.connect(_read_only(copy), uri=True)
            try:
                when =(dt.datetime.fromisoformat(since.replace("Z", "+00:00")) - MAC_EPOCH).total_seconds()
                rows = con.execute("select a.identifier, r.data, r.presented from record r join app a on a.app_id = r.app_id "
                                   "where r.delivered_date >= ? order by r.delivered_date desc", (when,)).fetchall()
            finally:
                con.close()
    except (OSError, sqlite3.Error, ValueError):
        return {"readable": False}
    if os.environ.get("UMP_READY_NOTIFICATIONS") == "0":  # not looked in for exports (General): no copy kept for this one
        drop_copy("notifications")
    for ident, data, presented in rows:
        try:
            req = plistlib.loads(data).get("req") or {}
        except Exception:
            continue
        if _text(req.get("titl")) == title:
            return {"readable": True, "found": True, "presented": bool(presented), "app": ident}
    return {"readable": True, "found": False}


def notification_prefs(bundle):
    """This app's switches in Notification settings, as macOS keeps them: whether its notifications are allowed, and
    their style (none: kept in Notification Center without showing; banners; alerts). From usernoted's preferences
    (in its group container since macOS 15; com.apple.ncprefs before), each app's flags: bit 25 allows them, bit 3 is
    banners and bit 4 alerts. {"readable": False} if they can't be read, {"found": False} before macOS has asked."""
    paths = [Path(os.environ["UMP_NOTIFICATION_PREFS"])] if os.environ.get("UMP_NOTIFICATION_PREFS") else [
        LIB / "Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist",
        LIB / "Preferences/com.apple.ncprefs.plist"]
    for p in paths:
        try:
            prefs = plistlib.loads(p.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        for a in prefs.get("apps") or []:
            if isinstance(a, dict) and a.get("bundle-id") == bundle and isinstance(a.get("flags"), int):
                f = a["flags"]
                return {"readable": True, "found": True, "allowed": bool(f >> 25 & 1),
                        "style": "alerts" if f >> 4 & 1 else "banners" if f >> 3 & 1 else "none"}
        return {"readable": True, "found": False}
    return {"readable": False}


def _text(x):
    """A notification field: usually a string, sometimes a list (a localized format and its arguments)."""
    if isinstance(x, list):
        return " ".join(_text(y) for y in x if not isinstance(y, (dict, bytes)))
    return x if isinstance(x, str) else ""


# ---------------------------------------------------------------- mail
# Apple Mail keeps an index of every message (sender, subject, the first lines) in one SQLite database, and each
# message as an .emlx file. A service's "your data is ready" email is the surest sign there is, and it holds the
# download link. Read on this Mac, from a copy; only the matches for exports you asked for leave here.

def mail_db():
    if os.environ.get("UMP_MAIL_DB"):
        return Path(os.environ["UMP_MAIL_DB"])
    dbs = sorted((LIB / "Mail").glob("V*/MailData/Envelope Index"), key=lambda x: int(re.sub(r"\D", "", x.parts[-3]) or 0))
    return dbs[-1] if dbs else None


def mail_messages(since):
    """(when, rowid, sender address, sender name, subject, first lines, mailbox url) of each message received since
    `since`, newest first, or None if there's no Mail database or it can't be read."""
    db = mail_db()
    if not db or not db.exists():
        return None
    try:
        with db_copy(db, "mail") as copy:
            con = sqlite3.connect(_read_only(copy), uri=True)
            try:
                rows = con.execute(
                    "select m.date_received, m.ROWID, a.address, a.comment, s.subject, su.summary, mb.url from messages m "
                    "left join addresses a on a.ROWID = m.sender left join subjects s on s.ROWID = m.subject "
                    "left join summaries su on su.ROWID = m.summary left join mailboxes mb on mb.ROWID = m.mailbox "
                    "where m.date_received >= ? and m.deleted = 0 order by m.date_received desc limit 5000",
                    (int(since.timestamp()),)).fetchall()
            finally:
                con.close()
    except (OSError, sqlite3.Error):
        return None
    return [(dt.datetime.fromtimestamp(w or 0, dt.timezone.utc), rid, addr or "", name or "", subj or "", summ or "", url or "")
            for w, rid, addr, name, subj, summ, url in rows]


def mail_file(rowid, mailbox_url):
    """The .emlx (or .partial.emlx) holding a message, under its account's folder."""
    db = mail_db()
    if not db:
        return None
    account = urlparse(mailbox_url).netloc
    root = db.parent.parent / account if account and (db.parent.parent / account).is_dir() else db.parent.parent
    for name in (f"{rowid}.emlx", f"{rowid}.partial.emlx"):
        for f in root.rglob(name):
            return f
    return None


LINK_WORDS = re.compile(r"download|takeout|dyi|export|archive|your[-_]?data|data[-_]?request|privacy", re.I)


def mail_link(rowid, mailbox_url, domains):
    """The link in a message most likely to be the download: on the service's own domains, with download-ish words."""
    f = mail_file(rowid, mailbox_url)
    if not f:
        return None
    try:
        raw = f.read_bytes()
        n = int(raw.split(b"\n", 1)[0].strip())
        import email
        from email import policy
        msg = email.message_from_bytes(raw.split(b"\n", 1)[1][:n], policy=policy.default)
        texts = []
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try:
                    texts.append(part.get_content())
                except Exception:
                    continue
    except (OSError, ValueError, IndexError):
        return None
    regs = {registrable(d) for d in domains if d}
    best = None
    for t in texts:
        for u in re.findall(r"https?://[^\s\"'<>()]+", t):
            u = u.replace("&amp;", "&").rstrip(".,;")
            host = urlparse(u).hostname or ""
            if regs and registrable(host) not in regs:
                continue
            score = (2 if LINK_WORDS.search(u) else 0) + (1 if "unsubscribe" not in u.lower() and "help" not in u.lower() else -3)
            if best is None or score > best[0]:
                best = (score, u)
    return best[1] if best and best[0] > 0 else None


def export_signals(asked):
    """Signs that an export you asked for is ready: an email (Apple Mail) or a notification that names the service
    (or comes from its domains, its app, or a sender by that name) and sounds ready. A guess, shown as "looks ready";
    an email from the service's own domain is a strong one, and carries the download link when there is one.
    asked: [{"id", "names": [...], "domains": [...], "since": ISO time, "seen": ISO time of the last sign already known}]."""
    if not asked:
        return {"readable": True, "mail": False, "matches": []}
    when_of = lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00"))
    start = min(when_of(a["since"]) for a in asked)
    # Your Setup can turn either off (UMP_READY_NOTIFICATIONS=0, UMP_READY_MAIL=0): then it isn't looked in at all.
    found = notifications(start) if os.environ.get("UMP_READY_NOTIFICATIONS") != "0" else None
    mails = mail_messages(start) if os.environ.get("UMP_READY_MAIL") != "0" else None
    best = {}

    def named(a, text, sender=""):
        names = [n.lower() for n in a["names"] if n.strip()]
        hit = any(sender.strip().lower() == n for n in names)  # a mail from "X", a notification titled "Reddit"
        return hit or any(len(n) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", text.lower()) for n in names)

    def keep(a, when, via, text, **more):
        if when < when_of(a["since"]) or (a.get("seen") and when <= when_of(a["seen"])):
            return
        cur = best.get(a["id"])
        # An email in Mail's index beats a notification about the same thing (it has the link); then the newest wins.
        if cur is None or ("mail" in more, when) > ("mail" in cur, cur["when"]):
            best[a["id"]] = {"when": when, "via": via, "text": re.sub(r"\s+", " ", text)[:200], **more}

    for when, ident, title, subtitle, body in found or []:
        text = " ".join(x for x in (title, subtitle, body) if x)
        if not ready_text(text):
            continue
        for a in asked:
            if named(a, f"{text} {ident}", title):
                via = APP_NAMES.get(ident.lower()) or next((v for k, v in APP_NAMES.items() if ident.lower().startswith(k)), None) \
                    or ident.split(".")[-1].replace("-", " ").title()
                keep(a, when, via, text)
    for when, rowid, addr, name, subject, summary, mailbox in mails or []:
        text = f"{subject} {summary}"
        if not ready_text(text) or re.search(r"(^|/)(junk|spam|bulk)", unquote(mailbox or "").lower()):
            continue  # Junk isn't the service writing to you
        sender_domain = registrable(addr.rsplit("@", 1)[-1]) if "@" in addr else ""
        for a in asked:
            ours = sender_domain and sender_domain in {registrable(d) for d in a.get("domains") or [] if d}
            if ours:  # from the service's own domain: sure, with its link
                keep(a, when, "Mail", subject or summary, subject=subject, sender=name or addr, mail=rowid, mailbox=mailbox)
            elif named(a, f"{subject} {name}", name):  # only naming it (anyone can): a guess, like a notification, and no link
                keep(a, when, "Mail", subject or summary)
    out = []
    for k, v in best.items():
        a = next(x for x in asked if x["id"] == k)
        link = mail_link(v["mail"], v["mailbox"], (a.get("domains") or [])) if "mail" in v else None
        out.append({"source": k, "at": v["when"].isoformat(timespec="milliseconds"), "via": v["via"], "text": v["text"],
                    **({"link": link} if link else {}), **({"sender": v["sender"]} if v.get("sender") else {})})
    return {"readable": found is not None or mails is not None, "mail": mails is not None, "matches": out}


def notification_access():
    """Whether the app can read notifications, and whether this Mac gets the iPhone's ("Allow notifications from
    iPhone"): those apps are listed in Notification Center's settings with no app on this Mac."""
    readable = _readable(notification_db())
    prefs = LIB / "Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist"
    iphone = False
    try:
        for a in plistlib.loads(prefs.read_bytes()).get("apps") or []:
            if not isinstance(a, dict) or str(a.get("bundle-id", "")).startswith("_SYSTEM_CENTER_"):
                continue
            paths = [x.get("path") for x in a.get("src") or [] if isinstance(x, dict) and x.get("path")] + ([a["path"]] if a.get("path") else [])
            if not any(Path(x).exists() for x in paths):
                iphone = True
                break
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    return {"readable": readable, "iphone": iphone}


def mac_apps():
    """(name, bundle id) of every app in /Applications and ~/Applications."""
    out = []
    for root in (Path(os.environ.get("UMP_APPLICATIONS") or "/Applications"), HOME / "Applications"):
        for app in sorted(root.glob("*.app")) + sorted(root.glob("*/*.app")):
            try:
                info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            except Exception:
                continue
            out.append((info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem, info.get("CFBundleIdentifier") or ""))
    return out


def discover_services():
    """Services you have an account with, from evidence in the corpus and on this Mac: who emails you (mail you
    received), sites you visit, apps on the iPhone and the Mac. Matched against services.json by domain and
    app name; mail senders that match nothing are returned too, so obscure services still show up."""
    services = json.loads(SERVICES.read_text()) if SERVICES.exists() else []
    by_domain, by_name = {}, {}
    by_slug = {s["slug"]: s for s in services}
    for s in services:
        for d in s["domains"]:
            by_domain.setdefault(d, s)
            by_domain.setdefault(registrable(d), s)
        if _norm_name(s["name"]):
            by_name.setdefault(_norm_name(s["name"]), s)
    ev = {}

    def E(key):
        return ev.setdefault(key, {"emails": 0, "first": None, "last": None, "visits": 0, "apps": [], "senders": collections.Counter(),
                                   "names": collections.Counter()})

    db = CORPUS / "corpus.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) if db.exists() else None
    if con:
        try:
            for frm, ts in con.execute("select json_extract(meta, '$.from'), ts from records where kind = 'email' "
                                       "and coalesce(is_me, '0') in ('0', 0, 'false') and json_extract(meta, '$.from') is not null"):
                m = re.search(r"@([\w.-]+\.[a-z]{2,})", str(frm), re.I)
                if not m:
                    continue
                dom = registrable(m.group(1))
                if dom in NOT_SERVICES or dom.split(".")[-1] in NOT_SERVICES:
                    continue
                e = E(dom)
                e["emails"] += 1
                if ts:
                    e["first"] = min(e["first"] or ts, ts)
                    e["last"] = max(e["last"] or ts, ts)
                local = str(frm).split("<")[-1].split("@")[0].strip().lower()
                e["senders"][local] += 1
                shown = str(frm).split("<")[0].strip().strip('"').strip()
                if shown and "@" not in shown:
                    e["names"][shown] += 1
            for url, n in con.execute("select url, count(*) from records where source in ('browser_history', 'chrome_synced', "
                                      "'phone_safarihistory') and url like 'http%' group by url"):
                dom = registrable(urlparse(url).hostname or "")
                if dom and dom not in NOT_SERVICES:
                    E(dom)["visits"] += n
            phone_apps = con.execute("select title, json_extract(meta, '$.bundle'), json_extract(meta, '$.developer') "
                                     "from records where source = 'phone_installed_apps'").fetchall()
        except sqlite3.Error:
            phone_apps = []
        con.close()
    else:
        phone_apps = []
    apps = [(n, b, d, "iPhone") for n, b, d in phone_apps] + [(n, b, None, "Mac") for n, b in mac_apps()]
    for name, bundle, developer, where in apps:
        if (bundle or "").startswith("com.apple."):
            continue
        parts = (bundle or "").lower().split(".")
        dom = f"{parts[1]}.{parts[0]}" if len(parts) >= 2 and parts[0] in ("com", "net", "org", "io", "co", "me", "app", "tv") else None
        s = by_domain.get(dom) if dom else None
        s = s or by_name.get(_norm_name(name) or "") or by_name.get(_norm_name(developer) or "")
        key = f"svc:{s['slug']}" if s else (dom or _norm_name(name) or name)
        label = f"{name} on your {where}"
        if label not in E(key)["apps"]:
            E(key)["apps"].append(label)
    found, unmatched = {}, []
    for dom, e in ev.items():
        s = by_slug.get(dom[4:]) if dom.startswith("svc:") else by_domain.get(dom)
        if not s and "." in dom:  # facebookmail.com, redditmail.com, lyftmail.com, uberemail.com...
            base, tld = dom.split(".", 1)
            stem = re.sub(r"(e?mail|news|info|notifications?)$", "", base)
            s = by_domain.get(f"{stem}.{tld}") if stem and stem != base else None
        auto = sum(n for who, n in e["senders"].items() if re.search(r"no.?reply|notif|info|hello|team|support|news|account|"
                                                                     r"updates?|mail|alerts?|security|welcome|accounts|do.?not.?reply", who))
        names = e["names"]
        e = {k: v for k, v in e.items() if k not in ("senders", "names")}
        e["automated"] = auto
        if s:
            cur = found.setdefault(s["slug"], {**{k: s.get(k) for k in ("slug", "name", "domains", "site", "export", "privacy_email", "popular") if s.get(k)},
                                               "emails": 0, "first": None, "last": None, "visits": 0, "apps": [], "automated": 0})
            for k in ("emails", "visits", "automated"):
                cur[k] += e[k]
            cur["apps"] = sorted(set(cur["apps"]) | set(e["apps"]))
            for k, f in (("first", min), ("last", max)):
                if e[k]:
                    cur[k] = f(cur[k] or e[k], e[k])
        elif e["automated"] >= 3 or e["apps"]:
            # What to call it: the name its mail comes from most often, else its app's name, else the domain.
            app = re.split(r"\s+[-–:|]\s+|: ", e["apps"][0])[0].removesuffix(f" on your iPhone").removesuffix(" on your Mac") if e["apps"] else None
            unmatched.append({"domain": dom, "name": names.most_common(1)[0][0] if names else app or dom, **e})
    def strength(x):
        return (len(x["apps"]) * 50) + min(x["automated"], 200) + min(x["emails"], 100) / 4 + min(x["visits"], 500) / 10
    found = [x for x in found.values() if x["apps"] or x["automated"] >= 2 or x["emails"] >= 5 or x["visits"] >= 20]
    found.sort(key=strength, reverse=True)
    unmatched.sort(key=strength, reverse=True)
    return {"found": found, "unmatched": unmatched[:200], "services": len(services)}


# ---------------------------------------------------------------- who you are, found rather than remembered

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
SENT_FOLDERS = ("sent", "sent items", "sent messages", "sent mail")


class Candidates:
    """Names, email addresses, usernames and phone numbers that evidence says are the person's, each with
    where it was seen. strong: confident enough to be ticked by default."""

    def __init__(self):
        self.items = {}

    @staticmethod
    def norm(kind, value):
        v = str(value or "").strip().strip("<>\"'")
        if kind == "email":
            m = EMAIL_RE.search(v)
            return m.group(0).lower() if m else None
        if kind == "phone":
            from phones import e164
            return e164(v) if len(re.sub(r"\D", "", v)) >= 7 else None
        if kind == "username":
            v = v.lstrip("@").lower()
            return v if 2 <= len(v) <= 40 and " " not in v else None
        v = re.sub(r"\s+", " ", v)
        return v if 2 <= len(v) <= 80 and not EMAIL_RE.search(v) else None

    def add(self, kind, value, label, count=None, strong=True):
        v = self.norm(kind, value)
        if not v:
            return
        key = (kind, v.lower())
        c = self.items.setdefault(key, {"kind": kind, "value": v, "sources": [], "strong": False})
        if not any(s["label"] == label for s in c["sources"]):
            c["sources"].append({"label": label, **({"count": count} if count else {})})
        c["strong"] = c["strong"] or strong

    def result(self):
        order = {"name": 0, "email": 1, "username": 2, "phone": 3}
        return sorted(self.items.values(), key=lambda c: (order[c["kind"]], not c["strong"], -len(c["sources"]), c["value"].lower()))


def _try(fn):
    try:
        fn()
    except Exception:
        pass


def _sent_handles(db, c, label):
    """The addresses and numbers Messages sent from (message.account is "E:addr" or "P:+1..."), with counts."""
    if access(db) != "ok":
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    for account, n in con.execute("select account, count(*) from message where is_from_me = 1 and account like '_:%' group by 1"):
        kind = "email" if account[0] in "Ee" else "phone"
        c.add(kind, account[2:], label, count=n, strong=n >= 5)
    con.close()


def _aliases(plist, c, label):
    d = read_plist(plist) or {}
    for v in (d.get("IMD-IDS-Aliases") or {}).get("allAliases") or []:
        c.add("email" if "@" in v else "phone", v, label)


def mac_candidates(c):
    def account():
        if HOME != Path(os.path.expanduser("~" + os.environ.get("USER", ""))):
            return  # a test HOME isn't this account
        full = subprocess.run(["id", "-F"], capture_output=True, text=True).stdout.strip()
        c.add("name", full, "Mac user account")
        c.add("username", os.environ.get("USER") or HOME.name, "Mac user account", strong=False)

    def apple_id():
        for a in (read_plist(LIB / "Preferences/MobileMeAccounts.plist") or {}).get("Accounts") or []:
            c.add("email", a.get("AccountID"), "Apple ID")

    def internet_accounts():
        db = LIB / "Accounts/Accounts4.sqlite"
        if access(db) != "ok":
            return
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        for user, kind in con.execute("select a.ZUSERNAME, t.ZACCOUNTTYPEDESCRIPTION from ZACCOUNT a join ZACCOUNTTYPE t "
                                      "on a.ZACCOUNTTYPE = t.Z_PK where a.ZUSERNAME is not null"):
            if user and "@" in user:
                c.add("email", user, "Internet Accounts")
        con.close()

    def chrome():
        import browsers
        for bid, bname, _, _, kind, root, _ in browsers.BROWSERS:
            if kind != "chromium" or not (root / "Local State").exists():
                continue
            st = json.loads((root / "Local State").read_text())
            for p in (st.get("profile") or {}).get("info_cache", {}).values():
                c.add("email", p.get("user_name"), f"{bname} profile")
                c.add("name", p.get("gaia_name"), f"{bname} profile")

    def claude():
        oa = json.loads((HOME / ".claude.json").read_text()).get("oauthAccount") or {}
        c.add("email", oa.get("emailAddress"), "Claude account")
        c.add("name", oa.get("fullName"), "Claude account")

    def git():
        from common import git_bin
        if not git_bin():  # the stub would ask to install the developer tools
            return
        out = subprocess.run([git_bin(), "config", "--global", "--get-regexp", r"^user\.(name|email)$"], capture_output=True, text=True,
                             env={**os.environ, "HOME": str(HOME)}).stdout
        for line in out.splitlines():
            k, _, v = line.partition(" ")
            c.add("email" if k.endswith("email") else "name", v, "git config")

    def contacts_card():
        s = suggest_identity() or {}
        for k, kind in (("names", "name"), ("emails", "email"), ("phones", "phone")):
            for v in s.get(k, []):
                c.add(kind, v, "Your Contacts card")

    for fn in (account, apple_id, internet_accounts, chrome, claude, git, contacts_card,
               lambda: _aliases(LIB / "Preferences/com.apple.madrid.plist", c, "Messages (iMessage address)"),
               lambda: _sent_handles(LIB / "Messages/chat.db", c, "Messages on this Mac")):
        _try(fn)
    phone = CORPUS / "raw/iphone/files/HomeDomain/Library"
    _try(lambda: _sent_handles(phone / "SMS/sms.db", c, "Messages on the iPhone"))
    _try(lambda: _aliases(phone / "Preferences/com.apple.madrid.plist", c, "iPhone (iMessage address)"))


def _meta_text(s):
    """Meta exports store UTF-8 as Latin-1 escapes ("Ã©"): undo that."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeError, AttributeError):
        return s


def export_candidates(c):
    root = CORPUS / "imports"
    if not root.exists():
        return
    zips = [p for p in root.rglob("*.zip") if not any(part.startswith(".") for part in p.relative_to(root).parts)]

    def read(z, suffix):
        # (a profile's file is small: one that isn't, or is locked, isn't read)
        i = next((x for x in z.infolist() if x.filename.endswith(suffix)), None)
        return z.read(i) if i and i.file_size < 50 << 20 and not common.zip_problem(i) else None

    def opened(zp):
        # LinkedIn delivers a zip inside a zip; look inside small inner zips too, one at a time.
        try:
            z = zipfile.ZipFile(zp)
        except (zipfile.BadZipFile, OSError):
            return
        with z:
            yield z
            for info in z.infolist():
                if info.filename.lower().endswith(".zip") and info.file_size < 200 << 20 and not common.zip_problem(info) \
                        and not common.looks_like_bomb(info, floor=1 << 20):
                    try:
                        with common.open_nested(z, info) as inner:
                            yield inner
                    except (zipfile.BadZipFile, OSError, EOFError, zlib.error):
                        pass

    for z in (z for zp in zips for z in opened(zp)):
        def linkedin():
            import csv
            for suffix, kind, col in (("Email Addresses.csv", "email", "Email Address"), ("PhoneNumbers.csv", "phone", "Number")):
                raw = read(z, suffix)
                for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))) if raw else []:
                    c.add(kind, row.get(col), "LinkedIn export")
            raw = read(z, "Profile.csv")
            for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))) if raw else []:
                c.add("name", f"{row.get('First Name', '')} {row.get('Last Name', '')}", "LinkedIn export")

        def instagram():
            raw = read(z, "personal_information/personal_information/personal_information.json")
            if not raw:
                return
            for prof in json.loads(raw).get("profile_user") or []:
                m = prof.get("string_map_data") or {}
                val = lambda k: _meta_text((m.get(k) or {}).get("value"))
                c.add("email", val("Email"), "Instagram export")
                c.add("username", val("Username"), "Instagram export")
                c.add("name", val("Name"), "Instagram export")
                c.add("phone", val("Phone Number"), "Instagram export")

        def facebook():
            raw = read(z, "profile_information/profile_information.json")
            if not raw:
                return
            p = json.loads(raw).get("profile_v2") or {}
            c.add("name", _meta_text((p.get("name") or {}).get("full_name")), "Facebook export")
            for e in (p.get("emails") or {}).get("emails") or []:
                c.add("email", e, "Facebook export")
            for ph in p.get("phone_numbers") or []:
                c.add("phone", ph.get("phone_number"), "Facebook export")
            for prev in p.get("previous_names") or []:
                c.add("name", _meta_text(prev.get("name")), "Facebook export (previous name)", strong=False)

        def discord():
            raw = read(z, "Account/user.json")
            if raw:
                u = json.loads(raw)
                c.add("username", u.get("username"), "Discord export")
                c.add("name", u.get("global_name"), "Discord export", strong=False)
                c.add("email", u.get("email"), "Discord export")
                c.add("phone", u.get("phone"), "Discord export")

        def x():
            raw = read(z, "data/account.js")
            if raw:
                t = raw.decode("utf-8", "replace")
                for a in json.loads(t[t.index("=") + 1:]):
                    a = a.get("account") or {}
                    c.add("email", a.get("email"), "X export")
                    c.add("username", a.get("username"), "X export")
                    c.add("name", a.get("accountDisplayName"), "X export", strong=False)

        def ai_accounts():
            raw = read(z, "user.json")
            if raw and b'"email"' in raw:
                c.add("email", json.loads(raw).get("email"), "ChatGPT export")
            raw = read(z, "users.json")
            if raw:
                for u in json.loads(raw):
                    c.add("email", u.get("email_address"), "Claude.ai export")
                    c.add("name", u.get("full_name"), "Claude.ai export")

        for fn in (linkedin, instagram, facebook, discord, x, ai_accounts):
            _try(fn)


def mailbox_candidates(c):
    """Mailboxes say whose they are: the address their sent mail came from, else the one most mail went to."""
    db = CORPUS / "corpus.db"
    if not db.exists():
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    sources = [r[0] for r in con.execute("select distinct source from records where kind = 'email'")]
    for src in sources:
        sent = collections_counter()
        for frm, in con.execute(
                "select json_extract(meta, '$.from') from records where source = ? and kind = 'email' and "
                "(json_extract(meta, '$.labels') like '%Sent%' or lower(json_extract(meta, '$.folder')) in "
                "('sent', 'sent items', 'sent messages', 'sent mail'))", (src,)):
            m = EMAIL_RE.search(frm or "")
            if m:
                sent[m.group(0).lower()] += 1
        label = src.replace("_", " ").title() if src != "gmail" else "Gmail"
        for addr, n in sent.most_common(3):
            if n >= 5:
                c.add("email", addr, f"{label}: sent mail", count=n)
        if not sent:
            to = collections_counter()
            total = 0
            for addr, in con.execute("select lower(j.value) from records, json_each(json_extract(records.meta, '$.to')) j "
                                     "where records.source = ? and records.kind = 'email'", (src,)):
                total += 1
                m = EMAIL_RE.search(addr or "")
                if m:
                    to[m.group(0).lower()] += 1
            for addr, n in to.most_common(1):
                if total and n / total > 0.25:
                    c.add("email", addr, f"{label}: receives the mail", count=n)
    con.close()


# Chat sources whose "is this me?" is decided by name. Whoever is in (almost) every conversation of an export
# is its owner: that finds the nickname or old display name nobody would think to type in.
CHAT_SOURCES = {"google_chat": "Google Chat", "whatsapp_export": "WhatsApp", "slack": "Slack", "linkedin": "LinkedIn messages",
                "reddit": "Reddit messages", "messenger": "Messenger", "instagram": "Instagram"}


def chat_candidates(c):
    db = CORPUS / "corpus.db"
    if not db.exists():
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    for src, label in CHAT_SOURCES.items():
        total = con.execute("select count(distinct thread) from records where source = ? and kind = 'message'", (src,)).fetchone()[0]
        if total < 3:
            continue
        need = max(3, -(-total * 8 // 10))  # at least 80% of the chats
        for author, n in con.execute(
                "select author, count(distinct thread) n from records where source = ? and kind = 'message' and author is not null "
                "and author != 'me' group by author having n >= ? order by n desc limit 3", (src, need)):
            c.add("email" if "@" in author else "name", author, f"{label}: in {n} of {total} chats")
    con.close()


def collections_counter():
    import collections
    return collections.Counter()


def identity_candidates():
    c = Candidates()
    mac_candidates(c)
    export_candidates(c)
    _try(lambda: mailbox_candidates(c))
    _try(lambda: chat_candidates(c))
    return {"candidates": c.result()}


# ---------------------------------------------------------------- identify downloads

UUIDISH = re.compile(r"^Export-[0-9a-f-]{20,}")
NOTION_PAGE = re.compile(r" [0-9a-f]{32}(_all)?\.(md|csv)$")
TAKEOUT_NAME = re.compile(r"takeout-(\d{8})T?\d*Z?-?(\d+)?-?(\d+)?", re.I)
# Photos and Drive, as Takeout names them in English, German, Spanish, French, Italian, Portuguese, Dutch...
TAKEOUT_MEDIA = re.compile(r"^(Google (Photos|Fotos|Foto|Zdjęcia)|Drive|Google Drive)$", re.I)


# A download a browser is still writing: Chrome's .crdownload ("Unconfirmed 1234.crdownload" at first), Safari's .download (a
# folder), Firefox's .part (beside an empty file under the final name), Opera's .opdownload; Mail's .partial.mbox. As downloads.ts's.
PARTIAL = re.compile(r"\.(crdownload|download|part|partial|tmp|opdownload)$|\.partial\.mbox$|^Unconfirmed \d+", re.I)
# Meta names its downloads instagram-<username>-<date>-<id>.zip and facebook-…: a part of one holding only photos and videos
# (media/, messages/<chat>/photos/) is told by its name, with these at its top.
META_NAME = re.compile(r"^(instagram|facebook)-.+-\d", re.I)
META_ROOTS = {"media", "messages", "photos_and_videos", "posts", "personal_information", "connections", "your_instagram_activity",
              "your_facebook_activity", "your_activity_across_facebook", "logged_information", "preferences", "ads_information"}


def _zip_names(z, limit=200_000):
    """A zip's members, named as its zip meant (common.member_name), without what a Mac adds: {name: its ZipInfo}."""
    out = {}
    for i in z.infolist()[:limit]:
        n = common.member_name(i)
        if not common.junk_member(n):
            out[n] = i
    return out


def _peek(z, info, n=200_000):
    with z.open(info) as f:
        return f.read(n).decode("utf-8", "replace")


def _zip_kind(z, filename="", depth=0):
    """What a zip is: {kind, entries}, or why it can't be used (locked, packed in a way that can't be read here, empty, a
    zip bomb). A zip with only a zip in it is looked into, two deep (LinkedIn's .zip.zip, WhatsApp's zip in a zip), in
    place: never all of it in memory."""
    infos = _zip_names(z)
    if any(i.flag_bits & 0x1 for i in infos.values()):  # WeChat's, for one: unzipped with the password it shows
        return {"valid": False, "encrypted": True, "reason": "locked with a password"}
    if any(common.zip_problem(i) for i in infos.values()):  # Windows packs big files with Deflate64, which Finder unpacks
        return {"valid": False, "needs_unzip": True, "reason": "packed in a way that can't be read here"}
    names = list(infos)
    if not any(not n.endswith("/") for n in names):
        return {"kind": None, "entries": len(names), "empty": True, "reason": "empty"}
    kind = classify_names(names, peek=lambda n: _peek(z, infos[n]), filename=filename)
    inner = [i for n, i in infos.items() if n.lower().endswith(".zip")]
    if not kind and len(inner) == 1 and len(names) <= 3 and depth < 2:
        if common.looks_like_bomb(inner[0], floor=1 << 20):
            return {"valid": False, "reason": "unpacks to far more than its size, which only a zip bomb does"}
        with common.open_nested(z, inner[0]) as zz:
            found = _zip_kind(zz, depth=depth + 1)
        if found.get("kind") or found.get("valid") is False:
            return {**found, "entries": len(names)}
    return {"kind": kind, "entries": len(names)}


def _partial(p):
    """Whether a browser is still writing p: by its name, or (Firefox) the .part beside it."""
    return bool(PARTIAL.search(p.name)) or any(p.with_name(p.name + x).exists() for x in (".part", ".crdownload", ".download"))


def classify_names(names, peek=None, filename=""):
    """The export kind from a listing of paths inside a zip or folder."""
    roots = {n.split("/")[0] for n in names}
    base = {n.rsplit("/", 1)[-1] for n in names}
    if any(n.startswith("Takeout/") for n in names):
        # By its folders, in whatever language the account uses: only Photos and Drive is that export, anything
        # else (Mail, Meine Aktivitäten, Correo...) is the main one.
        dirs = {n.split("/")[1] for n in names if n.startswith("Takeout/") and n.count("/") >= 2}
        media = {d for d in dirs if TAKEOUT_MEDIA.match(d)}
        return "google_photos_drive" if media and not (dirs - media) else "google_takeout"
    if "your_instagram_activity" in roots or any("/your_instagram_activity/" in n for n in names[:2000]):
        return "instagram"
    if roots & {"your_facebook_activity", "your_activity_across_facebook"} or \
            any("/your_facebook_activity/" in n or "/your_activity_across_facebook/" in n for n in names[:2000]):
        return "facebook"
    if any(re.match(r"(.*/)?Messages/(index\.json|c\d+/)", n) for n in names) and ("Account" in roots or "Servers" in roots or any("/Account/" in n for n in names[:50])):
        return "discord"
    if "Connections.csv" in base and ({"Registration.csv", "Profile.csv", "Email Addresses.csv"} & base):
        return "linkedin"
    if any(UUIDISH.match(r) for r in roots) or sum(bool(NOTION_PAGE.search(n)) for n in names[:500]) >= 2:
        return "notion"
    if any(n.endswith(("data/tweets.js", "data/account.js", "data/direct-messages.js")) for n in names):
        return "x"
    conv = [n for n in names if n.rsplit("/", 1)[-1] == "conversations.json"]
    if conv and peek:
        head = peek(conv[0])
        if '"chat_messages"' in head:
            return "claude_ai"
        if '"mapping"' in head:
            return "chatgpt"
    if any("StreamingHistory" in n or "Streaming_History" in n for n in names):
        return "spotify"
    if {"comments.csv", "posts.csv"} <= base or {"statistics.csv", "ip_logs.csv"} <= base:
        return "reddit"
    if "_chat.txt" in base or any(re.search(r"WhatsApp Chat", n) for n in names):
        return "whatsapp_chats"
    if {"users.json", "channels.json"} <= base:
        return "slack"
    files = [n for n in names if not n.endswith("/")]
    # Mail: mailboxes, an Outlook for Mac archive (.olm, a zip), or a folder of messages dragged out of a mail app
    mail = sum(n.lower().endswith((".eml", ".emlx")) for n in files)
    if any(n.lower().endswith(".mbox") or n.endswith(".mbox/mbox") for n in names) or \
            any("com.microsoft.__Messages/" in n for n in names) or mail and mail * 2 >= len(files):
        return "mailbox"
    if files and all(n.lower().endswith(".vtt") for n in files):
        return "zoom"
    if any(n.rsplit("/", 1)[-1] in ("Timeline.json", "location-history.json") for n in names):
        return "maps_timeline"
    m = META_NAME.match(filename)  # a part of a Meta download with only its photos and videos
    if m and roots & META_ROOTS:
        return "instagram" if m.group(1).lower() == "instagram" else "facebook"
    return None


def identify(path):
    p = Path(path)
    res = {"path": str(p), "name": p.name, "kind": None, "valid": True, "size": 0, "reason": None}
    try:
        st = p.stat()
    except OSError as e:
        return {**res, "valid": False, "reason": f"can't read: {e.strerror}"}
    lower = p.name.lower()
    if _partial(p):
        return {**res, "valid": False, "partial": True, "size": st.st_size, "reason": "still downloading"}
    if p.is_dir():
        if lower.endswith(".mbox"):
            res.update(kind="mailbox", size=sum(f.stat().st_size for f in p.rglob("*") if f.is_file()))
            return res
        names = [str(f.relative_to(p)) + ("/" if f.is_dir() else "") for f in itertools.islice(p.rglob("*"), 200_000)]
        names = [n for n in names if not common.junk_member(n.rstrip("/"))]
        if re.fullmatch(r"Takeout( \d+)?", p.name):  # a Takeout zip unzipped by Safari: the folder is its top
            names = ["Takeout/" + n for n in names]

        def peek(n):
            with open(p / n, "rb") as f:
                return f.read(200_000).decode("utf-8", "replace")
        res["size"] = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        res["kind"] = classify_names(names, peek=peek, filename=p.name)
        if res["kind"] is None and not any(not n.endswith("/") for n in names):
            res.update(empty=True, reason="empty")
        return res
    res["size"] = st.st_size
    if lower.endswith(".vcf"):
        res["kind"] = "iphone_vcard"
    elif lower.endswith(".mbox"):
        res["kind"] = "mailbox"
    elif lower.endswith(".vtt"):
        res["kind"] = "zoom"
    elif lower in ("timeline.json", "location-history.json"):
        res["kind"] = "maps_timeline"
    elif lower.endswith((".tgz", ".tar.gz", ".tar")):
        # Takeout can come as .tgz: its first entries say what it is (read as a stream, so a 50 GB part isn't unpacked).
        # Each header says how far in its file ends: one far past what the archive could hold is a tar bomb's.
        try:
            names = []
            with tarfile.open(p, mode="r|*") as t:
                for m in t:
                    if m.offset_data + m.size > max(common.BOMB_RATIO * st.st_size, 1 << 30):
                        return {**res, "valid": False, "reason": "unpacks to far more than its size, which only a tar bomb does"}
                    if not common.junk_member(m.name):
                        names.append(m.name + ("/" if m.isdir() else ""))
                    if len(names) >= 5000:
                        break
            res["kind"] = classify_names(names, filename=p.name)
            res["entries"] = len(names)
        except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
            res.update(valid=False, reason=f"not a complete archive ({e})")
    elif lower.endswith((".zip", ".olm")) or zipfile.is_zipfile(p):
        try:
            with zipfile.ZipFile(p) as z:
                res.update(_zip_kind(z, filename=p.name))
        except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as e:
            res.update(valid=False, reason=f"not a complete zip ({e})")
    if res["kind"] in ("google_takeout", "google_photos_drive"):
        m = TAKEOUT_NAME.search(p.name)
        res["export_id"] = m.group(1) if m else None
    if res["kind"] is None and res["valid"] and not res.get("empty"):
        res["reason"] = "not a recognized export"
    if res["kind"] and res["valid"]:
        res["already_imported"] = already_imported(p, st.st_size)
    return res


def already_imported(p, size):
    """corpus/imports/ path of a file with the same bytes as p, whatever it's called there (exports copied in
    by hand, or before the app existed), else None. Hashes only files of exactly the same size."""
    imports = CORPUS / "imports"
    if not imports.is_dir():
        return None
    same = [f for f in imports.rglob("*") if f.is_file() and ".incoming" not in f.parts and f.stat().st_size == size]
    if not same:
        return None
    digest = _sha256(p)
    return next((str(f.relative_to(imports)) for f in same if _sha256(f) == digest), None)


def _sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- run connectors

class LineEvents(io.TextIOBase):
    """stdout/stderr replacement: every printed line becomes a JSON log event."""

    def __init__(self, stream, connector):
        self.stream, self.connector, self.buf = stream, connector, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.stream.write(json.dumps({"type": "log", "connector": self.connector[0], "line": line[:2000]}) + "\n")
                self.stream.flush()
        return len(s)

    def flush(self):
        self.stream.flush()


def cloud_only(root):
    """Files under root that iCloud keeps only in the cloud ("Optimize Mac Storage")."""
    out = []
    for dp, _, fns in os.walk(root, followlinks=False):
        for f in fns:
            p = os.path.join(dp, f)
            try:
                if os.lstat(p).st_flags & SF_DATALESS:
                    out.append(p)
            except OSError:
                pass
    return out


def materialize(root, timeout=None):
    """Download cloud-only export files before parsing. Read on demand, a 2 GB mailbox can time out halfway
    through and leave a source half-imported. Returns the files still cloud-only after the wait."""
    timeout = float(os.environ.get("UMP_ICLOUD_TIMEOUT", 1800)) if timeout is None else timeout
    pending = cloud_only(root)
    if not pending:
        return []
    print(f"[imports] {len(pending)} export files are only in iCloud; downloading them first")
    for p in pending:
        subprocess.run(["brctl", "download", p], capture_output=True)
    end, shown = time.time() + timeout, None
    while pending and time.time() < end:
        time.sleep(2)
        pending = [p for p in pending if os.path.exists(p) and os.lstat(p).st_flags & SF_DATALESS]
        if len(pending) != shown:
            shown = len(pending)
            print(f"[imports] waiting for iCloud: {shown} files left")
    return pending


def resilient_imports(real):
    """connectors/imports.py's main(), except that one parser failing (an export format that changed, a
    file that can't be read) doesn't cost anything else: each parser runs on its own and its error is
    reported as connector "imports:<parser>"; the sources it was writing keep their previous records
    (their writers are discarded, not saved half-full); everything else is written as usual. Mirrors
    imports.main(); test_bridge.py checks the two stay in step."""
    import imports as im
    stuck = materialize(im.IMPORTS)
    if stuck:
        names = ", ".join(os.path.relpath(p, im.IMPORTS) for p in stuck[:5]) + (" …" if len(stuck) > 5 else "")
        raise RuntimeError(f"{len(stuck)} export files are still only in iCloud ({names}). In Finder, right-click "
                           f"corpus/imports and choose Download Now (or keep the corpus out of iCloud), then import again.")
    es = im.entries()
    if not es:
        print(f"[imports] nothing in {im.IMPORTS}")
        return []
    used, failed, writers, discard = set(), [], {}, set()

    def W(source):
        if source not in writers:
            parser = f"connectors/imports.py:{sys._getframe(1).f_code.co_name}"
            avenue = im.AV.get(source, f"Mailbox export (.mbox) dropped into corpus/imports/{source}/. {im.DROP}")
            w = im.Writer(source, avenue, parser=parser, accumulate=False)
            w.__enter__()
            writers[source] = w
        return writers[source]

    try:
        for parser in im.PARSERS:
            before = {s: w.count for s, w in writers.items()}
            try:
                parser(es, W, used)
            except Exception as e:
                traceback.print_exc()
                name = f"imports:{parser.__name__}"
                failed.append(name)
                touched = sorted(s for s, w in writers.items() if before.get(s) != w.count)
                discard.update(touched)
                if touched:
                    print(f"[imports] {parser.__name__} failed: keeping the previous {', '.join(touched)} records")
                real.write(json.dumps({"type": "error", "connector": name, "error": f"{type(e).__name__}: {e}"[:1000]}) + "\n")
                real.flush()
    finally:
        for source, w in writers.items():
            if source in discard:
                w.__exit__(RuntimeError, RuntimeError("parser failed"), None)  # drops the temp file, keeps the old one
            else:
                w.__exit__(None, None, None)
    ledger = getattr(im, "unclaimed_ledger", None)  # newer imports.py: list export files no parser read
    if ledger:
        ledger(es, used)
    return failed


def run_connectors(names, index=True, argv_for=None):
    import importlib
    real = sys.__stdout__
    current = ["bridge"]
    sys.stdout = sys.stderr = LineEvents(real, current)
    failed = []
    for name in names:
        current[0] = name
        t = time.time()
        real.write(json.dumps({"type": "start", "connector": name}) + "\n")
        real.flush()
        try:
            if name == "imports" and not os.environ.get("UMP_PLAIN_IMPORTS"):
                bad = resilient_imports(real)
                failed.extend(bad)
                real.write(json.dumps({"type": "done", "connector": name, "seconds": round(time.time() - t, 1), "partial": bool(bad)}) + "\n")
                real.flush()
                continue
            mod = importlib.import_module(name)
            if argv_for and name in argv_for:
                mod.main(argv_for[name])
            else:
                mod.main()
            real.write(json.dumps({"type": "done", "connector": name, "seconds": round(time.time() - t, 1)}) + "\n")
        except BaseException as e:  # SystemExit from a connector is a failure with a message, not our exit
            msg = str(e) if isinstance(e, SystemExit) and not isinstance(e.code, int) else f"{type(e).__name__}: {e}"
            if isinstance(e, SystemExit) and e.code in (0, None):
                real.write(json.dumps({"type": "done", "connector": name, "seconds": round(time.time() - t, 1)}) + "\n")
            else:
                if not isinstance(e, SystemExit):
                    traceback.print_exc()
                failed.append(name)
                real.write(json.dumps({"type": "error", "connector": name, "error": msg[:1000]}) + "\n")
            if isinstance(e, KeyboardInterrupt):
                break
        real.flush()
    if index and names:
        current[0] = "build_index"
        real.write(json.dumps({"type": "start", "connector": "build_index"}) + "\n")
        try:
            importlib.import_module("build_index").main()
            real.write(json.dumps({"type": "done", "connector": "build_index"}) + "\n")
        except Exception as e:
            traceback.print_exc()
            failed.append("build_index")
            real.write(json.dumps({"type": "error", "connector": "build_index", "error": f"{type(e).__name__}: {e}"}) + "\n")
    real.write(json.dumps({"type": "finished", "failed": failed}) + "\n")
    real.flush()
    sys.stdout, sys.stderr = real, sys.__stderr__
    return 1 if failed else 0


def write_identity(data):
    clean = {k: [str(v).strip() for v in data.get(k, []) if str(v).strip()] for k in ("names", "emails", "usernames", "phones")}
    CORPUS.mkdir(parents=True, exist_ok=True)
    tmp = CORPUS / "identity.json.tmp"
    tmp.write_text(json.dumps(clean, indent=2, ensure_ascii=False))
    tmp.replace(CORPUS / "identity.json")
    return clean


# ---------------------------------------------------------------- a phone that isn't yours

PHONE_ONLY = ("iphone_contacts", "health", "health_samples")  # and every phone_* source (iLEAPP)


def forget_phone():
    """What was read from an iPhone backup, taken out of the library, for one that turned out not to be yours (Your
    Setup picked another): the phone's own sources, the phone's copies in Messages and calls (what this Mac had stays),
    and the decrypted copy of the backup. The search index is rebuilt by the app afterwards."""
    from common import read_manifest, write_atomic, write_manifest
    norm = CORPUS / "normalized"
    manifest = read_manifest()
    removed = {}
    # By the manifest and by the files there (a manifest a crash cut short names none of them).
    here = {p.stem for p in norm.glob("*.jsonl")} if norm.is_dir() else set()
    for src in sorted(k for k in set(manifest) | here if k.startswith("phone_") or k in PHONE_ONLY):
        (norm / f"{src}.jsonl").unlink(missing_ok=True)
        removed[src] = (manifest.pop(src, None) or {}).get("count", 0)
    for src in ("imessage", "calls"):
        f = norm / f"{src}.jsonl"
        if not f.exists():
            continue
        kept, dropped, kinds, first, last = [], 0, collections.Counter(), None, None
        for line in f.open():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if (r.get("meta") or {}).get("copy") == "iphone":
                dropped += 1
                continue
            kept.append(line if line.endswith("\n") else line + "\n")
            kinds[r.get("kind", "?")] += 1
            ts = r.get("ts")
            if ts:
                first, last = min(first or ts, ts), max(last or ts, ts)
        write_atomic(f, "".join(kept))  # a temp name of its own: never a connector's <source>.jsonl.tmp
        if src in manifest:
            manifest[src].update(count=len(kept), kinds=dict(kinds), first=first, last=last)
        removed[src] = dropped
    write_manifest(manifest)
    raw = CORPUS / "raw/iphone"
    shutil.rmtree(raw / "files", ignore_errors=True)
    for name in ("backup.json", "mirror_state.json", "Info.plist", "inventory.json", "extract_failures.json"):
        (raw / name).unlink(missing_ok=True)
    return {"ok": True, "removed": removed}


def exclude_icloud():
    """corpus -> corpus.nosync plus a corpus symlink. iCloud skips .nosync names; the connectors keep
    using the old path. Refuses if any file is cloud-only (its data would be lost from this Mac)."""
    src = CORPUS
    if src.is_symlink() or src.name.endswith(".nosync"):
        return {"ok": True, "already": True, "path": str(src.resolve())}
    if not src.is_dir():
        return {"ok": False, "error": f"{src} isn't a folder"}
    dataless = 0
    for root, dirs, files in os.walk(src, followlinks=False):
        for f in files:
            try:
                if os.lstat(os.path.join(root, f)).st_flags & SF_DATALESS:
                    dataless += 1
            except OSError:
                pass
    if dataless:
        return {"ok": False, "error": f"{dataless} files in the corpus are only in iCloud. Open Finder, right-click the corpus folder and choose Download Now, then try again."}
    dst = src.with_name(src.name + ".nosync")
    if dst.exists():
        return {"ok": False, "error": f"{dst} already exists"}
    src.rename(dst)
    src.symlink_to(dst.name)
    return {"ok": True, "path": str(dst)}


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "probe":
        out(probe())
    elif cmd == "stats":
        out(stats())
    elif cmd == "describe-export":
        out(describe_export(rest[0], examples="--examples" in rest,
                            service=next((a.split("=", 1)[1] for a in rest if a.startswith("--service=")), None)))
    elif cmd == "try-mapping":
        try:
            out(try_mapping(rest[0], json.loads(sys.stdin.read())))
        except ValueError as e:
            out({"error": f"That isn't a usable mapping: {e}"})
    elif cmd == "save-mapping":
        try:
            out(save_mapping(rest[0], None if "--remove" in rest else json.loads(sys.stdin.read())))
        except ValueError as e:
            out({"error": f"That isn't a usable mapping: {e}"})
    elif cmd == "discover-services":
        out(discover_services())
    elif cmd == "notification-shown":
        a = json.loads(sys.stdin.read() or "{}")
        out(notification_shown(a.get("title", ""), a.get("since", "1970-01-01T00:00:00+00:00")))
    elif cmd == "notification-prefs":
        out(notification_prefs(rest[0] if rest else ""))
    elif cmd == "export-signals":
        if "--no-mail" in rest:  # the app's quick look between its looks in Mail: notifications only
            os.environ["UMP_READY_MAIL"] = "0"
        out(export_signals(json.loads(sys.stdin.read() or "[]")))
    elif cmd == "fix-shell-retention":
        out(fix_shell_retention())
    elif cmd == "identify":
        out([identify(p) for p in rest])
    elif cmd == "run":
        if "--reread" in rest:  # every export read again, none carried over (the readers changed)
            os.environ["UMP_REREAD_ALL"] = "1"
        index = "--no-index" not in rest
        return run_connectors([r for r in rest if not r.startswith("--")], index=index)
    elif cmd == "index":
        return _index_only(forget="--forget-phone" in rest)
    elif cmd == "iphone":
        module = os.environ.get("UMP_IPHONE_MODULE", "iphone")
        # iphone.py rebuilds the index itself
        return run_connectors([module], index=False, argv_for={module: rest})
    elif cmd == "identity-candidates":
        out(identity_candidates())
    elif cmd == "write-identity":
        out(write_identity(json.loads(sys.stdin.read() or "{}")))
    elif cmd == "exclude-icloud":
        out(exclude_icloud())
    elif cmd == "forget-phone":
        out(forget_phone())
    elif cmd == "glance":
        # A collected source at a glance (glance.py): its manifest keys as the arguments.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import glance
        db = CORPUS / "corpus.db"
        out(glance.glance(db, rest) if db.exists() else {"total": 0})
    elif cmd == "signins":
        # Which services Chrome and Safari are signed in to (signins.py), from cookie names and dates: never values.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import signins
        out(signins.signins(json.loads(sys.stdin.read() or "[]")))
    elif cmd == "samples":
        # Records to show as they are (glance.py samples): {"sources", "mode", "limit", "offset", "q"} on stdin.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import glance
        db = CORPUS / "corpus.db"
        a = json.loads(sys.stdin.read() or "{}")
        out(glance.samples(db, a.get("sources", []), a.get("mode", "years"), int(a.get("limit", 12)), int(a.get("offset", 0)), a.get("q", ""))
            if db.exists() else {"rows": [], "total": 0})
    else:
        print(f"unknown command {cmd}", file=sys.stderr)
        return 2
    return 0


def _index_only(forget=False):
    """The search index rebuilt; with forget, after what was read from the iPhone backup is taken out (forget_phone),
    as a job of the app's queue, so no read of the phone runs meanwhile."""
    real = sys.__stdout__
    step = ["forget-phone" if forget else "build_index"]
    sys.stdout = sys.stderr = LineEvents(real, step)
    try:
        if forget:
            print(f"Taken out: {json.dumps(forget_phone()['removed'])}")
            step[0] = "build_index"
        import build_index
        build_index.main()
        real.write(json.dumps({"type": "finished", "failed": []}) + "\n")
        return 0
    except Exception as e:
        real.write(json.dumps({"type": "error", "connector": step[0], "error": str(e)}) + "\n")
        real.write(json.dumps({"type": "finished", "failed": [step[0]]}) + "\n")
        return 1
    finally:
        sys.stdout, sys.stderr = real, sys.__stderr__


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
