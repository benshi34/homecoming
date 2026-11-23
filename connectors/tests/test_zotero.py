"""Zotero: from the Zotero app's zotero.sqlite, and nothing from zotero.org. Everyone and everything is made up.

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

CONNECTORS = Path(__file__).resolve().parents[1]
ASKED = []  # requests that reached the stand-in for zotero.org: there should be none


class NotZotero(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        ASKED.append(self.path)
        self.send_response(404)
        self.end_headers()


def app_db(path):
    """A zotero.sqlite in the app's schema (the tables zotero.py reads): your library (a paper with a note, in a
    collection; one with a PDF and two highlights in it; one in the trash) and a group's book."""
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
        INSERT INTO libraries VALUES (1, 'user'), (2, 'group');
        INSERT INTO groups VALUES (77, 2, 'Tide club');
        INSERT INTO itemTypesCombined VALUES (1, 'journalArticle'), (2, 'attachment'), (3, 'annotation'), (4, 'note'), (5, 'book');
        INSERT INTO fieldsCombined VALUES (1, 'title'), (2, 'date'), (3, 'url'), (4, 'DOI'), (5, 'publicationTitle'), (6, 'abstractNote');
        INSERT INTO items VALUES (1, 1, '2025-04-01 09:00:00', '2025-04-01 09:00:00', 1, 'L1'), (2, 2, '2025-04-01 09:00:00', '', 1, 'LPDF'),
                                 (3, 3, '2025-04-02 09:00:00', '', 1, 'LA'), (4, 1, '2025-04-03 09:00:00', '', 1, 'TRASHED'),
                                 (5, 1, '2025-03-01 10:00:00', '', 1, 'P1'), (6, 4, '2025-03-02 10:00:00', '', 1, 'N1'),
                                 (7, 3, '2025-04-02 10:00:00', '', 1, 'LA2'), (8, 5, '2025-02-01 10:00:00', '', 2, 'G1');
        INSERT INTO itemDataValues VALUES (1, 'Only on this Mac'), (2, '2023'), (3, 'Thrown away'), (4, 'Tides and the moon'),
                                          (5, '2024-06'), (6, '10.1000/tides'), (7, 'Journal of Tides'), (8, 'Why spring tides are higher.'),
                                          (9, 'Compilers'), (10, '1986');
        INSERT INTO itemData VALUES (1, 1, 1), (1, 2, 2), (4, 1, 3), (5, 1, 4), (5, 2, 5), (5, 4, 6), (5, 5, 7), (5, 6, 8), (8, 1, 9), (8, 2, 10);
        INSERT INTO creators VALUES (1, 'Alan', 'Turing', 0), (2, NULL, 'Bletchley Park', 1);
        INSERT INTO creatorTypes VALUES (1, 'author');
        INSERT INTO itemCreators VALUES (1, 1, 1, 0), (1, 2, 1, 1);
        INSERT INTO tags VALUES (1, 'machines');
        INSERT INTO itemTags VALUES (1, 1, 0);
        INSERT INTO collections VALUES (1, 'Reading list', 1, 'C1');
        INSERT INTO collectionItems VALUES (1, 5);
        INSERT INTO itemNotes VALUES (6, 5, '<h1>Tides</h1><p>Read this twice.</p>');
        INSERT INTO itemAttachments VALUES (2, 1);
        INSERT INTO itemAnnotations VALUES (3, 2, 5, 'can machines think', NULL, '#ffd400', '1'),
                                           (7, 2, 1, 'the imitation game', 'key point', '#ffd400', '3');
        INSERT INTO deletedItems VALUES (4);
    """)
    con.commit()
    con.close()


class ZoteroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), NotZotero)
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

    def run_zotero(self):
        # A key, a stand-in for zotero.org's API and a security that notes being asked: none is used, since nothing
        # comes from zotero.org (and were something to try, it would reach the stand-in, not the real one).
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_ZOTERO_KEY": "made-up-zotero-key",
               "UMP_ZOTERO_API": f"http://127.0.0.1:{self.server.server_port}", "PATH": f"{self.home}:{os.environ['PATH']}"}
        ASKED.clear()
        (self.home / "security").write_text(f"#!/bin/sh\ntouch {self.home / 'asked-the-keychain'}\nexit 44\n")
        (self.home / "security").chmod(0o755)
        r = subprocess.run([sys.executable, "-c", "import zotero; zotero.main()"], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.home / "asked-the-keychain").exists(), "no key looked for")
        self.assertEqual(ASKED, [], "nothing asked of zotero.org")
        f = self.corpus / "normalized/zotero.jsonl"
        return {r["id"]: r for r in map(json.loads, f.read_text().splitlines())} if f.exists() else {}

    def test_the_app(self):
        zdir = self.home / "Zotero"
        zdir.mkdir()
        app_db(zdir / "zotero.sqlite")
        recs = self.run_zotero()
        self.assertEqual(set(recs), {"user:L1", "user:LA", "user:LA2", "user:P1", "user:N1", "group:77:G1"},
                         "the trash left out; an attachment isn't a record of its own")
        l1 = recs["user:L1"]
        self.assertEqual((l1["title"], l1["ts"], l1["is_me"], l1["thread_name"], l1["meta"]["authors"], l1["meta"]["tags"]),
                         ("Only on this Mac", "2025-04-01T09:00:00Z", True, "My Library", ["Alan Turing", "Bletchley Park"], ["machines"]))
        self.assertEqual((recs["user:LA"]["title"], recs["user:LA"]["meta"]["type"]), ("Only on this Mac", "underline"))
        la2 = recs["user:LA2"]
        self.assertEqual((la2["kind"], la2["title"], la2["text"], la2["meta"]["page"], la2["meta"]["on"]),
                         ("highlight", "Only on this Mac", "the imitation game\nkey point", "3", "L1"), "a PDF's highlight names its paper")
        p1 = recs["user:P1"]
        self.assertEqual((p1["kind"], p1["url"], p1["text"], p1["meta"]["collections"]),
                         ("reference", "https://doi.org/10.1000/tides", "Tides and the moon\nJournal of Tides · 2024\nWhy spring tides are higher.",
                          ["Reading list"]))
        self.assertEqual((recs["user:N1"]["title"], recs["user:N1"]["text"]), ("Note on Tides and the moon", "Tides\nRead this twice."))
        g1 = recs["group:77:G1"]
        self.assertEqual((g1["title"], g1["thread_name"], g1["is_me"]), ("Compilers", "Tide club", False))

    def test_no_app_no_records(self):
        self.assertEqual(self.run_zotero(), {}, "without the app, nothing: zotero.org isn't asked, even with a key")


if __name__ == "__main__":
    unittest.main()
