"""The Ask assistant's tools over the corpus: what any model (an API, a local model, Claude Code, Codex) may do.

    sql        one read-only query on corpus.db (records + fts), as TSV
    search     full-text search with filters, each hit numbered by its record id
    python     Python over the records (files and corpus.db), in a sandbox: no network, nothing writable but temp,
               nothing readable in the home folder but the records, their media and the app's own code
    read_file  the full text of the file a record points to (a document's original, an attachment), in pages
    view_image the image a record points to (a photo, an attachment), downscaled, for models that can see

Records are reached through the database; files only through a record that points to them, so what the importers
left out on purpose (raw exports, the iPhone's raw files) stays out. Every text result is blanked of secrets
(connectors/redact.py) before a model sees it; images can't be, and are sent as they are.

    python3 ask_tools.py tools                 the tool definitions, JSON
    python3 ask_tools.py call NAME < args.json one call: {"text", "images": [{"media_type", "data"}], "error"}
    python3 ask_tools.py serve                 calls as lines of JSON on stdin, results as lines on stdout (the app's)
    python3 ask_tools.py record ROWID          one record, for the app to show (not sent to a model)
    python3 ask_tools.py inventory             records per source, for the assistant's instructions
    python3 ask_tools.py mcp --box DIR         an MCP server (stdio) whose calls go to the app through mailbox DIR
    python3 ask_tools.py ask --box DIR NAME    one call through the mailbox, for Codex's shell: JSON args on stdin
"""

import base64
import json
import os
import re
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(os.environ.get("UMP_REPO") or Path(__file__).resolve().parents[2])
CONNECTORS = REPO / "connectors"
sys.path.insert(0, str(CONNECTORS))
CORPUS = Path(os.environ.get("CORPUS_DIR") or REPO / "corpus")
DB = CORPUS / "corpus.db"
HOME = Path.home()
CAP = 20_000  # characters of one tool result
SECONDS = 30  # one sql or search call, at most: the tools answer one call at a time, so a runaway query is stopped
LONGEST = 100_000  # characters of a query
from library_paths import record_path  # noqa: E402
from redact import redact  # noqa: E402

TOOLS = [
    {"name": "sql",
     "description": ("Run one read-only SQL query on corpus.db and get the rows as TSV (default 200 rows and 300 characters per "
                     "cell; raise limit/width when you need more). Table records: one row per record (rowid, source, id, kind, "
                     "ts, ts_end, author, is_me, thread, thread_name, participants, title, text, url, meta). Table fts: FTS5 over "
                     "title, text, author, thread_name, participants (JOIN fts ON fts.rowid = records.rowid WHERE fts MATCH ...). "
                     "Extra functions: regexp(pattern, text) (also `text REGEXP pattern`), local_time(ts, 'America/Los_Angeles'), "
                     "median(x). Aggregate in SQL rather than pulling rows to count them. A query is stopped after 30 seconds."),
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "One SQL statement (SELECT / WITH)."},
         "limit": {"type": "integer", "description": "Max rows (default 200, at most 2000)."},
         "width": {"type": "integer", "description": "Max characters per cell (default 300, at most 20000)."}},
         "required": ["query"]}},
    {"name": "search",
     "description": ("Full-text search over every record, best matches first, each hit shown as #rowid with its time (UTC), "
                     "source, author, chat or thread, and a snippet. FTS5 syntax: \"exact phrase\", prefix*, a OR b, NOT, "
                     "NEAR(a b, 5), title:word. With no query it browses by time. context shows N records before and after "
                     "each hit in its thread. Fast: search broadly and often."),
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "source": {"type": "string", "description": "Comma-separated sources; a prefix matches (phone_ matches every phone source)."},
         "kind": {"type": "string", "description": "Comma-separated kinds (message, email, visit, note...)."},
         "after": {"type": "string", "description": "ISO date or time, UTC."},
         "before": {"type": "string", "description": "ISO date or time, UTC."},
         "me": {"type": "boolean", "description": "Only what the user wrote or did."},
         "thread": {"type": "string", "description": "Part of a chat or thread name."},
         "author": {"type": "string", "description": "Part of an author's name."},
         "limit": {"type": "integer", "description": "Hits to show (default 20, at most 200)."},
         "sort": {"type": "string", "enum": ["rank", "time", "time-desc"]},
         "context": {"type": "integer", "description": "Records around each hit in the same thread (at most 10)."},
         "full": {"type": "boolean", "description": "Whole text instead of a snippet."}}}},
    {"name": "python",
     "description": ("Run Python 3 (standard library) for analysis SQL makes awkward: reply times, streaks, joins across "
                     "sources, parsing text. Prints come back (up to 20,000 characters). Preloaded: sql(query, params=()) -> "
                     "list of dicts from corpus.db; records(source=None) yields records as dicts from the files "
                     "corpus/normalized/<source>.jsonl (slower than sql: a full pass takes seconds); CORPUS, NORM, MEDIA paths. "
                     "No network; only temp is writable; 120 s limit."),
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "read_file",
     "description": ("Read the file a record points to: a document's original (PDF, Word, text: the full text, which the "
                     "record may have cut short), or an attachment. Give the record's rowid, and for records with several "
                     "files (meta.files) which one (index from 0). Long files come in pages: pass offset to continue."),
     "input_schema": {"type": "object", "properties": {
         "rowid": {"type": "integer"}, "file": {"type": "integer", "description": "Index into meta.files (default 0)."},
         "offset": {"type": "integer", "description": "Character to start at (default 0)."},
         "length": {"type": "integer", "description": "Characters to return (default 8000, at most 20000)."}},
         "required": ["rowid"]}},
    {"name": "view_image",
     "description": ("Look at an image a record points to: a photo (source photos), an image attachment, the first page of a "
                     "scanned PDF, or a still from a video. Give the record's rowid; without a file index it shows the record's first "
                     "picture. Use it when what's in the picture matters and the record's labels don't say."),
     "input_schema": {"type": "object", "properties": {"rowid": {"type": "integer"}, "file": {"type": "integer"}}, "required": ["rowid"]}},
]


