"""Tests for desktop/py/ask_tools.py, the Ask assistant's tools. They run the tools as the app does (a subprocess
with HOME and CORPUS_DIR pointed at a sandbox) over a small made-up corpus (make_fixtures.ask_corpus)."""

import base64
import json
import os
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
        lines = [json.dumps({"id": 1, "name": "sql", "args": {"query": "select 1 + 1"}}), json.dumps({"id": 2, "name": "nope", "args": {}})]
        out = [json.loads(x) for x in self.run_tools("serve", stdin="\n".join(lines) + "\n").splitlines()]
        self.assertEqual([o["id"] for o in out], [1, 2])
        self.assertIn("2", out[0]["text"])
        self.assertTrue(out[1]["error"])

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
