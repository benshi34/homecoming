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


class NoDeveloperToolsTests(Base):
    """On a Mac without the Command Line Tools, /usr/bin/git is a stub that asks to install them: nothing may run it."""

    def env(self, xcode_ok):
        bin_ = Path(self.home.parent, "bin")
        bin_.mkdir(exist_ok=True)
        (bin_ / "git").unlink(missing_ok=True)
        (bin_ / "git").symlink_to("/usr/bin/git")
        xs = bin_ / "xcode-select"
        xs.write_text(f"#!/bin/sh\nexit {0 if xcode_ok else 2}\n")
        xs.chmod(0o755)
        return {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "PATH": str(bin_)}

    def python(self, code, env):
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_the_stub_counts_only_with_the_developer_tools(self):
        found = self.python("import common; print(common.git_bin())", self.env(xcode_ok=True))
        self.assertTrue(found.endswith("/git"))
        if not os.path.exists("/Applications/GitHub Desktop.app"):
            self.assertEqual(self.python("import common; print(common.git_bin())", self.env(xcode_ok=False)), "None")

    @unittest.skipIf(os.path.exists("/Applications/GitHub Desktop.app"), "GitHub Desktop's own git would be used")
    def test_commits_and_the_manifest_without_git(self):
        repo = self.home / "Developer/app"
        (repo / ".git").mkdir(parents=True)
        self.python("import git_commits; git_commits.main()", self.env(xcode_ok=False))
        self.assertEqual(records(self.corpus, "git_commits"), [])
        manifest = json.loads((self.corpus / "manifest.json").read_text())["git_commits"]
        self.assertEqual(manifest["notes"], {"no_git": 1})