# ---------------------------------------------------------------- the database

class Median:
    def __init__(self):
        self.xs = []

    def step(self, x):
        if x is not None:
            self.xs.append(x)

    def finalize(self):
        return statistics.median(self.xs) if self.xs else None


def _regexp(pattern, text):
    if text is None or pattern is None:
        return 0
    try:
        return 1 if re.search(pattern, str(text)) else 0
    except re.error:
        return 0


def _local_time(ts, tz):
    """'2024-05-01T03:00:00Z', 'America/Los_Angeles' -> '2024-04-30T20:00:00-07:00'."""
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")
    except (ValueError, KeyError, Exception):
        return None


def _deny(action, *_):
    if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def connect(seconds=None):
    """corpus.db, read-only (and nothing attached to it). With seconds, a query running longer is stopped
    (sqlite3.OperationalError "interrupted")."""
    if not DB.exists():
        raise FileNotFoundError("corpus.db doesn't exist yet: read some sources first")
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    con.execute("PRAGMA query_only = ON")
    con.create_function("regexp", 2, _regexp, deterministic=True)
    con.create_function("local_time", 2, _local_time, deterministic=True)
    con.create_aggregate("median", 1, Median)
    con.set_authorizer(_deny)
    if hasattr(con, "setlimit"):  # no value made bigger than this (zeroblob of a gigabyte), in memory or out
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000_000)
    if seconds:
        end = time.monotonic() + seconds
        con.set_progress_handler(lambda: time.monotonic() > end, 10_000)
    return con


def _failed(what, e):
    """A database error in plain words: a query stopped for taking too long says so, and what to do instead."""
    if "interrupted" in str(e):
        return f"Stopped after {SECONDS} second{'s' if SECONDS != 1 else ''}: narrow it (a date range, a source), or aggregate rather than read every row."
    return f"{what} error: {e}"


def _yes(v):
    """A yes from a model, however it says it: true, 1, "true", "yes"."""
    return v is True or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 1) or str(v).strip().casefold() in ("true", "1", "yes")


def _when(v, key):
    """A date or time a model gave, as the database writes times (UTC, '2024-05-01T18:30:00'); or an error saying how
    to write one. A date alone is its midnight; a time without a zone is UTC."""
    try:
        t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        return None, f"{key} isn't a date or time: write it like 2024-05-01 or 2024-05-01T18:30:00Z."
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S"), None


