"""Doing less work for the same library, on made-up data: the index loads again only the sources whose files changed
(and ends up as a full build would), a mailbox that hasn't changed isn't parsed again, and Google Photos' pictures
go with their sidecar's record instead of being copied out as files of their own.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
import common

with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'CORPUS', Path(tmp)):
    (Path(tmp) / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
    import imports


def jsonl(rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


def email(i, source, text=None):
    return {"id": f"<m{i}@example.test>", "source": source, "kind": "email", "ts": f"2026-01-{i + 1:02d}T10:00:00Z",
            "author": "Grace", "title": f"Subject {i}", "text": text or f"about the lighthouse {i}", "meta": {"from": "g@example.test"}}


class IndexTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)

    def corpus(self, name):
        c = self.root / name
        (c / "normalized").mkdir(parents=True, exist_ok=True)
        (c / "manifest.json").write_text(json.dumps({"mail": {"count": 0}, "gmail": {"count": 0}}))
        return c

    def write(self, c, source, rows):
        (c / "normalized" / f"{source}.jsonl").write_text(jsonl(rows))

    def index(self, c, **env):
        p = subprocess.run([sys.executable, str(CONNECTORS / "build_index.py")], capture_output=True, text=True, timeout=120,
                           env={**os.environ, "CORPUS_DIR": str(c), **env})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def library(self, c):
        con = sqlite3.connect(c / "corpus.db")
        con.execute("insert into fts(fts) values('integrity-check')")  # the search index agrees with the records
        rows = sorted(tuple(r) for r in con.execute(f"select {', '.join(common.FIELDS)} from records"))
        found = {w: sorted(con.execute("select r.source, r.id from fts join records r on r.rowid = fts.rowid where fts match ?", (w,)).fetchall())
                 for w in ("lighthouse", "harbour", "kettle", "Grace")}
        rowids = dict(((s, i), n) for s, i, n in con.execute("select source, id, rowid from records"))
        con.close()
        return rows, found, rowids, json.loads((c / "manifest.json").read_text())["mail"]

    def test_only_what_changed_is_loaded_again_and_the_result_is_a_full_builds(self):
        c = self.corpus("inc")
        self.write(c, "gmail", [email(i, "gmail") for i in range(5)])
        self.write(c, "mail", [email(i, "mail") for i in range(3, 8)] + [{"id": "n1", "source": "mail", "kind": "note", "text": "a kettle"}])
        self.write(c, "notes", [{"id": "a", "source": "notes", "kind": "note", "text": "the harbour at night"}])
        self.write(c, "photos", [{"id": "p", "source": "photos", "kind": "photo", "ts": "2026-02-01T00:00:00Z", "text": "Photo"}])
        self.write(c, "visits", [{"id": f"v{i}", "source": "visits", "kind": "visit", "ts": "2026-03-01T00:00:00Z",
                                  "title": f"page {i}", "url": f"https://example.test/{i}"} for i in range(300)])  # most of it stays
        out = self.index(c)
        self.assertIn("(2 already in an export)", out, "Mail's copies of Gmail's emails are left out")
        before = self.library(c)
        notes_rowid = before[2][("notes", "a")]

        time.sleep(0.01)
        self.write(c, "notes", [{"id": "a", "source": "notes", "kind": "note", "text": "the harbour at night"}])  # the same again
        self.write(c, "gmail", [email(i, "gmail") for i in range(1, 6)])  # one more, one gone: Mail's copies move
        self.write(c, "x", [{"id": "t", "source": "x", "kind": "post", "text": "a lighthouse keeper"}])
        (c / "normalized/photos.jsonl").unlink()
        out = self.index(c)
        self.assertIn("index: read again gmail, x, mail; taken out photos", out)
        after = self.library(c)
        self.assertEqual(after[2][("notes", "a")], notes_rowid, "what didn't change stays where it was")

        full = self.root / "full"
        shutil.copytree(c, full)
        (full / "corpus.db").unlink()
        self.index(full, UMP_FULL_INDEX="1")
        want = self.library(full)
        self.assertEqual(after[0], want[0], "the same records as a build from nothing")
        self.assertEqual(after[1], want[1], "found by the same words")
        self.assertEqual(after[3], want[3], "and the same count of Mail's emails already in an export")
        self.assertEqual(after[3]["notes"], {"in_an_export": 3})

        out = self.index(c)
        self.assertIn("index: read again nothing", out)
        self.assertEqual(self.library(c)[:2], want[:2])

    def test_an_index_from_before_is_built_from_nothing(self):
        c = self.corpus("old")
        self.write(c, "notes", [{"id": "a", "source": "notes", "kind": "note", "text": "the harbour"}])
        con = sqlite3.connect(c / "corpus.db")
        con.execute("create table records (rowid integer primary key, id text, source text)")
        con.commit()
        con.close()
        out = self.index(c)
        self.assertNotIn("index: read again", out)
        con = sqlite3.connect(c / "corpus.db")
        self.assertEqual(con.execute("pragma user_version").fetchone()[0], 2)
        self.assertIn("records_kind_source", [r[0] for r in con.execute("select name from sqlite_master where type = 'index'")])
        con.close()

    def test_citations_survive_full_builds_and_deleted_numbers_are_never_reused(self):
        c = self.corpus("citations")
        original = {"id": "original", "source": "notes", "kind": "note", "text": "the harbour"}
        self.write(c, "notes", [original])
        self.index(c)
        number = self.library(c)[2][("notes", "original")]

        # A large, alphabetically earlier source forces a fresh build. It must not take the old citation's number.
        self.write(c, "aaa", [{"id": "new", "source": "aaa", "kind": "note", "text": "a lighthouse " * 100}])
        self.index(c)
        self.assertEqual(self.library(c)[2][("notes", "original")], number)
        self.index(c, UMP_FULL_INDEX="1")
        self.assertEqual(self.library(c)[2][("notes", "original")], number)

        (c / "normalized/notes.jsonl").unlink()
        self.index(c, UMP_FULL_INDEX="1")
        self.write(c, "notes", [{**original, "id": "replacement"}])
        self.index(c, UMP_FULL_INDEX="1")
        with sqlite3.connect(c / "corpus.db") as db:
            self.assertIsNone(db.execute("select id from records where rowid = ?", (number,)).fetchone(),
                              "a deleted citation is missing, not a different record")
            reservation = db.execute("select key from record_ids where rowid = ?", (number,)).fetchone()[0]
            self.assertRegex(reservation, r"^[0-9a-f]{64}$", "reservations don't retain deleted records' source or identifier")
        self.write(c, "notes", [original])
        self.index(c, UMP_FULL_INDEX="1")
        self.assertEqual(self.library(c)[2][("notes", "original")], number, "a returning record keeps its number")

    def test_reordering_and_editing_a_source_keeps_its_citations_during_incremental_updates(self):
        c = self.corpus("citations-incremental")
        self.write(c, "visits", [{"id": str(i), "source": "visits", "kind": "visit", "text": "a lighthouse"} for i in range(1200)])
        notes = [{"id": str(i), "source": "notes", "kind": "note", "text": "the harbour"} for i in range(3)]
        self.write(c, "notes", notes)
        self.index(c)
        numbers = self.library(c)[2]
        self.write(c, "notes", [{**r, "text": "the harbour and kettle"} for r in reversed(notes)])
        self.assertIn("index: read again notes", self.index(c))
        self.assertEqual(self.library(c)[2], numbers)

        self.write(c, "notes", [{**notes[0], "id": "new"}])
        self.assertIn("index: read again notes", self.index(c))
        self.assertGreater(self.library(c)[2][("notes", "new")], max(numbers.values()))
        self.index(c, UMP_FULL_INDEX="1")
        with sqlite3.connect(c / "corpus.db") as db:
            for r in notes:
                self.assertIsNone(db.execute("select id from records where rowid = ?", (numbers[("notes", r["id"])],)).fetchone())

    def test_upgrade_adopts_existing_record_numbers(self):
        c = self.corpus("citations-upgrade")
        self.write(c, "notes", [{"id": "a", "source": "notes", "kind": "note", "text": "the harbour"}])
        with sqlite3.connect(c / "corpus.db") as db:
            db.execute("create table records (rowid integer primary key, source text, id text)")
            db.execute("insert into records values (41, 'notes', 'a')")
            db.execute("pragma user_version = 1")
        self.index(c)
        self.assertEqual(self.library(c)[2][("notes", "a")], 41)
        self.write(c, "aaa", [{"id": "b", "source": "aaa", "kind": "note", "text": "a lighthouse"}])
        self.index(c, UMP_FULL_INDEX="1")
        self.assertEqual(self.library(c)[2], {("notes", "a"): 41, ("aaa", "b"): 42})

    def test_mail_deduplication_reserves_the_missing_citation(self):
        c = self.corpus("citations-mail")
        self.write(c, "mail", [email(0, "mail")])
        self.index(c)
        number = self.library(c)[2][("mail", "<m0@example.test>")]
        self.write(c, "gmail", [email(0, "gmail")])
        self.index(c)
        with sqlite3.connect(c / "corpus.db") as db:
            self.assertIsNone(db.execute("select id from records where rowid = ?", (number,)).fetchone())
        (c / "normalized/gmail.jsonl").unlink()
        self.index(c)
        self.assertEqual(self.library(c)[2][("mail", "<m0@example.test>")], number)


class GooglePhotosTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.imports, self.media = self.root / "corpus/imports", self.root / "corpus/media"
        for name, value in (("IMPORTS", self.imports), ("MEDIA", self.media), ("CORPUS", self.imports.parent)):
            p = patch.object(imports, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.recs = {}

    def W(self, source):
        recs = self.recs

        class W:
            def has(self, key):
                return any(r["id"] == str(key) for r in recs.get(source, []))

            def add(self, **r):
                assert set(r) <= set(common.FIELDS) and not self.has(r["id"])
                recs.setdefault(source, []).append(r)
        return W()

    def sidecar(self, title, t=1704067200, lat=48.85, url=None):
        # Each photo has its own link in Google Photos: what keeps it once however many albums and Takeouts it's in.
        return json.dumps({"title": title, "photoTakenTime": {"timestamp": str(t)}, "geoData": {"latitude": lat, "longitude": 2.35},
                           "url": f"https://photos.google.com/photo/{url or title}"})

    def run_parsers(self):
        es, used = imports.entries(), set()
        imports.google(es, self.W, used)
        imports.other_files(es, self.W, used)
        # Each photo by its link's end (the sidecar's url).
        return {r["url"].rsplit("/", 1)[-1]: r for r in self.recs.get("google_photos", [])}, sorted(r["id"] for r in self.recs.get("takeout_files", []))

    def test_photos_go_with_their_sidecars_and_are_not_on_the_disk_twice(self):
        album = self.imports / "takeout-1/Takeout/Google Photos/Paris"
        album.mkdir(parents=True)
        files = {
            "IMG_0001.jpg": b"one", "IMG_0001.jpg.json": self.sidecar("IMG_0001.jpg", url="one"),
            "IMG_0001(1).jpg": b"one again", "IMG_0001.jpg(1).json": self.sidecar("IMG_0001.jpg", url="one-again"),
            "IMG_0002.HEIC": b"live", "IMG_0002.MP4": b"motion", "IMG_0002.HEIC.supplemental-metadata.json": self.sidecar("IMG_0002.HEIC"),
            "IMG_0003.jpg": b"three", "IMG_0003-edited.jpg": b"three, edited", "IMG_0003.jpg.supplemental-me.json": self.sidecar("IMG_0003.jpg"),
            "stray.jpg": b"no sidecar", "metadata.json": json.dumps({"title": "Paris"}),
        }
        for n, data in files.items():
            (album / n).write_bytes(data if isinstance(data, bytes) else data.encode())
        photos, leftover = self.run_parsers()
        rel = "takeout-1/Takeout/Google Photos/Paris"
        kept = {k: [Path(f).name for f in r["meta"].get("files", [])] for k, r in photos.items()}
        self.assertEqual(kept, {"one": ["IMG_0001.jpg"], "one-again": ["IMG_0001(1).jpg"],
                                "IMG_0002.HEIC": ["IMG_0002.HEIC", "IMG_0002.MP4"],
                                "IMG_0003.jpg": ["IMG_0003.jpg", "IMG_0003-edited.jpg"]})
        self.assertEqual(leftover, [f"{rel}/stray.jpg"], "only a picture no sidecar names is a file of its own")
        r = photos["IMG_0003.jpg"]
        self.assertEqual((r["kind"], r["ts"], r["meta"]["lat"]), ("photo", "2024-01-01T00:00:00Z", 48.85), "the sidecar's time and place")
        for f in r["meta"]["files"]:
            self.assertTrue(f.endswith(f"media/takeout/{rel}/{Path(f).name}"), f)
        copy = self.media / "takeout" / rel / "IMG_0003-edited.jpg"
        self.assertEqual(copy.read_bytes(), b"three, edited")
        self.assertNotEqual(copy.stat().st_ino, (album / "IMG_0003-edited.jpg").stat().st_ino, "a file of its own (a clone on APFS)")

    def test_a_copy_from_before_becomes_a_clone_once(self):
        album = self.imports / "takeout-1/Takeout/Google Photos/Paris"
        album.mkdir(parents=True)
        (album / "IMG_0001.jpg").write_bytes(b"one")
        (album / "IMG_0001.jpg.json").write_text(self.sidecar("IMG_0001.jpg"))
        old = self.media / "takeout/takeout-1/Takeout/Google Photos/Paris/IMG_0001.jpg"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"one")
        ino = old.stat().st_ino
        manifest = self.root / "corpus/manifest.json"
        with patch.object(common, "MANIFEST", manifest), \
                patch.object(common, "NORM", self.root / "corpus/normalized"):
            es, used = imports.entries(), set()
            imports.google(es, self.W, used)
            imports.unclaimed_ledger(es, used)
            self.assertNotEqual(old.stat().st_ino, ino, "made again, as a clone")
            self.assertEqual(old.read_bytes(), b"one")
            self.assertTrue(manifest.with_name(".media-cloned").exists())
            ino = old.stat().st_ino
            self.recs = {}
            imports.google(imports.entries(), self.W, set())
            self.assertEqual(old.stat().st_ino, ino, "once")

    def test_across_zip_parts(self):
        """A photo can be in one part of the export and its sidecar in another; in a zip, it's unzipped (once)."""
        d = self.imports / "takeout-2"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "takeout-2-001.zip", "w") as z:
            z.writestr("Takeout/Google Photos/Trip/IMG_0009.jpg.json", self.sidecar("IMG_0009.jpg"))
        with zipfile.ZipFile(d / "takeout-2-002.zip", "w") as z:
            z.writestr("Takeout/Google Photos/Trip/IMG_0009.jpg", b"nine")
            z.writestr("Takeout/Google Photos/Other/IMG_0009.jpg", b"not this one: another album")
        photos, leftover = self.run_parsers()
        r = photos["IMG_0009.jpg"]
        self.assertEqual(len(r["meta"]["files"]), 1)
        self.assertEqual((self.media / "takeout/Takeout/Google Photos/Trip/IMG_0009.jpg").read_bytes(), b"nine")
        self.assertEqual(leftover, ["Takeout/Google Photos/Other/IMG_0009.jpg"])


