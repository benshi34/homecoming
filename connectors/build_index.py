"""Load every corpus/normalized/*.jsonl into one searchable SQLite DB: corpus/corpus.db
(records table + FTS5 full-text index over title/text/author/thread/participants).

One email is one record: the same message (by Message-ID) read from Mail on this Mac and from a mailbox export
(Takeout's Gmail, an exported Outlook mailbox) is kept once, the export's copy, and Mail's count of the others goes in
the manifest's notes. Each source's own file keeps every message it read.

Only the sources whose files changed since the last build are loaded again (built_from keeps each file's size, time
and a hash of what it says: one written again the same is left as it is), into a clone of the database that then
takes its place, so a search never sees half a build. Mail goes again whenever a source with emails does (which of
its emails are an export's depends on them). It's built from nothing when the database is from before this (or
UMP_FULL_INDEX=1), when most of it changed, or when it has come to hold a lot of free space from what it dropped."""

import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
from itertools import islice

from common import CORPUS, FIELDS, MANIFEST, NORM, write_manifest

DB = CORPUS / "corpus.db"
COLS = [f for f in FIELDS]
SCHEMA = 2  # v2 reserves record numbers across incremental updates, full builds and deletions
FTS_COLS = "title, text, author, thread_name, participants"


def note_same(same):
    """Mail's emails that were already in the library from an export, in the manifest (shown on its page). Written
    only when it changes, and before the new index is in place: an index older than the manifest is rebuilt."""
    try:
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        return
    entry = manifest.get("mail")
    if not entry:
        return
    notes = dict(entry.get("notes") or {})
    if same.get("mail"):
        notes["in_an_export"] = same["mail"]
    else:
        notes.pop("in_an_export", None)
    if notes == (entry.get("notes") or {}):
        return
    if notes:
        entry["notes"] = notes
    else:
        entry.pop("notes", None)
    write_manifest(manifest)


class Rows:
    """A normalized file's records as table rows, read a line at a time (never all of a source at once). emails: the
    export emails' ids so far (Mail's copies of them are left out, and counted). Afterwards: how many rows, how many
    of Mail's were left out, whether it had emails, and the hash of the file."""

    def __init__(self, path, emails):
        self.path, self.emails, self.n, self.same, self.email, self.hash = path, emails, 0, 0, False, hashlib.sha1()

    def __iter__(self):
        with self.path.open("rb") as f:
            for line in f:
                self.hash.update(line)
                r = json.loads(line)
                if r.get("kind") == "email":
                    self.email = True
                    if r.get("id") in self.emails and self.path.stem == "mail":
                        self.same += 1
                        continue
                    self.emails.add(r.get("id"))
                r["is_me"] = None if r.get("is_me") is None else int(bool(r["is_me"]))
                for k in ("participants", "meta"):
                    if r.get(k) is None:
                        r[k] = None
                    elif k == "meta":
                        r[k] = json.dumps(r[k], ensure_ascii=False)
                    elif isinstance(r[k], (list, tuple)):
                        r[k] = ", ".join(map(str, r[k]))
                    else:  # one record from one app shaped oddly mustn't stop the whole index
                        r[k] = str(r[k])
                self.n += 1
                yield tuple(r.get(c) for c in COLS)


def file_hash(path):
    h = hashlib.sha1()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def files():
    """{source: (size, mtime_ns, path)} of the normalized files, Mail on this Mac last: an email it shares with an
    export is the export's."""
    out = {}
    for path in sorted(NORM.glob("*.jsonl"), key=lambda p: (p.stem == "mail", p.stem)):
        st = path.stat()
        out[path.stem] = (st.st_size, st.st_mtime_ns, path)
    return out


