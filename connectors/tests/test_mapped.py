"""Mappings: exports in formats no parser knows, read with data that says which fields are what.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mapped_exports as mx


class Entry:
    def __init__(self, path, data):
        self.path, self.origin, self._data = path, path.split("/")[0], data.encode()

    def text(self):
        return self._data.decode()


class MappedTests(unittest.TestCase):
    def test_validate(self):
        m = mx.validate({"items": [{"file": "a.json", "kind": "bogus", "text": "body", "evil": "x", "title": 3}]})
        self.assertEqual(m["items"], [{"file": "a.json", "path": "", "describe": "a.json", "kind": "record", "text": ["body"]}])
        for bad in ({}, {"items": []}, {"items": [{"kind": "post"}]}, []):
            with self.assertRaises(ValueError):
                mx.validate(bad)

    def test_records(self):
        m = mx.validate({"items": [
            {"describe": "Posts", "file": "posts/*.json", "path": "data.items", "kind": "post", "time": "meta.when",
             "title": "title", "text": ["body", "tags"], "author": "by.name", "thread": "board", "id": "id"},
            {"describe": "Likes", "file": "likes.csv", "kind": "like", "time": "date", "text": ["what"], "author": "me"},
            {"describe": "Tweets", "file": "tweets.js", "kind": "post", "text": ["tweet.full_text"], "author": "me"}]})
        es = [Entry("svc/posts/1.json", json.dumps({"data": {"items": [
                  {"id": "p1", "title": "Hello", "body": "First post", "tags": ["a", "b"], "meta": {"when": "2021-05-01T00:00:00Z"}, "by": {"name": "ada"}, "board": "general"},
                  {"id": "p2", "body": "Reply", "by": {"name": "bob"}}]}})),
              Entry("svc/likes.csv", "date,what\n2022-01-01,a song\n"),
              Entry("svc/tweets.js", 'window.YTD.tweets.part0 = [{"tweet": {"full_text": "hi"}}]'),
              Entry("svc/settings.json", "{}")]
        out = list(mx.records(m, es, when=lambda v: v, is_me=lambda a: a == "ada"))
        recs = [r for _, _, r in out]
        self.assertEqual([r["kind"] for r in recs], ["post", "post", "like", "post"])
        p1 = recs[0]
        self.assertEqual((p1["id"], p1["title"], p1["text"], p1["ts"], p1["author"], p1["is_me"], p1["thread"]),
                         ("svc/posts/1.json#data.items#p1", "Hello", "First post\na, b", "2021-05-01T00:00:00Z", "ada", True, "general"))
        self.assertFalse(recs[1]["is_me"])
        self.assertEqual((recs[2]["author"], recs[2]["is_me"], recs[2]["text"]), ("me", True, "a song"))
        self.assertEqual(recs[3]["text"], "hi")
        self.assertEqual(recs[0]["meta"]["mapped"], "Posts")
        self.assertEqual(mx.folder_key("Amazon-Audible"), "amazon_audible")

    def test_utc_zone(self):
        m = mx.validate({"items": [{"file": "a.json", "path": "x", "time": "Date", "zone": "utc"}]})
        self.assertEqual(m["items"][0]["zone"], "UTC")
        [(_, _, r)] = mx.records(m, [Entry("svc/a.json", json.dumps({"x": [{"Date": "2022-12-24 18:20:21"}]}))], when=lambda v: v)
        self.assertEqual(r["ts"], "2022-12-24 18:20:21 UTC", "TikTok's zoneless times are UTC")
        self.assertEqual(mx.utc("2022-12-24T18:20:21+02:00"), "2022-12-24T18:20:21+02:00", "a time with a zone keeps it")

    def test_shipped_tiktok_mapping_is_valid(self):
        shipped = Path(__file__).resolve().parents[2] / "desktop/data/mappings/tiktok.json"
        m = mx.validate(json.loads(shipped.read_text()))
        self.assertTrue(all(r["zone"] == "UTC" and r["author"] == "me" for r in m["items"]))
        self.assertEqual({r["kind"] for r in m["items"]}, {"watch", "search", "like", "post", "follow"})


if __name__ == "__main__":
    unittest.main()
