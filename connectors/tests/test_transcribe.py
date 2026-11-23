"""transcribe.py: which audio it hears (only what Apple left without words), what it keeps, what it hears again, and the
readers taking its text. A stand-in for hear.swift (UMP_HEAR) answers from a script and notes what it was asked; the
audio files are made up.

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

# hear.swift's stand-in: one JSON line a path, as it writes them; "music" hears nothing, a missing file can't be read
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ["HEAR_LOG"]
allowed = "--allow-model-downloads" in sys.argv[2:]
open(log + ".permissions", "a").write(json.dumps({"args": sys.argv[1:], "allowed": allowed}) + "\n")
models = os.environ.get("HEAR_MODELS")
installed = json.load(open(models)) if models else sys.argv[1].split(",")
for line in sys.stdin:
    p = line.strip()
    open(log, "a").write(p + "\n")
    missing = [lang for lang in sys.argv[1].split(",") if lang not in installed]
    if missing and allowed:
        open(log + ".downloads", "a").write(json.dumps(missing) + "\n")
        installed += missing
        json.dump(installed, open(models, "w"))
        missing = []
    notes = [f"The speech model for {lang} isn't on this Mac. Allow speech_models in corpus/network.json to download it (offline must be false)." for lang in missing]
    if missing and all(lang in missing for lang in sys.argv[1].split(",")):
        print(json.dumps({"path": p, "error": notes[0], "missingModels": missing, "notes": notes}))
        continue
    if p.endswith("hang.caf"):  # Apple's recognizer, never answering
        import time; time.sleep(30)
    if not os.path.exists(p):
        print(json.dumps({"path": p, "error": "can't open it"}))
    else:
        said = open(p).read()
        print(json.dumps({"path": p, "text": "" if said == "music" else said, "locale": "en_US", "confidence": 0.9,
                          "missingModels": missing, "notes": notes}))
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

    def run_it(self, on=True, wait="60", **extra):
        env = {**{k: v for k, v in os.environ.items() if k not in ("UMP_OFFLINE", "HEAR_MODELS")},
               "UMP_TRANSCRIBE_WAIT": wait, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_HEAR": str(self.fake),
               "HEAR_LOG": str(self.log), "UMP_TRANSCRIBE_LANGS": "en-US", **extra}
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

    def network(self, conf):
        (self.corpus / "network.json").write_text(json.dumps(conf))

    def permissions(self):
        return [json.loads(line) for line in Path(str(self.log) + ".permissions").read_text().splitlines()]

    def test_installed_models_still_transcribe_offline_without_download_permission(self):
        memo = self.file("memo.m4a", "the ferry leaves at ten")
        self.norm("voice_memos", [{"meta": {"path": memo}}])
        self.network({"offline": True, "sources": {"speech_models": True}})
        self.run_it(UMP_OFFLINE="1")
        self.assertEqual(list(self.kept().values())[0]["text"], "the ferry leaves at ten")
        self.assertEqual(self.permissions(), [{"args": ["en-US"], "allowed": False}])
        self.assertFalse(Path(str(self.log) + ".downloads").exists())

    def test_missing_models_need_permission_and_offline_always_wins(self):
        memo = self.file("memo.m4a", "the ferry leaves at ten")
        self.norm("voice_memos", [{"meta": {"path": memo}}])
        models = self.root / "models.json"
        models.write_text("[]")
        cases = [(None, {}), ({"sources": {"other": True}}, {}),
                 ({"sources": {"speech_models": "yes"}}, {}),
                 ({"offline": True, "sources": {"speech_models": True}}, {}),
                 ({"sources": {"speech_models": True}}, {"UMP_OFFLINE": "1"})]
        for conf, env in cases:
            with self.subTest(conf=conf, env=env):
                if conf is not None:
                    self.network(conf)
                output = self.run_it(HEAR_MODELS=str(models), **env)
                got = list(self.kept().values())[0]
                self.assertNotIn("text", got, "a missing model must remain retryable after three runs")
                self.assertNotIn("tries", got, "permission isn't an unreadable audio file")
                self.assertEqual(got["missingModels"], ["en-US"])
                self.assertIn("speech model for en-US isn't on this Mac", output)
                self.assertIn("speech_models in corpus/network.json", output)
                self.assertIn("1 waiting for speech models", output)
                self.assertFalse(self.permissions()[-1]["allowed"], "the helper must not receive download permission")
                self.assertFalse(Path(str(self.log) + ".downloads").exists())
        self.network({"offline": False, "sources": {"speech_models": True}})
        self.run_it(HEAR_MODELS=str(models))
        self.assertEqual(list(self.kept().values())[0]["text"], "the ferry leaves at ten")
        self.assertTrue(self.permissions()[-1]["allowed"])
        self.assertEqual(json.loads(Path(str(self.log) + ".downloads").read_text()), ["en-US"])

    def test_permission_is_read_again_for_each_file(self):
        files = [self.file(f"m{i}.m4a", f"memo {i}") for i in range(2)]
        self.norm("voice_memos", [{"ts": str(i), "meta": {"path": f}} for i, f in enumerate(files)])
        self.network({"sources": {"speech_models": True}})
        self.fake.write_text(FAKE + '\nopen(os.path.join(os.environ["CORPUS_DIR"], "network.json"), "w").write(\'{"offline": true}\')\n')
        self.run_it()
        self.assertEqual([r["allowed"] for r in self.permissions()], [True, False])
        self.assertEqual(sorted(v["text"] for v in self.kept().values()), ["memo 0", "memo 1"])

    def test_a_missing_language_is_not_silenced_by_an_installed_one(self):
        memo = self.file("memo.m4a", "the ferry leaves at ten")
        self.norm("voice_memos", [{"meta": {"path": memo}}])
        models = self.root / "models.json"
        models.write_text('["en-US"]')
        output = self.run_it(HEAR_MODELS=str(models), UMP_TRANSCRIBE_LANGS="en-US,fr-FR")
        self.assertEqual(list(self.kept().values())[0]["text"], "the ferry leaves at ten")
        self.assertIn("speech model for fr-FR isn't on this Mac", output)
        self.assertFalse(Path(str(self.log) + ".downloads").exists())

    def test_the_desktop_bridge_waits_for_permission_then_reads_offline(self):
        rec = self.home / "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
        rec.mkdir(parents=True)
        (rec / "first.m4a").write_text("the ferry leaves at ten")
        db = rec / "CloudRecordings.db"
        with sqlite3.connect(db) as con:
            con.executescript("""
                create table ZCLOUDRECORDING (Z_PK integer primary key, ZUNIQUEID text, ZDATE real,
                    ZDURATION real, ZPATH text, ZCUSTOMLABEL text, ZEVICTIONDATE real);
                insert into ZCLOUDRECORDING values (1, 'V1', 794000000, 12, 'first.m4a', 'Harbor', null);
            """)
        models = self.root / "models.json"
        models.write_text("[]")
        env = {**{k: v for k, v in os.environ.items() if k != "UMP_OFFLINE"},
               "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_HEAR": str(self.fake),
               "HEAR_LOG": str(self.log), "HEAR_MODELS": str(models), "UMP_TRANSCRIBE_LANGS": "en-US",
               "UMP_TRANSCRIBE": "1"}

        def run_bridge():
            result = subprocess.run([sys.executable, str(CONNECTORS.parent / "desktop/py/bridge.py"), "run", "voice_memos"],
                                    env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(events[-1], {"type": "finished", "failed": []})
            self.assertFalse([event for event in events if event["type"] == "error"], events)
            with sqlite3.connect(self.corpus / "corpus.db") as index:
                texts = [row[0] for row in index.execute("select text from records where source = 'voice_memos' order by id")]
            return events, texts

        self.network({"offline": True, "sources": {"speech_models": True}})
        events, texts = run_bridge()
        self.assertEqual(texts, ["Harbor"])
        self.assertTrue(any("speech model for en-US isn't on this Mac" in event.get("line", "") for event in events), events)
        self.assertEqual([p["allowed"] for p in self.permissions()], [False])
        self.assertEqual(json.loads(models.read_text()), [])

        self.network({"offline": False, "sources": {"speech_models": True}})
        _, texts = run_bridge()
        self.assertEqual(texts, ["Harbor\nthe ferry leaves at ten"])
        self.assertEqual([p["allowed"] for p in self.permissions()], [False, True])

        self.network({"offline": True, "sources": {"speech_models": True}})
        (rec / "second.m4a").write_text("the last ferry is at six")
        with sqlite3.connect(db) as con:
            con.execute("insert into ZCLOUDRECORDING values (2, 'V2', 794086400, 12, 'second.m4a', 'Pier', null)")
        _, texts = run_bridge()
        self.assertEqual(texts, ["Harbor\nthe ferry leaves at ten", "Pier\nthe last ferry is at six"])
        self.assertEqual([p["allowed"] for p in self.permissions()], [False, True, False])
        self.assertEqual(Path(str(self.log) + ".downloads").read_text().splitlines(), ['["en-US"]'])

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

    def test_one_that_never_answers_is_given_up_on_after_three_tries(self):
        hang, fine = self.file("hang.caf", "x"), self.file("fine.caf", "on my way")
        self.norm("imessage", [{"ts": "2026-01-06", "meta": {"audio": True, "attachments": [{"path": hang}]}},
                               {"ts": "2026-01-05", "meta": {"audio": True, "attachments": [{"path": fine}]}}])
        for _ in range(4):
            self.run_it(wait="1")
        names = [Path(p).name for p in self.asked()]
        self.assertEqual((names.count("hang.caf"), names.count("fine.caf")), (3, 1), "the one after it heard; it, three times")
        kept = {Path(k.split("|")[0]).name: v for k, v in self.kept().items()}
        self.assertEqual((kept["hang.caf"]["tries"], kept["hang.caf"]["text"]), (3, ""))
        self.assertEqual(kept["fine.caf"]["text"], "on my way")

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