def _cell(v, width):
    if v is None:
        return ""
    s = v[: width * 4].decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
    s = s.replace("\t", " ").replace("\r", "").replace("\n", " ⏎ ")
    return s if len(s) <= width else s[: width - 1] + "…"


def tool_sql(a):
    limit = max(1, min(int(a.get("limit") or 200), 2000))
    width = max(20, min(int(a.get("width") or 300), 20000))
    q = a.get("query")
    if not isinstance(q, str) or not q.strip():
        return "Give query: one SQL statement (SELECT or WITH), as text.", True
    if len(q) > LONGEST:
        return f"That query is {len(q):,} characters long: keep it under {LONGEST:,}.", True
    con = connect(SECONDS)
    try:
        cur = con.execute(q)
        lines = ["\t".join(d[0] for d in cur.description or [])]
        n, size = 0, len(lines[0])
        for row in cur:
            if n == limit:
                lines.append(f"... stopped at {limit} rows (raise limit, or aggregate in SQL)")
                break
            line = "\t".join(_cell(v, width) for v in row)
            if size + len(line) > CAP - 200:  # past what one result holds: the rest would be cut anyway
                lines.append(f"... stopped at {n} rows, {CAP:,} characters (lower width, pick fewer columns, or aggregate)")
                break
            lines.append(line)
            size += len(line) + 1
            n += 1
        else:
            lines.append(f"({n} rows)")
    except sqlite3.Error as e:
        return _failed("SQL", e), True
    return "\n".join(lines), False


def _line(r, full=False):
    who = "me" if r["is_me"] in (1, "1") else (r["author"] or "")
    where = f" in {r['thread_name']}" if r["thread_name"] else ""
    body = (r["text"] or "") if full else (r["snip"] or (r["text"] or "")[:200])
    title = f"{r['title']} | " if r["title"] and r["title"] not in body else ""
    return f"#{r['rowid']}  {r['ts'] or '(no time)'}  {r['source']}/{r['kind']}  {who}{where}: {title}{body}".replace("\n", " ⏎ ")


