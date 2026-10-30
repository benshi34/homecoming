"""Signal Desktop: its SQLCipher database (tests/data/signal_db.sqlite, made from signal_db.sql with sqlcipher), read
in memory, with its write-ahead log and its key from the Keychain. Everyone is made up.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CONNECTORS = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "data/signal_db.sqlite"
KEY = "2b7e151628aed2a6abf7158809cf4f3c762e7160f38b4da56a784d9045190cfe"
PAGE, RESERVE = 4096, 80
sys.path.insert(0, str(CONNECTORS))
import signal_desktop  # noqa: E402


def encrypt_page(n, plain, key, salt):
    """One page as SQLCipher 4 writes it: AES-256-CBC, then its IV and an HMAC-SHA512 in the reserved bytes."""
    mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(b ^ 0x3A for b in salt), 2, 32)
    start = 16 if n == 1 else 0
    iv = os.urandom(16)
    e = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    body = e.update(plain[start:PAGE - RESERVE]) + e.finalize()
    tag = hmac.new(mac_key, body + iv + struct.pack("<I", n), hashlib.sha512).digest()
    return (salt if n == 1 else b"") + body + iv + tag + bytes(RESERVE - 16 - 64)


def plain_pages(db):
    """The fixture's pages, decrypted, as a list."""
    plain = signal_desktop.decrypted(db, b"", KEY)
    return [plain[i:i + PAGE] for i in range(0, len(plain), PAGE)]


