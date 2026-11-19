"""Disk space and recovery through the real index builder, on made-up records.

Run: python -m unittest tests.test_build_index (from connectors/).
"""

import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import closing
from pathlib import Path


CONNECTORS = Path(__file__).resolve().parents[1]
MIB = 1 << 20


class IndexDiskTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.corpus = Path(directory.name)
        self.norm = self.corpus / "normalized"
        self.norm.mkdir()
        self.db = self.corpus / "corpus.db"
        self.tmp = self.corpus / "corpus.db.tmp"
        self.manifest = self.corpus / "manifest.json"
        self.manifest.write_text(json.dumps({"notes": {"count": 1}, "static": {"count": 1}}))
        self.write_source("notes", "harbour")
        self.write_source("static", "lighthouse " * 1000)
        self.index()
        self.before = self.db.read_bytes()
        self.db_stamp = self.db.stat().st_mtime_ns
        self.write_source("notes", "kettle at the harbour")
        # A read writes the manifest after its sources. Make the ordering explicit without sleeping.
        os.utime(self.manifest, ns=(self.db_stamp + 10_000_000, self.db_stamp + 10_000_000))
        self.manifest_stamp = self.manifest.stat().st_mtime_ns

    def write_source(self, source, text):
        record = {"id": "one", "source": source, "kind": "note", "ts": "2026-01-02T10:00:00Z", "text": text}
        (self.norm / f"{source}.jsonl").write_text(json.dumps(record) + "\n")

    def need(self, fresh=False, margin=8):
        paths = self.norm.glob("*.jsonl") if fresh else [self.norm / "notes.jsonl"]
        return 2 * sum(p.stat().st_size for p in paths) + margin * MIB

    def index(self, free=10_000_000_000, fresh=False, margin="8", setup="", rebuilt=True, after_clone=False,
              check_closed=False, ok=True):
        # Patch in the child process so this drives main(), a real SQLite file, and the real stream builder.
        # No test-only environment switch is needed in production.
        code = textwrap.dedent(f"""
            import errno
            import sqlite3
            from contextlib import ExitStack
            from types import SimpleNamespace
            from unittest.mock import patch
            import build_index
            import stream

            opened = []
            def usage(path):
                assert path == build_index.CORPUS
                if {after_clone!r}:
                    tmp = build_index.DB.with_suffix('.db.tmp')
                    assert tmp.read_bytes() == build_index.DB.read_bytes(), 'space checked before the clone finished'
                return SimpleNamespace(free={free})

            with ExitStack() as patches:
                patches.enter_context(patch('build_index.shutil.disk_usage', side_effect=usage))
                stream_build = patches.enter_context(patch('stream.build', wraps=stream.build))
        """)
        code += textwrap.indent(textwrap.dedent(setup), "    ")
        code += f"    build_index.main()\n    assert stream_build.call_count == {int(rebuilt)}, 'wrong stream build count'\n"
        if check_closed:
            code += textwrap.indent(textwrap.dedent("""
                assert opened, 'no database connection was exercised'
                for con in opened:
                    try:
                        con.execute('select 1')
                    except sqlite3.ProgrammingError:
                        pass
                    else:
                        raise AssertionError('temporary database connection was left open')
            """), "    ")
        env = {**os.environ, "CORPUS_DIR": str(self.corpus)}
        env.pop("UMP_FULL_INDEX", None)
        env.pop("UMP_INDEX_MARGIN_MB", None)
        if fresh:
            env["UMP_FULL_INDEX"] = "1"
        if margin is not None:
            env["UMP_INDEX_MARGIN_MB"] = margin
        result = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True,
                                text=True, timeout=120)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def assert_not_rebuilt(self, result, free, need, old=True):
        self.assertEqual(result.returncode, 0, result.stderr)
        if old:
            self.assertEqual(self.db.read_bytes(), self.before, "the last index must be byte-identical")
            self.assertEqual(self.db.stat().st_mtime_ns, self.db_stamp, "the old index must stay out of date")
            with closing(sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)) as con:
                self.assertEqual(con.execute("select count(*) from fts where fts match 'harbour'").fetchone()[0], 1)
                self.assertEqual(con.execute("select count(*) from fts where fts match 'kettle'").fetchone()[0], 0)
        else:
            self.assertFalse(self.db.exists())
        self.assertFalse(self.tmp.exists(), "no half-built copy is left on disk")
        manifest = json.loads(self.manifest.read_text())
        self.assertEqual(manifest["notes"], {"count": 1})
        note = manifest["index"]["not_rebuilt"]
        self.assertEqual(set(note), {"free_bytes", "need_bytes", "at"})
        self.assertEqual((note["free_bytes"], note["need_bytes"]), (free, need))
        self.assertIsNotNone(dt.datetime.fromisoformat(note["at"]).tzinfo)
        self.assertEqual(result.stdout.splitlines(), [
            f"index: not rebuilt: {free / 1e9:.1f} GB free, it needs about {need / 1e9:.1f} GB. "
            "The last index stays; the next read tries again."
        ])
        return note

    def test_fresh_checks_all_files_and_the_default_margin_before_building(self):
        self.tmp.write_bytes(b"an interrupted build")
        free = self.need(fresh=True, margin=5120) - 1
        result = self.index(free=free, fresh=True, margin=None, rebuilt=False)
        self.assert_not_rebuilt(result, free, self.need(fresh=True, margin=5120))
        self.assertEqual(self.manifest.stat().st_mtime_ns, self.manifest_stamp)

    def test_first_build_without_room_leaves_no_database(self):
        self.db.unlink()
        result = self.index(free=0, rebuilt=False)
        self.assert_not_rebuilt(result, 0, self.need(fresh=True), old=False)

    def test_update_checks_changed_files_after_the_clone_and_does_not_try_fresh(self):
        free = self.need() - 1
        result = self.index(free=free, rebuilt=False, after_clone=True)
        self.assert_not_rebuilt(result, free, self.need())

    def test_enough_space_rebuilds_clears_the_note_and_updates_the_real_search_and_stream(self):
        self.index(free=0, rebuilt=False)
        # Touch an unchanged source: its hash excludes it from the space budget as well as the reload.
        self.write_source("static", "lighthouse " * 1000)
        result = self.index(free=self.need(), after_clone=True, setup="""
            patches.enter_context(patch('build_index.ctypes.CDLL', side_effect=AttributeError('no clonefile')))
        """)
        self.assertIn("index: read again notes", result.stdout)
        self.assertIn("stream:", result.stdout)
        self.assertNotIn("index", json.loads(self.manifest.read_text()))
        self.assertFalse(self.tmp.exists())
        self.assertGreaterEqual(self.db.stat().st_mtime_ns, self.manifest.stat().st_mtime_ns)
        with closing(sqlite3.connect(f"file:{self.db}?mode=ro", uri=True)) as con:
            self.assertEqual(con.execute("select count(*) from fts where fts match 'kettle'").fetchone()[0], 1)
            self.assertEqual(con.execute("pragma integrity_check").fetchone()[0], "ok")
        self.assertTrue((self.corpus / "stream/months.json").exists())
        self.assertIn("kettle at the harbour", (self.corpus / "stream/2026-01.jsonl").read_text())

    def test_fresh_with_exactly_enough_room_clears_the_note(self):
        self.index(free=0, fresh=True, rebuilt=False)
        self.index(free=self.need(fresh=True), fresh=True)
        self.assertNotIn("index", json.loads(self.manifest.read_text()))
        self.assertFalse(self.tmp.exists())
        self.assertGreaterEqual(self.db.stat().st_mtime_ns, self.manifest.stat().st_mtime_ns)

    @staticmethod
    def failing_insert(error):
        return f"""
            class FullConnection(sqlite3.Connection):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    opened.append(self)
                def executemany(self, sql, rows):
                    result = super().executemany(sql, rows)
                    if sql.startswith('insert into incoming'):
                        raise {error}
                    return result
            real_connect = sqlite3.connect
            def connect(*args, **kwargs):
                return real_connect(*args, **kwargs, factory=FullConnection)
            patches.enter_context(patch('build_index.sqlite3.connect', side_effect=connect))
        """

    def test_sqlite_filling_during_insert_preserves_the_old_index_in_both_build_paths(self):
        for fresh in (False, True):
            with self.subTest(fresh=fresh):
                result = self.index(fresh=fresh, rebuilt=False, check_closed=True,
                                    setup=self.failing_insert("sqlite3.OperationalError('database or disk is full')"))
                self.assert_not_rebuilt(result, 10_000_000_000, self.need(fresh=fresh))

    def test_sqlite_full_error_code_is_recognized_without_the_message(self):
        setup = """
            error = sqlite3.OperationalError('storage exhausted')
            error.sqlite_errorcode = sqlite3.SQLITE_FULL
        """ + self.failing_insert("error")
        result = self.index(rebuilt=False, check_closed=True, setup=setup)
        self.assert_not_rebuilt(result, 10_000_000_000, self.need())

    def test_os_enospc_during_insert_is_recognized(self):
        result = self.index(rebuilt=False, check_closed=True,
                            setup=self.failing_insert("OSError(errno.ENOSPC, 'No space left on device')"))
        self.assert_not_rebuilt(result, 10_000_000_000, self.need())

    def test_a_plain_copy_that_fills_the_disk_is_removed(self):
        result = self.index(rebuilt=False, setup="""
            def copy(src, dst):
                dst.write_bytes(b'a partial copy')
                raise OSError(errno.ENOSPC, 'No space left on device')
            patches.enter_context(patch('build_index.ctypes.CDLL', side_effect=AttributeError('no clonefile')))
            patches.enter_context(patch('build_index.shutil.copyfile', side_effect=copy))
        """)
        self.assert_not_rebuilt(result, 10_000_000_000, self.need())

    def test_non_space_errors_still_fail_without_replacing_the_index(self):
        for error in ("sqlite3.OperationalError('no such table: missing')", "OSError(errno.EIO, 'I/O error')"):
            with self.subTest(error=error):
                result = self.index(rebuilt=False, ok=False, setup=self.failing_insert(error))
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("not rebuilt", result.stdout)
                self.assertEqual(self.db.read_bytes(), self.before)
                self.assertFalse(self.tmp.exists())
                self.assertNotIn("index", json.loads(self.manifest.read_text()))

    def test_failed_retries_keep_the_manifest_stale_without_changing_its_retry_stamp(self):
        self.index(free=0, rebuilt=False)
        self.assertGreater(self.manifest.stat().st_mtime_ns, self.db.stat().st_mtime_ns)
        self.assertEqual(self.manifest.stat().st_mtime_ns, self.manifest_stamp)
        self.index(free=1, rebuilt=False)
        self.assertEqual(self.manifest.stat().st_mtime_ns, self.manifest_stamp,
                         "maybeReindex() remembers this stamp, so changing it would queue another retry")

    def test_a_failed_manual_rebuild_makes_a_current_index_stale_only_once(self):
        os.utime(self.manifest, ns=(self.db_stamp - 10_000_000, self.db_stamp - 10_000_000))
        self.index(free=0, fresh=True, rebuilt=False)
        stamp = self.manifest.stat().st_mtime_ns
        self.assertGreater(stamp, self.db_stamp)
        self.index(free=1, fresh=True, rebuilt=False)
        self.assertEqual(self.manifest.stat().st_mtime_ns, stamp)


if __name__ == "__main__":
    unittest.main()
