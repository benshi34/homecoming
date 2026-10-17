"""Load every corpus/normalized/*.jsonl into one searchable SQLite DB: corpus/corpus.db
(records table + FTS5 full-text index over title/text/author/thread/participants).

One email is one record: the same message (by Message-ID) read from Mail on this Mac and from a mailbox export
(Takeout's Gmail, an exported Outlook mailbox) is kept once, the export's copy, and Mail's count of the others goes in
the manifest's notes. Each source's own file keeps every message it read."""

import json
import os
import sqlite3

from common import CORPUS, FIELDS, MANIFEST, NORM

DB = CORPUS / "corpus.db"
COLS = [f for f in FIELDS]


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
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def main():
    tmp = DB.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(f"""
        create table records (rowid integer primary key, {", ".join(f"{c} text" for c in COLS)}, unique(source, id));
        create virtual table fts using fts5(title, text, author, thread_name, participants,
            content='records', content_rowid='rowid', tokenize='porter unicode61 remove_diacritics 2');
    """)
    totals, emails, same = {}, set(), {}
    # Mail on this Mac last: an email it shares with an export is the export's.
    for path in sorted(NORM.glob("*.jsonl"), key=lambda p: (p.stem == "mail", p.stem)):
        rows = []
        for line in path.open():
            r = json.loads(line)
            if r.get("kind") == "email":
                if r.get("id") in emails and path.stem == "mail":
                    same[path.stem] = same.get(path.stem, 0) + 1
                    continue
                emails.add(r.get("id"))
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
            rows.append(tuple(r.get(c) for c in COLS))
        con.executemany(f"insert or ignore into records ({', '.join(COLS)}) values ({', '.join('?' * len(COLS))})", rows)
        totals[path.stem] = len(rows)
    con.executescript("""
        insert into fts(fts) values('rebuild');
        create index records_ts on records(ts);
        create index records_source_ts on records(source, ts);
        create index records_thread_ts on records(thread, ts);
    """)
    con.commit()
    con.execute("vacuum")
    con.close()
    note_same(same)
    tmp.replace(DB)
    os.utime(DB)  # newer than the manifest it was built from, note included: the app rebuilds an index older than it
    for k, v in totals.items():
        print(f"{k:18s} {v:>8,}" + (f"  ({same[k]:,} already in an export)" if same.get(k) else ""))
    print(f"{'TOTAL':18s} {sum(totals.values()):>8,}  -> {DB}")
    # The event stream (corpus/stream/), for the months whose records changed. Never fails the index.
    try:
        import stream
        stream.build()
    except Exception as e:  # noqa: BLE001
        print(f"stream: not updated ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
