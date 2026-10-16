"""glance.py: a collected source at a glance, on a small made-up library."""

import datetime as dt
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "py"))
import glance  # noqa: E402

COLS = ["id", "source", "kind", "ts", "ts_end", "author", "is_me", "thread", "thread_name", "participants", "title", "text", "url", "meta"]


def library(rows):
    d = tempfile.mkdtemp()
    db = Path(d) / "corpus.db"
    con = sqlite3.connect(db)
    con.execute(f"create table records (rowid integer primary key, {', '.join(c + ' text' for c in COLS)}, unique(source, id))")
    for i, r in enumerate(rows):
        r = {"id": str(i), **r}
        if isinstance(r.get("meta"), dict):
            r["meta"] = json.dumps(r["meta"])
        con.execute(f"insert into records ({', '.join(r)}) values ({', '.join('?' * len(r))})", list(r.values()))
    con.commit()
    con.close()
    return db


class GlanceTest(unittest.TestCase):
    def test_messages_over_time_and_in_words(self):
        # The library keeps UTC; the charts are in this Mac's time zone. Noon UTC is the same day everywhere but the far east (and June has no clock change).
        rows = [{"source": "imessage", "kind": "message", "ts": f"2024-06-{d:02d}T12:00:00Z", "is_me": "1" if d % 2 else "0", "thread": "t1",
                 "thread_name": "Maya Chen", "text": "hello there"} for d in range(1, 11)]
        rows += [{"source": "imessage", "kind": "message", "ts": "2024-08-02T20:30:00Z", "is_me": "0", "thread": "t2", "text": "x"}]
        g = glance.glance(library(rows), ["imessage"])
        self.assertEqual(g["total"], 11)
        self.assertEqual(g["months"], {"2024-06": 10, "2024-08": 1})
        self.assertEqual(sum(g["hours"]), 11)
        local = dt.datetime(2024, 6, 1, 12, tzinfo=dt.timezone.utc).astimezone().hour
        self.assertEqual(g["hours"][local], 10, "at this Mac's hour")
        facts = {f["label"]: f for f in g["facts"]}
        self.assertEqual(facts["Your first message"]["value"], "Jun 1, 2024, with Maya Chen")
        self.assertEqual(facts["Your first message"]["detail"], "“hello there”")
        self.assertEqual(facts["Longest run"]["value"], "10 days in a row")
        self.assertEqual(facts["Written by you"]["value"], "45%")
        self.assertEqual(facts["Conversations"]["value"], "2")

    def test_calls_health_and_what_isnt_activity(self):
        rows = [{"source": "calls", "kind": "call", "ts": "2025-01-05T10:00:00", "thread_name": "Dad", "meta": {"seconds": 3600}},
                {"source": "calls", "kind": "call", "ts": "2025-01-06T10:00:00", "meta": {"seconds": 600}},
                {"source": "health", "kind": "health_day", "ts": "2025-01-05", "meta": {"steps": 10000, "distance_km": 7}},
                {"source": "health", "kind": "health_day", "ts": "2025-01-06", "meta": {"steps": 4000, "distance_km": 3}},
                {"source": "health", "kind": "health_sample", "ts": "2025-01-06T08:00:00"}]
        db = library(rows)
        calls = {f["label"]: f for f in glance.glance(db, ["calls"])["facts"]}
        self.assertEqual(calls["Time on calls"]["value"], "1.2 hours")
        self.assertEqual(calls["Longest call"]["value"], "1 hours")
        self.assertIn("with Dad", calls["Longest call"]["detail"])
        h = glance.glance(db, ["health"])
        self.assertEqual(h["total"], 2, "raw samples aren't something you did")
        hf = {f["label"]: f for f in h["facts"]}
        self.assertEqual(hf["Steps a day"]["value"], "7,000")
        self.assertEqual(hf["Most steps in a day"]["detail"], "Jan 5, 2025")
        self.assertNotIn("Busiest day", hf, "one a day: no busiest day")
        self.assertEqual(sum(h["hours"]), 0, "whole days have no hour")

    def test_nothing_there(self):
        self.assertEqual(glance.glance(library([]), ["imessage"]), {"total": 0})


if __name__ == "__main__":
    unittest.main()
