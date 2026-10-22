"""Zotero: through zotero.org's API (a stand-in server on localhost) and from the Zotero app's zotero.sqlite. Everyone
and everything is made up.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONNECTORS = Path(__file__).resolve().parents[1]
KEY = "made-up-zotero-key"
ADA, GRACE = {"id": 1, "username": "ada_l"}, {"id": 2, "username": "grace_h"}


def item(key, data, by=ADA):
    return {"key": key, "meta": {"createdByUser": by}, "data": {"key": key, "dateAdded": "2025-03-01T10:00:00Z", **data}}


PAPER = {"itemType": "journalArticle", "title": "Tides and the moon", "date": "2024-06", "DOI": "10.1000/tides",
         "publicationTitle": "Journal of Tides", "abstractNote": "Why spring tides are higher.", "collections": ["C1"],
         "creators": [{"firstName": "Grace", "lastName": "Hopper", "creatorType": "author"}, {"name": "Tide Lab", "creatorType": "author"}],
         "tags": [{"tag": "oceans"}]}
LIBRARY = {  # a library path -> its items
    "/users/1": [item("P1", PAPER), item("PDF1", {"itemType": "attachment", "parentItem": "P1", "contentType": "application/pdf"}),
                 item("A1", {"itemType": "annotation", "parentItem": "PDF1", "annotationType": "highlight",
                             "annotationText": "the sun and the moon line up", "annotationComment": "key point", "annotationPageLabel": "3"}),
                 item("N1", {"itemType": "note", "parentItem": "P1", "note": "<h1>Tides</h1><p>Read this twice.</p>"})]
                + [item(f"W{i}", {"itemType": "webpage", "title": f"Page {i}", "url": f"https://example.com/{i}"}) for i in range(150)],
    "/groups/77": [item("G1", {"itemType": "book", "title": "Compilers", "date": "1986"}, by=GRACE),
                   item("G2", {"itemType": "book", "title": "Mine in the group"}, by=ADA)],
}


class FakeZotero(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, total=None, code=200):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        if total is not None:
            self.send_header("Total-Results", str(total))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("Zotero-API-Key") != KEY:
            return self.send({"error": "forbidden"}, code=403)
        u = urlparse(self.path)
        q = {k: int(v[0]) for k, v in parse_qs(u.query).items() if k in ("limit", "start")}
        start, limit = q.get("start", 0), q.get("limit", 25)
        if u.path == "/keys/current":
            return self.send({"userID": 1, "access": {"user": {"library": True}, "groups": {"all": {"library": True}}}})
        if u.path == "/users/1/groups":
            groups = [{"id": 77, "data": {"name": "Tide club"}}, {"id": 88, "data": {"name": "Locked out"}}]
            return self.send(groups[start:start + limit], total=len(groups))
        if u.path == "/groups/88/collections":
            return self.send({"error": "forbidden"}, code=403)
        for lib, items in LIBRARY.items():
            if u.path == f"{lib}/items":
                return self.send(items[start:start + limit], total=len(items))
            if u.path == f"{lib}/collections":
                cols = [{"key": "C1", "data": {"name": "Reading list"}}] if lib == "/users/1" else []
                return self.send(cols, total=len(cols))
        self.send({"error": "no such path"}, code=404)


def app_db(path):
    """A zotero.sqlite in the app's schema (the tables zotero.py reads): one unsynced paper with a highlight, one in the
    trash, and a copy of the API's P1 (kept once)."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
        CREATE TABLE groups (groupID INTEGER, libraryID INTEGER, name TEXT);
        CREATE TABLE itemTypesCombined (itemTypeID INTEGER, typeName TEXT);
        CREATE TABLE fieldsCombined (fieldID INTEGER, fieldName TEXT);
        CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, dateAdded TEXT, dateModified TEXT, libraryID INTEGER, key TEXT);
        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        CREATE TABLE itemDataValues (valueID INTEGER, value TEXT);
        CREATE TABLE creators (creatorID INTEGER, firstName TEXT, lastName TEXT, fieldMode INTEGER);
        CREATE TABLE creatorTypes (creatorTypeID INTEGER, creatorType TEXT);
        CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
        CREATE TABLE tags (tagID INTEGER, name TEXT);
        CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER);
        CREATE TABLE collections (collectionID INTEGER, collectionName TEXT, libraryID INTEGER, key TEXT);
        CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
        CREATE TABLE itemNotes (itemID INTEGER, parentItemID INTEGER, note TEXT);
        CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER);
        CREATE TABLE itemAnnotations (itemID INTEGER, parentItemID INTEGER, type INTEGER, text TEXT, comment TEXT, color TEXT, pageLabel TEXT);
        CREATE TABLE deletedItems (itemID INTEGER);
        INSERT INTO libraries VALUES (1, 'user');
        INSERT INTO itemTypesCombined VALUES (1, 'journalArticle'), (2, 'attachment'), (3, 'annotation');
        INSERT INTO fieldsCombined VALUES (1, 'title'), (2, 'date'), (3, 'url');
        INSERT INTO items VALUES (1, 1, '2025-04-01 09:00:00', '2025-04-01 09:00:00', 1, 'L1'), (2, 2, '2025-04-01 09:00:00', '', 1, 'LPDF'),
                                 (3, 3, '2025-04-02 09:00:00', '', 1, 'LA'), (4, 1, '2025-04-03 09:00:00', '', 1, 'TRASHED'),
                                 (5, 1, '2025-03-01 10:00:00', '', 1, 'P1');
        INSERT INTO itemDataValues VALUES (1, 'Only on this Mac'), (2, '2023'), (3, 'Thrown away'), (4, 'Tides and the moon');
        INSERT INTO itemData VALUES (1, 1, 1), (1, 2, 2), (4, 1, 3), (5, 1, 4);
        INSERT INTO creators VALUES (1, 'Alan', 'Turing', 0), (2, NULL, 'Bletchley Park', 1);
        INSERT INTO creatorTypes VALUES (1, 'author');
        INSERT INTO itemCreators VALUES (1, 1, 1, 0), (1, 2, 1, 1);
        INSERT INTO tags VALUES (1, 'machines');
        INSERT INTO itemTags VALUES (1, 1, 0);
        INSERT INTO itemAttachments VALUES (2, 1);
        INSERT INTO itemAnnotations VALUES (3, 2, 5, 'can machines think', NULL, '#ffd400', '1');
        INSERT INTO deletedItems VALUES (4);
    """)
    con.commit()
    con.close()


class ZoteroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeZotero)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()

    def run_zotero(self, key=KEY):
        env = {k: v for k, v in os.environ.items() if k != "UMP_ZOTERO_KEY"}
        env.update(HOME=str(self.home), CORPUS_DIR=str(self.corpus), UMP_ZOTERO_API=f"http://127.0.0.1:{self.server.server_port}",
                   PATH=f"{self.home}:{os.environ['PATH']}")
        if key:
            env["UMP_ZOTERO_KEY"] = key
        (self.home / "security").write_text("#!/bin/sh\nexit 44\n")  # no Keychain item: not this Mac's real one
        (self.home / "security").chmod(0o755)
        r = subprocess.run([sys.executable, "-c", "import zotero; zotero.main()"], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self.corpus / "normalized/zotero.jsonl"
        recs = {r["id"]: r for r in map(json.loads, f.read_text().splitlines())} if f.exists() else {}
        return recs, json.loads((self.corpus / "manifest.json").read_text())["zotero"]

    def test_the_api(self):
        recs, manifest = self.run_zotero()
        self.assertEqual(sum(1 for k in recs if k.startswith("user:W")), 150, "every page of a library, not the first 100")
        p1 = recs["user:P1"]
        self.assertEqual((p1["kind"], p1["title"], p1["url"], p1["is_me"], p1["thread_name"]),
                         ("reference", "Tides and the moon", "https://doi.org/10.1000/tides", True, "My Library"))
        self.assertEqual(p1["text"], "Tides and the moon\nGrace Hopper, Tide Lab · Journal of Tides · 2024\nWhy spring tides are higher.\nTags: oceans")
        self.assertEqual((p1["meta"]["collections"], p1["meta"]["authors"]), (["Reading list"], ["Grace Hopper", "Tide Lab"]))
        self.assertNotIn("user:PDF1", recs, "an attachment isn't a record of its own")
        a1 = recs["user:A1"]
        self.assertEqual((a1["kind"], a1["title"], a1["text"], a1["meta"]["page"], a1["meta"]["on"]),
                         ("highlight", "Tides and the moon", "the sun and the moon line up\nkey point", "3", "P1"), "a PDF's highlight names its paper")
        self.assertEqual((recs["user:N1"]["title"], recs["user:N1"]["text"]), ("Note on Tides and the moon", "Tides\nRead this twice."))
        g1, g2 = recs["group:77:G1"], recs["group:77:G2"]
        self.assertEqual((g1["thread_name"], g1["is_me"], g1["author"], g1["meta"]["added_by"]), ("Tide club", False, "grace_h", "grace_h"))
        self.assertTrue(g2["is_me"], "what you added to a group is yours")
        self.assertEqual(manifest["notes"]["not_read"], {"group:88": "HTTP 403"}, "a group it can't read stops no other")

    def test_the_app_alone_and_both_at_once(self):
        zdir = self.home / "Zotero"
        zdir.mkdir()
        app_db(zdir / "zotero.sqlite")
        recs, _ = self.run_zotero(key=None)
        self.assertEqual(set(recs), {"user:L1", "user:LA", "user:P1"}, "no key: the app's library; the trash left out")
        l1 = recs["user:L1"]
        self.assertEqual((l1["title"], l1["ts"], l1["meta"]["authors"], l1["meta"]["tags"]),
                         ("Only on this Mac", "2025-04-01T09:00:00Z", ["Alan Turing", "Bletchley Park"], ["machines"]))
        self.assertEqual((recs["user:LA"]["title"], recs["user:LA"]["meta"]["type"]), ("Only on this Mac", "underline"))
        recs, _ = self.run_zotero()
        self.assertIn("user:L1", recs, "what isn't synced comes from the app")
        self.assertEqual(recs["user:P1"]["meta"]["venue"], "Journal of Tides", "an item in both is the API's copy")

    def test_a_wrong_key_keeps_what_was_read(self):
        self.run_zotero()
        recs, manifest = self.run_zotero(key="not-the-key")
        self.assertIn("user:P1", recs, "a key revoked or offline: earlier records stay")
        self.assertEqual(manifest["notes"]["api"], "not read: 403")


if __name__ == "__main__":
    unittest.main()