def tool_search(a):
    q = a.get("query")
    if isinstance(q, (int, float)) and not isinstance(q, bool):
        q = str(q)
    if q is not None and not isinstance(q, str):
        return "query is the words to search for, as text.", True
    if q and len(q) > LONGEST:
        return f"That query is {len(q):,} characters long: keep it under {LONGEST:,}.", True
    sort = a.get("sort") or ("rank" if q else "time-desc")
    if sort not in ("rank", "time", "time-desc"):
        return "sort is rank (best matches first), time (oldest first) or time-desc (newest first).", True
    con = connect(SECONDS)
    con.row_factory = sqlite3.Row
    where, args = [], []
    for col, key in (("r.source", "source"), ("r.kind", "kind")):
        if a.get(key):
            parts = [p.strip() for p in str(a[key]).split(",") if p.strip()]
            if parts:
                where.append("(" + " or ".join(f"{col} like ?" for _ in parts) + ")")
                args += [f"{p}%" if key == "source" else p for p in parts]
    when = {}
    for key, op in (("after", ">="), ("before", "<")):
        if a.get(key):
            when[key], err = _when(a[key], key)
            if err:
                return err, True
            where.append(f"r.ts {op} ?")
            args.append(when[key])
    if len(when) == 2 and when["after"] >= when["before"]:
        return f"after ({when['after']}) isn't before before ({when['before']}): no time is in between. The other way round?", True
    if _yes(a.get("me")):
        where.append("r.is_me in (1, '1')")
    for col, key in (("r.thread_name", "thread"), ("r.author", "author")):
        if a.get(key):
            where.append(f"{col} like ?")
            args.append(f"%{a[key]}%")
    limit = max(1, min(int(a.get("limit") or 20), 200))
    full = _yes(a.get("full"))
    order = {"rank": "rank", "time": "r.ts", "time-desc": "r.ts desc"}[sort]
    cols = "r.rowid, r.ts, r.source, r.kind, r.author, r.is_me, r.thread, r.thread_name, r.title, r.text"
    if q:
        sql = (f"select {cols}, snippet(fts, 1, '[', ']', '…', 32) as snip from fts join records r on r.rowid = fts.rowid "
               f"where fts match ? {''.join(' and ' + w for w in where)} order by {order if sort != 'rank' else 'rank'} limit ?")
        params = [q, *args, limit]
    else:
        sql = f"select {cols}, null as snip from records r {'where ' + ' and '.join(where) if where else ''} order by {order if sort != 'rank' else 'r.ts desc'} limit ?"
        params = [*args, limit]
    try:
        rows = con.execute(sql, params).fetchall()
        if not rows:
            return _no_matches(con, a), False
        ctx = max(0, min(int(a.get("context") or 0), 10))
        out, size = [], 0
        for r in rows:
            if size > CAP - 200:  # past what one result holds
                out.append(f"... the rest left out: over {CAP:,} characters (lower limit, or leave out full)")
                break
            if ctx and r["thread"]:
                before = con.execute(f"select {cols}, null as snip from records r where r.source = ? and r.thread = ? and r.ts < ? "
                                     "order by r.ts desc limit ?", (r["source"], r["thread"], r["ts"], ctx)).fetchall()
                after = con.execute(f"select {cols}, null as snip from records r where r.source = ? and r.thread = ? and r.ts > ? "
                                    "order by r.ts limit ?", (r["source"], r["thread"], r["ts"], ctx)).fetchall()
                hit = ["  " + _line(x, full) for x in reversed(before)] + ["> " + _line(r, full)] + ["  " + _line(x, full) for x in after] + [""]
            else:
                hit = [_line(r, full)]
            out += hit
            size += sum(len(x) + 1 for x in hit)
    except sqlite3.Error as e:
        if "interrupted" in str(e):
            return _failed("Search", e), True
        return f"Search error: {e} (FTS5 syntax: quote phrases, and words with - or : in them)", True
    return "\n".join(out) + f"\n({len(rows)} hit{'s' if len(rows) != 1 else ''}{', more may exist: raise limit' if len(rows) == limit else ''})", False


def _no_matches(con, a):
    """Why a search found nothing, when it isn't the words: an empty library, or a source or kind there's none of."""
    if con.execute("select 1 from records limit 1").fetchone() is None:
        return "No matches: the library is empty (nothing has been read into it yet)."
    for col, key, prefix in (("source", "source", True), ("kind", "kind", False)):
        parts = [p.strip() for p in str(a.get(key) or "").split(",") if p.strip()]
        if not parts:
            continue
        if not any(con.execute(f"select 1 from records where {col} like ? limit 1", (f"{p}%" if prefix else p,)).fetchone() for p in parts):
            have = [v for (v,) in con.execute(f"select distinct {col} from records where {col} is not null order by 1")]
            return f"No matches: there's no {key} {', '.join(parts)}. The library's {key}s: {', '.join(have)}."
    return "No matches. Try other words, a prefix (word*), OR, fewer filters, or the sql tool."


# ---------------------------------------------------------------- python, sandboxed

BOOT = r'''
import sys, os, json, sqlite3, re, statistics
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
sys.path.insert(0, {connectors!r})
os.environ["ASK_ME_REDACT"] = "1"
from redact import install_if_asked
install_if_asked()
from pathlib import Path
CORPUS = Path({corpus!r}); NORM = CORPUS / "normalized"; MEDIA = CORPUS / "media"
sys.path.insert(0, {here!r})
import ask_tools as _t
_con = _t.connect()
_con.row_factory = sqlite3.Row

def sql(query, params=()):
    return [dict(r) for r in _con.execute(query, params)]

def records(source=None):
    paths = [NORM / f"{{source}}.jsonl"] if source else sorted(NORM.glob("*.jsonl"))
    for p in paths:
        with open(p) as f:
            for line in f:
                yield json.loads(line)

def stream(month):
    """A month's events in order ('2026-09'), from corpus/stream/ (connectors/stream.py)."""
    p = CORPUS / "stream" / f"{{month}}.jsonl"
    if not p.exists():
        return []
    with open(p) as f:
        return [json.loads(line) for line in f]

code = sys.stdin.read()
exec(compile(code, "<python tool>", "exec"), {{k: v for k, v in globals().items() if not k.startswith("_t")}})
'''