def load(con, source, f, emails):
    """One source's file into the table, and noted in built_from. Returns its Rows."""
    rows = Rows(f[2], emails)
    # Stage a source in bulk, then join it to its permanent numbers. Assigning numbers as records are inserted
    # would make a saved Ask citation point elsewhere after a source is re-read or the index is rebuilt.
    con.execute(f"create temp table if not exists incoming as select {', '.join(COLS)} from records where 0")
    records = iter(rows)
    # Bound the staging space even for a multi-gigabyte mailbox or message history.
    for batch in iter(lambda: list(islice(records, 512)), []):
        con.execute("delete from incoming")
        con.executemany(f"insert into incoming values ({', '.join('?' * len(COLS))})", batch)
        con.execute("""insert into record_ids (key)
                       select distinct record_key(source, id) from incoming i
                       where not exists (select 1 from record_ids k where k.key = record_key(i.source, i.id))""")
        con.execute(f"""insert or ignore into records (rowid, {', '.join(COLS)})
                        select k.rowid, {', '.join('i.' + c for c in COLS)} from incoming i
                        join record_ids k on k.key = record_key(i.source, i.id)""")
    con.execute("delete from incoming")
    con.execute("insert into built_from values (?, ?, ?, ?, ?, ?)", (source, f[0], f[1], rows.hash.hexdigest(), rows.n, rows.same))
    return rows


def record_key(source, rid):
    # Deleted records leave only an opaque reservation, not their original source or identifier.
    return hashlib.sha256(json.dumps([source, rid], ensure_ascii=False).encode()).hexdigest()


def fresh(tmp, now):
    """A new database with every source in it: {source: (rows, Mail's left out)}."""
    con = sqlite3.connect(tmp)
    con.create_function("record_key", 2, record_key, deterministic=True)
    con.execute("pragma journal_mode = off")  # a file of its own until it's done: nothing to roll back to
    con.executescript(f"""
        create table records (rowid integer primary key, {", ".join(f"{c} text" for c in COLS)}, unique(source, id));
        create table record_ids (rowid integer primary key, key text not null unique);
        create virtual table fts using fts5({FTS_COLS},
            content='records', content_rowid='rowid', tokenize='porter unicode61 remove_diacritics 2');
        create table built_from (source text primary key, size integer, mtime_ns integer, hash text, rows integer, same integer);
    """)
    if DB.exists():
        previous = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            # Keep reservations for deleted records too: a missing citation must never open a new record. On the
            # first v2 build, adopt the existing numbers so saved answers survive the upgrade.
            if previous.execute("select 1 from sqlite_master where name = 'record_ids'").fetchone():
                reserved = previous.execute("select rowid, key from record_ids")
            else:
                reserved = ((rowid, record_key(source, rid)) for rowid, source, rid in previous.execute("select rowid, source, id from records"))
            con.executemany("insert into record_ids (rowid, key) values (?, ?)", reserved)
        finally:
            previous.close()
    totals, emails = {}, set()
    for source, f in now.items():
        r = load(con, source, f, emails)
        totals[source] = (r.n, r.same)
    con.executescript(f"""
        insert into fts(fts) values('rebuild');
        create index records_ts on records(ts);
        create index records_source_ts on records(source, ts);
        create index records_thread_ts on records(thread, ts);
        create index records_kind_source on records(kind, source);
        pragma user_version = {SCHEMA};
    """)
    con.commit()
    con.close()
    return totals, True


def clone(src, dst):
    """dst as an APFS clone of src (no copying, no space until one changes), else a plain copy."""
    try:
        if ctypes.CDLL(None).clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
            return
    except (OSError, AttributeError):
        pass
    shutil.copyfile(src, dst)


