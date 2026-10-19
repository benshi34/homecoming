"""What leaves this Mac for a model has its secrets blanked; ordinary text doesn't.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from redact import redact

# BIP39's published test vector, not anyone's wallet.
PHRASE = "legal winner thank year wave sausage worth useful legal winner thank yellow"


class RedactTests(unittest.TestCase):
    def test_secrets_are_blanked(self):
        cases = {
            f"backup: {PHRASE}": "backup: [redacted recovery phrase]",
            "export OPENAI_API_KEY=sk-proj-" + "a" * 40: "export OPENAI_API_KEY=[redacted API key]",
            "router sk-or-v1-" + "b" * 60 + " ok": "router [redacted API key] ok",
            "token ghp_" + "c" * 36 + " end": "token [redacted token] end",
            "Authorization: Bearer " + "d" * 30: "Authorization: Bearer [redacted token]",
            "the password is \"open sesame\" ok": "the password is [redacted password] ok",
            '{"private_key": "-----BEGIN PRIVATE KEY-----\\nMIIE' + "x" * 60 + '\\n-----END PRIVATE KEY-----\\n"}': '{"private_key": "[redacted private key]"}',
            "reset: https://x.example/r?token=" + "e" * 30 + "&u=1": "reset: https://x.example/r?token=[redacted secret]&u=1",
            "Visa card 4111 1111 1111 1111 exp 01/30": "Visa card [redacted card number] exp 01/30",
        }
        for text, want in cases.items():
            with self.subTest(text=text[:30]):
                self.assertEqual(redact(text), want)

    def test_look_alikes_are_left_alone(self):
        for text in ("I want to go to the park and see a big tree with my friend today please",
                     "zoo " * 30,  # one word repeated isn't a phrase
                     "Order 4111 1111 1111 1111 shipped",  # passes Luhn, but nothing says card
                     "ssh -p 22 host", "the passwords meeting is at noon", "sk-learn is a library"):
            with self.subTest(text=text[:30]):
                self.assertEqual(redact(text), text)



class MoreSecretsTests(unittest.TestCase):
    """What slipped past before (an audit, 2026-10-18), on made-up values."""

    def test_more_kinds(self):
        from redact import redact
        for text, gone in [("the password for chase is hunter2!", "hunter2"), ("DB_PASSWORD=s3cr3tvalue", "s3cr3tvalue"),
                           ("PGPASSWORD=abc123xyz", "abc123xyz"), ("postgres://ada:Sup3rS3cret@db.example.com/app", "Sup3rS3cret"),
                           ("SSN: 123-45-6789", "6789"), ("my social security number is 123 45 6789", "6789"),
                           ("routing number 021000021", "021000021"), ("account number 123456789012", "123456789012"),
                           ("ya29.a0AfH6SMBabcdefghijklmnopqrstuvwxyz", "a0AfH6"), ("glpat-abcdefghijklmnopqrstuv", "abcdefghij"),
                           ("npm_abcdefghijklmnopqrstuvwxyz0123456789", "abcdefghij"), ("hf_abcdefghijklmnopqrstuvwxyzABCDEF12", "abcdefghij"),
                           ("SG.abcdefghijklmnopqr.stuvwxyzABCDEFGHIJKLmnop", "abcdefghij"), ("card 2223 0031 2200 3222 exp 12/27", "3222"),
                           ("?secret=abcdefghijklmnop", "abcdefghijklmnop")]:
            self.assertNotIn(gone, redact(text), text)
        for text in ("call me at 415-555-0100", "order 1234-56-7890 shipped", "the account was opened in 2019"):
            self.assertEqual(redact(text), text, "not a secret")

    def test_a_key_cut_short_or_followed_by_more(self):
        from redact import redact
        key = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj\n"
        self.assertNotIn("BKcwggSj", redact(key + "and then " + "a long message. " * 800))
        self.assertNotIn("MIIEvQ", redact(key))


if __name__ == "__main__":
    unittest.main()