def sandbox_profile(scratch):
    """What the python tool may do: read the library's records and this code, write only its own scratch folder, and
    nothing else. No network, no other program (not `open`, not `osascript`), no Apple Events or Launch Services, no
    child processes, nothing of the home folder, other users' or other disks. The last rule that matches wins."""
    c = str(CORPUS.resolve())
    here = str(Path(__file__).resolve().parent)
    py = {os.path.realpath(sys.executable), sys.executable}
    # A framework Python (python.org's) starts its Python.app; a standalone one (the installed app's) is itself.
    run = " ".join(f'(literal "{p}")' for p in sorted(py)) + f' (subpath "{os.path.realpath(sys.base_prefix)}")'
    return ("(version 1)(allow default)(deny network*)"
            f"(deny process-fork)(deny process-exec)(allow process-exec {run})"
            "(deny appleevent-send)"
            '(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd") (global-name-prefix "com.apple.lsd.") '
            '(global-name "com.apple.coreservices.appleevents") (global-name "com.apple.pasteboard.1"))'
            f'(deny file-read* (subpath "{HOME}") (subpath "/Users") (subpath "/Volumes"))(allow file-read-metadata)'
            f'(allow file-read* (subpath "{c}/normalized") (subpath "{c}/media") (subpath "{c}/stream") (regex #"^{re.escape(c)}/corpus\\.db(-wal|-shm|-journal)?$") '
            f'(subpath "{CONNECTORS.resolve()}") (subpath "{here}") (subpath "{os.path.realpath(sys.base_prefix)}") (subpath "{scratch}"))'
            f'(deny file-write*)(allow file-write* (subpath "{scratch}") (literal "/dev/null"))'
            f'(deny file-write* (subpath "{c}"))')


def tool_python(a):
    boot = BOOT.format(connectors=str(CONNECTORS.resolve()), corpus=str(CORPUS.resolve()), here=str(Path(__file__).resolve().parent))
    # Its own scratch folder, gone afterwards: nothing it writes is left where anything else (an agent's run folder, the
    # next call) would find it.
    scratch = os.path.realpath(tempfile.mkdtemp(prefix="ump-py-"))
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "ASK_ME_REDACT": "1", "CORPUS_DIR": str(CORPUS.resolve()), "UMP_REPO": str(REPO),
           "TMPDIR": scratch, "HOME": scratch}
    p = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", sandbox_profile(scratch), sys.executable, "-I", "-c", boot], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=scratch, start_new_session=True)
    try:
        out, err = p.communicate(a.get("code", ""), timeout=120)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = "", "Stopped after 120 s: make it faster (sql is quicker than records()), or do less per call.", 1
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)  # anything it started goes with it
        except OSError:
            pass
        p.wait()
        shutil.rmtree(scratch, ignore_errors=True)
    # Blanked here too, as a whole: what the tool prints itself is blanked line by line, which a key spread over lines
    # or a write to sys.__stdout__ gets around.
    out = redact(out or "")
    text = out if len(out) <= CAP else out[:CAP] + f"\n... (cut at {CAP} of {len(out)} characters: print less, or aggregate)"
    if rc:
        text += "\n[error]\n" + redact("\n".join((err or "").strip().splitlines()[-25:]))
    return text or "(nothing printed: print what you need)", bool(rc)


# ---------------------------------------------------------------- files records point to

def _record(rowid):
    con = connect()
    con.row_factory = sqlite3.Row
    r = con.execute("select rowid, * from records where rowid = ?", (int(rowid),)).fetchone()
    return dict(r) if r else None


