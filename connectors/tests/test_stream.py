"""The event stream (stream.py) over a small made-up corpus, indexed by build_index.py (which also writes the stream).
Times are written in UTC; the stream reads them in Los Angeles time (UMP_TZ), except photos, which keep their own.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


def rec(source, i, ts, kind="record", **f):
    return {"id": f"{source}-{i}", "source": source, "kind": kind, "ts": ts, **f}


RECORDS = [
    # One page seen by three sources, then another page and a search seen twice: one session of browsing.
    rec("browser_history", 1, "2026-09-10T16:00:00Z", "visit", url="https://example.com/a", title="Page A", is_me=True),
    rec("chrome_synced", 1, "2026-09-10T16:00:30Z", "visit", url="https://example.com/a", title="Page A", is_me=True),
    rec("google_activity", 1, "2026-09-10T16:01:00Z", "visit", url="https://www.example.com/a/", title="Page A", meta={"product": "example.com"}),
    rec("browser_history", 2, "2026-09-10T16:05:00Z", "visit", url="https://example.com/b", title="Page B", is_me=True),
    rec("browser_history", 3, "2026-09-10T16:06:00Z", "search", title="cats", url="https://www.google.com/search?q=cats", is_me=True),
    rec("google_activity", 2, "2026-09-10T16:06:40Z", "search", title="Searched for cats", meta={"product": "Search"}),
    # An hour later: a session of its own. And the iPhone's Safari, synced to the Mac: a session on the iPhone.
    rec("browser_history", 4, "2026-09-10T17:00:00Z", "visit", url="https://example.com/c", title="Page C", is_me=True),
    rec("browser_history", 5, "2026-09-10T16:02:00Z", "visit", url="https://m.example.org/x", title="On the phone", meta={"other_device": True}),
    # Texts with Grace: three within 45 minutes, a reaction, then one much later.
    rec("imessage", 1, "2026-09-10T18:00:00Z", "message", author="Grace Hopper", thread="c1", thread_name="Grace Hopper", text="Dinner on Friday?"),
    rec("imessage", 2, "2026-09-10T18:10:00Z", "message", author="me", is_me=True, thread="c1", thread_name="Grace Hopper", text="Yes, 7:30"),
    rec("imessage", 3, "2026-09-10T18:20:00Z", "message", author="Grace Hopper", thread="c1", thread_name="Grace Hopper", text="Great"),
    rec("imessage", 4, "2026-09-10T18:21:00Z", "reaction", author="me", is_me=True, thread="c1", thread_name="Grace Hopper", text="Loved “Great”"),
    rec("imessage", 5, "2026-09-10T20:00:00Z", "message", author="me", is_me=True, thread="c1", thread_name="Grace Hopper", text="See you there"),
    rec("imessage", 6, "2026-09-10T19:00:00Z", "message", author="Alan Turing", thread="g1", thread_name="Book Club", text="Next book?", meta={"group": 1}),
    # Calls: one you made, one you missed.
    rec("calls", 1, "2026-09-10T21:00:00Z", "call", thread_name="Grace Hopper", is_me=True, meta={"direction": "outgoing", "seconds": 120}),
    rec("calls", 2, "2026-09-10T21:30:00Z", "call", thread_name="Alan Turing", meta={"direction": "incoming", "seconds": 0}),
    # Mail: sent, personal, two newsletters (a Gmail category; "unsubscribe" in it) and spam.
    rec("gmail", 1, "2026-09-10T15:00:00Z", "email", author="me", is_me=True, title="Hi", meta={"labels": "Sent", "to": "grace@example.com"}),
    rec("gmail", 2, "2026-09-10T15:30:00Z", "email", author="Grace Hopper", title="Re: Hi", text="Hello!", meta={"labels": "Inbox", "from": "grace@example.com"}),
    rec("gmail", 3, "2026-09-10T15:10:00Z", "email", author="Shop", title="Sale", meta={"labels": "Inbox,Category Promotions", "from": "shop@example.com"}),
    rec("gmail", 4, "2026-09-10T15:20:00Z", "email", author="Weekly", title="This week", text="News... Unsubscribe here", meta={"labels": "Inbox", "from": "weekly@example.com"}),
    rec("gmail", 5, "2026-09-10T15:40:00Z", "email", author="Scam", title="Win", meta={"labels": "Spam", "tier": "spam"}),
    # One dinner in two calendars.
    rec("calendar", 1, "2026-09-11T02:00:00Z", "event", ts_end="2026-09-11T04:00:00Z", title="Dinner"),
    rec("google_calendar", 1, "2026-09-11T02:03:00Z", "event", ts_end="2026-09-11T04:00:00Z", title="dinner"),
    # Photos in Lisbon, in Lisbon's time.
    *[rec("photos", i, f"2026-09-10T22:{m}:00Z", "photo", title=f"IMG_{i}.HEIC", text="Place: Lisbon, Portugal\nPeople: Grace Hopper",
          meta={"timezone": "Europe/Lisbon", "type": "photo"}) for i, m in ((1, "00"), (2, "10"), (3, "20"))],
    # Screen Time: a run of Xcode long enough to count, a glance at Safari that doesn't.
    rec("app_usage", 1, "2026-09-10T17:00:00Z", "app_usage", ts_end="2026-09-10T17:01:00Z", title="Xcode", meta={"seconds": 60, "device": "Mac"}),
    rec("app_usage", 2, "2026-09-10T17:02:00Z", "app_usage", ts_end="2026-09-10T17:03:30Z", title="Xcode", meta={"seconds": 90, "device": "Mac"}),
    rec("app_usage", 3, "2026-09-10T17:30:00Z", "app_usage", ts_end="2026-09-10T17:30:30Z", title="Safari", meta={"seconds": 30, "device": "Mac"}),
    # Not events: a Health sample, the iPhone's file index, an ad.
    rec("health_samples", 1, "2026-09-10T12:00:00Z", "health_sample", meta={"steps": 10}),
    rec("phone_filesapp", 1, "2026-09-10T12:00:00Z", text="a file", meta={"tier": "device"}),
    rec("instagram_activity", 1, "2026-09-10T12:00:00Z", title="ad", meta={"file": "ads_viewed"}),
    # A day's totals, at local midnight.
    rec("health", 1, "2026-09-10T07:00:00Z", "health_day", is_me=True, meta={"steps": 1234, "distance_km": 1.5, "tz": "America/Los_Angeles"}),
    # The month's edges in Los Angeles: late on Sep 30 (Oct 1 in UTC) is September; late on Aug 31 is August.
    rec("imessage", 7, "2026-10-01T05:30:00Z", "message", author="Grace Hopper", thread="c1", thread_name="Grace Hopper", text="Last of September"),
    rec("imessage", 8, "2026-09-01T06:30:00Z", "message", author="Grace Hopper", thread="c1", thread_name="Grace Hopper", text="Last of August"),
    # A date far ahead (a bad date): no month for it.
    rec("calendar", 2, "2099-01-01T12:00:00Z", "event", title="Someday"),
]


class Stream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.corpus = Path(cls.tmp.name) / "corpus"
        (cls.corpus / "normalized").mkdir(parents=True)
        (cls.corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"]}))
        by = {}
        for r in RECORDS:
            by.setdefault(r["source"], []).append(r)
        for s, rows in by.items():
            (cls.corpus / "normalized" / f"{s}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        cls.env = {**os.environ, "CORPUS_DIR": str(cls.corpus), "UMP_TZ": "America/Los_Angeles"}
        cls.index()
        cls.events = cls.month("2026-09")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def index(cls):
        p = subprocess.run([sys.executable, str(CONNECTORS / "build_index.py")], env=cls.env, capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return p.stdout

    @classmethod
    def month(cls, m):
        p = subprocess.run([sys.executable, str(CONNECTORS / "stream.py"), "month", m], env=cls.env, capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        return [json.loads(x) for x in p.stdout.splitlines()]

    def of(self, kind):
        return [e for e in self.events if e["kind"] == kind]

    def test_in_order_with_local_times(self):
        from datetime import datetime
        instants = [datetime.fromisoformat(e["start"]) for e in self.events]
        self.assertEqual(instants, sorted(instants), "in the order things happened, whatever zone each is written in")
        lisbon = next(i for i, e in enumerate(self.events) if e["kind"] == "photos")
        self.assertLess(datetime.fromisoformat(self.events[lisbon - 1]["start"]), instants[lisbon])
        self.assertTrue(all("rowids" not in e for e in self.events), "the file refers to records by source and id")

    def test_one_page_from_three_sources_and_sessions_of_browsing(self):
        web = self.of("browsing")
        mac = [e for e in web if e["device"] == "Mac"]
        self.assertEqual(len(mac), 2, "a pause of an hour starts a new session")
        first = mac[0]
        self.assertEqual(first["title"], "Browsed 2 pages and searched once")
        self.assertEqual(first["count"], 3)
        self.assertEqual(sorted(first["refs"]), sorted(["browser_history:browser_history-1", "chrome_synced:chrome_synced-1",
                         "google_activity:google_activity-1", "browser_history:browser_history-2", "browser_history:browser_history-3",
                         "google_activity:google_activity-2"]), "every copy is kept, merged into one")
        self.assertIn("Searched “cats”", first["lines"])
        self.assertIn("example.com (2)", first["lines"])
        phone = [e for e in web if e["device"] == "iPhone"]
        self.assertEqual(len(phone), 1)
        self.assertEqual(phone[0]["title"], "Visited On the phone on your iPhone")

    def test_conversations(self):
        talks = [e for e in self.of("conversation") if e["people"] == ["Grace Hopper"]]
        self.assertEqual([e["title"] for e in talks],
                         ["Texted with Grace Hopper (3 messages)", "Texted Grace Hopper", "Grace Hopper texted you"])
        self.assertEqual(talks[0]["lines"], ["Grace: Dinner on Friday?", "You: Yes, 7:30", "Grace: Great"])
        self.assertEqual(talks[0]["count"], 4, "the reaction is part of it")
        self.assertTrue(talks[-1]["start"].startswith("2026-09-30T22:30"), "late on Sep 30 in Los Angeles is September")
        self.assertNotIn("Last of August", json.dumps(self.events))
        group = [e for e in self.of("conversation") if "Book Club" in e["title"]]
        self.assertEqual(group[0]["title"], "Alan Turing wrote in “Book Club”")
        self.assertEqual(group[0]["people"], ["Alan Turing"])

    def test_calls_and_mail(self):
        self.assertEqual([e["title"] for e in self.of("call")], ["Called Grace Hopper (2 min)", "Missed a call from Alan Turing"])
        self.assertEqual(sorted(e["title"] for e in self.of("email")), ["Email from Grace Hopper: “Re: Hi”", "Emailed grace@example.com: “Hi”"])
        digest = self.of("mail")
        self.assertEqual(len(digest), 1)
        self.assertEqual(digest[0]["title"], "2 newsletters and notifications in Gmail")
        self.assertTrue(digest[0]["all_day"])
        self.assertTrue(digest[0]["start"].startswith("2026-09-10T00:00:00"))
        self.assertNotIn("Win", json.dumps(self.events), "spam is left out")

    def test_one_dinner_in_two_calendars(self):
        cal = self.of("calendar")
        self.assertEqual(len(cal), 1)
        self.assertEqual(cal[0]["title"], "Dinner")
        self.assertEqual(len(cal[0]["refs"]), 2)
        self.assertTrue(cal[0]["start"].startswith("2026-09-10T19:00:00-07:00"))
        self.assertTrue(cal[0]["end"].startswith("2026-09-10T21:00:00"))

    def test_photos_in_their_own_time(self):
        ph = self.of("photos")
        self.assertEqual(len(ph), 1)
        self.assertEqual(ph[0]["title"], "Took 3 photos in Lisbon")
        self.assertEqual(ph[0]["people"], ["Grace Hopper"])
        self.assertTrue(ph[0]["start"].startswith("2026-09-10T23:00:00+01:00"))

    def test_apps_and_what_is_left_out(self):
        self.assertEqual([e["title"] for e in self.of("app")], ["Used Xcode for 2 min on your Mac"])
        sources = {r.split(":")[0] for e in self.events for r in e["refs"]}
        for gone in ("health_samples", "phone_filesapp", "instagram_activity"):
            self.assertNotIn(gone, sources)
        h = self.of("health")
        self.assertEqual(h[0]["title"], "You walked 1,234 steps, 1.5 km")
        self.assertTrue(h[0]["all_day"])
        self.assertTrue(h[0]["start"].startswith("2026-09-10T00:00:00-07:00"))

    def test_files_written_once_and_again_only_where_records_changed(self):
        out = self.corpus / "stream"
        self.assertEqual(sorted(p.name for p in out.glob("*.jsonl")), ["2026-08.jsonl", "2026-09.jsonl"], "no month for 2099")
        index = json.loads((out / "months.json").read_text())
        self.assertEqual(index["2026-09"]["events"], len(self.events))
        self.assertEqual([json.loads(x) for x in (out / "2026-09.jsonl").read_text().splitlines()], self.events)
        aug, sep = (out / "2026-08.jsonl").stat().st_mtime_ns, (out / "2026-09.jsonl").stat().st_mtime_ns
        self.assertIn("stream: 0 months written", self.index(), "nothing changed")
        time.sleep(0.01)
        f = self.corpus / "normalized" / "imessage.jsonl"
        f.write_text(f.read_text() + json.dumps(rec("imessage", 9, "2026-09-20T18:00:00Z", "message", author="Grace Hopper",
                                                    thread="c1", thread_name="Grace Hopper", text="One more")) + "\n")
        try:
            self.assertIn("stream: 1 month written", self.index())
            self.assertEqual((out / "2026-08.jsonl").stat().st_mtime_ns, aug)
            self.assertNotEqual((out / "2026-09.jsonl").stat().st_mtime_ns, sep)
            self.assertIn("One more", (out / "2026-09.jsonl").read_text())
        finally:
            f.write_text("".join(json.dumps(r) + "\n" for r in RECORDS if r["source"] == "imessage"))
            self.index()


if __name__ == "__main__":
    unittest.main()


class WhenDataIsMissingOrOdd(unittest.TestCase):
    """The stream never fails because an app's data is absent, partial or shaped oddly: every record still lands in a
    well-formed event or is left out on purpose, and a month with nothing in it is just empty."""

    def corpus(self, records, identity=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        c = Path(tmp.name) / "corpus"
        (c / "normalized").mkdir(parents=True)
        if identity:
            (c / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"]}))
        by = {}
        for r in records:
            by.setdefault(r["source"], []).append(r)
        for s, rows in by.items():
            (c / "normalized" / f"{s}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        env = {**os.environ, "CORPUS_DIR": str(c), "UMP_TZ": "America/Los_Angeles"}
        p = subprocess.run([sys.executable, str(CONNECTORS / "build_index.py")], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("stream: not updated", p.stdout, p.stdout)
        return c, env

    def month(self, env, m="2026-09"):
        p = subprocess.run([sys.executable, str(CONNECTORS / "stream.py"), "month", m], env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-3000:])
        return [json.loads(x) for x in p.stdout.splitlines()]

    def well_formed(self, events):
        from datetime import datetime
        for e in events:
            self.assertTrue(isinstance(e["title"], str) and e["title"].strip(), e)
            datetime.fromisoformat(e["start"])
            if e["end"]:
                self.assertGreater(datetime.fromisoformat(e["end"]), datetime.fromisoformat(e["start"]), e)
            self.assertTrue(e["refs"] and e["count"] >= 1, e)
            self.assertTrue(all(isinstance(x, str) for x in e["lines"] + e["people"]), e)
        instants = [datetime.fromisoformat(e["start"]) for e in events]
        self.assertEqual(instants, sorted(instants))

    def test_every_field_missing_or_odd(self):
        odd_meta = [None, [], "not json at all", {"seconds": "abc", "steps": "1,234", "distance_km": "far", "flights": None,
                    "asleep_min": "lots", "labels": 5, "from": None, "to": ["x"], "file": 7, "fields": "nope", "timezone": "Not/A_Zone",
                    "tz": 12, "type": 3, "group": "yes", "direction": None, "repo": None, "cwd": 5, "product": None, "tag": 1}]
        out = []
        for r in RECORDS:
            for f in ("author", "thread", "thread_name", "participants", "title", "text", "url", "ts_end", "is_me"):
                out.append({**r, f: None})
            for m in odd_meta:
                out.append({**r, "meta": m})
            if r["ts"] and r["ts"].startswith("2026-09"):
                out.append({**r, "ts": r["ts"][:10]})  # a date and no time
                out.append({**r, "ts": r["ts"].replace("Z", "")})  # no zone
                out.append({**r, "ts": r["ts"].replace("Z", "+05:45")})
                out.append({**r, "ts_end": "2026-09-01T00:00:00Z"})  # an end before its start
        out = [{**r, "id": f"{r['id']}-v{i}"} for i, r in enumerate(out)]
        c, env = self.corpus(out, identity=False)
        events = self.month(env)
        self.assertGreater(len(events), 20)
        self.well_formed(events)
        index = json.loads((c / "stream" / "months.json").read_text())
        self.assertEqual(index["2026-09"]["events"], len(events))

    def test_each_app_on_its_own(self):
        for source in sorted({r["source"] for r in RECORDS}):
            with self.subTest(source=source):
                _, env = self.corpus([r for r in RECORDS if r["source"] == source])
                events = self.month(env)
                self.well_formed(events)
                self.assertTrue(all(ref.startswith(f"{source}:") for e in events for ref in e["refs"]))

    def test_nothing_at_all(self):
        c, env = self.corpus([])
        self.assertEqual(self.month(env), [])
        self.assertEqual(json.loads((c / "stream" / "months.json").read_text()), {})
        r = subprocess.run([sys.executable, str(CONNECTORS.parent / "desktop" / "py" / "explore.py"), "stream"], env={**env, "UMP_EXPLORE_CACHE": str(c / "cache")},
                           capture_output=True, text=True, timeout=120)
        d = json.loads(r.stdout)
        self.assertEqual((d["events"], d["months"]), ([], []), "an empty month, not an error")

    def test_only_what_is_left_out(self):
        c, env = self.corpus([r for r in RECORDS if r["source"] in ("health_samples", "phone_filesapp", "instagram_activity")])
        self.assertEqual(self.month(env), [])
        self.assertFalse((c / "stream" / "2026-09.jsonl").exists(), "no file for a month with no events")

    def test_no_database_yet(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {**os.environ, "CORPUS_DIR": tmp.name, "UMP_EXPLORE_CACHE": tmp.name}
        r = subprocess.run([sys.executable, str(CONNECTORS.parent / "desktop" / "py" / "explore.py"), "stream", "2026-09"], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertIn("doesn't exist yet", json.loads(r.stdout)["error"])
