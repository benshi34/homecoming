"""Shared helpers for personal-corpus connectors.

Every connector snapshots its source into corpus/raw/ and writes one JSONL file
to corpus/normalized/<source>.jsonl using the record schema below.

Record schema (keys with None values are dropped):
    id            stable id, unique within the source
    source        connector name, e.g. "imessage"
    kind          message | reaction | note | event | contact | call | reminder |
                  visit | search | app_usage | app_usage_day | media | document | ai_turn |
                  email | photo | voice_memo | commit | post | place | place_visit | activity |
                  (phone, via ileapp.py) transaction | trip | interaction | app | record | health_sample
    meta.person_id optional: who the conversation is with, when a connector knows for certain; Explore joins records
                  with the same one as one person (meta.person_name: the name to show them by)
    meta.tier     optional: "device" (phone internals), "spam" / "deleted" / "unsent" (mail folders), "superseded" (an
                  earlier version: an edited X post's, a ChatGPT answer regenerated or prompt edited), so searches
                  can leave low-signal records out without the corpus dropping them
    ts            ISO-8601 UTC time the record happened
    ts_end        optional end time (events, app usage); for editable content (notes) the last edit, i.e.
                  when the text as stored was written. Checkpoint by ts_end, or future text leaks into the past
    author        "me" for the user, else a display name / handle
    is_me         True if the user wrote / did it
    thread        conversation, calendar, folder, or session id
    thread_name   human-readable thread name
    participants  list of display names / handles
    title         subject, note title, page title
    text          searchable body text
    url           link, if any
    meta          source-specific extras (dict)
"""

import contextlib
import ctypes
import datetime as dt
import fcntl
import io
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path(os.environ.get("CORPUS_DIR", ROOT / "corpus"))
RAW = CORPUS / "raw"
NORM = CORPUS / "normalized"
MANIFEST = CORPUS / "manifest.json"
HOME = Path.home()
LIB = HOME / "Library"
# Notification Center and Mail are live SQLite stores. Keep a private copy while reading them so the owning app can
# keep writing without changing a query halfway through. The desktop bridge imports these helpers too.
COPIES = Path(os.environ.get("UMP_CACHE_DIR") or LIB / "Caches/Homecoming") / "copies"
MAC_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
# Decrypted iPhone backup, mirrored as <domain>/<relativePath> by iphone_backup.py (corpus/raw/iphone is a
# symlink to ~/Library/Application Support/q1_user_model/iphone, outside iCloud Drive).
IPHONE = RAW / "iphone" / "files"


def phone(domain, rel=""):
    """A file (or folder) from the decrypted iPhone backup, e.g. phone("HomeDomain", "Library/SMS/sms.db")."""
    return IPHONE / domain / rel


def phone_unencrypted():
    """Whether the iPhone backup copied last wasn't encrypted (iphone_backup.py's backup.json): Finder leaves Health, call
    history and Safari out of those, so their readers say that rather than that nothing was decrypted yet."""
    try:
        return json.loads((IPHONE.parent / "backup.json").read_text()).get("encrypted") is False
    except (OSError, ValueError, AttributeError):
        return False


def _clone(src, dst):
    """Make an APFS clone when possible, otherwise copy the SQLite file."""
    try:
        if ctypes.CDLL(None).clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
            return
    except (OSError, AttributeError):
        pass
    shutil.copy2(src, dst)