def _record_file(a, prefer=None):
    """The path a record points to (meta.path, or meta.files[i]), resolved; or an error message. Without a file index,
    the first file with an extension in `prefer` (a photo's picture rather than its Live Photo video)."""
    try:
        rowid = int(a.get("rowid"))
    except (TypeError, ValueError):
        return None, "Give rowid: a record's number (the # of a search hit)."
    r = _record(rowid) if abs(rowid) < 2 ** 63 else None
    if not r:
        return None, f"No record #{rowid}."
    meta = json.loads(r["meta"] or "{}")
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    files = [f if isinstance(f, str) else (f.get("path") if isinstance(f, dict) else None) for f in files]
    files = [f for f in files if f]
    if a.get("file") is not None or files:
        first = next((j for j, f in enumerate(files) if Path(f).suffix.lower() in prefer), 0) if prefer else 0
        i = int(a["file"]) if a.get("file") is not None else first
        if not 0 <= i < len(files):
            return None, f"Record #{r['rowid']} has {len(files)} file{'s' if len(files) != 1 else ''}" + (f" (0 to {len(files) - 1})." if files else ".")
        p = files[i]
    elif meta.get("path"):
        p = meta["path"]
    else:
        return None, f"Record #{r['rowid']} doesn't point to a file."
    path = Path(p).expanduser()
    if not path.is_absolute():  # one of the library's own files: never one a ../ takes out of it
        logical = record_path(p, CORPUS)
        path = logical.resolve()
        # The app deliberately links raw/iphone to its local decrypted mirror, outside an iCloud-synced corpus.
        # A record under that link may reach the mirror, but a link inside it mustn't reach anything beyond it.
        mirror = CORPUS / "raw/iphone"
        in_mirror = logical.is_relative_to(mirror) and path.is_relative_to(mirror.resolve())
        if not path.is_relative_to(CORPUS.resolve()) and not in_mirror:
            return None, f"Record #{r['rowid']} points to a file outside the library ({Path(p).name}), so it isn't read."
    if not path.exists():
        return None, f"The file record #{r['rowid']} points to isn't on this Mac any more ({path.name})."
    return path, None


TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".tex", ".py", ".js", ".ts", ".log", ".yaml", ".yml", ".eml", ".vtt", ".srt"}
def _webarchive_text(path):
    """A saved web page's text, from the archive itself (no network: nothing it refers to is fetched)."""
    try:
        import plistlib
        main = plistlib.loads(Path(path).read_bytes()).get("WebMainResource") or {}
        html = (main.get("WebResourceData") or b"").decode(main.get("WebResourceTextEncodingName") or "utf-8", "replace")
    except Exception:
        return ""
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"<[^>]+>", " ", html)
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(text)).strip()


