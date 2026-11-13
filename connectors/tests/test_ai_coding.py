"""Codex transcripts (ai_coding.codex) on a synthetic home folder: forked and resumed sessions.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


def run(home, corpus):
    env = {**os.environ, "HOME": str(home), "CORPUS_DIR": str(corpus)}
    r = subprocess.run([sys.executable, "-c", "import ai_coding; ai_coding.main()"], cwd=CONNECTORS, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    f = corpus / "normalized" / "ai_coding.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def meta(sid, ts, forked=None, cwd="/Users/ada/src"):
    p = {"id": sid, "cwd": cwd, "originator": "codex_cli"}
    if forked:
        p["forked_from_id"] = forked
    return {"type": "session_meta", "timestamp": ts, "payload": p}


def msg(role, text, ts):
    return {"type": "response_item", "timestamp": ts, "payload": {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}}


def other(kind, ts):
    return {"type": "event_msg", "timestamp": ts, "payload": {"type": kind}}


class CodexTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.days = self.home / ".codex/sessions/2026/10"
        self.corpus.mkdir(parents=True)

    def rollout(self, day, name, rows):
        d = self.days / day
        d.mkdir(parents=True, exist_ok=True)
        (d / f"rollout-{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_a_fork_reads_only_its_own_messages_and_its_parent_keeps_its_ids(self):
        before = [msg("developer", "rules", "2026-10-15T09:53:56Z"), msg("user", "plan the importer", "2026-10-15T09:54:00Z"),
                  msg("assistant", "looking at the code", "2026-10-15T09:54:30Z"), msg("assistant", "here is a plan", "2026-10-15T09:55:00Z"),
                  msg("user", "now write it", "2026-10-15T10:00:00Z"), msg("assistant", "written", "2026-10-15T10:05:00Z")]
        # After the fork, the parent goes on, and happens to say what the fork says first: still the fork's.
        after = [msg("user", "review the parser", "2026-10-16T04:00:00Z"), msg("assistant", "it reported two bugs", "2026-10-16T04:01:00Z")]
        parent = [meta("P", "2026-10-15T09:53:55Z"), *before, *after]
        # The fork's file: its own session, then its parent's and a copy of the parent's conversation up to the fork
        # (stamped when it forked, and without the in-between "looking at the code"), a settings event, its own turn.
        fork_at = "2026-10-16T03:12:20Z"
        copy = [r for r in before if r["payload"]["content"][0]["text"] != "looking at the code"]
        fork = [meta("F", fork_at, forked="P", cwd="/Users/ada/src/sub"), meta("P", fork_at),
                *[{**r, "timestamp": fork_at} for r in copy], other("thread_settings_applied", fork_at),
                msg("user", "review the parser", "2026-10-16T03:12:22Z"), msg("assistant", "two bugs found", "2026-10-16T03:17:13Z")]
        # Named so it sorts before its parent: the parent is still read first.
        self.rollout("14", "2026-10-14T00-00-00-F", fork)
        self.rollout("15", "2026-10-15T09-53-55-P", parent)
        rs = run(self.home, self.corpus)
        ids = {r["id"]: r for r in rs}
        self.assertEqual(sorted(i for i in ids if i.startswith("codex:P:")), [f"codex:P:{n}" for n in range(1, 8)])
        self.assertEqual(sorted(i for i in ids if i.startswith("codex:F:")), ["codex:F:1", "codex:F:2"])
        self.assertEqual(ids["codex:F:1"]["text"], "review the parser")
        self.assertEqual(ids["codex:F:2"]["thread"], "F")
        self.assertEqual(ids["codex:F:1"]["meta"]["cwd"], "/Users/ada/src/sub", "where the fork itself ran")
        self.assertEqual([r["text"] for r in rs].count("plan the importer"), 1, "the copied conversation is kept once, as the parent's")
        self.assertEqual(ids["codex:P:1"]["ts"][:10], "2026-10-15", "with its own time, not the copy's")

    def test_a_session_resumed_in_another_file_goes_on_from_what_was_read(self):
        self.rollout("14", "2026-10-14T10-00-00-R", [meta("R", "2026-10-14T10:00:00Z"), msg("user", "first", "2026-10-14T10:00:01Z"),
                                                    msg("assistant", "one", "2026-10-14T10:00:02Z")])
        self.rollout("15", "2026-10-15T10-00-00-R", [meta("R", "2026-10-15T10:00:00Z"), msg("user", "first", "2026-10-15T10:00:00Z"),
                                                    msg("assistant", "one", "2026-10-15T10:00:00Z"), msg("user", "second", "2026-10-15T10:00:05Z")])
        rs = run(self.home, self.corpus)
        self.assertEqual(sorted(r["id"] for r in rs), ["codex:R:1", "codex:R:2", "codex:R:3"])
        self.assertEqual({r["id"]: r["text"] for r in rs}["codex:R:3"], "second")

    def test_archived_threads_are_read_too(self):
        arch = self.home / ".codex/archived_sessions"
        arch.mkdir(parents=True)
        (arch / "rollout-2026-09-22T09-44-37-A.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
            meta("A", "2026-09-22T09:44:37Z"), msg("user", "an old thread", "2026-09-22T09:44:40Z")]))
        self.rollout("07", "2026-10-07T15-45-15-S", [meta("S", "2026-10-07T15:45:15Z"), msg("user", "hello", "2026-10-07T15:45:16Z")])
        rs = run(self.home, self.corpus)
        self.assertEqual(sorted(r["id"] for r in rs), ["codex:A:1", "codex:S:1"])

    def test_an_ordinary_session_keeps_the_ids_it_always_had(self):
        self.rollout("07", "2026-10-07T15-45-15-S", [meta("S", "2026-10-07T15:45:15Z"), msg("user", "hello", "2026-10-07T15:45:16Z"),
                                                    msg("user", "<environment_context>noise", "2026-10-07T15:45:17Z"),
                                                    msg("assistant", "hi", "2026-10-07T15:45:18Z")])
        (self.home / ".codex/session_index.jsonl").write_text(json.dumps({"id": "S", "thread_name": "Greetings"}) + "\n")
        rs = run(self.home, self.corpus)
        self.assertEqual([(r["id"], r["text"], r["author"]) for r in rs], [("codex:S:1", "hello", "me"), ("codex:S:2", "hi", "codex")])
        self.assertEqual(rs[0]["thread_name"], "Greetings")


def claude_session(home, slug, sid, cwd, texts):
    d = home / ".claude/projects" / slug
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"type": "user", "uuid": f"{sid}-{i}", "sessionId": sid, "cwd": cwd, "timestamp": f"2026-10-20T10:0{i}:00Z",
             "message": {"role": "user", "content": t}} for i, t in enumerate(texts)]
    (d / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


class LeaveOutTests(unittest.TestCase):
    """$CORPUS_DIR/ai_coding.json's leave_out: sessions run in those folders aren't read, and what an earlier run kept
    of them goes."""
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / "home", Path(t.name) / "corpus"
        self.corpus.mkdir(parents=True)
        h = str(self.home)
        claude_session(self.home, "-Users-ada-src-app", "keep", f"{h}/src/app", ["fix the login bug"])
        claude_session(self.home, "-Users-ada-evals-run-3", "eval", f"{h}/evals/run-3/item", ["HELDOUT-ALPHA"])
        claude_session(self.home, "-private-var-folders-xy-T-tmp1", "tmp", "/private/var/folders/xy/T/tmp1", ["HELDOUT-BETA"])
        days = self.home / ".codex/sessions/2026/10/20"
        days.mkdir(parents=True)
        def rollout(name, rows):
            (days / f"rollout-{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        # A session in a left-out folder, and a fork of it made somewhere else: the fork's copy of it is left out too.
        rollout("a", [meta("E", "2026-10-20T09:00:00Z", cwd=f"{h}/evals/run-4"),
                      msg("user", "HELDOUT-GAMMA", "2026-10-20T09:00:01Z")])
        rollout("b", [meta("F", "2026-10-20T09:10:00Z", forked="E", cwd=f"{h}/src/app"),
                      meta("E", "2026-10-20T09:00:00Z", cwd=f"{h}/evals/run-4"),
                      msg("user", "HELDOUT-GAMMA", "2026-10-20T09:00:01Z"),
                      msg("user", "now the real question", "2026-10-20T09:10:01Z")])

    def configure(self, leave_out):
        (self.corpus / "ai_coding.json").write_text(json.dumps({"leave_out": leave_out}))

    def test_sessions_in_left_out_folders_are_not_read(self):
        self.configure(["~/evals", "/var/folders/xy/*"])
        texts = " ".join(r["text"] for r in run(self.home, self.corpus))
        self.assertIn("fix the login bug", texts)
        self.assertIn("now the real question", texts)
        self.assertNotIn("HELDOUT", texts)

    def test_what_an_earlier_run_kept_goes(self):
        before = " ".join(r["text"] for r in run(self.home, self.corpus))
        self.assertIn("HELDOUT-ALPHA", before)  # nothing set: everything is read
        self.configure(["~/evals/run-*", "/private/var/folders/xy"])
        recs = run(self.home, self.corpus)
        self.assertNotIn("HELDOUT", " ".join(r["text"] for r in recs))
        self.assertIn("fix the login bug", " ".join(r["text"] for r in recs))

    def test_a_folder_only_sharing_a_prefix_stays(self):
        self.configure(["~/src/ap"])
        self.assertIn("fix the login bug", " ".join(r["text"] for r in run(self.home, self.corpus)))


if __name__ == "__main__":
    unittest.main()