def _stat(path):
    try:
        return os.stat(path)
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def db_copy(db, name):
    """Yield a stable private copy of a live SQLite database and its sidecars."""
    db = Path(db)
    d = COPIES / name
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(COPIES, 0o700)
    with open(d / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(db, "rb") as f:
                f.read(1)
        except OSError:
            for suffix in ("", "-wal", "-shm", ".json"):
                (d / f"db{suffix}").unlink(missing_ok=True)
            raise
        stamp = {"db": str(db), "files": [[suffix, st.st_size, st.st_mtime_ns]
                  for suffix in ("", "-wal", "-shm")
                  for st in [_stat(f"{db}{suffix}")] if st]}
        try:
            same = json.loads((d / "db.json").read_text()) == stamp and (d / "db").exists()
        except (OSError, ValueError):
            same = False
        if not same:
            for suffix in (".json", "", "-wal", "-shm"):
                (d / f"db{suffix}").unlink(missing_ok=True)
            for suffix, *_ in stamp["files"]:
                _clone(f"{db}{suffix}", d / f"db{suffix}")
            (d / "db.json").write_text(json.dumps(stamp))
        yield d / "db"


def drop_copy(name):
    """Remove a cached database copy once no reader is using it."""
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


def _readable(path):
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


def _read_only(path):
    from urllib.parse import quote
    return f"file:{quote(str(path))}?mode=ro"


def notification_db():
    """The macOS 15 Notification Center database, or its pre-macOS 15 location."""
    if os.environ.get("UMP_NOTIFICATIONS_DB"):
        return Path(os.environ["UMP_NOTIFICATIONS_DB"])
    new = LIB / "Group Containers/group.com.apple.usernoted/db2/db"
    if new.exists():
        return new
    try:
        d = subprocess.run(["getconf", "DARWIN_USER_DIR"], capture_output=True, text=True, timeout=5).stdout.strip()
        return Path(d) / "com.apple.notificationcenter/db2/db"
    except (OSError, subprocess.SubprocessError):
        return new


def _notification_text(value):
    if isinstance(value, list):
        return " ".join(_notification_text(x) for x in value if not isinstance(x, (dict, bytes)))
    return value if isinstance(value, str) else ""


def _notification_id(value, rec_id):
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        if len(value) == 16:
            try:
                return str(uuid.UUID(bytes=value))
            except ValueError:
                pass
        return value.hex() or str(rec_id)
    if value is None or value == "":
        return str(rec_id)
    return str(value)


def _notification_value(req, *keys):
    for key in keys:
        value = req.get(key)
        if value not in (None, "", [], {}):
            return _notification_text(value)
    return None


def _notification_payload(data):
    try:
        root = plistlib.loads(data)
    except (TypeError, ValueError, plistlib.InvalidFileException):
        return None
    if not isinstance(root, dict):
        return None
    req = root.get("req") or {}
    if not isinstance(req, dict):
        return None
    return {
        "title": _notification_text(req.get("titl")),
        "subtitle": _notification_text(req.get("subt")),
        "body": _notification_text(req.get("body")),
        "thread_id": _notification_value(req, "thread-id", "threadIdentifier", "thread_id", "thread"),
        "category_id": _notification_value(req, "category-id", "categoryIdentifier", "category_id", "category", "cate"),
    }


def notification_style(value):
    """Decode Notification Center's record.style enum: 0 none, 1 banner, 2 alert."""
    return {0: "none", 1: "banner", 2: "alert"}.get(value)


def notification_records(since=None):
    """Return decoded Notification Center rows, or None when Full Disk Access prevents reading the DB."""
    since = since or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    try:
        with db_copy(notification_db(), "notifications") as copy:
            con = sqlite3.connect(_read_only(copy), uri=True)
            try:
                rows = con.execute(
                    "select r.rec_id, a.identifier, r.uuid, r.data, r.delivered_date, r.presented, r.style "
                    "from record r join app a on a.app_id = r.app_id where r.delivered_date >= ? "
                    "order by r.delivered_date, r.rec_id",
                    ((since - MAC_EPOCH).total_seconds(),),
                ).fetchall()
            finally:
                con.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    out = []
    for rec_id, bundle, value, data, delivered, presented, style in rows:
        payload = _notification_payload(data)
        if payload is None:
            continue
        try:
            when = MAC_EPOCH + dt.timedelta(seconds=float(delivered or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        out.append({"id": _notification_id(value, rec_id), "when": when, "bundle": bundle or "", **payload,
                    "presented": bool(presented), "style": notification_style(style)})
    return out


def notification_shown(title, since):
    """Whether a recent notification with title reached Notification Center and appeared on screen."""
    try:
        since_dt = dt.datetime.fromisoformat(since.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return {"readable": False}
    rows = notification_records(since_dt)
    if rows is None:
        return {"readable": False}
    if os.environ.get("UMP_READY_NOTIFICATIONS") == "0":
        drop_copy("notifications")
    for row in reversed(rows):
        if row["title"] == title:
            return {"readable": True, "found": True, "presented": row["presented"], "app": row["bundle"]}
    return {"readable": True, "found": False}


def notification_prefs(bundle):
    """Read an app's Notification Center permission and presentation style."""
    paths = [Path(os.environ["UMP_NOTIFICATION_PREFS"])] if os.environ.get("UMP_NOTIFICATION_PREFS") else [
        LIB / "Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist",
        LIB / "Preferences/com.apple.ncprefs.plist",
    ]
    for path in paths:
        try:
            prefs = plistlib.loads(path.read_bytes())
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        for app in prefs.get("apps") or []:
            if isinstance(app, dict) and app.get("bundle-id") == bundle and isinstance(app.get("flags"), int):
                flags = app["flags"]
                return {"readable": True, "found": True, "allowed": bool(flags >> 25 & 1),
                        "style": "alerts" if flags >> 4 & 1 else "banners" if flags >> 3 & 1 else "none"}
        return {"readable": True, "found": False}
    return {"readable": False}


def notification_apps():
    """{bundle id, lowercased: {"name", "iphone"}} for each app Notification Center knows (usernoted's preferences;
    the database keeps bundle ids lowercased). iphone: none of its paths is on this Mac (an app on your iPhone whose
    notifications come here). name: its .app's own, when it's on this Mac."""
    path = Path(os.environ.get("UMP_NOTIFICATION_PREFS") or
                LIB / "Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist")
    try:
        apps = plistlib.loads(path.read_bytes()).get("apps") or []
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}
    out = {}
    for app in apps:
        if not isinstance(app, dict) or not app.get("bundle-id") or str(app["bundle-id"]).startswith("_SYSTEM_CENTER_"):
            continue
        paths = ([app["path"]] if app.get("path") else []) + [  # the app's own path first: src can be an extension in it
            x.get("path") for x in app.get("src") or [] if isinstance(x, dict) and x.get("path")]
        here = [p for p in paths if Path(p).exists()]
        name = None
        for p in here:
            try:
                info = plistlib.loads((Path(p) / "Contents/Info.plist").read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            name = info.get("CFBundleDisplayName") or info.get("CFBundleName")
            if name:
                break
        name = str(name).strip("\u200e\u200f\u202a\u202c ") if name else None  # some apps name themselves with direction marks
        out[str(app["bundle-id"]).lower()] = {"name": name or None, "iphone": not here}
    return out


def notification_access():
    """Whether Notification Center is readable and whether iPhone notifications are forwarded to this Mac."""
    readable = _readable(notification_db())
    prefs = LIB / "Group Containers/group.com.apple.usernoted/Library/Preferences/group.com.apple.usernoted.plist"
    iphone = False
    try:
        for app in plistlib.loads(prefs.read_bytes()).get("apps") or []:
            if not isinstance(app, dict) or str(app.get("bundle-id", "")).startswith("_SYSTEM_CENTER_"):
                continue
            paths = [x.get("path") for x in app.get("src") or [] if isinstance(x, dict) and x.get("path")]
            if app.get("path"):
                paths.append(app["path"])
            if not any(Path(x).exists() for x in paths):  # none listed, or none on this Mac
                iphone = True
                break
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    return {"readable": readable, "iphone": iphone}

UTC = dt.timezone.utc
APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=UTC)
UNIX_EPOCH = dt.datetime(1970, 1, 1, tzinfo=UTC)
WEBKIT_EPOCH = dt.datetime(1601, 1, 1, tzinfo=UTC)

FIELDS = ("id", "source", "kind", "ts", "ts_end", "author", "is_me", "thread",
          "thread_name", "participants", "title", "text", "url", "meta")


def _iso(base, seconds):
    try:
        return (base + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    except (OverflowError, ValueError):
        return None


def from_apple(v):
    """Core Data / Cocoa time: seconds (or nanoseconds) since 2001-01-01."""
    if v in (None, 0, ""):
        return None
    v = float(v)
    if abs(v) > 1e11:
        v /= 1e9
    return _iso(APPLE_EPOCH, v)


def from_unix(v, unit="s"):
    if v in (None, 0, ""):
        return None
    div = {"s": 1, "ms": 1e3, "us": 1e6, "ns": 1e9}[unit]
    return _iso(UNIX_EPOCH, float(v) / div)


def from_webkit(v):
    """Chrome time: microseconds since 1601-01-01."""
    if v in (None, 0, ""):
        return None
    return _iso(WEBKIT_EPOCH, float(v) / 1e6)


def norm_ts(ts):
    """ISO times with a UTC offset -> UTC 'Z' so all sources sort together."""
    if isinstance(ts, str) and len(ts) > 19 and not ts.endswith("Z") and ts[-6] in "+-" and ts[-3] == ":":
        try:
            return dt.datetime.fromisoformat(ts).astimezone(UTC).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return ts


def write_atomic(path, text):
    """A file written whole or not at all: a temp file beside it, flushed to disk, then renamed over it. A run cut off
    midway (a crash, a full disk, the app quit) leaves the old file, never half of a new one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path, default=None):
    """A JSON file, or `default` when it's missing or can't be read (cut off by a crash): one bad file mustn't stop
    every later run."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def read_manifest():
    m = read_json(MANIFEST, {})
    return m if isinstance(m, dict) else {}


def write_manifest(manifest):
    write_atomic(MANIFEST, json.dumps(manifest, indent=2, sort_keys=True))


ID_AT_START = re.compile(rb'^\{"id": ("(?:[^"\\]|\\.)*")')  # Writer writes each record's id first


def ids_in(path):
    """The ids of the records in a source's file, read off the start of each line (no record is parsed)."""
    try:
        with open(path, "rb") as f:
            return {json.loads(m.group(1)) for line in f for m in [ID_AT_START.match(line)] if m}
    except (OSError, ValueError):
        return set()


# Half of a surrogate pair (an emoji cut in two by an export) can't be written as UTF-8: it becomes U+FFFD.
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def snapshot_sqlite(src, name):
    """Copy a live SQLite DB into corpus/raw/<name> without disturbing the owning app."""
    src, dst = Path(src), RAW / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(dst) + suffix).unlink(missing_ok=True)
    def give_up_if_busy(status, remaining, total):
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise sqlite3.OperationalError("source locked")

    try:
        s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=2)
        s.execute("select count(*) from sqlite_master").fetchone()
        d = sqlite3.connect(dst)
        s.backup(d, progress=give_up_if_busy)
        d.close()
        s.close()
    except sqlite3.OperationalError:
        Path(dst).unlink(missing_ok=True)
        # Locked by its app (e.g. Chrome holds an exclusive lock): copy the files.
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = Path(str(src) + suffix)
            if p.exists():
                shutil.copy2(p, str(dst) + suffix)
        # Copied in the middle of a write, the copy has the app's journal of it: opened once to write, SQLite rolls
        # it back (or takes in its write-ahead log), so it can be read read-only, as it was before that write.
        if dst.exists():
            try:
                d = sqlite3.connect(dst)
                try:
                    d.execute("select count(*) from sqlite_master").fetchone()
                finally:
                    d.close()
            except sqlite3.Error:
                pass
    return dst


def connect(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def columns(con, table):
    return {r[1] for r in con.execute(f"pragma table_info({table})")}


def tables(con):
    """The tables a database has: none in a file its app made and never wrote to, so a connector says so rather than
    fail on its first query."""
    return {r[0] for r in con.execute("select name from sqlite_master where type = 'table'")}


def select(con, table, want):
    """select want from table, a column this version of the app doesn't have as null: older and newer schemas differ,
    and one column missing mustn't lose every row. ROWID is always there, declared or not."""
    have = columns(con, table) | {"ROWID"}
    return f"select {', '.join(c if c in have else f'null {c}' for c in want)} from {table}"


# st_flags bit of a file whose contents are only in iCloud Drive (or another cloud drive): it keeps its own name, and
# opening it downloads it, slowly, all of it, and not at all offline.
SF_DATALESS = 0x40000000


def cloud_only(path):
    """Whether reading this file (or the one a link points to) would download it from iCloud first. Asking doesn't."""
    try:
        return bool(os.stat(path).st_flags & SF_DATALESS)
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------- zips (imports.py reads them, bridge.py's identify looks in them)

# How zip members can be packed that Python reads. Windows packs big files with Deflate64 (9), WinZip with AES (99): neither.
ZIP_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA, getattr(zipfile, "ZIP_ZSTANDARD", 93)}
IN_MEMORY = 64 << 20  # a zip inside a zip up to this size is read into memory; a bigger one isn't
# An export's files pack to a tenth of their size or more (text; photos hardly shrink); a zip bomb's to a thousandth (a GB of
# zeros in a MB).
BOMB_RATIO = 100


def member_name(info):
    """A zip member's name as its zip meant it. Archive Utility on a Mac writes names in UTF-8 without saying so, which zipfile
    then reads as the old DOS code page ("Caf├⌐"); zips made on Windows can use backslashes; some tools start names with "./".
    A name that really is in the DOS code page, or another one zipfile can't know (a Chinese Windows'), is kept as read."""
    name = info.filename
    if not info.flag_bits & 0x800 and not name.isascii():
        try:
            name = unicodedata.normalize("NFC", name.encode("cp437").decode("utf-8"))
        except UnicodeError:
            pass
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name


def junk_member(name):
    """What a Mac adds to a zip that isn't anyone's data: __MACOSX/ and ._ files (a file's Finder details), .DS_Store."""
    base = name.rsplit("/", 1)[-1]
    return "__MACOSX/" in name or base.startswith("._") or base == ".DS_Store"


def zip_problem(info):
    """Why a zip member can't be read as it is, in words, or None: locked with a password, or packed in a way Python can't unpack."""
    if info.flag_bits & 0x1:
        return "locked with a password"
    if info.compress_type not in ZIP_METHODS:
        return "packed in a way that can't be read here"
    return None


def looks_like_bomb(info, floor=256 << 20):
    """A member that unpacks to more than floor, and to over BOMB_RATIO times its packed size: no export's data does that."""
    return info.file_size > floor and info.file_size > BOMB_RATIO * max(info.compress_size, 1)


def open_nested(z, info, spill=None):
    """A zip inside a zip, without all of it in memory: one stored as it is (Notion's parts, LinkedIn's .zip.zip) is read in place;
    a small packed one from memory; a big packed one in place too (fine for a listing), or, with spill (a folder), from an
    unnamed copy there, gone once it's closed, as reading its files one by one in place would unpack it again each time."""
    if info.compress_type == zipfile.ZIP_STORED or info.file_size > IN_MEMORY and spill is None:
        return zipfile.ZipFile(z.open(info))
    if info.file_size <= IN_MEMORY:
        return zipfile.ZipFile(io.BytesIO(z.read(info)))
    Path(spill).mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(spill).free < info.file_size + (1 << 30):
        raise OSError(f"no room to unpack it ({info.file_size / 1e9:.1f} GB)")
    f = tempfile.TemporaryFile(dir=spill)
    try:
        with z.open(info) as src:
            shutil.copyfileobj(src, f, 1 << 20)
        return zipfile.ZipFile(f)
    except BaseException:
        f.close()
        raise


_GIT = {}
_GIT_BIN = []
# GitHub Desktop brings a git of its own, for people who never installed the developer tools.
GITHUB_DESKTOP_GIT = "/Applications/GitHub Desktop.app/Contents/Resources/app/git/bin/git"


def git_bin():
    """The git to run, or None. On a Mac without the Command Line Tools, /usr/bin/git is only a stub, and running it
    puts up macOS's "install the developer tools?" dialog: it counts only once xcode-select has a developer folder."""
    if not _GIT_BIN:
        found = shutil.which("git")
        if found and os.path.realpath(found) == "/usr/bin/git":
            try:
                ok = subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=10).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                ok = False
            found = found if ok else None
        if not found and os.access(GITHUB_DESKTOP_GIT, os.X_OK):
            found = GITHUB_DESKTOP_GIT
        _GIT_BIN.append(found)
    return _GIT_BIN[0]


def code_version():
    """The repo commit the connectors ran from, plus any connector files edited since, so each manifest
    entry says exactly which code produced it. Nothing when they don't run from a clone (the packaged app)."""
    if not _GIT:
        if not (ROOT / ".git").exists() or not git_bin():
            _GIT.update(commit=None, uncommitted=[])
            return dict(_GIT)

        def git(*args):
            return subprocess.run([git_bin(), "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()
        changed = [line.split(maxsplit=1)[1] for line in git("status", "--porcelain", "--", "connectors").splitlines()]
        _GIT.update(commit=git("rev-parse", "--short", "HEAD") or None, uncommitted=sorted(changed))
    return dict(_GIT)


class Writer:
    """Writes normalized records for one source and records stats in the manifest, including the
    parser (file:function) and code version that produced them."""

    def __init__(self, source, avenue, parser=None, accumulate=True, forget=None):
        self.source = source
        self.avenue = avenue
        self.accumulate = accumulate  # keep earlier runs' records the source no longer has (off for full exports)
        # An earlier run's record this says yes to isn't kept either: how things were then, not something that
        # happened (the tabs open on another device), or one that turned out not to be this source's.
        self.forget = forget or (lambda rec: False)
        if parser is None:  # default: the connector function that opened this Writer
            caller = sys._getframe(1).f_code
            parser = f"{Path(caller.co_filename).resolve().relative_to(ROOT)}:{caller.co_name}"
        self.parser = parser
        self.path = NORM / f"{source}.jsonl"
        self.count = 0
        self.kinds = {}
        self.first = self.last = None
        self.seen = set()
        self.notes = {}  # parser-reported facts for the manifest (rows skipped, duplicates dropped, ...)

    def __enter__(self):
        NORM.mkdir(parents=True, exist_ok=True)
        self.tmp = self.path.with_suffix(".jsonl.tmp")
        self.f = open(self.tmp, "w", encoding="utf-8")
        return self

    def has(self, rid):
        return str(rid) in self.seen

    def skip(self, rid):
        """Mark an id as handled without writing it (a duplicate of another record), so the accumulate step
        doesn't restore a copy written by an earlier run."""
        self.seen.add(str(rid))

    def add(self, **rec):
        unknown = set(rec) - set(FIELDS)
        if unknown:
            raise ValueError(f"unknown fields {unknown}")
        rec["source"] = self.source
        rid = str(rec.get("id"))
        if rec.get("id") is None or rid in self.seen:
            raise ValueError(f"missing or duplicate id {rid!r} in {self.source}")
        self.seen.add(rid)
        rec["id"] = rid
        if isinstance(rec.get("text"), str):
            rec["text"] = rec["text"].replace("\x00", "").strip()
        for key in ("ts", "ts_end"):
            rec[key] = norm_ts(rec.get(key))
        out = {k: rec[k] for k in FIELDS if rec.get(k) not in (None, "", [], {})}
        line = json.dumps(out, ensure_ascii=False, default=str)
        try:
            self.f.write(line + "\n")
        except UnicodeEncodeError:  # half an emoji: replaced, rather than the whole source failing
            self.f.write(LONE_SURROGATE.sub("�", line) + "\n")
        self.count += 1
        kind = out.get("kind", "?")
        self.kinds[kind] = self.kinds.get(kind, 0) + 1
        ts = out.get("ts")
        if ts:
            self.first = ts if self.first is None or ts < self.first else self.first
            self.last = ts if self.last is None or ts > self.last else self.last

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.f.close()
            self.tmp.unlink(missing_ok=True)
            return False
        # Accumulate: keep records from earlier runs that the source no longer has
        # (screen time, Chrome, calls, Claude Code etc. only retain weeks of history).
        kept = 0
        if self.accumulate and self.path.exists():
            with self.path.open(encoding="utf-8", errors="replace") as before:
                for line in before:
                    try:
                        old = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(old, dict) or self.forget(old):
                        continue
                    if str(old.get("id")) not in self.seen:
                        self.f.write(line if line.endswith("\n") else line + "\n")
                        self.seen.add(str(old.get("id")))
                        kept += 1
                        self.count += 1
                        kind = old.get("kind", "?")
                        self.kinds[kind] = self.kinds.get(kind, 0) + 1
                        ts = old.get("ts")
                        if ts:
                            self.first = ts if self.first is None or ts < self.first else self.first
                            self.last = ts if self.last is None or ts > self.last else self.last
        self.f.flush()
        os.fsync(self.f.fileno())
        self.f.close()
        self.tmp.replace(self.path)
        if kept:
            print(f"[{self.source}] kept {kept} records from earlier runs")
        manifest = read_manifest()
        manifest[self.source] = {
            "count": self.count, "kinds": self.kinds, "first": self.first,
            "last": self.last, "avenue": self.avenue, "parser": self.parser, "code": code_version(),
            "ran_at": dt.datetime.now(UTC).isoformat(timespec="seconds"),
            **({"notes": self.notes} if self.notes else {}),
        }
        write_manifest(manifest)
        print(f"[{self.source}] {self.count} records {self.kinds} {self.first} → {self.last}")
        if self.notes:
            print(f"[{self.source}] notes: {self.notes}")
        return False
