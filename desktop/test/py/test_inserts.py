"""What an Ask answer shows in place (desktop/py/explore.py embed): a map, a day, a chart over time, a person, an
email, songs, a trip, a calendar, and what a company decided about you. Run as the app runs it (a subprocess with
CORPUS_DIR pointed at a made-up corpus, make_fixtures.inserts_corpus) in UTC."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[2]
REPO = DESKTOP.parent
EXPLORE = DESKTOP / "py" / "explore.py"
sys.path.insert(0, str(DESKTOP / "test" / "fixtures"))
import make_fixtures  # noqa: E402


class Inserts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.corpus = Path(make_fixtures.inserts_corpus(root / "corpus"))
        cls.env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
        cls.env.update(CORPUS_DIR=str(cls.corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"),
                       PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def embed(self, kind, spec=""):
        p = subprocess.run([sys.executable, str(EXPLORE), "embed", kind, spec], capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        return json.loads(p.stdout)

    def rowids(self, where):
        with closing(sqlite3.connect(self.corpus / "corpus.db")) as con:
            return [r for (r,) in con.execute(f"select rowid from records where {where} order by ts, rowid")]

    def test_a_map_of_records_or_of_days(self):
        tokyo = self.embed("map", "2025-03-20..2025-03-22")
        self.assertEqual(tokyo["kind"], "map")
        self.assertEqual([(p["place"], p["photos"], p["days"]) for p in tokyo["points"]], [("Shinjuku", 3, 3)], "three days in one spot")
        self.assertEqual((tokyo["countries"], tokyo["from"], tokyo["to"]), (["Japan"], "2025-03-20", "2025-03-22"))
        # The days around the trip: home, then Tokyo, then home; a friend's photo from a shared album isn't where you were.
        march = self.embed("map", "2025-03-01..2025-06-30")
        self.assertEqual(sorted(p["place"] for p in march["points"]), ["Princeton", "Shinjuku"])
        self.assertNotIn("Lisbon", json.dumps(march))
        picked = self.embed("map", ",".join(map(str, self.rowids("source = 'photos' and text like '%Princeton%'")[:1] + self.rowids("text like '%Shinjuku%'")[:1])))
        self.assertEqual(sorted(p["place"] for p in picked["points"]), ["Princeton", "Shinjuku"])
        self.assertIn("error", self.embed("map", str(self.rowids("source = 'gmail'")[0])), "an email has no place")
        self.assertIn("error", self.embed("map", "1999-01-01"))

    def test_a_day_as_your_stream_has_it(self):
        d = self.embed("day", "2025-03-12")
        kinds = {e["kind"] for e in d["events"]}
        self.assertTrue({"conversation", "call", "code", "note", "calendar", "health", "listen", "photos"} <= kinds, kinds)
        self.assertEqual([e["start"] for e in d["events"]], sorted(e["start"] for e in d["events"]), "in order")
        self.assertTrue(all(e["start"].startswith("2025-03-12") for e in d["events"]), "that day only")
        self.assertTrue(d["cover"] and all(c["thumb"].startswith("data:image/") for c in d["cover"]), "a few of its photos")
        self.assertIn("error", self.embed("day", "2025-02-30"))
        self.assertIn("error", self.embed("day", "1999-01-01"), "nothing that day")

    def test_a_chart_over_time(self):
        grace = self.embed("trend", "messages:Grace Hopper")
        self.assertEqual(grace["label"], "Messages with Grace Hopper")
        self.assertEqual(grace["months"], {"2024-01": 2, "2024-03": 4, "2025-03": 2, "2025-07": 2, "2026-03": 4}, "both apps, one person")
        self.assertEqual((grace["total"], grace["peak"]["month"]), (14, "2024-03"))
        self.assertEqual(self.embed("trend", "messages:grace")["months"], grace["months"], "by her first name: the one Grace you talk to")
        self.assertEqual(self.embed("trend", "messages:Grace Hopper:2025")["months"], {"2025-03": 2, "2025-07": 2}, "a year of it")
        self.assertEqual(self.embed("trend", "calls:Grace Hopper")["months"], {"2025-03": 1})
        self.assertEqual(self.embed("trend", "steps")["months"], {"2025-03": 6500}, "a day, on average")
        sleep = self.embed("trend", "sleep")
        self.assertEqual((sleep["months"], sleep["average"], sleep["total"]), ({"2025-03": 7.0}, True, None))
        self.assertEqual(self.embed("trend", "songs:the weavers")["label"], "Songs you played by The Weavers")
        self.assertEqual(self.embed("trend", "songs:the weavers")["total"], 5)
        self.assertEqual(self.embed("trend", "searches:tokyo")["total"], 1)
        self.assertEqual(self.embed("trend", "commits")["total"], 3, "yours, not someone else's")
        self.assertEqual(self.embed("trend", "texts")["what"], "messages")
        for bad in ("weather", "messages:Nobody Atall", "searches:zzzz"):
            self.assertIn("error", self.embed("trend", bad), bad)

    def test_a_person(self):
        p = self.embed("person", "Grace")
        self.assertEqual((p["name"], p["messages"], p["calls"], p["photos"]), ("Grace Hopper", 14, 1, 3))
        self.assertEqual(p["app_names"], {"imessage": "Messages", "instagram": "Instagram"})
        self.assertEqual(self.embed("person", "Grace H")["key"], p["key"], "by any of her names")
        self.assertIn("error", self.embed("person", "Ada Lovelace"), "you aren't one of your people")

    def test_an_email_without_the_reply_it_quotes(self):
        e = self.embed("email", str(self.rowids("source = 'gmail' and is_me = 0")[0]))
        self.assertEqual((e["subject"], e["from"], e["address"], e["to"]), ("Orbit numbers for Friday", "Katherine Johnson", "katherine@example.com", ["You"]))
        self.assertEqual(e["body"], "Hi Ada,\n\nThe numbers check out: launch at 9:40.\nThe sheet is attached.\n\nKatherine")
        self.assertEqual((e["attachments"], e["thread_count"]), (["orbit.xlsx"], 2))
        self.assertEqual(self.embed("email", str(self.rowids("source = 'gmail' and is_me = 1")[0]))["from"], "You")
        self.assertIn("error", self.embed("email", str(self.rowids("source = 'imessage'")[0])), "a message isn't an email")

    def test_songs_and_a_podcast(self):
        ids = self.rowids("source = 'podcasts'") + self.rowids("source = 'spotify' and title = 'Warp'")[:1] + self.rowids("title = 'Spindle'")
        s = self.embed("songs", ",".join(map(str, ids)))["songs"]
        self.assertEqual([(x["title"], x["artist"], x["app"], x["plays"], x["podcast"]) for x in s],
                         [("Episode 12: Gears", "Engine Hour", "Podcasts", 1, True), ("Warp", "The Weavers", "Spotify", 5, False),
                          ("Spindle", "The Looms", "Spotify", 1, False)])
        self.assertIn("error", self.embed("songs", str(self.rowids("source = 'photos'")[0])))

    def test_a_trip(self):
        t = self.embed("trip", "2025-03-21")
        self.assertEqual((t["trip"]["start"], t["trip"]["end"], t["trip"]["countries"]), ("2025-03-20", "2025-03-22", ["Japan"]))
        self.assertEqual([p["place"] for p in t["map"]["points"]], ["Shinjuku"])
        self.assertTrue(t["thumbs"] and t["trip"]["photo_ids"], "its photos, for the card and the trip's page")
        self.assertEqual(self.embed("trip", t["trip"]["id"])["trip"]["id"], t["trip"]["id"], "or by its id")
        self.assertIn("error", self.embed("trip", "2025-03-12"), "a day at home")

    def test_a_calendar(self):
        day = self.embed("agenda", "2025-03-12")
        self.assertEqual([(e["title"], e["start"][11:16], e["place"]) for e in day["events"]], [("Orbit review", "15:00", "Room 4"), ("Dinner with Grace", "19:30", None)])
        trip = self.embed("agenda", "2025-03-19..2025-03-23")["events"]
        self.assertEqual([(e["title"], e["all_day"], e["start"], e["end"]) for e in trip], [("Tokyo trip", True, "2025-03-19", "2025-03-22")],
                         "an all-day event ends on its last day, not the morning after")
        soon = (date.today() + timedelta(days=30)).isoformat()
        self.assertEqual([e["title"] for e in self.embed("agenda", f"{soon}..{soon}")["events"]], ["Dentist"], "plans to come are on a calendar too")
        ids = self.rowids("source = 'calendar' and title in ('Dentist', 'Orbit review')")
        self.assertEqual(sorted(e["title"] for e in self.embed("agenda", ",".join(map(str, ids)))["events"]), ["Dentist", "Orbit review"])
        self.assertIn("error", self.embed("agenda", str(self.rowids("source = 'gmail'")[0])), "an email isn't an event")
        long = self.embed("agenda", "2025-03-01..2025-12-31")
        self.assertEqual((long["to"], [e["title"] for e in long["events"]]), ("2025-03-14", ["Orbit review", "Dinner with Grace"]), "two weeks at most")

    def test_what_a_company_decided(self):
        meta = self.embed("they-know", "Meta")
        self.assertEqual(meta["services"], ["Facebook", "Instagram"], "Meta: both")
        self.assertEqual(sorted(i["value"] for g in meta["decided"] for i in g["items"]), ["Frequent travelers", "Rock climbing"])
        self.assertEqual((meta["advertisers"], meta["advertiser_names"]), (1, ["Acme Outdoor"]))
        self.assertEqual([i["value"] for g in self.embed("they-know", "instagram")["decided"] for i in g["items"]], ["Frequent travelers"])
        self.assertEqual(self.embed("they-know")["services"], ["Facebook", "Instagram"], "every service's")
        self.assertIn("error", self.embed("they-know", "TikTok"))

    def test_nothing_else(self):
        self.assertEqual(self.embed("weather", "today"), {"error": "can't show weather"})


if __name__ == "__main__":
    unittest.main()