def mbox(*mids):
    return "".join(f"From x@example.test Mon Jan 01 00:00:00 2024\nFrom: Grace <g@example.test>\nTo: ada@example.test\n"
                   f"Message-ID: <{m}@example.test>\nSubject: Note {m}\nDate: Mon, 01 Jan 2024 00:00:00 +0000\n\nHello {m}.\n"
                   for m in mids)


class MailboxAsBeforeTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.corpus = Path(t.name) / "corpus"
        (self.corpus / "imports/takeout-1/Takeout/Mail").mkdir(parents=True)
        (self.corpus / "imports/hotmail").mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada"], "emails": ["ada@example.test"], "usernames": []}))
        self.box = self.corpus / "imports/takeout-1/Takeout/Mail/All mail.mbox"
        self.box.write_text(mbox("a", "b"))
        (self.corpus / "imports/hotmail/Inbox.mbox").write_text(mbox("c"))

    def run_imports(self, **env):
        code = "import imports; imports.main()"
        p = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, capture_output=True, text=True, timeout=120,
                           env={**os.environ, "CORPUS_DIR": str(self.corpus), **env})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def gmail(self):
        return (self.corpus / "normalized/gmail.jsonl").read_text()

    @staticmethod
    def kept(out):
        line = next((l for l in out.splitlines() if l.endswith("kept as read")), "")
        return line.split("] ", 1)[-1].split(":")[0].split(", ") if line else []

    def test_an_unchanged_mailbox_keeps_its_read(self):
        self.assertEqual(self.kept(self.run_imports()), [])
        first, at = self.gmail(), (self.corpus / "normalized/gmail.jsonl").stat().st_mtime_ns
        ran = json.loads((self.corpus / "manifest.json").read_text())["gmail"]["ran_at"]
        time.sleep(1.1)
        (self.corpus / "imports/spotify").mkdir()
        (self.corpus / "imports/spotify/StreamingHistory_music_0.json").write_text("[]")  # a new export of something else
        out = self.run_imports()
        self.assertIn("gmail, hotmail: the mailboxes are as they were when last read; kept as read", out)
        self.assertEqual(self.kept(out), ["gmail", "hotmail"])
        self.assertEqual((self.corpus / "normalized/gmail.jsonl").stat().st_mtime_ns, at, "not written again")
        m = json.loads((self.corpus / "manifest.json").read_text())
        self.assertGreater(m["gmail"]["ran_at"], ran, "but read as far as the page says")
        self.assertEqual(m["gmail"]["count"], 2)

        self.assertEqual(self.kept(self.run_imports(UMP_REREAD_ALL="1")), [], "the readers changed: all read")
        self.assertEqual(self.gmail(), first)
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada"], "emails": ["g@example.test"], "usernames": []}))
        self.assertEqual(self.kept(self.run_imports()), [], "who you are changed: read again")
        self.assertIn('"is_me": true', self.gmail())
        self.box.write_text(mbox("a", "b", "d"))
        self.assertEqual(self.kept(self.run_imports()), ["hotmail"], "the other one is still as it was")
        self.assertEqual(len(self.gmail().splitlines()), 3, "the one that changed is read again")

    def test_a_read_that_failed_is_not_remembered(self):
        self.run_imports()
        self.box.write_text(mbox("a", "b", "d"))
        code = textwrap.dedent("""
            import imports
            real = imports.google
            def failing(es, W, used):
                real(es, W, used)
                raise RuntimeError("cut short")
            imports.PARSERS = [failing if p is real else p for p in imports.PARSERS]
            try:
                imports.main()
            except RuntimeError:
                pass
            imports.unclaimed_ledger(imports.entries(), set())
        """)
        subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, capture_output=True, text=True, timeout=120,
                       env={**os.environ, "CORPUS_DIR": str(self.corpus)})
        self.assertEqual(len(self.gmail().splitlines()), 2, "the old read is kept")
        self.assertEqual(self.kept(self.run_imports()), ["hotmail"], "and the mailbox read again next time")
        self.assertEqual(len(self.gmail().splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
