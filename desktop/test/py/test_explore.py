"""Tests for desktop/py/explore.py, the Explore page's artifacts, run as the app runs them (a subprocess with
CORPUS_DIR pointed at a made-up corpus, make_fixtures.explore_corpus) in UTC."""

import json
import re
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
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
        self.assertEqual({t["name"] for t in y["messages"]["threads"]}, {"Grace Hopper", "Dinner club", "lin"}, "by the names Your People uses")
        club = next(t for t in y["messages"]["threads"] if t["name"] == "Dinner club")
        self.assertEqual((club["group"], club["members"], club["key"]), (True, ["Alan Turing"], None), "a group, as a group")
        grace = next(t for t in y["messages"]["threads"] if t["name"] == "Grace Hopper")
        self.assertEqual((grace["group"], grace["key"], grace["apps"]), (False, "gracehopper", ["Messages"]))
        self.assertEqual(y["steps"], 9000, "a Health day is that date, never the day before")
        self.assertEqual([s["text"] for s in y["searches"]], ["tokyo ramen"])
        self.assertEqual((y["watch_count"], [w["title"] for w in y["watched"]]), (1, ["How engines work"]))
        self.assertEqual({m["kind"] for m in y["made"]}, {"code", "writing"})
        self.assertEqual([e["title"] for e in y["events"]], ["Dinner with Grace"])
        self.assertEqual(y["calls"][0]["name"], "Grace Hopper")
        self.assertNotIn("nearest", out, "a day with something on it")

    def test_on_this_day_one_person_across_apps(self):
        """Grace in Messages and on Instagram the same day is one face, opening the busier conversation."""
        y = next(y for y in self.run_explore("on-this-day", "01-02")["years"] if y["year"] == 2024)
        [grace] = y["messages"]["threads"]
        self.assertEqual((grace["name"], grace["messages"], grace["apps"]), ("Grace Hopper", 2, ["Instagram"]))

    def test_on_this_day_with_nothing_says_how_far_the_nearest_days_are(self):
        out = self.run_explore("on-this-day", "03-16")
        self.assertEqual(out["years"], [])
        self.assertEqual(out["nearest"], {"before": 2, "after": 3}, "March 14 (Grace, in 2024) and March 19 (a photo)")
    def test_places_and_trips(self):
        out = self.run_explore("places")
        self.assertEqual(out["countries"], {"United States": 13, "Japan": 3})
        [trip] = out["trips"]
        self.assertEqual((trip["start"], trip["end"], trip["days"], trip["photos"]), ("2025-03-20", "2025-03-22", 3, 3))
        self.assertEqual(len(trip["photo_ids"]), 3, "every photo of the trip, not a sample")
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
        self.assertEqual(out["kinds"]["searches"]["count"], self.run_explore("curiosity")["searches"], "the searches Curiosity counts")
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
        self.assertEqual(out["days"]["2025-05-01"]["posts"], 1, "a retweet isn't a post you made")
        day = next(y for y in self.run_explore("on-this-day", "05-01")["years"] if y["year"] == 2025)
        self.assertEqual([m["title"] for m in day["made"]], ["Shipped the engine"])

    def test_summary_and_thumbs(self):
        s = self.run_explore("summary")
        self.assertEqual(s["places"]["trips"], 1)
        self.assertEqual(s["people"]["top"][0], "Grace Hopper")
        people = self.run_explore("people")["people"]
        self.assertEqual([p["messages"] for p in people], sorted((p["messages"] for p in people), reverse=True), "most messages first")
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

    def test_the_page_explore_has_for_a_conversation(self):
        """A one-on-one opens its person's page in Your People, by the name Your People shows them under ("Grace H" in
        Messages is Grace Hopper's); a group chat its page in Group Chats; a server channel only your side is kept of,
        neither. Asked for again (earlier or later), it isn't worked out again."""
        day = next(d for d in self.run_explore("person", "gracehopper")["busiest_days"] if d["date"] == "2025-03-12")
        t = self.run_explore("thread", str(day["rowid"]))
        self.assertEqual(t["explore"], {"page": "person", "key": "graceh", "name": "Grace H"})
        merged = self.run_explore("person", "graceh")
        self.assertEqual((merged["key"], merged["name"]), ("gracehopper", "Grace Hopper"), "one person, by either name")
        self.assertEqual(merged["months"], self.run_explore("person", "gracehopper")["months"])
        for g in self.run_explore("groups")["groups"]:
            self.assertEqual(self.run_explore("thread", str(g["first"]["rowid"]))["explore"], {"page": "group", "key": g["key"], "name": g["name"]})
        earlier = self.run_explore("thread", str(day["rowid"]), "before", t["messages"][0]["at"])
        self.assertNotIn("explore", earlier)
        with closing(sqlite3.connect(self.corpus / "corpus.db")) as con:
            channel, dm = (con.execute("select rowid from records where thread = ? limit 1", (th,)).fetchone()[0] for th in ("chan1", "dm1"))
        self.assertIsNone(self.run_explore("thread", str(channel))["explore"], "not a group you can see the others in")
        # A handle alone, and no one in your Contacts by it: Discord's lin, kept as Your People keeps them.
        self.assertEqual(self.run_explore("thread", str(dm))["explore"], {"page": "person", "key": "discord:lin", "name": "lin"})
        self.assertIn("discord:lin", [p["key"] for p in self.run_explore("people")["people"]], "a page that's there")

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


