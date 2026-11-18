"""common.online: a source reaches the internet only when it's switched on, and never when Homecoming is offline.

Run: python3 -m unittest discover -s connectors/tests -p 'test_network.py'
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]
ASK = "import common, sys; print(common.online(sys.argv[1]))"


class OnlineTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.corpus = Path(t.name)

    def online(self, source, conf=None, **env):
        if conf is not None:
            (self.corpus / "network.json").write_text(conf if isinstance(conf, str) else json.dumps(conf))
        e = {**{k: v for k, v in os.environ.items() if k != "UMP_OFFLINE"}, "CORPUS_DIR": str(self.corpus), **env}
        r = subprocess.run([sys.executable, "-c", ASK, source], cwd=CONNECTORS, env=e, capture_output=True, text=True,
                           check=True)
        return r.stdout.strip() == "True"

    def test_off_unless_switched_on(self):
        self.assertFalse(self.online("slack"))  # no file: nothing goes online
        self.assertFalse(self.online("slack", {"sources": {}}))
        self.assertFalse(self.online("slack", {"sources": {"slack": "yes"}}))  # only a real true
        self.assertTrue(self.online("slack", {"sources": {"slack": True}}))
        self.assertFalse(self.online("drive_api", {"sources": {"slack": True}}))

    def test_offline_wins_over_every_switch(self):
        on = {"sources": {"slack": True}}
        self.assertFalse(self.online("slack", {**on, "offline": True}))
        self.assertFalse(self.online("slack", on, UMP_OFFLINE="1"))

    def test_a_broken_file_means_offline(self):
        self.assertFalse(self.online("slack", "{not json"))
        self.assertFalse(self.online("slack", "[1, 2]"))


if __name__ == "__main__":
    unittest.main()