TEXT_MOST = 50_000_000  # bytes of a text file read_file reads
DOC_EXT = {".docx", ".doc", ".rtf", ".rtfd", ".pages", ".odt", ".webarchive"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tiff", ".tif", ".bmp"}
VIDEO_EXT = {".mov", ".mp4", ".m4v"}


def _extract(path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return None, "Reading PDFs needs pypdf (the app's Python packages check installs it)."
        return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages), None
    if ext in DOC_EXT:
        if ext == ".webarchive":  # its page, read here: textutil would load what the page links to
            return _webarchive_text(path), None
        p = subprocess.run(["/usr/bin/textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, text=True, timeout=60)
        return (p.stdout, None) if p.returncode == 0 else (None, f"Couldn't read {path.name}.")
    if ext in (".xlsx", ".xlsm"):  # each sheet's cell text, as Documents reads it
        from documents import xlsx_text
        try:
            return xlsx_text(path), None
        except Exception:  # not a real spreadsheet, or a password-protected one
            return None, f"Couldn't read {path.name}."
    if ext in IMAGE_EXT:
        return None, "That's an image: use view_image."
    if ext in TEXT_EXT or path.stat().st_size < 2_000_000:
        with path.open("rb") as f:  # the first 50 MB of a bigger one (a log of years), not all of it in memory
            data = f.read(TEXT_MOST)
        if b"\x00" in data[:4096]:
            return None, f"{path.name} isn't text."
        more = path.stat().st_size - len(data)
        return data.decode("utf-8", "replace") + (f"\n\n[{more:,} more bytes of {path.name} aren't read: it's too big]" if more > 0 else ""), None
    return None, f"{path.name} isn't a kind of file the app can read."


def tool_read_file(a):
    path, err = _record_file(a)
    if err:
        return err, True
    text, err = _extract(path)
    if err:
        return err, True
    if not text.strip():
        return f"{path.name} has no text to read (a scan?). view_image shows {'its first page' if path.suffix.lower() == '.pdf' else 'it'} instead.", True
    offset = max(0, int(a.get("offset") or 0))
    length = max(100, min(int(a.get("length") or 8000), 20000))
    part = text[offset:offset + length]
    more = len(text) - (offset + len(part))
    head = f"{path.name}: characters {offset}-{offset + len(part)} of {len(text)}" + (f" ({more} more: offset={offset + len(part)})" if more > 0 else "")
    return head + "\n\n" + redact(part), False


def tool_view_image(a):
    path, err = _record_file(a, prefer=IMAGE_EXT | {".pdf"})
    if err:
        return err, True, []
    ext = path.suffix.lower()
    if ext not in IMAGE_EXT | VIDEO_EXT | {".pdf"}:  # a PDF shows its first page, a video a still
        return f"{path.name} isn't an image: use read_file.", True, []
    with tempfile.TemporaryDirectory() as tmp:
        src = path
        if ext in VIDEO_EXT:
            subprocess.run(["/usr/bin/qlmanage", "-t", "-s", "1568", "-o", tmp, str(path)], capture_output=True, timeout=60)
            src = Path(tmp) / f"{path.name}.png"
            if not src.exists():
                return f"Couldn't make a still of {path.name}.", True, []
        out = Path(tmp) / "view.jpg"
        p = subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "80", "-Z", "1568", str(src), "--out", str(out)],
                           capture_output=True, text=True, timeout=60)
        if p.returncode or not out.exists():
            return f"Couldn't open {path.name}.", True, []
        data = base64.b64encode(out.read_bytes()).decode()
    what = " (a still from the video)" if ext in VIDEO_EXT else ""
    return f"{path.name}{what}, record #{a['rowid']}", False, [{"media_type": "image/jpeg", "data": data}]


def call(name, a):
    """One tool call -> {"text", "images", "error", "seconds"}. Text is blanked of secrets."""
    t = time.time()
    images = []
    try:
        if not isinstance(a, dict):
            raise TypeError("they're a JSON object, like {\"query\": \"...\"}")
        if name == "sql":
            text, err = tool_sql(a)
        elif name == "search":
            text, err = tool_search(a)
        elif name == "python":
            text, err = tool_python(a)
        elif name == "read_file":
            text, err = tool_read_file(a)
        elif name == "view_image":
            text, err, images = tool_view_image(a)
        else:
            text, err = f"No tool named {name}.", True
    except (KeyError, ValueError, TypeError) as e:
        text, err = f"Bad arguments for {name}: {e}", True
    except (FileNotFoundError, sqlite3.Error, OSError) as e:
        text, err = f"{name} failed: {e}", True
    except Exception as e:  # noqa: BLE001 - anything else a call trips on is its answer, never the end of the tools
        text, err = f"{name} failed: {type(e).__name__}: {e}", True
    if name not in ("python", "read_file"):  # those redact what they print themselves
        text = redact(text)
    if len(text) > CAP:
        text = text[:CAP] + f"\n... (cut at {CAP} characters)"
    return {"text": text, "images": images, "error": bool(err), "seconds": round(time.time() - t, 3)}


# ---------------------------------------------------------------- for the app

def record_view(rowid):
    """A record as the app shows it when an answer cites it (stays on this Mac, so not blanked)."""
    r = _record(rowid)
    if not r:
        return None
    meta = json.loads(r.pop("meta") or "{}")
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    return {**r, "meta": meta, "files": [str(f) for f in files][:20]}


def inventory():
    """Records per source, and their first and last dates: of the times that can be right (from 1900 to tomorrow, and
    not Apple's first second, which is a missing time read as 0), as Explore counts them."""
    con = connect()
    tomorrow = (datetime.now(timezone.utc).date().toordinal() + 1)
    end = datetime.fromordinal(tomorrow).strftime("%Y-%m-%dT99")
    ok = f"case when ts >= '1900' and ts < '{end}' and ts not like '1900-01-01T00:00:00%' and ts not like '1970-01-01T00:00:00%' and ts not like '2001-01-01T00:00:00%' and ts not in ('1900-01-01', '1970-01-01', '2001-01-01') then ts end"
    rows = con.execute(f"select source, count(*), min({ok}), max({ok}) from records group by source order by count(*) desc").fetchall()
    return [{"source": s, "count": n, "first": (a or "")[:10], "last": (b or "")[:10]} for s, n, a, b in rows]


# ---------------------------------------------------------------- for Claude Code and Codex

def relay(box, name, args, image_files=False):
    """One tool call handed to the app through the run's mailbox folder: the agent (and, for Codex, its shell) is
    sandboxed away from the corpus and can't open sockets; the app isn't, and answers with call() above. A request is
    <id>.req, its answer <id>.res (each written under another name, then renamed into place)."""
    box = Path(box)
    rid = os.urandom(8).hex()
    tmp = box / f"{rid}.part"
    tmp.write_text(json.dumps({"name": name, "args": args, "image_files": image_files}))
    tmp.rename(box / f"{rid}.req")
    res = box / f"{rid}.res"
    deadline = time.time() + 300
    while time.time() < deadline:
        if res.exists():
            r = json.loads(res.read_text())
            res.unlink(missing_ok=True)
            return r
        time.sleep(0.02)
    return {"text": "The app didn't answer in time.", "error": True, "images": []}


def mcp(box):
    """A stdio MCP server (for Claude Code) whose tool calls go to the app through the mailbox."""
    defs = [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]} for t in TOOLS]
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue
        if method == "initialize":
            res = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                   "serverInfo": {"name": "corpus", "version": "1"}}
        elif method == "tools/list":
            res = {"tools": defs}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                r = relay(box, p.get("name"), p.get("arguments") or {})
            except OSError as e:
                r = {"text": f"The app isn't reachable: {e}", "error": True, "images": []}
            content = [{"type": "text", "text": r.get("text", "")}] + [{"type": "image", "data": i["data"], "mimeType": i["media_type"]} for i in r.get("images") or []]
            res = {"content": content, "isError": bool(r.get("error"))}
        elif method == "ping":
            res = {}
        else:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
        sys.stdout.flush()