class ExploreMedia(unittest.TestCase):
    """Listening, Moving and Sleep, Curiosity and Watching, on make_fixtures.media_corpus."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.corpus = Path(make_fixtures.media_corpus(root / "corpus"))
        cls.env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
        cls.env.update(CORPUS_DIR=str(cls.corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"),
                       PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    run_explore = Explore.run_explore

    def test_listening(self):
        out = self.run_explore("listening")
        # 30 + 40 + 5 on Spotify (the 12-second skip isn't a play), 3 from the Mac's Spotify, 2 from YouTube's artist channel;
        # Netflix playing on the Mac is watching.
        self.assertEqual(out["plays"], 80)
        self.assertEqual(out["from"], {"Spotify": 78, "YouTube": 2})
        self.assertEqual([a["name"] for a in out["top_artists"]], ["The Looms", "The Weavers", "Ada's Band"])
        self.assertEqual(out["top_artists"][1]["plays"], 32, "two plays on YouTube's Topic channel count for The Weavers")
        self.assertEqual([(e["artist"], e["start"]) for e in out["eras"]], [("The Weavers", "2025-Q1"), ("The Looms", "2025-Q3")])
        self.assertEqual(out["on_repeat"][0]["title"], "Spindle")
        self.assertEqual(out["on_repeat"][0]["date"], "2025-07-04")
        self.assertEqual(out["years"]["2025"]["new_artists"], 3)

    def test_watching(self):
        out = self.run_explore("watching")
        # 11 on YouTube (the artist channel's songs are in Listening), 2 Netflix episodes, and Netflix the Mac was playing.
        self.assertEqual(out["videos"], 14)
        self.assertEqual(out["from"], {"YouTube": 11, "Netflix": 3})
        self.assertEqual(out["top_channels"][0]["name"], "Engine Lab")
        self.assertIn("Our Planet", [c["name"] for c in out["top_channels"]], "episodes are their show")
        self.assertEqual([(r["title"], r["count"]) for r in out["rewatched"]], [("How engines work 0", 2)])
        self.assertEqual((out["binges"][0]["date"], out["binges"][0]["count"]), ("2025-10-10", 5))

    def test_curiosity(self):
        out = self.run_explore("curiosity")
        # 6 + 6 + 8, with Safari's "tokyo ramen" a minute after Google's counted once and the Gmail search left out.
        self.assertEqual(out["searches"], 20)
        self.assertEqual(out["top"][0], {**out["top"][0], "q": "weather", "count": 8})
        self.assertEqual([t["word"] for t in out["years"]["2024"]["topics"]][:1], ["sourdough starter"])
        self.assertNotIn("sourdough", [t["word"] for t in out["years"]["2024"]["topics"]], "not the word again once its phrase is in")
        self.assertEqual([t["word"] for t in out["years"]["2025"]["topics"]][:1], ["tokyo"])
        self.assertEqual([q["q"] for q in out["years"]["2024"]["questions"]], ["how to make sourdough starter", "why is my sourdough starter flat"])
        trip = out["before_trips"][0]
        self.assertEqual((trip["places"], trip["count"]), (["Shinjuku"], 6), "six different searches for Tokyo, which the trip's photos name; not the one in Gmail")
        self.assertIn("is the tokyo jr pass worth it", [q["q"] for q in trip["searches"]])

    def test_movement(self):
        out = self.run_explore("movement")
        self.assertEqual(out["days"], 20)
        self.assertEqual(out["best"]["date"], "2025-03-22")
        self.assertEqual((out["goal_days"], out["streak"]["days"], out["streak"]["start"]), (3, 3, "2025-03-20"))
        self.assertEqual(out["trips"]["days"], 3, "the three days in Tokyo were a trip")
        self.assertGreater(out["trips"]["avg"], 2 * out["trips"]["home_avg"])
        s = out["sleep"]
        self.assertEqual(s["nights"], 15, "a nap isn't a night")
        self.assertEqual(s["years"]["2025"]["bedtime"], 23.5)
        self.assertEqual(max(s["weekday"]), 470, "the late nights are longer")

    def test_your_year_counts_what_the_pages_count(self):
        """Your Year's numbers are the other pages' numbers for that year: songs past a skip, every video service but
        not the artist channels' songs, each search once; and Your Rhythms counts videos as Watching does."""
        out = self.run_explore("year", "2025")
        listening, watching, curiosity = (self.run_explore(op) for op in ("listening", "watching", "curiosity"))
        self.assertEqual(out["counts"]["songs played"], listening["years"]["2025"]["plays"])
        self.assertEqual(out["counts"]["songs played"], 80)
        self.assertEqual(out["counts"]["videos watched"], watching["years"]["2025"]["count"])
        self.assertEqual(out["counts"]["videos watched"], 14)
        self.assertEqual(out["counts"]["searches"], curiosity["years"]["2025"]["count"])
        rh = self.run_explore("rhythms")["kinds"]["watching"]
        self.assertEqual((rh["label"], rh["count"]), ("Videos you watched", watching["videos"]))

    def test_a_years_panels_have_that_years_numbers(self):
        """What a year picker shows below it, for each page: by hour, songs on repeat, long nights, watched again,
        searched again, every question once, biggest days and streaks."""
        ls = self.run_explore("listening")["years"]["2025"]
        self.assertEqual(sum(ls["by_hour"]), 80)
        self.assertEqual(ls["on_repeat"][0]["title"], "Spindle")
        w = self.run_explore("watching")
        self.assertEqual(sum(w["years"]["2025"]["by_hour"]), 14)
        self.assertEqual(w["years"]["2025"]["binges"][0]["date"], "2025-10-10")
        self.assertEqual([r["title"] for r in w["years"]["2025"]["rewatched"]], ["How engines work 0"])
        c = self.run_explore("curiosity")
        self.assertEqual(sum(len(v["questions"]) for v in c["years"].values()), c["questions"], "each question once, in the year first asked")
        self.assertEqual(c["years"]["2025"]["top"][0]["q"], "weather")
        self.assertEqual(sum(c["years"]["2024"]["by_hour"]), c["years"]["2024"]["count"])
        mv = self.run_explore("movement")["years"]["2025"]
        self.assertEqual((mv["goal_days"], mv["streak"]["days"], mv["top_days"][0]["date"]), (3, 3, "2025-03-22"))
        self.assertEqual(self.run_explore("movement")["sleep"]["years"]["2025"]["longest"]["minutes"], 470)

    def test_an_artist_opens_their_latest_play(self):
        out = self.run_explore("listening")
        looms = next(a for a in out["top_artists"] if a["name"] == "The Looms")
        self.assertEqual(looms["last"][:10], "2025-07-30")
        latest = self.run_explore("records", str(looms["rowid"]))[0]
        self.assertEqual(latest["ts"][:10], "2025-07-30", "the latest play, not the first")