def built():
    """{source: (size, mtime_ns, hash, rows, same)} the database was built from, or None if it wasn't built this way."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            if con.execute("pragma user_version").fetchone()[0] != SCHEMA:
                return None
            return {s: tuple(x) for s, *x in con.execute("select source, size, mtime_ns, hash, rows, same from built_from")}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def drop(con, source):
    """A source's records out of the table and the search index (an index of another table's text is told what it had)."""
    con.execute(f"insert into fts(fts, rowid, {FTS_COLS}) select 'delete', rowid, {FTS_COLS} from records where source = ?", (source,))
    con.execute("delete from records where source = ?", (source,))
    con.execute("delete from built_from where source = ?", (source,))


def index_text(con, source):
    con.execute(f"insert into fts(rowid, {FTS_COLS}) select rowid, {FTS_COLS} from records where source = ?", (source,))


def update(tmp, now, was):
    """The database, cloned to tmp, with the sources whose files changed loaded again: {source: (rows, Mail's left
    out)}, and whether Mail's were counted again. None when building it from nothing is as quick (most of it changed)
    or tidier (it holds a lot of free space)."""
    touched = [s for s in now if now[s][:2] != was.get(s, (None, None))[:2]]
    hashes = {s: file_hash(now[s][2]) for s in touched if s in was}
    same_text = [s for s in hashes if hashes[s] == was[s][2]]  # written again, saying the same
    changed = [s for s in touched if s not in same_text]
    gone = [s for s in was if s not in now]
    if sum(now[s][0] for s in changed) + sum(was[s][0] for s in gone) > sum(f[0] for f in now.values()) / 2:
        return None
    clone(DB, tmp)
    con = sqlite3.connect(tmp)
    con.create_function("record_key", 2, record_key, deterministic=True)
    con.execute("pragma journal_mode = off")
    if con.execute("pragma freelist_count").fetchone()[0] * 4 > con.execute("pragma page_count").fetchone()[0]:
        con.close()
        return None
    for s in same_text:
        con.execute("update built_from set size = ?, mtime_ns = ? where source = ?", (now[s][0], now[s][1], s))
    totals = {s: (n, same) for s, (_, _, _, n, same) in was.items()}
    emails_moved = False  # an export's emails changed: which of Mail's it has may be different now
    for s in gone + changed:
        if s != "mail":
            emails_moved = emails_moved or con.execute("select 1 from records where kind = 'email' and source = ? limit 1", (s,)).fetchone() is not None
            drop(con, s)
            totals.pop(s, None)
    for s in changed:
        if s != "mail":
            r = load(con, s, now[s], set())
            index_text(con, s)
            totals[s] = (r.n, r.same)
            emails_moved = emails_moved or r.email
    mail = "mail" in now and (emails_moved or "mail" in changed)
    if mail or "mail" in gone:
        drop(con, "mail")
        totals.pop("mail", None)
    if mail:
        emails = {i for (i,) in con.execute("select id from records where kind = 'email' and source != 'mail'")}
        r = load(con, "mail", now["mail"], emails)
        index_text(con, "mail")
        totals["mail"] = (r.n, r.same)
    con.commit()
    con.close()
    again = [s for s in changed if s != "mail"] + (["mail"] if mail else [])
    print(f"index: read again {', '.join(again) or 'nothing'}" + (f"; taken out {', '.join(gone)}" if gone else ""))
    return {s: totals[s] for s in now if s in totals}, mail or "mail" in gone


def main():
    tmp = DB.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    now = files()
    was = built() if DB.exists() and os.environ.get("UMP_FULL_INDEX") != "1" else None
    result = update(tmp, now, was) if was is not None else None
    if result is None:
        tmp.unlink(missing_ok=True)
        result = fresh(tmp, now)
    totals, mail = result
    if mail:  # what Mail shares with an export was counted again
        note_same({"mail": totals["mail"][1]} if "mail" in totals else {})
    tmp.replace(DB)
    os.utime(DB)  # newer than the manifest it was built from, note included: the app rebuilds an index older than it
    for k, (n, same) in totals.items():
        print(f"{k:18s} {n:>8,}" + (f"  ({same:,} already in an export)" if same else ""))
    print(f"{'TOTAL':18s} {sum(n for n, _ in totals.values()):>8,}  -> {DB}")
    # The event stream (corpus/stream/), for the months whose records changed. Never fails the index.
    try:
        import stream
        stream.build()
    except Exception as e:  # noqa: BLE001
        print(f"stream: not updated ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