def ask_command(box, name, inline=None):
    """`ask NAME` in Codex's shell: JSON arguments on stdin, the result on stdout (images are saved as files). The
    arguments on the command line work too (`ask sql '{...}'`): Codex runs commands in a terminal, where waiting on
    stdin that never comes would hang the lookup for good."""
    if inline is not None:
        raw = inline.strip()
    elif sys.stdin.isatty():
        print(f"No arguments. Pass them as a JSON object on stdin, in a heredoc: ask {name} <<'EOF' ... EOF")
        return 1
    else:
        raw = sys.stdin.read().strip()
    try:
        args = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        print(f"The arguments aren't JSON ({e}). Pass them as a JSON object on stdin, in a heredoc: ask {name} <<'EOF' ... EOF")
        return 1
    r = relay(box, name, args, image_files=True)
    print(r.get("text", ""))
    return 1 if r.get("error") else 0


def serve():
    """For the app: one call per line of stdin, {"id", "name", "args"}, each answered with a line of call()'s result."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue  # not a call: nothing to answer
        if not isinstance(req, dict):
            continue
        sys.stdout.write(json.dumps({"id": req.get("id"), **call(req.get("name", ""), req.get("args") or {})}) + "\n")
        sys.stdout.flush()


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "tools":
        print(json.dumps(TOOLS))
    elif cmd == "call":
        print(json.dumps(call(argv[1], json.loads(sys.stdin.read() or "{}"))))
    elif cmd == "record":
        print(json.dumps(record_view(int(argv[1])), default=str))
    elif cmd == "inventory":
        print(json.dumps(inventory()))
    elif cmd == "serve":
        serve()
    elif cmd == "mcp":
        mcp(argv[argv.index("--box") + 1])
    elif cmd == "ask":
        rest = argv[argv.index("--box") + 2:]  # the tool's name, and its arguments if they're given there
        if not rest:
            print("Which tool? ask NAME, with its arguments as JSON on stdin.")
            return 2
        return ask_command(argv[argv.index("--box") + 1], rest[0], rest[1] if len(rest) > 1 else None)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
