"""Search the personal corpus.

    python3 search.py "dinner plans"                      # full-text, best matches first
    python3 search.py "thesis" --source imessage,notes --after 2025-01-01 --me
    python3 search.py "mom" --kind message --context 4    # show surrounding messages in each thread
    python3 search.py --thread "Family" --after 2026-09-01 --sort time   # browse, no query
    python3 search.py --stats

FTS5 query syntax works: "exact phrase", prefix*, a OR b, NEAR(a b, 5), title:resume.
"""

import argparse
import json
import sqlite3
import sys

from common import CORPUS

DB = CORPUS / "corpus.db"


def stats(con):
    for src, n, first, last in con.execute(
            "select source, count(*), min(ts), max(ts) from records group by source order by count(*) desc"):
        print(f"{src:18s} {n:>8,}  {str(first)[:10]} → {str(last)[:10]}")
    print(f"{'TOTAL':18s} {con.execute('select count(*) from records').fetchone()[0]:>8,}")


def main(argv=None):
    from redact import install_if_asked
    install_if_asked()  # the ask-my-data app sets ASK_ME_REDACT=1: no secret reaches the model
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?")
    ap.add_argument("--source", help="comma-separated sources (prefix match, e.g. 'notes' matches apple_notes)")
    ap.add_argument("--kind", help="comma-separated kinds")
    ap.add_argument("--after")
    ap.add_argument("--before")
    ap.add_argument("--me", action="store_true", help="only things the user wrote/did")
    ap.add_argument("--thread", help="substring of thread name")
    ap.add_argument("--author", help="substring of author")
    ap.add_argument("-n", "--limit", type=int, default=20)
    ap.add_argument("--sort", choices=["rank", "time", "time-desc"], default=None)
    ap.add_argument("--context", type=int, default=0, help="show N records before/after in the same thread")
    ap.add_argument("--full", action="store_true", help="print full text instead of a snippet")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args(argv)

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if a.stats:
        return stats(con)

    where, params = [], []
    if a.query:
        where.append("fts match ?")
        params.append(a.query)
    if a.source:
        srcs = [s.strip() for s in a.source.split(",")]
        where.append("(" + " or ".join("r.source like ?" for _ in srcs) + ")")
        params += [f"%{s}%" for s in srcs]
    if a.kind:
        kinds = [k.strip() for k in a.kind.split(",")]
        where.append(f"r.kind in ({','.join('?' * len(kinds))})")
        params += kinds
    if a.after:
        where.append("r.ts >= ?")
        params.append(a.after)
    if a.before:
        where.append("r.ts < ?")
        params.append(a.before)
    if a.me:
        where.append("r.is_me = 1")
    if a.thread:
        where.append("r.thread_name like ?")
        params.append(f"%{a.thread}%")
    if a.author:
        where.append("r.author like ?")
        params.append(f"%{a.author}%")
    sort = a.sort or ("rank" if a.query else "time-desc")
    order = {"rank": "bm25(fts, 4.0, 1.0, 1.0, 2.0, 1.0)", "time": "r.ts", "time-desc": "r.ts desc"}[sort]
    snippet = "snippet(fts, 1, '[', ']', ' … ', 24)" if a.query else "substr(r.text, 1, 240)"
    join = "join fts on fts.rowid = r.rowid" if a.query else ""
    sql = (f"select r.*, {snippet} snip from records r {join} "
           f"{'where ' + ' and '.join(where) if where else ''} order by {order} limit ?")
    try:
        rows = con.execute(sql, params + [a.limit]).fetchall()
    except sqlite3.OperationalError as e:
        sys.exit(f"query error: {e} (quote special characters, e.g. '\"don't\"')")

    out = []
    for r in rows:
        item = {k: r[k] for k in r.keys() if k not in ("snip",) and r[k] is not None}
        if not a.full:
            item["text"] = r["snip"]
        if a.context and r["thread"]:
            around = con.execute(
                """select * from (select ts, author, text from records where thread = ? and source = ? and ts < ?
                                  order by ts desc limit ?) union all
                   select * from (select ts, author, text from records where thread = ? and source = ? and ts > ?
                                  order by ts limit ?) order by ts""",
                (r["thread"], r["source"], r["ts"], a.context, r["thread"], r["source"], r["ts"], a.context)).fetchall()
            item["context"] = [dict(x) for x in around]
        out.append(item)

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for item in out:
        where_ = item.get("thread_name") or item.get("title") or ""
        who = item.get("author", "")
        print(f"{str(item.get('ts', ''))[:16]}  {item['source']}/{item.get('kind', '')}  {where_[:50]}  {who}")
        for c in item.get("context", []):
            if c["ts"] < item.get("ts", ""):
                print(f"      {c['ts'][:16]} {c['author'] or ''}: {(c['text'] or '')[:160]}")
        print("    " + (item.get("text") or "").replace("\n", " ")[: (100_000 if a.full else 400)])
        for c in item.get("context", []):
            if c["ts"] > item.get("ts", ""):
                print(f"      {c['ts'][:16]} {c['author'] or ''}: {(c['text'] or '')[:160]}")
        print()


if __name__ == "__main__":
    main()
