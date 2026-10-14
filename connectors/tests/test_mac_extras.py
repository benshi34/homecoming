"""Terminal history, Podcasts, code editors and Cursor / VS Code chat, on a synthetic home folder.

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
APPLE = 978307200  # 2001-01-01 in Unix seconds


def run(home, corpus, module):
    env = {**os.environ, "HOME": str(home), "CORPUS_DIR": str(corpus)}
    r = subprocess.run([sys.executable, "-c", f"import {module}; {module}.main()"], cwd=CONNECTORS, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def records(corpus, source):
    f = corpus / "normalized" / f"{source}.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()


class ShellHistoryTests(Base):
    def test_zsh_bash_fish(self):
        # zsh: extended lines, a multi-line command, a secret, a metafied é (0x83 then byte ^ 0x20), and Terminal's
        # per-window file repeating a command from ~/.zsh_history.
        zsh = (b": 1700000000:0;git status\n"
               b": 1700000060:3;for f in *.txt; do\\\ncat $f\\\ndone\n"
               b": 1700000120:0;export OPENAI_API_KEY=sk-abcdefghijklmnopqrstu\n"
               b": 1700000180:0;echo caf" + bytes([0x83, 0xc3 ^ 0x20, 0x83, 0xa9 ^ 0x20]) + b"\n"
               b"ls\nls\n")
        (self.home / ".zsh_history").write_bytes(zsh)
        (self.home / ".zsh_sessions").mkdir()
        (self.home / ".zsh_sessions/ABC.history").write_bytes(b": 1700000000:0;git status\nls\n")
        (self.home / ".bash_history").write_text("#1600000000\ncd ~/src\nmake\n")
        (self.home / ".local/share/fish").mkdir(parents=True)
        (self.home / ".local/share/fish/fish_history").write_text("- cmd: brew update\n  when: 1650000000\n")
        run(self.home, self.corpus, "shell_history")
        rs = records(self.corpus, "shell_history")
        texts = [r["text"] for r in rs]
        self.assertEqual(texts.count("git status"), 1, "a per-window copy is the same record")
        self.assertEqual(texts.count("ls"), 2, "the same untimed command twice is two records")
        self.assertIn("for f in *.txt; do\ncat $f\ndone", texts)
        self.assertIn("export OPENAI_API_KEY=[redacted]", texts)
        self.assertFalse(any("sk-abc" in t for t in texts))
        self.assertIn("echo café", texts)
        by = {r["text"]: r for r in rs}
        self.assertEqual(by["git status"]["ts"], "2023-11-14T22:13:20Z")
        self.assertIsNone(by["make"].get("ts"))
        self.assertEqual(by["cd ~/src"]["ts"], "2020-09-13T12:26:40Z")
        self.assertEqual(by["brew update"]["meta"]["shell"], "fish")
        # A second run after zsh trimmed its file keeps what it dropped and adds nothing twice.
        (self.home / ".zsh_history").write_bytes(b": 1700000240:0;whoami\n")
        run(self.home, self.corpus, "shell_history")
        again = [r["text"] for r in records(self.corpus, "shell_history")]
        self.assertEqual(len(again), len(texts) + 1)


class PodcastsTests(Base):
    def test_follows_and_plays(self):
        db = self.home / "Library/Group Containers/243LU875E5.groups.com.apple.podcasts/Documents/MTLibrary.sqlite"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.execute("create table ZMTPODCAST (Z_PK integer primary key, ZUUID text, ZTITLE text, ZAUTHOR text, "
                    "ZSUBSCRIBED integer, ZADDEDDATE real, ZWEBPAGEURL text, ZFEEDURL text)")
        con.execute("create table ZMTEPISODE (Z_PK integer primary key, ZUUID text, ZTITLE text, ZPODCAST integer, "
                    "ZLASTDATEPLAYED real, ZPLAYCOUNT integer, ZPLAYHEAD real, ZDURATION real, ZPUBDATE real, "
                    "ZWEBPAGEURL text, ZHASBEENPLAYED integer)")
        con.execute("insert into ZMTPODCAST values (1, 'p1', 'Engines Weekly', 'Ada', 1, 700000000, null, 'https://feed.example/e')")
        con.execute("insert into ZMTPODCAST values (2, 'p2', 'Unfollowed Show', 'Bob', 0, null, null, null)")
        con.executemany("insert into ZMTEPISODE values (?,?,?,?,?,?,?,?,?,?,?)", [
            (1, 'e1', 'Gears', 1, 780000000, 2, 1500, 1800, 770000000, None, 1),
            (2, 'e2', 'Not played', 1, None, 0, 0, 1800, 770000000, None, 0),
            (3, 'e3', 'Marked played', 2, None, 0, 0, 900, None, None, 1)])
        con.commit()
        con.close()
        run(self.home, self.corpus, "podcasts")
        rs = records(self.corpus, "podcasts")
        self.assertEqual(sorted(r["kind"] for r in rs), ["listen", "listen", "subscription"])
        gears = next(r for r in rs if r.get("title") == "Gears")
        self.assertEqual(gears["thread_name"], "Engines Weekly")
        self.assertEqual(gears["meta"]["seconds_in"], 1500)
        self.assertTrue(gears["ts"].startswith("2025-09-19"))


class EditorTests(Base):
    def test_history_cursor_and_vscode_chat(self):
        code = self.home / "Library/Application Support/Code/User"
        (code / "History/abc").mkdir(parents=True)
        (code / "History/abc/entries.json").write_text(json.dumps({
            "version": 1, "resource": "file:///Users/ada/engine/gear%20box.py",
            "entries": [{"id": "x1.py", "timestamp": 1700000000000}, {"id": "x2.py", "timestamp": 1700000500000, "source": "Undo"}]}))
        # VS Code's chat change log: the session, then a request appended, then its response set.
        chat = code / "workspaceStorage/w1/chatSessions"
        chat.mkdir(parents=True)
        ops = [{"kind": 0, "v": {"version": 3, "sessionId": "s1", "creationDate": 1700000000000, "responderUsername": "GitHub Copilot", "requests": []}},
               {"kind": 2, "k": ["requests"], "v": [{"requestId": "r1", "timestamp": 1700000100000, "message": {"text": "Why does the gear slip?"}, "response": []}]},
               {"kind": 1, "k": ["requests", 0, "response"], "v": [{"kind": "markdownContent", "content": {"value": "The teeth are worn."}}]}]
        (chat / "s1.jsonl").write_text("\n".join(json.dumps(o) for o in ops))
        cursor = self.home / "Library/Application Support/Cursor/User/globalStorage"
        cursor.mkdir(parents=True)
        con = sqlite3.connect(cursor / "state.vscdb")
        con.execute("create table cursorDiskKV (key text unique on conflict replace, value blob)")
        con.executemany("insert into cursorDiskKV values (?, ?)", [
            ("composerData:c1", json.dumps({"composerId": "c1", "name": "Fix the gear", "createdAt": 1700000000000,
                                            "fullConversationHeadersOnly": [{"bubbleId": "b1", "type": 1}, {"bubbleId": "b2", "type": 2}]})),
            ("bubbleId:c1:b1", json.dumps({"type": 1, "text": "Make the gear stronger"})),
            ("bubbleId:c1:b2", json.dumps({"type": 2, "text": "Use steel."})),
            ("composerData:c2", json.dumps({"composerId": "c2", "conversation": [{"type": 1, "bubbleId": "o1", "text": "Old format question"}]})),
            ("composerData:empty", json.dumps({"composerId": "empty", "fullConversationHeadersOnly": []})),
            ("composerData:broken", None)])
        con.commit()
        con.close()
        run(self.home, self.corpus, "editor_history")
        run(self.home, self.corpus, "ai_coding")
        edits = records(self.corpus, "editor_history")
        self.assertEqual(len(edits), 2)
        self.assertEqual(edits[0]["meta"]["path"], "/Users/ada/engine/gear box.py")
        self.assertEqual(edits[0]["title"], "gear box.py")
        turns = {(r["meta"]["tool"], r["author"], r["text"]) for r in records(self.corpus, "ai_coding")}
        self.assertEqual(turns, {("cursor", "me", "Make the gear stronger"), ("cursor", "cursor", "Use steel."),
                                 ("cursor", "me", "Old format question"), ("vscode", "me", "Why does the gear slip?"),
                                 ("vscode", "GitHub Copilot", "The teeth are worn.")})


if __name__ == "__main__":
    unittest.main()


class ClaudeCodeTests(Base):
    def test_a_forked_session_repeating_a_turned_down_tool_call_is_read_once(self):
        lines = [
            {"type": "assistant", "uuid": "a-1", "sessionId": "s-1", "timestamp": "2026-10-09T10:00:00Z",
             "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]}},
            {"type": "user", "uuid": "u-1", "sessionId": "s-1", "timestamp": "2026-10-09T10:00:05Z",
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                                      "content": "The user doesn't want to proceed with this tool use. the user said: not now"}]}},
        ]
        for name in ("-proj/s-1.jsonl", "-proj-fork/s-2.jsonl"):  # the fork copies the history
            f = self.home / ".claude/projects" / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
        run(self.home, self.corpus, "ai_coding")
        turned_down = [r for r in records(self.corpus, "ai_coding") if r["meta"].get("decision") == "rejected_tool"]
        self.assertEqual([r["text"] for r in turned_down], ["[rejected Bash call] not now"])