class BrowserTests(Base):
    """Every browser's history, not just Safari and Chrome; and the ones turned off in Your Setup aren't read."""

    def chromium(self, folder, url, term=None):
        db = self.home / "Library/Application Support" / folder / "Default/History"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.executescript("""create table urls (id integer primary key, url text, title text, visit_count int);
            create table visits (id integer primary key, url int, visit_time int, transition int, visit_duration int);
            create table keyword_search_terms (url_id int, term text);""")
        con.execute("insert into urls values (1, ?, 'A page', 3)", (url,))
        con.execute("insert into visits values (7, 1, 13370000000000000, 1, 5000000)")
        if term:
            con.execute("insert into keyword_search_terms values (1, ?)", (term,))
        con.commit()
        con.close()

    def firefox(self, url):
        db = self.home / "Library/Application Support/Firefox/Profiles/ab12.default-release/places.sqlite"
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.executescript("""create table moz_places (id integer primary key, url text, title text, visit_count int);
            create table moz_historyvisits (id integer primary key, place_id int, visit_date int, visit_type int);""")
        con.execute("insert into moz_places values (1, ?, 'Fox page', 2)", (url,))
        con.execute("insert into moz_places values (2, 'https://ads.example/frame', 'frame', 1)")
        con.execute("insert into moz_historyvisits values (1, 1, 1700000000000000, 1)")
        con.execute("insert into moz_historyvisits values (2, 2, 1700000000000000, 4)")  # an embedded frame
        con.commit()
        con.close()

    def run_with(self, skip=""):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_BROWSERS_SKIP": skip}
        r = subprocess.run([sys.executable, "-c", "import browser_history; browser_history.main()"], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {r["id"]: r for r in records(self.corpus, "browser_history")}

    def test_arc_brave_and_firefox(self):
        self.chromium("Arc/User Data", "https://example.com/arc")
        self.chromium("BraveSoftware/Brave-Browser", "https://tides.example/harbour", term="tide tables")
        self.firefox("https://www.google.co.uk/search?q=kettle+descaling")
        recs = self.run_with()
        self.assertEqual(recs["arc:Default:7"]["url"], "https://example.com/arc")
        self.assertEqual(recs["arc:Default:7"]["thread_name"], "Arc (Default)")
        self.assertEqual(recs["brave:Default:7:q"]["title"], "tide tables")
        fox = [r for r in recs.values() if r["id"].startswith("firefox:")]
        self.assertEqual(len(fox), 1, "the embedded frame isn't a page you went to")
        self.assertEqual(fox[0]["thread_name"], "Firefox (default-release)")
        self.assertEqual(fox[0]["ts"][:10], "2023-11-14")
        self.assertEqual((fox[0]["kind"], fox[0]["title"]), ("search", "kettle descaling"), "Google in the UK is a search too")

    def test_a_browser_turned_off_isnt_read(self):
        self.chromium("Arc/User Data", "https://example.com/arc")
        self.firefox("https://example.com/fox")
        recs = self.run_with(skip="arc")
        self.assertFalse(any(k.startswith("arc:") for k in recs))
        self.assertTrue(any(k.startswith("firefox:") for k in recs))
        manifest = json.loads((self.corpus / "manifest.json").read_text())["browser_history"]
        self.assertEqual(manifest["notes"]["not_read"], ["arc"])

    def test_found_needs_the_app_or_history(self):
        # Claude Code writes into every Chromium browser's folder: a folder alone isn't a browser.
        (self.home / "Library/Application Support/Vivaldi/NativeMessagingHosts").mkdir(parents=True)
        self.chromium("Arc/User Data", "https://example.com/arc")
        (self.home / "Applications/Brave Browser.app").mkdir(parents=True)
        env = {**os.environ, "HOME": str(self.home), "UMP_BROWSERS_SKIP": "arc"}
        out = subprocess.run([sys.executable, "-c", "import browsers, json; print(json.dumps(browsers.found()))"], cwd=CONNECTORS,
                             env=env, capture_output=True, text=True, timeout=60)
        found = {b["id"]: b for b in json.loads(out.stdout)}
        self.assertNotIn("vivaldi", found)
        self.assertEqual((found["arc"]["history"], found["arc"]["read"], found["arc"]["claude"]), (True, False, False), "no Arc app here")
        self.assertEqual((found["brave"]["history"], found["brave"]["claude"]), (False, True))


class ICloudOnlyTests(Base):
    """With Optimize Mac Storage, a file only in iCloud keeps its name; opening it would download it. Documents lists
    it without reading it (one read before keeps its text), and Git commits leaves a repository like that alone."""

    def run_patched(self, module, cloud):
        code = (f"import common, pathlib; common.cloud_only = lambda p: any(x in {cloud!r} for x in pathlib.Path(p).parts); "
                f"import {module}; {module}.main()")
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_documents(self):
        docs = self.home / "Documents"
        docs.mkdir()
        (docs / "here.md").write_text("Notes kept on this Mac")
        (docs / "away.md").write_text("Only in iCloud")
        (docs / "away.md").chmod(0)  # opening it would fail: proof it isn't opened
        (docs / "read_before.md").write_text("Now only in iCloud")
        (self.corpus / "normalized").mkdir()
        old = {"id": str(docs / "read_before.md"), "source": "documents", "kind": "document", "ts": "2025-01-01T00:00:00Z",
               "title": "read_before.md", "text": "What it said when it was on this Mac"}
        (self.corpus / "normalized/documents.jsonl").write_text(json.dumps(old) + "\n")
        try:
            self.run_patched("documents", ("away.md", "read_before.md"))
        finally:
            (docs / "away.md").chmod(0o644)
        recs = {Path(r["id"]).name: r for r in records(self.corpus, "documents")}
        self.assertEqual(recs["here.md"]["text"], "Notes kept on this Mac")
        self.assertEqual(recs["away.md"]["text"], "away.md (in iCloud, not downloaded)")
        self.assertEqual(recs["away.md"]["meta"]["downloaded"], False)
        self.assertNotIn("error", recs["away.md"]["meta"])
        self.assertEqual(recs["read_before.md"]["text"], "What it said when it was on this Mac")
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["documents"]["notes"], {"in_icloud_only": 2})

    def test_git_history_only_in_icloud(self):
        env = {**os.environ, "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com",
               "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada@example.com"}
        for name in ("here", "away", "branchy"):
            repo = self.home / "Developer" / name
            repo.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
            (repo / "a.txt").write_text(name)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
            subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-q", "-m", f"Start {name}"], check=True, env=env)
        subprocess.run(["git", "-C", str(self.home / "Developer/branchy"), "branch", "side-branch"], check=True, env=env)
        # All of "away" is in iCloud; of "branchy", one branch's file is (HEAD and the rest are here).
        self.run_patched("git_commits", ("away", "side-branch"))
        self.assertEqual([r["title"] for r in records(self.corpus, "git_commits")], ["Start here"])
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["git_commits"]["notes"], {"in_icloud_only": 2})
