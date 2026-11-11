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


class StandalonePasswordTests(unittest.TestCase):
    """A generated password saved in a note, alone on its line or after a short label, with no word "password"
    near it; and the IDs, names, paths and PDF fragments that look a little like one. Made-up values."""

    def test_saved_passwords_are_blanked(self):
        for text, gone in [("Xk9#mP2qL!vR4t", "Xk9#mP2qL!vR4t"), ("Bank: Tq7vWp2Lm9Xz", "Tq7vWp2Lm9Xz"),
                           ("- email = hR5tYq0pWm3z", "hR5tYq0pWm3z"), ("  3. N7x-Qf2r-Lp8k", "N7x-Qf2r-Lp8k"),
                           ("abcdEf-g1hijk-lmnopq", "g1hijk"), ("the db one is Xk9#mP2qL!vR4t for now", "Xk9#mP2qL!vR4t"),
                           ("use `Ab/.@#CDEFGH9J` there", "CDEFGH9J"), ("#Ab9cd-E#FGH!=+k", "FGH!=+k"),
                           ("**Password**: hunter2abc!", "hunter2abc"), ("notes\nkP3vRw9ZtqLm\nmore", "kP3vRw9ZtqLm"),
                           ("- Ab\"9#k`Q2!x@Lm", "Q2!x@Lm"), ("- Ab:9#kQ2!x@Lmzz", "Ab:9#"), ("> - [ ] Zqxjvk12!w", "Zqxjvk12"),
                           ("\tdbpass - Rr4!kd93LsQ0x", "Rr4!kd93LsQ0x"), ("- qwzxkvbn47!", "qwzxkvbn"), ("- Purple7!Horse", "Purple7"), ("Summer2024!", "Summer2024"),
                           ("- [Qx7#vR2!mK9p", "Qx7#vR2"), ("> ~k8!Tz/Q3#pLw9", "Tz/Q3"), ("- 12.7Kq!x#Rv9w%P", "Kq!x#Rv9"), ("- Wp4!z#Lq8Rm(", "Wp4!z#"),
                           ("- 12.7Kq!x#Rv9w!P#z", "Kq!x#Rv9"), ("then use ~k8!Tz/Q3#pLw9 for it", "Tz/Q3")]:
            with self.subTest(text=text):
                self.assertNotIn(gone, redact(text))
                self.assertIn("[redacted password]", redact(text))

    def test_look_alikes_are_left_alone(self):
        for text in ("iPhone15Pro", "MacBookAir2", "Qwen2.5-72B-Instruct", "use Llama-3.1-8B-Instruct here", "STM32H7S3A8",
                     "v1.2.3-beta", "IMG_1234.JPG", "Report.PDF", "src/Main9Ab.tsx", "~/dev/Ab9cdEfg1", "#projectTag2",
                     "a1b2c3d4-e5f6-7a8b-9c0d-112233445566", "getUserById()", "2024-07-01", "ada@example.com",
                     "https://ex.com/aB3x9Kq2", "Ref: Tq7vWp2Lm9Xz", "Order ID: Tq7vWp2Lm9Xz", "[cid:image001.png@01DC2A3B]",
                     "abcAB9=", "see https://youtu.be/dQw4w9WgXcQ ok", "commit 3f2a9c1b7e5d4a6f8b0c",
                     "arXiv:2412.19437v1 [cs.CL]", "paid $1,234.56 today.", "Hannum,", "some text kP3vRw9ZtqLm in a sentence",
                     "- Meeting 10:30am-11:00am", "- $1,299.99", "- RTX4090_24GB", "GPT4o-mini", "- 10-Nov-2026", "x: 9!important;", "time: 12:30:45pm", "- [cid:Ab9#cd!Ef@x.Y2]", "- ~/a!b#c$Dd9Xq/x.txt", "- Eq.~(A1)--(B2))].", "- ABCD9(core::ops9::IndexMut),", "- Ab&#8217;Cd9!x#q?", "**`ab-c12-defghi:A-9`**", "at 2026.111.11:10:30:45.12#alpha#Bravo ok", "- /*Field#12Abc#34Defgh-56789", "- 9.8*bravo*C3^2", "a |Alpha|1-23ab|<456c| row", "Smith~\\cite{key:abc12}", r"9.981234~\\mathrm{Ab/\\AB^2}"):
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)


if __name__ == "__main__":
    unittest.main()
