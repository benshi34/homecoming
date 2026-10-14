"""Tests for desktop/py/explore.py, the Explore page's artifacts, run as the app runs them (a subprocess with
CORPUS_DIR pointed at a made-up corpus, make_fixtures.explore_corpus) in UTC."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[2]
REPO = DESKTOP.parent
EXPLORE = DESKTOP / "py" / "explore.py"
sys.path.insert(0, str(DESKTOP / "test" / "fixtures"))
import make_fixtures  # noqa: E402


class Explore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.corpus = Path(make_fixtures.explore_corpus(root / "corpus"))
        cls.env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
        cls.env.update(CORPUS_DIR=str(cls.corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"),
                       PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_explore(self, *args):
        p = subprocess.run([sys.executable, str(EXPLORE), *args], capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        return json.loads(p.stdout)

    def test_people_across_apps_and_names(self):
        out = self.run_explore("people")
        by = {p["name"]: p for p in out["people"]}
        self.assertNotIn("Ada Lovelace", by, "you aren't one of your people")
        self.assertNotIn("Dinner club", by, "group chats aren't one person")
        self.assertNotIn("Grace H", by, "Grace H in Messages and Grace Hopper on Instagram are one person")
        g = by["Grace Hopper"]
        self.assertEqual((g["messages"], g["sent"], g["calls"], g["call_minutes"]), (14, 7, 1, 10))
        self.assertEqual(g["apps"], {"imessage": 12, "instagram": 2})
        self.assertEqual(g["photos"], 3, 'photos naming "Grace" are hers: she is the only Grace you talk to')
        self.assertEqual(g["first"]["ts"][:10], "2024-01-02")
        self.assertEqual((g["starts_them"], g["starts_me"]), (6, 1), "she breaks the silence in Messages; you did on Instagram")
        self.assertEqual(by["lin"]["starts_me"] + by["lin"]["starts_them"], 0, "Discord keeps only your side: no one 'starts'")
        self.assertEqual([c["name"] for c in out["circle"]["2025"]][:1], ["Grace Hopper"])

    def test_one_person(self):
        out = self.run_explore("person", "gracehopper")
        self.assertEqual(out["name"], "Grace Hopper")
        self.assertEqual(out["months"]["2024-03"], {"imessage": 4})
        self.assertEqual(out["months"]["2024-01"], {"instagram": 2})
        self.assertEqual((out["call_count"], out["photo_count"]), (1, 3))
        self.assertEqual(out["hours"][17], 12)

    def test_on_this_day(self):
        out = self.run_explore("on-this-day", "03-12")
        self.assertEqual(out["label"], "March 12")
        years = {y["year"]: y for y in out["years"]}
        self.assertEqual(sorted(years), [2024, 2025, 2026])
        y = years[2025]
        self.assertEqual(y["photos"]["count"], 3)
        self.assertEqual(y["photos"]["places"], ["Princeton"])
        self.assertEqual(y["messages"]["count"], 4, "Grace, the group chat, and your side of a Discord DM")
        self.assertEqual({t["name"] for t in y["messages"]["threads"]}, {"Grace H", "Dinner club", "lin"})
        self.assertEqual(y["steps"], 9000, "a Health day is that date, never the day before")
        self.assertEqual([s["text"] for s in y["searches"]], ["tokyo ramen"])
        self.assertEqual((y["watch_count"], [w["title"] for w in y["watched"]]), (1, ["How engines work"]))
        self.assertEqual({m["kind"] for m in y["made"]}, {"code", "writing"})
        self.assertEqual([e["title"] for e in y["events"]], ["Dinner with Grace"])
        self.assertEqual(y["calls"][0]["name"], "Grace H")

    def test_places_and_trips(self):
        out = self.run_explore("places")
        self.assertEqual(out["countries"], {"United States": 13, "Japan": 3})
        [trip] = out["trips"]
        self.assertEqual((trip["start"], trip["end"], trip["days"], trip["photos"]), ("2025-03-20", "2025-03-22", 3, 3))
        self.assertEqual((trip["places"], trip["countries"]), (["Shinjuku"], ["Japan"]))
        self.assertGreater(trip["farthest_km"], 10000)
        self.assertEqual(len(out["points"]), 2, "home and Tokyo")

    def test_rhythms(self):
        out = self.run_explore("rhythms")
        m = out["kinds"]["messages"]
        self.assertEqual(m["peak_hour"], 17)
        self.assertEqual(m["count"], 42, "messages you sent, in every app, groups too")
        self.assertEqual(sum(map(sum, m["grid"])), 42)
        self.assertEqual(out["kinds"]["coding"]["count"], 3, "only your own commits")
        self.assertEqual(out["steps"]["weekday"][2], 9000, "12 March 2025 was a Wednesday")

    def test_firsts(self):
        out = self.run_explore("firsts")
        kinds = {(i["kind"], i["what"]) for i in out["items"]}
        self.assertTrue({("country", "United States"), ("country", "Japan"), ("project", "engine"), ("place", "Princeton")} <= kinds)
        self.assertIn(("place", "Shinjuku"), kinds, "a place counts once you've been there on three days")
        self.assertEqual([i["ts"][:10] for i in out["items"]], sorted(i["ts"][:10] for i in out["items"]))

    def test_made(self):
        out = self.run_explore("made")
        self.assertEqual(out["streak"], {"days": 3, "start": "2025-03-10", "end": "2025-03-12"})
        self.assertEqual(out["totals"]["2025"]["code"], 3)
        self.assertEqual(out["days"]["2025-03-12"]["writing"], 1)

    def test_summary_and_thumbs(self):
        s = self.run_explore("summary")
        self.assertEqual(s["places"]["trips"], 1)
        self.assertEqual(s["people"]["top"][0], "Grace Hopper")
        rowid = s["on_this_day"]["cover"] or self.run_explore("places")["points"][0]["rowid"]
        t = self.run_explore("thumbs", str(rowid))
        self.assertTrue(t[str(rowid)].startswith("data:image/jpeg;base64,"))

    def test_a_conversation_around_a_message(self):
        """Both sides of the day's exchange, a little either side, and earlier or later on request."""
        mid = self.run_explore("person", "gracehopper")["busiest_days"]
        day = next(d for d in mid if d["date"] == "2025-03-12")
        t = self.run_explore("thread", str(day["rowid"]))
        self.assertEqual((t["name"], t["app"], t["group"]), ("Grace H", "Messages", False))
        texts = [(m["me"], m["text"]) for m in t["messages"]]
        self.assertIn((False, "hey! day 2"), texts)
        self.assertIn((True, "hi Grace"), texts)
        self.assertEqual([m["ts"][:10] for m in t["messages"]], sorted(m["ts"][:10] for m in t["messages"]), "oldest first")
        self.assertIn("2024-03-14", {m["ts"][:10] for m in t["messages"]}, "the messages just before that day, for context")
        self.assertNotIn("Dinner club", json.dumps(t), "only this conversation")
        first = t["messages"][0]
        earlier = self.run_explore("thread", str(day["rowid"]), "before", first["at"])
        self.assertTrue(all(m["at"] < first["at"] for m in earlier["messages"]))
        self.assertIn("error", self.run_explore("thread", str(self.run_explore("places")["points"][0]["rowid"])), "a photo isn't a conversation")

    def test_what_an_answer_shows(self):
        """A few messages around one, an exchange from one message to another, and photos with where and when."""
        day = next(d for d in self.run_explore("person", "gracehopper")["busiest_days"] if d["date"] == "2025-03-12")
        t = self.run_explore("thread", str(day["rowid"]))
        at = next(i for i, m in enumerate(t["messages"]) if m["rowid"] == day["rowid"])
        one = self.run_explore("embed", "chat", str(day["rowid"]))
        self.assertEqual((one["kind"], one["name"], one["app"], one["group"]), ("chat", "Grace H", "Messages", False))
        self.assertEqual([m["rowid"] for m in one["messages"]], [m["rowid"] for m in t["messages"][max(0, at - 2):at + 4]],
                         "two before it and three after, in order")
        a, b = t["messages"][1]["rowid"], t["messages"][4]["rowid"]
        span = self.run_explore("embed", "chat", f"{b}-{a}")
        self.assertEqual([m["rowid"] for m in span["messages"]], [m["rowid"] for m in t["messages"][1:5]], "either way round")
        self.assertIn("error", self.run_explore("embed", "chat", "999999"))
        photo = self.run_explore("places")["points"][0]["rowid"]
        self.assertIn("error", self.run_explore("embed", "chat", str(photo)), "a photo isn't a conversation")
        convo = self.run_explore("groups")["groups"][0]["first"]["rowid"]
        self.assertIn("different conversations", self.run_explore("embed", "chat", f"{day['rowid']}-{convo}")["error"])
        ph = self.run_explore("embed", "photos", f"{photo},{day['rowid']},{photo}")
        self.assertEqual([p["rowid"] for p in ph["photos"]], [photo], "only photos, once each")
        self.assertTrue(ph["photos"][0]["thumb"].startswith("data:image/jpeg;base64,"))
        self.assertIn("error", self.run_explore("embed", "photos", str(day["rowid"])))

    def test_progress_while_building(self):
        """An artifact being built says its steps and how far it has got, on stderr, for the loading screen."""
        env = {**self.env, "UMP_EXPLORE_CACHE": str(Path(self.tmp.name) / "fresh-cache")}
        p = subprocess.run([sys.executable, str(EXPLORE), "firsts"], capture_output=True, text=True, env=env, timeout=120)
        lines = [json.loads(line[10:]) for line in p.stderr.splitlines() if line.startswith("@progress ")]
        self.assertEqual(lines[0], {"steps": ["Your people", "Places and countries", "Projects and apps"]})
        self.assertTrue(any(x.get("detail") == "Reading your messages" for x in lines), "people, built inside, reports as a detail")
        self.assertEqual(max(x.get("at", -1) for x in lines), 2)
        self.assertNotIn("steps", json.dumps(lines[1:]), "one list of steps, even with people built inside")

    def test_group_chats_from_any_app(self):
        """Groups come from how a conversation looks, not which app it's in: one Messages marks as a group, and one in an
        app this code has never heard of with two others in it. A channel an export keeps only your side of isn't one."""
        out = self.run_explore("groups")
        by = {g["name"]: g for g in out["groups"]}
        self.assertEqual(set(by), {"Dinner club", "Katherine, Dorothy"}, "named by its members when nobody named it; not #general, not Airbnb")
        self.assertEqual(by["Katherine, Dorothy"]["app"], "Signal")
        self.assertFalse(by["Katherine, Dorothy"]["named"])
        club = by["Dinner club"]
        self.assertEqual([w["word"] for w in club["words"]], ["croissant"], "its own word; not the lines the app wrote itself")
        self.assertEqual(club["emoji"], [{"emoji": "🥐", "count": 8}])
        self.assertEqual({m["name"] for m in club["members"]}, {"Alan Turing", "Grace H", "You"})
        self.assertEqual(club["mine"], 8)
        sig = by["Katherine, Dorothy"]
        self.assertEqual(sig["messages"], 35, "the three whose writer wasn't kept count toward the chat")
        self.assertEqual({m["name"] for m in sig["members"]}, {"Katherine Johnson", "Dorothy Vaughan"}, "but aren't a person in it")
        sup = {x["title"]: x["name"] for x in by["Katherine, Dorothy"]["superlatives"]}
        self.assertEqual(sup["Night owl"], "Dorothy Vaughan")
        # A group's conversation opens like any other, from any app.
        convo = self.run_explore("thread", str(by["Katherine, Dorothy"]["first"]["rowid"]))
        self.assertEqual((convo["app"], convo["group"]), ("Signal", True))

    def test_journeys_and_flights(self):
        """Moves between places you were, from where photos were taken; flights where nothing on the ground is that
        fast. A picture saved from Messages, and one nothing could have reached in time, aren't where you were."""
        out = self.run_explore("journeys")
        legs = [(leg["from"]["place"], leg["to"]["place"], leg["flew"]) for leg in out["legs"]]
        self.assertEqual(legs, [("Shinjuku", "Princeton", True), ("Princeton", "Shinjuku", True)], "newest first; no Sydney")
        self.assertEqual(out["flights"], 2)
        self.assertTrue(21000 < out["km"] < 22500, out["km"])
        self.assertEqual([c["country"] for c in out["countries"]], ["United States", "Japan"])
        self.assertNotIn("Australia", json.dumps(self.run_explore("places")), "places and trips leave them out too")
        self.assertNotIn("Australia", json.dumps(self.run_explore("firsts")))

    def test_your_year(self):
        """A year as a story, from the other artifacts and that year's records."""
        out = self.run_explore("year", "2025")
        self.assertEqual(out["years"], ["2025", "2024"], "years with twenty or more things you did")
        self.assertEqual((out["people"]["count"], out["people"]["new"]), (2, 1), "Grace and lin; lin was new")
        self.assertEqual(out["trip_count"], 1)
        self.assertEqual((out["travel"]["flights"], out["travel"]["countries"]), (2, ["Japan", "United States"]))
        self.assertEqual(out["steps"]["total"], 13000)
        self.assertEqual(out["steps"]["best"], {"date": "2025-03-12", "steps": 9000})
        self.assertEqual(out["made"]["streak"]["days"], 3)
        self.assertEqual(out["busiest"]["date"], "2025-03-12")
        self.assertEqual(self.run_explore("year")["year"], "2025", "the latest year with data, by default")

    def test_no_corpus(self):
        env = {**self.env, "CORPUS_DIR": str(Path(self.tmp.name) / "nowhere")}
        p = subprocess.run([sys.executable, str(EXPLORE), "summary"], capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("error", json.loads(p.stdout))


if __name__ == "__main__":
    unittest.main()
