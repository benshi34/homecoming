"""Load every corpus/normalized/*.jsonl into one searchable SQLite DB: corpus/corpus.db
(records table + FTS5 full-text index over title/text/author/thread/participants)."""

import json
import sqlite3

from common import CORPUS, FIELDS, NORM

DB = CORPUS / "corpus.db"
COLS = [f for f in FIELDS]


def main():
    tmp = DB.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(f"""
        create table records (rowid integer primary key, {", ".join(f"{c} text" for c in COLS)}, unique(source, id));
        create virtual table fts using fts5(title, text, author, thread_name, participants,
            content='records', content_rowid='rowid', tokenize='porter unicode61 remove_diacritics 2');
    """)
    totals = {}
    for path in sorted(NORM.glob("*.jsonl")):
        rows = []
        for line in path.open():
            r = json.loads(line)
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
    tmp.replace(DB)
    for k, v in totals.items():
        print(f"{k:18s} {v:>8,}")
    print(f"{'TOTAL':18s} {sum(totals.values()):>8,}  -> {DB}")
    # The event stream (corpus/stream/), for the months whose records changed. Never fails the index.
    try:
        import stream
        stream.build()
    except Exception as e:  # noqa: BLE001
        print(f"stream: not updated ({type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
