"""Run the real Swift helper with a fake Speech framework: no Apple asset service or real audio is used.

AVFoundation still reads a made-up silent WAV. The fake Speech module logs asset requests and downloads.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"), "needs the Mac's Swift compiler")
class HearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.exe = cls.root / "hear"
        flags = ["-module-cache-path", str(cls.root / "module-cache")]
        for args in [
            ["-emit-library", "-emit-module", "-module-name", "Speech",
             "-emit-module-path", str(cls.root / "Speech.swiftmodule"),
             str(CONNECTORS / "tests/fixtures/speech/Speech.swift"), "-o", str(cls.root / "libSpeech.dylib")],
            ["-O", str(CONNECTORS / "hear.swift"), "-I", str(cls.root), "-L", str(cls.root), "-lSpeech",
             "-Xlinker", "-rpath", "-Xlinker", str(cls.root), "-o", str(cls.exe)],
        ]:
            subprocess.run(["swiftc", *flags, *args], capture_output=True, text=True, check=True, timeout=120)
        cls.audio = cls.root / "silence.wav"
        with wave.open(str(cls.audio), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(16000)
            f.writeframes(b"\x00\x00" * 160)

    def hear(self, langs="en-US", installed="", allow=False):
        events = self.root / "events.log"
        events.unlink(missing_ok=True)
        result = subprocess.run([str(self.exe), langs, *(["--allow-model-downloads"] if allow else [])],
                                input=str(self.audio) + "\n", capture_output=True, text=True, check=True, timeout=30,
                                env={**os.environ, "HEAR_EVENTS": str(events), "HEAR_INSTALLED": installed})
        return json.loads(result.stdout), events.read_text().splitlines() if events.exists() else []

    def test_installed_model_works_with_downloads_denied(self):
        got, events = self.hear(installed="en-US")
        self.assertEqual(got["text"], "the ferry leaves at ten")
        self.assertNotIn("error", got)
        self.assertEqual(events, ["analyze"], "an installed model downloads nothing, though its status says only .supported")

    def test_missing_model_denied_by_default_before_any_download(self):
        got, events = self.hear()
        self.assertEqual(events, [], "denied downloads must not download")
        self.assertNotIn("text", got)
        self.assertEqual(got["missingModels"], ["en-US"])
        self.assertIn("speech model for en-US isn't on this Mac", got["error"])
        self.assertIn("speech_models in corpus/network.json", got["notes"][0])

    def test_permission_allows_only_missing_models_to_download(self):
        got, events = self.hear(langs="en-US,fr-FR", installed="en-US", allow=True)
        self.assertEqual(got["text"], "the ferry leaves at ten")
        self.assertNotIn("error", got)
        self.assertEqual(events, ["analyze", "download:fr-FR", "analyze"])

    def test_each_missing_language_is_noted_even_when_another_transcribes(self):
        for langs in ("en-US,fr-FR", "fr-FR,en-US"):
            with self.subTest(langs=langs):
                got, events = self.hear(langs=langs, installed="en-US")
                self.assertEqual(got["text"], "the ferry leaves at ten")
                self.assertNotIn("error", got)
                self.assertEqual(got["missingModels"], ["fr-FR"])
                self.assertIn("speech model for fr-FR isn't on this Mac", got["notes"][0])
                self.assertEqual(events, ["analyze"])


if __name__ == "__main__":
    unittest.main()
