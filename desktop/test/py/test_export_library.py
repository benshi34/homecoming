"""Tests for desktop/py/export_library.py, run as the app runs it (a subprocess) on a made-up library in a temp folder."""

import json
import os
from contextlib import closing
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[2]
SCRIPT = DESKTOP / "py" / "export_library.py"


def run(*args, timeout=120):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise AssertionError(f"exit {r.returncode}: {r.stderr[-2000:]}")
    return json.loads(r.stdout.strip().splitlines()[-1]), r.stderr


def library(root: Path) -> Path:
    c = root / "corpus"
    (c / "normalized").mkdir(parents=True)
    (c / "normalized" / "imessage.jsonl").write_text('{"text": "hi"}\n' * 2000)
    (c / "normalized" / ".DS_Store").write_bytes(b"\0" * 10)
    (c / "stream").mkdir()
    (c / "stream" / "2026-10.jsonl").write_text('{"what": "a walk"}\n')
    (c / "media" / "instagram").mkdir(parents=True)
    (c / "media" / "instagram" / "photo.jpg").write_bytes(os.urandom(50_000))
    (c / "imports" / "x").mkdir(parents=True)
    (c / "imports" / "x" / "twitter-2026.zip").write_bytes(os.urandom(30_000))
    (c / "raw" / "notes").mkdir(parents=True)
    (c / "raw" / "notes" / "NoteStore.sqlite").write_bytes(b"notes" * 100)
    # Not the library's: research kept beside it, and the decrypted iPhone backup, linked from elsewhere.
    (c / "training").mkdir()
    (c / "training" / "episodes.jsonl").write_text("{}\n")
    phone = root / "elsewhere" / "iphone"
    (phone / "files").mkdir(parents=True)
    (phone / "files" / "sms.db").write_bytes(b"secret" * 100)
    (c / "raw" / "iphone").symlink_to(phone)
    (c / "manifest.json").write_text('{"sources": {}}')
    (c / "identity.json").write_text('{"names": ["Ada"]}')
    con = sqlite3.connect(c / "corpus.db")
    con.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, text TEXT)")
    con.executemany("INSERT INTO records (text) VALUES (?)", [(f"message {i}",) for i in range(5000)])
    con.commit()
    con.close()
    return c


class ExportLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.corpus = library(self.root)
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_sizes_by_part_without_what_isnt_the_librarys(self):
        s, _ = run("sizes", str(self.corpus))
        self.assertEqual(s["media"], 50_000)
        self.assertEqual(s["originals"], 30_000 + 500, "the zip and the Notes copy; not the linked iPhone backup")
        self.assertGreater(s["records"], (self.corpus / "corpus.db").stat().st_size)
        self.assertEqual(s["estimate"]["media"], 50_000, "a photo takes as much in the zip")
        self.assertLess(s["estimate"]["records"], s["records"], "records shrink")
        self.assertTrue(s["phone_backup"], "there's a decrypted iPhone backup it leaves out")

    def test_everything_in_one_zip_under_one_folder(self):
        dest = self.out / "Homecoming Library 2026-10-15.zip"
        r, err = run("write", str(self.corpus), str(dest), "records,media,originals")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["path"], str(dest))
        self.assertIn("@progress", err)
        with zipfile.ZipFile(dest) as z:
            self.assertIsNone(z.testzip())
            names = set(z.namelist())
            top = "Homecoming Library 2026-10-15/"
            self.assertTrue(all(n.startswith(top) for n in names), names)
            rel = {n[len(top):] for n in names}
            for want in ["corpus.db", "manifest.json", "identity.json", "normalized/imessage.jsonl", "stream/2026-10.jsonl",
                         "media/instagram/photo.jpg", "imports/x/twitter-2026.zip", "raw/notes/NoteStore.sqlite", "README.txt"]:
                self.assertIn(want, rel)
            self.assertFalse([n for n in rel if n.startswith(("training", "raw/iphone")) or n.endswith(".DS_Store")], rel)
            self.assertEqual(z.getinfo(top + "media/instagram/photo.jpg").compress_type, zipfile.ZIP_STORED, "photos as they are")
            self.assertEqual(z.getinfo(top + "normalized/imessage.jsonl").compress_type, zipfile.ZIP_DEFLATED)
            readme = z.read(top + "README.txt").decode()
            self.assertIn("corpus.db: every record", readme)
            self.assertIn("imports/: each service's download", readme)
            db = self.out / "corpus.db"
            db.write_bytes(z.read(top + "corpus.db"))
        with closing(sqlite3.connect(db)) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM records").fetchone()[0], 5000, "the database opens, whole")
        self.assertEqual([p.name for p in self.out.iterdir() if p.name.startswith(".")], [], "no temporary file left")

    def test_records_alone(self):
        dest = self.out / "records.zip"
        r, _ = run("write", str(self.corpus), str(dest), "records")
        self.assertTrue(r["ok"], r)
        with zipfile.ZipFile(dest) as z:
            rel = {n.split("/", 1)[1] for n in z.namelist()}
        self.assertIn("corpus.db", rel, "records always go in")
        self.assertFalse([n for n in rel if n.startswith(("media/", "imports/", "raw/"))], rel)
        readme = zipfile.ZipFile(dest).read("records/README.txt").decode()
        self.assertNotIn("media/", readme, "the readme lists only what's there")

    def test_not_enough_space_says_so_and_writes_nothing(self):
        # Pretend the drive is nearly full: the estimate is more than what's free.
        env = dict(os.environ)
        code = (f"import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); import export_library as e; "
                f"e.free_bytes = lambda p: 1000; import json; from pathlib import Path; "
                f"print(json.dumps(e.write(Path({str(self.corpus)!r}), Path({str(self.out / 'x.zip')!r}), ['media'])))")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        res = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(res["error"], "space")
        self.assertEqual(res["free"], 1000)
        self.assertGreater(res["need"], 50_000)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_stopped_leaves_nothing(self):
        (self.corpus / "media" / "big.mov").write_bytes(os.urandom(1 << 20) * 300)  # long enough to stop part-way
        dest = self.out / "stopped.zip"
        p = subprocess.Popen([sys.executable, str(SCRIPT), "write", str(self.corpus), str(dest), "media"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 30
        while time.time() < deadline and not any(x.name.endswith(".partial") for x in self.out.iterdir()):
            time.sleep(0.02)
        p.send_signal(signal.SIGTERM)
        out, _ = p.communicate(timeout=60)
        self.assertEqual(json.loads(out.strip().splitlines()[-1]), {"ok": False, "error": "stopped"})
        self.assertEqual(list(self.out.iterdir()), [], "neither the zip nor its temporary file")

    def test_a_write_waits_while_the_database_is_copied(self):
        sys.path.insert(0, str(SCRIPT.parent))
        import export_library
        db = self.corpus / "corpus.db"
        lock = export_library.db_lock(db)
        other = sqlite3.connect(db, timeout=0.2)
        with self.assertRaises(sqlite3.OperationalError, msg="an import can't write while it's held"):
            other.execute("INSERT INTO records (text) VALUES ('new')")
            other.commit()
        other.rollback()
        lock.rollback()
        lock.close()
        other.execute("INSERT INTO records (text) VALUES ('new')")
        other.commit()
        self.assertEqual(other.execute("SELECT count(*) FROM records").fetchone()[0], 5001, "and can once it's let go")
        other.close()


if __name__ == "__main__":
    unittest.main()
