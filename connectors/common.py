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
    meta.tier     optional: "device" (phone internals), "spam" / "deleted" / "unsent" (mail folders), so searches
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

import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = Path(os.environ.get("CORPUS_DIR", ROOT / "corpus"))
RAW = CORPUS / "raw"
NORM = CORPUS / "normalized"
MANIFEST = CORPUS / "manifest.json"
HOME = Path.home()
LIB = HOME / "Library"
# Decrypted iPhone backup, mirrored as <domain>/<relativePath> by iphone_backup.py (corpus/raw/iphone is a
# symlink to ~/Library/Application Support/q1_user_model/iphone, outside iCloud Drive).
IPHONE = RAW / "iphone" / "files"


def phone(domain, rel=""):
    """A file (or folder) from the decrypted iPhone backup, e.g. phone("HomeDomain", "Library/SMS/sms.db")."""
    return IPHONE / domain / rel

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
    return dst


def connect(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def columns(con, table):
    return {r[1] for r in con.execute(f"pragma table_info({table})")}


# st_flags bit of a file whose contents are only in iCloud Drive (or another cloud drive): it keeps its own name, and
# opening it downloads it, slowly, all of it, and not at all offline.
SF_DATALESS = 0x40000000


def cloud_only(path):
    """Whether reading this file (or the one a link points to) would download it from iCloud first. Asking doesn't."""
    try:
        return bool(os.stat(path).st_flags & SF_DATALESS)
    except (OSError, AttributeError):
        return False


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

    def __init__(self, source, avenue, parser=None, accumulate=True):
        self.source = source
        self.avenue = avenue
        self.accumulate = accumulate  # keep earlier runs' records the source no longer has (off for full exports)
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
        self.f = open(self.tmp, "w")
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
        self.f.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")
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
            for line in self.path.open():
                try:
                    old = json.loads(line)
                except ValueError:
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
        self.f.close()
        self.tmp.replace(self.path)
        if kept:
            print(f"[{self.source}] kept {kept} records from earlier runs")
        manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
        manifest[self.source] = {
            "count": self.count, "kinds": self.kinds, "first": self.first,
            "last": self.last, "avenue": self.avenue, "parser": self.parser, "code": code_version(),
            "ran_at": dt.datetime.now(UTC).isoformat(timespec="seconds"),
            **({"notes": self.notes} if self.notes else {}),
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        print(f"[{self.source}] {self.count} records {self.kinds} {self.first} → {self.last}")
        if self.notes:
            print(f"[{self.source}] notes: {self.notes}")
        return False
