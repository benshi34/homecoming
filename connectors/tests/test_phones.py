"""Phone numbers read in the region the person lives in (phones.py), and contacts matched by them.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phones

CONNECTORS = Path(__file__).resolve().parents[1]


class E164Tests(unittest.TestCase):
    def test_by_region(self):
        cases = [("US", "(415) 555-0100", "+14155550100"), ("US", "1-415-555-0100", "+14155550100"), ("US", "011 44 7700 900123", "+447700900123"),
                 ("GB", "07700 900123", "+447700900123"), ("GB", "0044 7700 900123", "+447700900123"), ("GB", "+1 415 555 0100", "+14155550100"),
                 ("FR", "06 12 34 56 78", "+33612345678"), ("FR", "33612345678", "+33612345678"), ("IT", "06 1234 5678", "+390612345678"),
                 ("SG", "9123 4567", "+6591234567"), ("AU", "0011 44 7700 900123", "+447700900123"), ("AU", "0412 345 678", "+61412345678")]
        for reg, raw, want in cases:
            self.assertEqual(phones.e164(raw, reg), want, (reg, raw))
        self.assertIsNone(phones.e164("ada@example.com", "US"))
        self.assertIsNone(phones.e164("1234", "US"))
        self.assertEqual(phones.e164("0612 345 678", "ZZ"), "+0612345678", "a region not known: as written")

    def test_the_macs_region_unless_one_is_chosen(self):
        with tempfile.TemporaryDirectory() as home:
            prefs = Path(home, "Library/Preferences/.GlobalPreferences.plist")
            prefs.parent.mkdir(parents=True)
            prefs.write_bytes(plistlib.dumps({"AppleLocale": "en_GB"}))
            self.assertEqual(phones.mac_region(home), "GB")
            prefs.write_bytes(plistlib.dumps({"AppleLocale": "zh-Hant_TW"}))
            self.assertEqual(phones.mac_region(home), "TW")
            env = {**os.environ, "HOME": home, "UMP_PHONE_REGION": "fr"}
            out = subprocess.run([sys.executable, "-c", "import phones, json; print(json.dumps(phones.info()))"], cwd=CONNECTORS, env=env,
                                 capture_output=True, text=True).stdout
            self.assertIn('"region": "FR"', out)
            self.assertIn('"chosen": true', out)


class ResolverTests(unittest.TestCase):
    """A UK contact saved as 07700 900123 is the same person Messages knows as +447700900123; a friend abroad saved
    without their country code still matches by the number's last digits."""

    def test_names_by_number(self):
        with tempfile.TemporaryDirectory() as t:
            home, corpus = Path(t, "home"), Path(t, "corpus")
            vcards = corpus / "imports/contacts"
            vcards.mkdir(parents=True)
            (vcards / "c.vcf").write_text("BEGIN:VCARD\nVERSION:3.0\nFN:Grace Hopper\nTEL:07700 900123\nEND:VCARD\n"
                                          "BEGIN:VCARD\nVERSION:3.0\nFN:Alan Turing\nTEL:(212) 555-0199\nEND:VCARD\n")
            code = ("import contacts; r = contacts.Resolver(); "
                    "print(r.name('+447700900123'), r.name('+12125550199'), r.name('+33612345678'))")
            env = {**os.environ, "HOME": str(home), "CORPUS_DIR": str(corpus), "UMP_PHONE_REGION": "GB"}
            out = subprocess.run([sys.executable, "-c", code], cwd=CONNECTORS, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            # Alan's US number was saved without +1: read as British it's wrong, but its last nine digits still match.
            self.assertEqual(out.stdout.split(), ["Grace", "Hopper", "Alan", "Turing", "None"])


if __name__ == "__main__":
    unittest.main()
