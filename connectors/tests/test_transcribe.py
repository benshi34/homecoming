"""transcribe.py: which audio it hears (only what Apple left without words), what it keeps, what it hears again, and the
readers taking its text. A stand-in for hear.swift (UMP_HEAR) answers from a script and notes what it was asked; the
audio files are made up.

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

# hear.swift's stand-in: one JSON line a path, as it writes them; "music" hears nothing, a missing file can't be read
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ["HEAR_LOG"]
for line in sys.stdin:
    p = line.strip()
    open(log, "a").write(p + "\n")
    if not os.path.exists(p):
        print(json.dumps({"path": p, "error": "can't open it"}))
    else:
        said = open(p).read()
        print(json.dumps({"path": p, "text": "" if said == "music" else said, "locale": "en_US", "confidence": 0.9}))
'''


class TranscribeTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus = self.root / "home", self.root / "corpus"
        (self.corpus / "normalized").mkdir(parents=True)
        self.home.mkdir()
        self.fake = self.root / "hear"
        self.fake.write_text(FAKE)
        self.fake.chmod(0o755)
        self.log = self.root / "heard.log"
        self.audio = self.root / "audio"
        self.audio.mkdir()

    def file(self, name, said):
        p = self.audio / name
        p.write_text(said)
        return str(p)

    def norm(self, source, recs):
        (self.corpus / "normalized" / f"{source}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))

    def run_it(self, on=True):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_HEAR": str(self.fake),
               "HEAR_LOG": str(self.log), "UMP_TRANSCRIBE_LANGS": "en-US"}
        env.pop("UMP_TRANSCRIBE", None)
        if on:
            env["UMP_TRANSCRIBE"] = "1"
        r = subprocess.run([sys.executable, "transcribe.py"], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def asked(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def kept(self):
        return json.loads((self.corpus / "raw/transcripts.json").read_text())

    def test_only_audio_apple_left_without_words_and_only_when_asked(self):
        memo, done_memo, music = self.file("memo.m4a", "pick up the tripod"), self.file("done.m4a", "x"), self.file("song.m4a", "music")
        voice, voicemail = self.file("Audio Message.caf", "running late"), self.file("12.amr", "call me back")
        self.norm("voice_memos", [{"ts": "2026-01-02", "meta": {"path": memo, "transcribed": False}},
                                  {"ts": "2026-01-03", "meta": {"path": done_memo, "transcribed": True}},
                                  {"ts": "2026-01-04", "meta": {"path": music, "transcribed": False}}])
        self.norm("imessage", [{"ts": "2026-01-05", "meta": {"audio": True, "attachments": [{"path": voice, "name": "Audio Message.caf"}]}},
                               {"ts": "2026-01-06", "meta": {"audio": True, "transcribed": True, "attachments": [{"path": self.file("t.caf", "y")}]}},
                               {"ts": "2026-01-07", "meta": {"attachments": [{"path": self.file("song.mp3", "z")}]}}])  # not an audio message
        self.norm("phone_voicemail", [{"ts": "2026-01-08", "kind": "voicemail", "text": "[voicemail, 00:00:09, no transcript]", "meta": {"files": [voicemail]}},
                                      {"ts": "2026-01-09", "kind": "voicemail", "text": "Apple heard this", "meta": {"files": [self.file("13.amr", "w")]}}])
        self.assertIn("off", self.run_it(on=False))
        self.assertEqual(self.asked(), [], "nothing heard unless it's turned on")
        self.run_it()
        self.assertEqual(sorted(Path(p).name for p in self.asked()), ["12.amr", "Audio Message.caf", "memo.m4a", "song.m4a"])
        texts = {Path(k.split("|")[0]).name: v["text"] for k, v in self.kept().items()}
        self.assertEqual(texts, {"memo.m4a": "pick up the tripod", "song.m4a": "", "Audio Message.caf": "running late", "12.amr": "call me back"})
        # Again: what was heard isn't heard again, music included; a file changed since is
        Path(memo).write_text("pick up the tripod and the lens")
        os.utime(memo, (1_900_000_000, 1_900_000_000))
        self.run_it()
        self.assertEqual([Path(p).name for p in self.asked()[4:]], ["memo.m4a"])

    def test_one_that_couldnt_be_read_is_tried_again(self):
        gone = self.file("gone.caf", "x")
        self.norm("imessage", [{"ts": "2026-01-05", "meta": {"audio": True, "attachments": [{"path": gone}]}}])
        Path(gone).chmod(0)  # there, but unreadable: the stand-in can't open it
        self.run_it()
        Path(gone).chmod(0o644)
        self.assertTrue(all("error" in v for v in self.kept().values()))
        self.run_it()
        self.assertEqual(len(self.asked()), 2, "an error isn't an answer")
        self.assertEqual(list(self.kept().values())[0]["text"], "x")

    def test_a_run_stops_at_its_budget_and_says_which_sources_have_new_words(self):
        files = [self.file(f"m{i}.m4a", f"memo {i}") for i in range(3)]
        self.norm("voice_memos", [{"ts": f"2026-01-0{i + 1}", "meta": {"path": f, "transcribed": False}} for i, f in enumerate(files)])
        self.norm("imessage", [{"ts": "2025-12-01", "meta": {"audio": True, "attachments": [{"path": self.file("song.caf", "music")}]}}])
        code = ("import os, transcribe; os.environ.update(UMP_TRANSCRIBE='1', UMP_TRANSCRIBE_SECONDS='0'); print(transcribe.main()); "
                "os.environ['UMP_TRANSCRIBE_SECONDS'] = '60'; print(transcribe.main())")
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, capture_output=True, text=True, timeout=60,
                           env={**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_HEAR": str(self.fake),
                                "HEAR_LOG": str(self.log), "UMP_TRANSCRIBE_LANGS": "en-US"})
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = [l for l in r.stdout.splitlines() if l.startswith("[")][1::2]
        self.assertEqual(first, "['voice_memos']", "the newest one, then out of time")
        self.assertEqual(second, "['voice_memos']", "the other two; the song had no words, so iMessage has nothing new")
        self.assertEqual(len(set(self.asked())), 4)

    def test_the_readers_take_what_was_heard(self):
        memo = self.file("memo.m4a", "pick up the tripod")
        self.norm("voice_memos", [{"meta": {"path": memo, "transcribed": False}}])
        self.run_it()
        code = f"import common; print(repr(common.heard({memo!r}))); print(repr(common.heard({str(self.audio / 'other.m4a')!r})))"
        r = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, capture_output=True, text=True,
                           env={**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)})
        self.assertEqual(r.stdout.split(), ["'pick", "up", "the", "tripod'", "None"])


if __name__ == "__main__":
    unittest.main()