def changed_pages(db, sql):
    plain = bytearray(b"".join(plain_pages(db)))
    plain[18:20] = b"\x01\x01"
    with sqlite3.connect(":memory:") as con:
        con.deserialize(bytes(plain))
        con.execute(sql)
        con.commit()
        after = con.serialize()
    return [(i + 1, after[i * PAGE:(i + 1) * PAGE]) for i in range(len(after) // PAGE)
            if after[i * PAGE:(i + 1) * PAGE] != bytes(plain[i * PAGE:(i + 1) * PAGE])]


def wal_bytes(db, frames, endian="<"):
    """Encrypted pages with SQLite's header and rolling frame checksums, including either checksum byte order."""
    state = [0, 0]

    def checksum(data):
        words = struct.unpack(endian + "I" * (len(data) // 4), data)
        for i in range(0, len(words), 2):
            state[0] = (state[0] + words[i] + state[1]) % 2**32
            state[1] = (state[1] + words[i + 1] + state[0]) % 2**32
        return struct.pack(">II", *state)

    salts = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    header = struct.pack(">IIII", 0x377F0682 if endian == "<" else 0x377F0683, 3007000, PAGE, 0) + salts
    wal = bytearray(header + checksum(header))
    for n, commit, plain in frames:
        head = struct.pack(">II", n, commit)
        page = encrypt_page(n, plain, bytes.fromhex(KEY), db[:16])
        wal += head + salts + checksum(head + page) + page
    return wal


class SignalTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus = self.root / "home", self.root / "corpus"
        self.sql = self.home / "Library/Application Support/Signal/sql"
        self.sql.mkdir(parents=True)
        self.corpus.mkdir()
        shutil.copy(FIXTURE, self.sql / "db.sqlite")

    def run_connector(self, **env):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "UMP_SIGNAL_KEY": KEY, **env}
        r = subprocess.run([sys.executable, "-c", "import signal_desktop; signal_desktop.main()"], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self.corpus / "normalized/signal.jsonl"
        recs = {r["id"]: r for r in map(json.loads, f.read_text().splitlines())} if f.exists() else {}
        return recs, json.loads((self.corpus / "manifest.json").read_text())["signal"]

    def test_messages_people_groups_and_calls(self):
        recs, manifest = self.run_connector()
        self.assertEqual(set(recs), {"m1", "m2", "m3", "m4", "m5", "m6", "call:k1", "call:k2"}, "a key change isn't a message")
        self.assertEqual(manifest["notes"]["not_messages"], {"keychange": 1})
        m1, m2 = recs["m1"], recs["m2"]
        self.assertEqual((m1["author"], m1["is_me"], m1["thread_name"], m1["participants"], m1["ts"]),
                         ("Grace Hopper", False, "Grace Hopper", ["Grace Hopper"], "2026-01-01T10:00:00Z"),
                         "your name for her (from Contacts), not her profile name")
        self.assertEqual(m1["meta"]["reactions"], [{"who": "me", "reaction": "❤️", "ts": "2026-01-01T10:01:40Z"}], "your reaction comes from Note to Self")
        self.assertEqual((m2["author"], m2["is_me"], m2["meta"]["edits"]), ("me", True, 1))
        self.assertEqual((m2["meta"]["reply_to"], m2["meta"]["reply_text"]), ("m1", "high tide at 6?"),
                         "a reply names the message it quotes by its id, not when that was sent")
        m3 = recs["m3"]
        self.assertEqual((m3["author"], m3["thread_name"], m3["participants"], m3["meta"]["group"]),
                         ("Alan Turing", "Tide club", ["Alan Turing", "Grace Hopper"], True), "a group: who wrote it, everyone but you")
        self.assertEqual(m3["text"], "see you there\n[attachment: tides.jpg (image/jpeg)]", "a link's preview isn't an attachment")
        self.assertEqual((recs["m4"]["text"], recs["m4"]["meta"]["tier"]), ("[deleted message]", "deleted"))
        self.assertEqual(recs["m5"]["text"], "[poll] Dinner?: Thai / Pizza")
        self.assertEqual(recs["m6"]["text"], "[sticker 🌊]")
        k1, k2 = recs["call:k1"], recs["call:k2"]
        self.assertEqual((k1["kind"], k1["author"], k1["thread_name"], k1["meta"]["seconds"]), ("call", "Grace Hopper", "Grace Hopper", 300))
        self.assertEqual((k2["author"], k2["thread_name"], k2["meta"]["status"]), ("Alan Turing", "Tide club", "Missed"), "who rang the group")

    def test_the_write_ahead_log(self):
        # Signal's newest writes sit in db.sqlite-wal: committed frames count, one after the last commit doesn't.
        db = (self.sql / "db.sqlite").read_bytes()
        committed = changed_pages(db, "update messages set body = 'low tide at 7?' where id = 'm1'")
        uncommitted = changed_pages(db, "update messages set body = 'never saved' where id = 'm3'")
        size = len(db) // PAGE
        frames = [(n, size if i == len(committed) - 1 else 0, page) for i, (n, page) in enumerate(committed)]
        frames += [(n, 0, page) for n, page in uncommitted]
        for endian in ("<", ">"):
            with self.subTest(endian=endian):
                (self.sql / "db.sqlite-wal").write_bytes(wal_bytes(db, frames, endian))
                recs, _ = self.run_connector()
                self.assertEqual(recs["m1"]["text"], "low tide at 7?")
                self.assertEqual(recs["m3"]["text"].split("\n")[0], "see you there")

    def test_a_bad_wal_checksum_keeps_only_the_last_valid_commit(self):
        db = (self.sql / "db.sqlite").read_bytes()
        size = len(db) // PAGE
        first = changed_pages(db, "update messages set body = 'saved' where id = 'm1'")
        second = changed_pages(db, "update messages set body = 'invalid' where id = 'm1'")
        frames = [(n, size if i == len(first) - 1 else 0, page) for i, (n, page) in enumerate(first)]
        frames += [(n, size if i == len(second) - 1 else 0, page) for i, (n, page) in enumerate(second)]
        for bad_frame, expected in ((0, 'high tide at 6?'), (len(first), 'saved')):
            with self.subTest(bad_frame=bad_frame):
                wal = wal_bytes(db, frames)
                wal[32 + bad_frame * (24 + PAGE) + 16] ^= 1  # page and its HMAC are still valid
                (self.sql / "db.sqlite-wal").write_bytes(wal)
                recs, _ = self.run_connector()
                self.assertEqual(recs["m1"]["text"], expected)

    def test_invalid_wal_headers_are_reported(self):
        db = (self.sql / "db.sqlite").read_bytes()
        for offset in (0, 4, 8, 24):  # magic, format version, page size, header checksum
            with self.subTest(offset=offset):
                wal = wal_bytes(db, [])
                wal[offset] ^= 1
                with self.assertRaisesRegex(signal_desktop.SignalError, "invalid_wal_header"):
                    signal_desktop.decrypted(db, wal, KEY)

    def test_wal_checksums_match_sqlites_own_writer(self):
        # Independent reference: SQLite itself writes the checksums, rather than the encrypted test builder.
        path = self.root / "checksum-reference.sqlite"
        con = sqlite3.connect(path)
        try:
            con.execute("pragma journal_mode=wal")
            con.execute("create table example (body text)")
            con.execute("insert into example values ('hello')")
            con.commit()
            wal = path.with_name(path.name + "-wal").read_bytes()
            endian = "<" if struct.unpack(">I", wal[:4])[0] == 0x377F0682 else ">"
            state = signal_desktop.wal_checksum(wal[:24], endian)
            self.assertEqual(state, struct.unpack(">II", wal[24:32]))
            size = struct.unpack(">I", wal[8:12])[0]
            for at in range(32, len(wal), 24 + size):
                state = signal_desktop.wal_checksum(wal[at:at + 8] + wal[at + 24:at + 24 + size], endian, state)
                self.assertEqual(state, struct.unpack(">II", wal[at + 16:at + 24]))
        finally:
            con.close()

    def test_a_wrong_key_reads_nothing_and_says_so(self):
        recs, manifest = self.run_connector(UMP_SIGNAL_KEY="00" * 32)
        self.assertEqual(recs, {})
        self.assertEqual(manifest["notes"], {"not_read": "wrong_key_or_damaged"})

    def test_the_key_from_the_keychain(self):
        # config.json's encryptedKey is the database key, encrypted with the Keychain's "Signal Safe Storage".
        password = b"made-up-safe-storage-password"
        kek = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
        p = padding.PKCS7(128).padder()
        e = Cipher(algorithms.AES(kek), modes.CBC(b" " * 16)).encryptor()
        enc = b"v10" + e.update(p.update(KEY.encode()) + p.finalize()) + e.finalize()
        (self.sql.parent / "config.json").write_text(json.dumps({"encryptedKey": enc.hex()}))
        bin_ = self.root / "bin"
        bin_.mkdir()
        (bin_ / "security").write_text(f"#!/bin/sh\n[ \"$3\" = 'Signal Safe Storage' ] && echo '{password.decode()}' || exit 44\n")
        (bin_ / "security").chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k != "UMP_SIGNAL_KEY"}
        env.update(HOME=str(self.home), CORPUS_DIR=str(self.corpus), PATH=f"{bin_}:{os.environ['PATH']}")
        r = subprocess.run([sys.executable, "-c", "import signal_desktop; print(signal_desktop.db_key())"], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), KEY, r.stderr)
        (bin_ / "security").write_text("#!/bin/sh\nexit 51\n")  # the dialog turned down
        r = subprocess.run([sys.executable, "-c", "import signal_desktop; signal_desktop.main()"], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.corpus / "manifest.json").read_text())["signal"]["notes"], {"not_read": "keychain_refused"})


if __name__ == "__main__":
    unittest.main()
