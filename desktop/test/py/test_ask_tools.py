"""Tests for desktop/py/ask_tools.py, the Ask assistant's tools. They run the tools as the app does (a subprocess
with HOME and CORPUS_DIR pointed at a sandbox) over a small made-up corpus (make_fixtures.ask_corpus)."""

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[2]
REPO = DESKTOP.parent
TOOLS = DESKTOP / "py" / "ask_tools.py"
sys.path.insert(0, str(DESKTOP / "test" / "fixtures"))
import make_fixtures  # noqa: E402


class AskTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        cls.home = root / "home"
        cls.home.mkdir()
        (cls.home / "secret.txt").write_text("not for the model")
        cls.corpus = Path(make_fixtures.ask_corpus(root / "corpus"))
        cls.env = {k: v for k, v in os.environ.items() if k not in ("CORPUS_DIR", "ASK_ME_REDACT")}
        cls.env.update(HOME=str(cls.home), CORPUS_DIR=str(cls.corpus), UMP_REPO=str(REPO), PYTHONDONTWRITEBYTECODE="1")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_tools(self, *args, stdin=""):
        p = subprocess.run([sys.executable, str(TOOLS), *args], input=stdin, capture_output=True, text=True, env=self.env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        return p.stdout

    def call(self, name, **args):
        return json.loads(self.run_tools("call", name, stdin=json.dumps(args)))

    def rowid(self, source, title=None):
        r = self.call("sql", query=f"select rowid from records where source = '{source}'" + (f" and title = '{title}'" if title else "") + " limit 1")
        return int(r["text"].splitlines()[1])

    # ------------------------------------------------------------ the tools

    def test_tool_list(self):
        names = [t["name"] for t in json.loads(self.run_tools("tools"))]
        self.assertEqual(names, ["sql", "search", "python", "read_file", "view_image"])

    def test_sql_with_helpers(self):
        r = self.call("sql", query="select source, count(*) n from records group by source order by source")
        self.assertFalse(r["error"])
        self.assertIn("calendar\t2", r["text"])
        self.assertIn("imessage\t3", r["text"])
        r = self.call("sql", query="select local_time('2026-03-02T18:04:00Z', 'America/Los_Angeles') t, "
                                   "(select count(*) from records where text regexp 'din+er') d, "
                                   "(select median(length(text)) from records where source = 'imessage') m")
        self.assertIn("2026-03-02T10:04:00-08:00", r["text"])
        self.assertEqual(r["text"].splitlines()[1].split("\t")[1], "2")  # the chat and the photo's labels

    def test_sql_is_read_only(self):
        for q in ("delete from records", "insert into records (source) values ('x')", f"attach database '{self.corpus}/x.db' as x"):
            r = self.call("sql", query=q)
            self.assertTrue(r["error"], q)
        self.assertIn("7", self.call("sql", query="select count(*) from records")["text"])

    def test_sql_whatever_a_model_writes(self):
        """Nothing a model writes reaches outside the index or writes anything; a query that would run forever is
        stopped; an answer is never bigger than one result holds; and each says what went wrong in words."""
        stolen = self.corpus.parent / "stolen.db"
        for q in (f"vacuum into '{stolen}'", f"attach '{stolen}' as x", "select load_extension('/tmp/x')", "create temp table t(x)",
                  "select 1; delete from records", "select 'a\x00b'", "pragma query_only = off; delete from records"):
            r = self.call("sql", query=q)
            self.assertTrue(r["error"], q)
            self.assertNotIn("Traceback", r["text"])
        self.assertFalse(stolen.exists(), "no copy of the library written anywhere")
        self.assertIn("7", self.call("sql", query="select count(*) from records")["text"])
        for bad in ({}, {"query": ""}, {"query": None}, {"query": "select " + "1+" * 60_000 + "1"}):
            r = self.call("sql", **bad)
            self.assertTrue(r["error"])
            self.assertRegex(r["text"], r"^(Give query|That query is)")
        wide = self.call("sql", query="select r.text, r.text, r.text from records r, records, records, records", width=20000, limit=2000)
        self.assertLess(len(wide["text"]), 21_000)
        self.assertIn("stopped at", wide["text"])
        # Forever, stopped (after a second here; SECONDS in the app), in words.
        p = subprocess.run([sys.executable, "-c", "import json, ask_tools as t; t.SECONDS = 1; print(json.dumps(t.call('sql', {'query': "
                            "'with recursive c(x) as (select 1 union all select x + 1 from c) select count(*) from c'})))"],
                           capture_output=True, text=True, env=self.env, cwd=TOOLS.parent, timeout=60)
        r = json.loads(p.stdout)
        self.assertTrue(r["error"])
        self.assertTrue(r["text"].startswith("Stopped after 1 second:"), r["text"])
        self.assertLess(r["seconds"], 10)

    def test_search_answers_odd_input_in_words(self):
        """Search syntax a model gets wrong, filters that can't match, and arguments of the wrong shape: each comes back
        as a plain message (never a traceback, never "no matches" when the reason is something else)."""
        for q in ('"unbalanced', "*", "a OR", "NEAR(", "nosuch:column", "'; drop table records; --", "AND"):
            r = self.call("search", query=q)
            self.assertTrue(r["error"], q)
            self.assertTrue(r["text"].startswith("Search error:"), r["text"])
        self.assertIn("isn't a date or time", self.call("search", query="dinner", after="last week")["text"])
        self.assertIn("isn't a date or time", self.call("search", query="dinner", before="2026-3-1")["text"])
        self.assertIn("isn't before", self.call("search", query="dinner", after="2026-04-01", before="2026-01-01")["text"])
        self.assertIn("Dinner with Grace", self.call("search", query="dinner", after="2026-03-06T20:00:00+01:00")["text"], "an offset, as UTC")
        nosuch = self.call("search", query="dinner", source="nosuchapp")["text"]
        self.assertIn("there's no source nosuchapp", nosuch)
        self.assertIn("calendar, documents, imessage, photos", nosuch)
        self.assertIn("there's no kind", self.call("search", kind="nosuch")["text"])
        self.assertIn("calendar", self.call("search", query="dinner", me="false")["text"], "\"false\" isn't yes")
        self.assertIn("sort is rank", self.call("search", query="dinner", sort="best")["text"])
        self.assertIn("as text", self.call("search", query=["dinner"])["text"])
        for name, args in (("search", [1, 2]), ("sql", "select 1"), ("read_file", {"rowid": 10 ** 30}), ("read_file", {}), ("view_image", {"rowid": "x"})):
            r = json.loads(self.run_tools("call", name, stdin=json.dumps(args)))
            self.assertTrue(r["error"], (name, args))
            self.assertRegex(r["text"], r"JSON object|No record|Give rowid")

    def test_an_empty_library(self):
        """What a model sees when nothing has been read yet: lookups that say so, and nothing to list."""
        with tempfile.TemporaryDirectory() as t:
            corpus = Path(make_fixtures.edge_corpus(Path(t) / "corpus", "empty"))
            env = {**self.env, "CORPUS_DIR": str(corpus)}
            run = lambda *a, stdin="": subprocess.run([sys.executable, str(TOOLS), *a], input=stdin, capture_output=True, text=True, env=env, timeout=60).stdout  # noqa: E731
            r = json.loads(run("call", "search", stdin='{"query": "dinner"}'))
            self.assertIn("the library is empty", r["text"])
            self.assertIn("the library is empty", json.loads(run("call", "search", stdin="{}"))["text"])
            self.assertIn("0", json.loads(run("call", "sql", stdin='{"query": "select count(*) from records"}'))["text"])
            self.assertEqual(json.loads(run("inventory")), [])

    def test_inventory_dates_are_ones_that_can_be_right(self):
        with tempfile.TemporaryDirectory() as t:
            corpus = Path(make_fixtures.edge_corpus(Path(t) / "corpus", "messy"))
            inv = {r["source"]: r for r in json.loads(subprocess.run([sys.executable, str(TOOLS), "inventory"], capture_output=True, text=True,
                                                                      env={**self.env, "CORPUS_DIR": str(corpus)}, timeout=60).stdout)}
            self.assertEqual((inv["imessage"]["first"], inv["git_commits"]["first"]), ("1990-01-15", "1990-01-15"), "not 1970, nor 1985")
            self.assertLess(inv["imessage"]["last"], "2100", "not 2099, nor 9999")

    def test_search_filters_context_and_secrets(self):
        r = self.call("search", query="dinner")
        self.assertFalse(r["error"])
        self.assertRegex(r["text"], r"#\d+")
        self.assertIn("calendar", r["text"])
        only = self.call("search", query="dinner", source="imess")["text"]
        self.assertNotIn("calendar/", only)
        self.assertIn("imessage", only)
        ctx = self.call("search", query="Tasca", context=2)["text"]
        self.assertIn("booked a table", ctx)
        wifi = self.call("search", query="wifi")["text"]
        self.assertNotIn("hunter2", wifi)
        self.assertIn("[redacted password]", wifi)

    def test_python_reads_records_but_nothing_else(self):
        r = self.call("python", code="print(len(sql('select * from records')), sum(1 for _ in records('calendar')))")
        self.assertEqual(r["text"].strip(), "7 2", r["text"])
        home = self.call("python", code=f"print(open({str(self.home / 'secret.txt')!r}).read())")
        self.assertTrue(home["error"])
        self.assertNotIn("not for the model", home["text"])
        net = self.call("python", code="import socket; socket.create_connection(('1.1.1.1', 80), timeout=3); print('connected')")
        self.assertTrue(net["error"])
        self.assertNotIn("connected", net["text"])
        write = self.call("python", code=f"open({str(self.corpus / 'normalized' / 'x.jsonl')!r}, 'w').write('x')")
        self.assertTrue(write["error"])
        self.assertFalse((self.corpus / "normalized" / "x.jsonl").exists())
        printed = self.call("python", code="print([r['text'] for r in records('imessage')][-1])")
        self.assertNotIn("hunter2", printed["text"])

    def test_python_reads_the_event_stream(self):
        # build_index (run by the fixture) writes corpus/stream/; the sandbox lets stream() read it.
        r = self.call("python", code="e = stream('2026-03'); print(len(e), sorted({x['kind'] for x in e})); print(stream('1999-01'))")
        self.assertFalse(r["error"], r["text"])
        self.assertIn("['calendar', 'conversation', 'photos']", r["text"])
        self.assertIn("[]", r["text"])

    def test_read_file_pages_and_blanks_secrets(self):
        doc = self.rowid("documents")
        r = self.call("read_file", rowid=doc, length=200)
        self.assertFalse(r["error"])
        self.assertIn("Packing list for Lisbon", r["text"])
        rest = self.call("read_file", rowid=doc, offset=1500)["text"]
        self.assertIn("The end.", rest)
        self.assertNotIn("FAKEFAKE", rest)
        self.assertIn("redacted", rest)
        self.assertTrue(self.call("read_file", rowid=self.rowid("calendar"))["error"])  # points to no file
        self.assertTrue(self.call("read_file", rowid=999999)["error"])

    def test_iphone_files_through_the_library_link(self):
        """The decrypted mirror lives outside the corpus, linked at raw/iphone; its referenced attachments are readable,
        but traversal and links from that mirror to other files still aren't."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            corpus = Path(make_fixtures.ask_corpus(root / "corpus"))
            home = root / "home"
            home.mkdir()
            mirror = home / "Library/Application Support/q1_user_model/iphone"
            files = mirror / "files/MediaDomain/Library/SMS/Attachments"
            files.mkdir(parents=True)
            (files / "note.txt").write_text("A note attached to a phone message")
            shutil.copy2(corpus / "files/IMG_0001.png", files / "picture.png")
            (home / "secret.txt").write_text("not an attachment")
            (files / "outside.txt").symlink_to(home / "secret.txt")
            (corpus / "raw").mkdir()
            (corpus / "raw/iphone").symlink_to(mirror, target_is_directory=True)
            env = {**self.env, "HOME": str(home), "CORPUS_DIR": str(corpus)}

            def read_attachment(name, source, path):
                with sqlite3.connect(corpus / "corpus.db") as con:
                    rowid = con.execute("select rowid from records where source = ? limit 1", (source,)).fetchone()[0]
                    con.execute("update records set meta = ? where rowid = ?", (json.dumps({"files": [path]}), rowid))
                r = subprocess.run([sys.executable, str(TOOLS), "call", name], input=json.dumps({"rowid": rowid}),
                                   capture_output=True, text=True, env=env, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                return json.loads(r.stdout)

            prefix = "raw/iphone/files/MediaDomain/Library/SMS/Attachments/"
            for base in ("", "corpus/"):
                text = read_attachment("read_file", "documents", base + prefix + "note.txt")
                self.assertFalse(text["error"], text["text"])
                self.assertIn("A note attached to a phone message", text["text"])
            picture = read_attachment("view_image", "photos", "corpus/" + prefix + "picture.png")
            self.assertFalse(picture["error"], picture["text"])
            self.assertEqual(len(picture["images"]), 1)
            for path in ("../home/secret.txt", prefix + "outside.txt"):
                denied = read_attachment("read_file", "documents", path)
                self.assertTrue(denied["error"], path)
                self.assertIn("outside the library", denied["text"])
                self.assertNotIn("not an attachment", denied["text"])

    def test_view_image_sends_the_picture(self):
        photo = self.rowid("photos")
        r = self.call("view_image", rowid=photo)
        self.assertFalse(r["error"], r["text"])
        self.assertEqual(len(r["images"]), 1)
        self.assertEqual(r["images"][0]["media_type"], "image/jpeg")
        self.assertTrue(base64.b64decode(r["images"][0]["data"]).startswith(b"\xff\xd8"))
        self.assertTrue(self.call("view_image", rowid=photo, file=3)["error"])
        self.assertTrue(self.call("view_image", rowid=self.rowid("documents"))["error"])

    def test_record_and_inventory(self):
        rec = json.loads(self.run_tools("record", str(self.rowid("imessage"))))
        self.assertEqual(rec["source"], "imessage")
        inv = {r["source"]: r for r in json.loads(self.run_tools("inventory"))}
        self.assertEqual(inv["imessage"]["count"], 3)
        self.assertEqual(inv["calendar"]["first"], "2026-03-06")

    # ------------------------------------------------------------ how the app and the agents reach them

    def test_serve_answers_line_by_line(self):
        lines = [json.dumps({"id": 1, "name": "sql", "args": {"query": "select 1 + 1"}}), json.dumps({"id": 2, "name": "nope", "args": {}}),
                 "not json", "[1, 2]", json.dumps({"id": 3, "name": "sql", "args": "select 1"}), json.dumps({"id": 4, "name": "sql", "args": {"query": "select 4"}})]
        out = [json.loads(x) for x in self.run_tools("serve", stdin="\n".join(lines) + "\n").splitlines()]
        self.assertEqual([o["id"] for o in out], [1, 2, 3, 4], "a line that isn't a call is passed over; the tools carry on")
        self.assertIn("2", out[0]["text"])
        self.assertTrue(out[1]["error"])
        self.assertTrue(out[2]["error"])
        self.assertIn("4", out[3]["text"])

    def answer_mailbox(self, box, stop):
        """What the app does: run each request in the mailbox and write its answer."""
        sys.path.insert(0, str(TOOLS.parent))
        while not stop.is_set():
            for req in box.glob("*.req"):
                q = json.loads(req.read_text())
                req.unlink()
                r = {"text": f"ran {q['name']} {json.dumps(q['args'])}", "error": False,
                     "images": [{"media_type": "image/jpeg", "data": "AAAA"}] if q["name"] == "view_image" else []}
                if q.get("image_files") and r["images"]:
                    r = {**r, "images": [], "text": r["text"] + " saved as image-1.jpg"}
                tmp = box / (req.stem + ".part")
                tmp.write_text(json.dumps(r))
                tmp.rename(box / (req.stem + ".res"))
            time.sleep(0.01)

    def with_mailbox(self, fn):
        box = Path(tempfile.mkdtemp())
        stop = threading.Event()
        t = threading.Thread(target=self.answer_mailbox, args=(box, stop), daemon=True)
        t.start()
        try:
            return fn(box)
        finally:
            stop.set()
            t.join()

    def test_ask_command_for_codex(self):
        def go(box):
            p = subprocess.run([sys.executable, str(TOOLS), "ask", "--box", str(box), "search"], input='{"query": "dinner"}',
                               capture_output=True, text=True, env=self.env, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('ran search {"query": "dinner"}', p.stdout)
            bad = subprocess.run([sys.executable, str(TOOLS), "ask", "--box", str(box), "sql"], input="select 1",
                                 capture_output=True, text=True, env=self.env, timeout=30)
            self.assertEqual(bad.returncode, 1)
            self.assertIn("aren't JSON", bad.stdout)
            img = subprocess.run([sys.executable, str(TOOLS), "ask", "--box", str(box), "view_image"], input='{"rowid": 1}',
                                 capture_output=True, text=True, env=self.env, timeout=30)
            self.assertIn("saved as", img.stdout)
            # The arguments on the command line, as a model may write it: taken from there.
            inline = subprocess.run([sys.executable, str(TOOLS), "ask", "--box", str(box), "search", '{"query": "lunch"}'],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, env=self.env, timeout=30)
            self.assertIn('ran search {"query": "lunch"}', inline.stdout)
            # None at all, in a terminal (Codex runs commands in one): said at once, not waited for.
            master, slave = os.openpty()
            try:
                tty = subprocess.run([sys.executable, str(TOOLS), "ask", "--box", str(box), "search"], stdin=slave,
                                     capture_output=True, text=True, env=self.env, timeout=30)
            finally:
                os.close(slave)
                os.close(master)
            self.assertEqual(tty.returncode, 1)
            self.assertIn("No arguments. Pass them as a JSON object on stdin", tty.stdout)
            self.assertEqual(list(box.iterdir()), [])  # every request answered and cleaned up
        self.with_mailbox(go)

    def test_mcp_server_for_claude_code(self):
        def go(box):
            msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sql", "arguments": {"query": "select 1"}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "view_image", "arguments": {"rowid": 7}}},
                    {"jsonrpc": "2.0", "id": 5, "method": "bogus"}]
            p = subprocess.run([sys.executable, str(TOOLS), "mcp", "--box", str(box)], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                               capture_output=True, text=True, env=self.env, timeout=30)
            out = {r["id"]: r for r in map(json.loads, p.stdout.splitlines())}
            self.assertEqual(sorted(out), [1, 2, 3, 4, 5])
            self.assertEqual(out[1]["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(len(out[2]["result"]["tools"]), 5)
            self.assertEqual(out[3]["result"]["content"][0]["text"], 'ran sql {"query": "select 1"}')
            self.assertEqual(out[4]["result"]["content"][1], {"type": "image", "data": "AAAA", "mimeType": "image/jpeg"})
            self.assertIn("error", out[5])
        self.with_mailbox(go)


if __name__ == "__main__":
    unittest.main()
