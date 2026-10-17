"""Photos on a synthetic library: your own photos, and the ones others shared with you kept apart (shared_photos).

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


def library(home):
    db = home / "Pictures/Photos Library.photoslibrary/database"
    (db / "search").mkdir(parents=True)
    con = sqlite3.connect(db / "Photos.sqlite")
    con.executescript("""
        create table ZMOMENT (Z_PK integer primary key, ZTITLE text, ZSUBTITLE text);
        create table ZPERSON (Z_PK integer primary key, ZFULLNAME text, ZDISPLAYNAME text);
        create table ZDETECTEDFACE (ZASSETFORFACE int, ZPERSONFORFACE int);
        create table ZASSETDESCRIPTION (Z_PK integer primary key, ZLONGDESCRIPTION text);
        create table ZADDITIONALASSETATTRIBUTES (ZASSET int, ZORIGINALFILENAME text, ZTITLE text, ZTIMEZONENAME text,
            ZIMPORTEDBYDISPLAYNAME text, ZASSETDESCRIPTION int);
        create table ZGENERICALBUM (Z_PK integer primary key, ZTITLE text, ZKIND int);
        create table Z_30ASSETS (Z_30ALBUMS int, Z_3ASSETS int);
        create table ZASSET (Z_PK integer primary key, ZUUID text, ZDATECREATED real, ZLATITUDE real, ZLONGITUDE real,
            ZFILENAME text, ZKIND int, ZFAVORITE int, ZHIDDEN int, ZTRASHEDSTATE int, ZDURATION real, ZMOMENT int,
            ZBUNDLESCOPE int, ZCLOUDISMYASSET int, ZLIBRARYSCOPE int);
        create table ZSHAREPARTICIPANT (Z_PK integer primary key, ZISCURRENTUSER int);
        create table ZASSETCONTRIBUTOR (Z_PK integer primary key, ZPARTICIPANT int, Z3LIBRARYSCOPEASSETCONTRIBUTORS int);
        insert into ZGENERICALBUM values (1, 'Family', 1505);
        insert into ZSHAREPARTICIPANT values (1, 1), (2, 0);
    """)
    # uuid, bundle scope, posted by you (shared albums), Shared Library, who added it (1 you, 2 someone else)
    rows = [("A0000000-0000-0000-0000-000000000001", 0, None, None, None),  # yours
            ("A0000000-0000-0000-0000-000000000002", 2, 0, None, None),     # a friend's, in a shared album
            ("A0000000-0000-0000-0000-000000000003", 2, 1, None, None),     # yours, posted to a shared album: a copy
            ("A0000000-0000-0000-0000-000000000004", 3, None, None, None),  # Shared with You in Messages
            ("A0000000-0000-0000-0000-000000000005", 0, None, 9, 1),        # you added it to the Shared Library
            ("A0000000-0000-0000-0000-000000000006", 0, None, 9, 2)]        # someone else added it
    for pk, (u, scope, mine, lib, who) in enumerate(rows, 1):
        con.execute("insert into ZASSET values (?, ?, 700000000, 38.72, -9.14, 'IMG.HEIC', 0, 0, 0, 0, 0, null, ?, ?, ?)",
                    (pk, u, scope, mine, lib))
        if who:
            con.execute("insert into ZASSETCONTRIBUTOR values (?, ?, ?)", (pk, who, pk))
    con.execute("insert into Z_30ASSETS values (1, 2)")
    con.commit()
    con.close()
    psi = sqlite3.connect(db / "search/psi.sqlite")
    psi.executescript("create table groups (category int, content_string text); create table assets (uuid_0 int, uuid_1 int);"
                      "create table ga (groupid int, assetid int);")
    psi.close()


class PhotosTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.corpus.mkdir()
        library(self.home)

    def run_photos(self):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", "import photos; photos.main()"], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        read = lambda s: {x["id"][-1]: x for x in map(json.loads, (self.corpus / f"normalized/{s}.jsonl").read_text().splitlines())}
        return read("photos"), read("shared_photos")

    def test_others_photos_are_kept_apart(self):
        mine, shared = self.run_photos()
        self.assertEqual(set(mine), {"1", "5"}, "yours: your library, and what you added to the Shared Library")
        self.assertEqual(set(shared), {"2", "3", "4", "6"})
        self.assertEqual((shared["2"]["is_me"], shared["2"]["author"], shared["2"]["meta"]["shared"]), (False, "someone else", "shared_album"))
        self.assertIn("Albums: Family", shared["2"]["text"])
        self.assertEqual((shared["3"]["is_me"], shared["3"]["meta"].get("copy")), (True, True), "one you posted: a copy of yours")
        self.assertEqual(shared["4"]["meta"]["shared"], "shared_with_you")
        self.assertEqual(shared["6"]["meta"]["shared"], "shared_library")
        self.assertEqual(mine["5"]["meta"]["shared"], "shared_library")
        self.assertTrue(all(x["is_me"] for x in mine.values()))

    def test_ones_kept_as_yours_by_an_earlier_run_move(self):
        # Before shared photos were told apart, every one was written as yours; reading again doesn't carry them over.
        (self.corpus / "normalized").mkdir()
        old = {"id": "A0000000-0000-0000-0000-000000000002", "source": "photos", "kind": "photo", "ts": "2023-03-08T00:00:00Z", "is_me": True}
        (self.corpus / "normalized/photos.jsonl").write_text(json.dumps(old) + "\n")
        mine, shared = self.run_photos()
        self.assertNotIn("2", mine)
        self.assertIn("2", shared)

    def test_a_library_from_before_sharing(self):
        db = self.home / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
        con = sqlite3.connect(db)
        con.executescript("drop table ZASSETCONTRIBUTOR; drop table ZSHAREPARTICIPANT; alter table ZASSET drop column ZBUNDLESCOPE;"
                          "alter table ZASSET drop column ZCLOUDISMYASSET; alter table ZASSET drop column ZLIBRARYSCOPE;")
        con.close()
        mine, shared = self.run_photos()
        self.assertEqual((len(mine), len(shared)), (6, 0), "no sharing columns: everything is yours, as before")


if __name__ == "__main__":
    unittest.main()