class ExploreNotEnough(unittest.TestCase):
    """A corpus with none of it: each artifact says so with zeros, and the app locks its tile."""

    def test_empty(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve()
            corpus = Path(make_fixtures.explore_corpus(root / "corpus"))
            env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
            env.update(CORPUS_DIR=str(corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"), PYTHONDONTWRITEBYTECODE="1")
            out = {}
            for op in ("listening", "movement", "curiosity", "watching"):
                p = subprocess.run([sys.executable, str(EXPLORE), op], capture_output=True, text=True, env=env, timeout=120)
                self.assertEqual(p.returncode, 0, p.stderr[-2000:])
                out[op] = json.loads(p.stdout)
            self.assertEqual((out["listening"]["plays"], out["listening"]["first"], out["listening"]["eras"]), (0, None, []))
            self.assertEqual(out["movement"]["days"], 2)
            self.assertIsNone(out["movement"]["sleep"])
            self.assertEqual(out["curiosity"]["searches"], 21)
            self.assertLess(out["watching"]["videos"], 30)


class TheyKnow(unittest.TestCase):
    """What They Know, on make_fixtures.ads_corpus."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        corpus = Path(make_fixtures.ads_corpus(root / "corpus"))
        env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
        env.update(CORPUS_DIR=str(corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"), PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, str(EXPLORE), "they-know"], capture_output=True, text=True, env=env, timeout=120)
        assert p.returncode == 0, p.stderr[-2000:]
        cls.out = json.loads(p.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_advertisers_once_each_with_every_service_and_route(self):
        o = self.out
        by = {a["name"]: a for a in o["advertiser_list"]}
        self.assertEqual(o["advertisers"], 2, "Acme on Facebook and Instagram, and @acmeoutdoor on X, are one company")
        self.assertEqual(by["Acme Outdoor"]["services"], {"Facebook": ["list", "activity"], "Instagram": ["list", "activity"], "X": ["lookalike"]})
        self.assertNotIn("@acmeoutdoor", by, "named by its name, not its handle")
        self.assertEqual((o["on_lists"], o["from_activity"]), (1, 2))
        self.assertTrue(by["Acme Outdoor"]["emailed"], "you have email from Acme Outdoor")
        self.assertFalse(by["Night Owl Games"]["emailed"])
        self.assertEqual(o["emailed"], 1)
        self.assertEqual(o["advertiser_list"][0]["name"], "Acme Outdoor", "on two services, by a list: first")

    def test_what_they_decided_grouped_by_what_it_is(self):
        groups = {(g["service"], g["what"]): g for g in self.out["decided"]}
        self.assertEqual(groups[("Facebook and Instagram", "category")]["group"], "guess")
        self.assertEqual(groups[("Facebook and Instagram", "category")]["services"], ["Facebook", "Instagram"], "the same list from both, said once")
        self.assertEqual(groups[("X", "gender")]["group"], "guess")
        self.assertEqual([i["value"] for i in groups[("Instagram", "interest")]["items"]], ["Rock climbing"], "an older import's interest, by its file")
        self.assertTrue(groups[("X", "interest")]["items"][0]["off"], "an interest you turned off says so")
        self.assertEqual(groups[("LinkedIn", "Member Skills")]["group"], "other")
        self.assertFalse(any(g["what"] == "ad_targeting.csv" for g in self.out["decided"]), "an older import's whole targeting file isn't one of them")
        self.assertEqual(self.out["decided_count"], 5)

    def test_who_told_on_you_and_the_ads(self):
        told = {t["name"]: t for t in self.out["told"]}
        self.assertEqual((told["Night Owl Games"]["events"], told["Night Owl Games"]["types"]), (2, {"PURCHASE": 1, "PAGE_VIEW": 1}))
        self.assertEqual(told["Night Owl Games"]["last"], "2026-01-03T00:00:00Z")
        self.assertEqual(told["Corner Bakery"]["events"], 2, "an older import's record, its events read from the text")
        self.assertEqual(self.out["told_months"], {"2026-01": 2})
        ads = self.out["ads"]
        self.assertEqual(ads["by_service"], {"Instagram": 2, "X": 1, "Google": 1})
        self.assertEqual(ads["top"][0], {"name": "Acme Outdoor", "count": 2, "rowid": ads["top"][0]["rowid"]})
        self.assertEqual(self.out["ads_count"], 4)
        svc = {s["service"]: s for s in self.out["services"]}
        self.assertEqual((svc["Facebook"]["advertisers"], svc["Facebook"]["told"], svc["X"]["advertisers"]), (2, 2, 1))


class ExploreCited(unittest.TestCase):
    """A conversation opened from what an Ask answer cites (make_fixtures.cited_corpus): each message as the app it's
    from shows it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.corpus = Path(make_fixtures.cited_corpus(root / "corpus"))
        cls.env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
        cls.env.update(CORPUS_DIR=str(cls.corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"),
                       PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    run_explore = Explore.run_explore

    def rowid(self, like):
        with closing(sqlite3.connect(self.corpus / "corpus.db")) as con:
            return con.execute("select rowid from records where text like ?", (like,)).fetchone()[0]

    def test_a_message_as_its_app_shows_it(self):
        """A picture on this Mac is drawn; a file is named (not left as an empty bubble); an edit says so, with what it
        said before; a tapback is a line of its own; and the whole day is there, with the days before and after."""
        t = self.run_explore("thread", str(self.rowid("Are we still%")))
        self.assertEqual((t["name"], t["app"], t["group"]), ("Grace Hopper", "Messages", False))
        self.assertEqual(t["explore"], {"page": "person", "key": "gracehopper", "name": "Grace Hopper"})
        by = {m["text"]: m for m in t["messages"]}
        self.assertTrue(by["Did you see the eclipse?"] and by["That was so much fun"], "the days either side")
        picture = next(m for m in t["messages"] if m["image"])
        self.assertEqual((picture["text"], picture["attachments"]), ("", []), "drawn, not named too")
        menu = next(m for m in t["messages"] if m["attachments"])
        self.assertEqual((menu["text"], menu["attachments"], menu["me"]), ("", ["Tasca menu.pdf"], True))
        wine = by["Should I bring the wine?"]
        self.assertEqual((wine["edited"], wine["before"]), (True, ["Should I bring wine"]))
        self.assertFalse(by["Yes! 7:30, I booked a table."]["edited"])
        self.assertEqual(by["Loved “Yes! 7:30, I booked a table.”"]["kind"], "reaction")
        self.assertIsNone(t["messages"][0]["ts"], "the one whose time was lost: no made-up time")

    def test_reactions_kept_on_a_message_and_a_group(self):
        t = self.run_explore("thread", str(self.rowid("Chapter 7%")))
        self.assertEqual((t["name"], t["app"], t["group"]), ("Book club", "Instagram", True))
        [m] = [m for m in t["messages"] if m["reactions"]]
        self.assertEqual(m["reactions"], [{"who": "Dorothy Vaughan", "reaction": "❤"}, {"who": "You", "reaction": "😂"}], "yours, as you")
        [g] = self.run_explore("groups")["groups"]
        self.assertEqual(t["explore"], {"page": "group", "key": g["key"], "name": "Book club"})

    def test_earlier_and_later(self):
        t = self.run_explore("thread", str(self.rowid("That was so much fun")))
        self.assertTrue(t["more_before"])
        self.assertFalse(t["more_after"])
        earlier = self.run_explore("thread", str(self.rowid("That was so much fun")), "before", t["messages"][0]["at"])
        self.assertEqual([m["text"] for m in earlier["messages"]], ["an old message whose time was lost", "Can you send me the slides?", "Sure, give me a minute"])
        self.assertFalse(earlier["more_before"])

    def test_not_a_message(self):
        with closing(sqlite3.connect(self.corpus / "corpus.db")) as con:
            for (rowid,) in con.execute("select rowid from records where source in ('calendar', 'apple_notes')"):
                self.assertIn("error", self.run_explore("thread", str(rowid)))


class ExploreEdges(unittest.TestCase):
    """Explore on make_fixtures.edge_corpus("messy"), in Los Angeles time: 37 years with records whose times are
    missing or can't be right, offsets and clock changes, odd text and names. Nothing crashes, and no time that can't
    be right is a day, a year, a first or a trip."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.corpus = Path(make_fixtures.edge_corpus(root / "corpus", "messy"))
        cls.env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
        cls.env.update(CORPUS_DIR=str(cls.corpus), UMP_REPO=str(REPO), UMP_TZ="America/Los_Angeles", UMP_EXPLORE_CACHE=str(root / "cache"),
                       PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    run_explore = Explore.run_explore
    WRONG = ("1970", "1601", "2099", "9999", "never")  # the bad times' years, and the project only they are in

    def test_no_time_that_cant_be_right_shows(self):
        for op in ("people", "places", "rhythms", "firsts", "made", "groups", "journeys", "listening", "movement", "curiosity", "watching", "year", "summary"):
            out = json.dumps(self.run_explore(op))
            for w in self.WRONG:
                self.assertNotIn(f'"{w}', out, f"{op} has nothing from {w}")
        self.assertEqual(self.run_explore("year")["years"], [str(y) for y in range(2026, 1989, -1)], "every year from 1990, no other")
        firsts = self.run_explore("firsts")["items"]
        self.assertEqual(firsts[0]["ts"][:4], "1990")
        self.assertNotIn("never", [i["what"] for i in firsts], "a project whose every commit has a bad time has no first")
        months = [m["month"] for m in self.run_explore("stream")["months"]]
        self.assertTrue(all(re.fullmatch(r"(199\d|20[0-2]\d)-(0[1-9]|1[0-2])", m) for m in months), "only months that exist")
        self.assertEqual(self.run_explore("movement")["first"], "1990-01-15")

    def test_people_and_you(self):
        names = [p["name"] for p in self.run_explore("people")["people"]]
        self.assertEqual(names[0], "Grace Hopper", "one name in two apps is one person")
        self.assertNotIn("me", names, '"me" is how some exports write you')
        self.assertNotIn("Ada Lovelace", names, "you aren't one of your people")
        grace = self.run_explore("people")["people"][0]
        self.assertEqual(set(grace["apps"]), {"imessage", "instagram"})

    def test_a_local_day_with_offsets_and_clock_changes(self):
        """On This Day is the day here: times written with an offset land on their own day, and a day the clocks
        change on is 23 or 25 hours long."""
        day = lambda md: next((y for y in self.run_explore("on-this-day", md)["years"] if y["year"] == 2025), None)  # noqa: E731
        self.assertEqual(day("06-01")["messages"]["count"], 2, "23:30 at -07:00 and 00:30 the next day at +09:00, both 1 June here")
        self.assertEqual(day("03-09")["messages"]["count"], 2, "1:59 am before the clocks went forward, 3:30 am after")
        self.assertEqual(day("11-02")["messages"]["count"], 2, "1:30 am, and 11:30 pm: the 25th hour of the day")
        self.assertIsNone(day("11-03"))

    def test_odd_arguments_say_so(self):
        for args in (("on-this-day", "13-40"), ("on-this-day", "xx"), ("year", "1899"), ("year", "9999"), ("thread", "abc"), ("person",)):
            self.assertIn("error", self.run_explore(*args), args)
        self.assertEqual(self.run_explore("stream", "2025-13")["month"], self.run_explore("stream")["month"], "a month that doesn't exist: the latest")
        self.assertEqual(sorted(r["rowid"] for r in self.run_explore("records", "1,2,abc,999999999")), [1, 2], "the ones there are")

    def test_a_conversation_with_messages_at_bad_times(self):
        grace = self.run_explore("people")["people"][0]
        t = self.run_explore("thread", str(grace["first"]["rowid"]))
        self.assertTrue(t["messages"])
        rowid = int(subprocess.run([sys.executable, "-c", "import sqlite3, sys; print(sqlite3.connect(sys.argv[1]).execute(\"select rowid from records "
                                    "where ts is null and kind = 'message' limit 1\").fetchone()[0])", str(self.corpus / "corpus.db")],
                                   capture_output=True, text=True).stdout)
        t = self.run_explore("thread", str(rowid))
        self.assertIn(rowid, [m["rowid"] for m in t["messages"]], "one with no time opens too")
        self.assertIsNone(next(m for m in t["messages"] if m["rowid"] == rowid)["ts"], "with no time, not a made-up one")


class ExploreBigAndBlank(unittest.TestCase):
    """An index with nothing in it, and one with everything on one day: every artifact answers."""

    def test_every_artifact_answers(self):
        for case in ("empty", "one-day"):
            with tempfile.TemporaryDirectory() as t:
                root = Path(t).resolve()
                corpus = Path(make_fixtures.edge_corpus(root / "corpus", case))
                env = {k: v for k, v in os.environ.items() if k != "CORPUS_DIR"}
                env.update(CORPUS_DIR=str(corpus), UMP_REPO=str(REPO), UMP_TZ="UTC", UMP_EXPLORE_CACHE=str(root / "cache"), PYTHONDONTWRITEBYTECODE="1")
                for op in ("summary", "on-this-day", "people", "places", "rhythms", "firsts", "made", "groups", "journeys", "year", "stream",
                           "listening", "movement", "curiosity", "watching", "they-know"):
                    p = subprocess.run([sys.executable, str(EXPLORE), op], capture_output=True, text=True, env=env, timeout=120)
                    self.assertEqual(p.returncode, 0, p.stderr[-2000:])
                    self.assertNotIn("error", json.loads(p.stdout), (case, op))
                if case == "one-day":
                    self.assertEqual(json.loads(subprocess.run([sys.executable, str(EXPLORE), "year"], capture_output=True, text=True, env=env).stdout)["years"], ["2025"])
