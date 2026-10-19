"""The iPhone side in every shape it comes in, on made-up backups and databases: several backups (one in progress, one
interrupted, one too old, an iPad's, one on a disk that isn't plugged in), encrypted or not (made-up keys, a made-up
password: never a real one, never the Keychain), a damaged index, files missing or removed from the phone; the phone's
messages, calls, contacts, Health and WhatsApp from older and newer iOS, empty or damaged; and iLEAPP's output with
artifacts that fail, odd columns and types. Each is read, or said plainly, and never stops the rest of the phone.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import datetime as dt
import hashlib
import json
import os
import plistlib
import sqlite3
import struct
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import aes_key_wrap

CONNECTORS = Path(__file__).resolve().parents[1]
T = 780000000  # 2025-09-19 in Apple time
PASSWORD = "fixture-password-1234"  # made up for these fixtures; no real backup has it


def make_db(path, script="", rows=()):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(script)
    for sql, params in rows:
        con.execute(sql, params)
    con.commit()
    con.close()
    return path


# ---------------------------------------------------------------- a Finder backup, made up

def key_for(n):
    return hashlib.sha256(f"fixture key {n}".encode()).digest()  # 32 bytes, the same each run


def tlv(tag, value):
    value = value if isinstance(value, bytes) else struct.pack(">I", value)
    return tag.encode() + struct.pack(">I", len(value)) + value


def keybag(password, classes, ios10_2=True):
    """BackupKeyBag as Finder writes it: a header (salts, rounds) and one record per protection class, each class key
    wrapped with the key the password makes (iOS 10.2 on: PBKDF2-SHA256 over DPSL, then PBKDF2-SHA1 over SALT; before,
    the second only). Rounds kept small: these are made-up keys."""
    salt, dpsl = b"s" * 20, b"d" * 20
    kek = password.encode()
    if ios10_2:
        kek = hashlib.pbkdf2_hmac("sha256", kek, dpsl, 10, 32)
    kek = hashlib.pbkdf2_hmac("sha1", kek, salt, 10, 32)
    out = tlv("VERS", 3) + tlv("TYPE", 1) + tlv("UUID", b"u" * 16) + tlv("HMCK", b"h" * 40) + tlv("WRAP", 1) + tlv("SALT", salt) + tlv("ITER", 10)
    if ios10_2:
        out += tlv("DPWT", 1) + tlv("DPIC", 10) + tlv("DPSL", dpsl)
    for n, key in classes.items():
        out += tlv("UUID", bytes([n]) * 16) + tlv("CLAS", n) + tlv("WRAP", 3) + tlv("KTYP", 0) + tlv("WPKY", aes_key_wrap(kek, key))
    return out


def encrypt(key, data, pad=True):
    if pad:
        n = 16 - len(data) % 16
        data += bytes([n]) * n
    e = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return e.update(data) + e.finalize()


def mbfile(size, mtime, wrapped=None, protection=3):
    """Files.file: an MBFile in an NSKeyedArchiver plist, with the file's own key wrapped by its class key if encrypted."""
    root = {"$class": plistlib.UID(2), "Size": size, "LastModified": mtime, "Birth": mtime, "Mode": 33188, "Flags": 0,
            "InodeNumber": 1, "UserID": 501, "GroupID": 501, "ProtectionClass": protection}
    objects = ["$null", root, {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]}]
    if wrapped:
        root["EncryptionKey"] = plistlib.UID(3)
        objects += [{"NS.data": struct.pack("<I", protection) + wrapped, "$class": plistlib.UID(4)},
                    {"$classname": "NSMutableData", "$classes": ["NSMutableData", "NSData", "NSObject"]}]
    return plistlib.dumps({"$version": 100000, "$archiver": "NSKeyedArchiver", "$top": {"root": plistlib.UID(1)},
                           "$objects": objects}, fmt=plistlib.FMT_BINARY)


def file_id(domain, rel):
    return hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()


def make_backup(folder, files, product="iPhone15,2", ios="18.5", state="finished", password=None, ios10_2=True,
                device="Fixture iPhone", when=dt.datetime(2026, 10, 1, 12, 0)):
    """A Finder backup in `folder`: Info.plist, Status.plist, Manifest.plist, Manifest.db and each file stored by its id
    (encrypted with made-up keys under `password` if one is given). files: (domain, relativePath, bytes, mtime)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Info.plist").write_bytes(plistlib.dumps({
        "Device Name": device, "Product Type": product, "Product Version": ios, "Build Version": "22F76",
        "Target Identifier": folder.name, "Unique Identifier": folder.name, "Last Backup Date": when}))
    if state:
        (folder / "Status.plist").write_bytes(plistlib.dumps({"SnapshotState": state, "BackupState": "new", "Date": when,
                                                             "IsFullBackup": False, "Version": "3.3"}))
    classes = {3: key_for(3), 4: key_for(4)}
    manifest = {"IsEncrypted": bool(password), "Version": "10.0", "Date": when}
    if password:
        manifest["BackupKeyBag"] = keybag(password, classes, ios10_2)
    index = folder / "Manifest.db.plain"
    con = sqlite3.connect(index)
    con.execute("create table Files (fileID text primary key, domain text, relativePath text, flags int, file blob)")
    con.execute("create table Properties (key text primary key, value blob)")
    for n, (domain, rel, data, mtime) in enumerate(files):
        fid = file_id(domain, rel)
        wrapped = None
        if password:
            own = key_for(f"file {n}")
            wrapped = aes_key_wrap(classes[3], own)
            data = encrypt(own, data)
        (folder / fid[:2]).mkdir(exist_ok=True)
        (folder / fid[:2] / fid).write_bytes(data)
        con.execute("insert into Files values (?,?,?,1,?)", (fid, domain, rel, mbfile(len(data), mtime, wrapped)))
    con.commit()
    con.close()
    raw = index.read_bytes()
    index.unlink()
    if password and ios10_2:  # iOS 10.2 on: the index itself is encrypted, its key wrapped with class 4
        manifest["ManifestKey"] = struct.pack("<I", 4) + aes_key_wrap(classes[4], key_for("manifest"))
        raw = encrypt(key_for("manifest"), raw, pad=False)
    (folder / "Manifest.db").write_bytes(raw)
    (folder / "Manifest.plist").write_bytes(plistlib.dumps(manifest))
    return folder


SMS = """
create table handle (ROWID integer primary key, id text, service text);
create table chat (ROWID integer primary key, guid text, style int, display_name text, chat_identifier text);
create table chat_handle_join (chat_id int, handle_id int);
create table chat_message_join (chat_id int, message_id int);
create table attachment (ROWID integer primary key, filename text, mime_type text, transfer_name text, total_bytes int);
create table message_attachment_join (message_id int, attachment_id int);
create table message (ROWID integer primary key, guid text, text text, attributedBody blob, handle_id int, service text,
  is_from_me int, date int, item_type int, associated_message_type int);
insert into handle values (1, '+15555550123', 'iMessage');
insert into chat values (1, 'chat-bea', 45, null, '+15555550123');
insert into chat_handle_join values (1, 1);
"""


def sms_db(path, messages=(("m1", "Leeks are up", 0), ("m2", "Great, Friday then", 1)), script=SMS):
    rows = []
    for n, (guid, text, me) in enumerate(messages, 1):
        rows.append(("insert into message (ROWID, guid, text, handle_id, service, is_from_me, date, item_type, associated_message_type) "
                     "values (?,?,?,1,'iMessage',?,?,0,0)", (n, guid, text, me, (T + n) * 10**9)))
        rows.append(("insert into chat_message_join values (1, ?)", (n,)))
    return make_db(path, script, rows)


class Phone(unittest.TestCase):
    """A made-up home folder (its MobileSync backups) and library. Everything runs in its own process, as the app runs
    it, with a stand-in for macOS's `security` first on the PATH, so nothing here can reach the real Keychain."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus = self.root / "home", self.root / "corpus"
        self.home.mkdir()
        self.corpus.mkdir()
        (self.corpus / "identity.json").write_text('{"names":["Ada"],"emails":["ada@example.test"],"usernames":[],"phones":[]}')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "security").write_text("#!/bin/sh\nexit 44\n")  # "the item could not be found"
        (self.bin / "security").chmod(0o755)
        self.backups = self.home / "Library/Application Support/MobileSync/Backup"
        self.files = self.corpus / "raw/iphone/files"

    def run_py(self, code, ok=True, stdin=None, **env):
        e = {**{k: v for k, v in os.environ.items() if k != "IPHONE_BACKUP_PASSWORD"}, "HOME": str(self.home),
             "CORPUS_DIR": str(self.corpus), "TZ": "UTC", "UMP_PHONE_REGION": "US",
             "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}", **env}
        r = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=CONNECTORS, env=e, capture_output=True, text=True,
                           timeout=180, input=stdin)
        if ok is True:
            self.assertEqual(r.returncode, 0, r.stderr[-3000:] + r.stdout[-2000:])
        elif ok is False:
            self.assertNotEqual(r.returncode, 0, r.stdout[-2000:])
            self.assertNotIn("Traceback", r.stderr, "said plainly, not a crash")
        return r

    def mirror(self, *args, password=None, ok=True):
        env = {"IPHONE_BACKUP_PASSWORD": password} if password else {}
        return self.run_py(f"import iphone_backup; iphone_backup.main({list(args)!r})", ok=ok, **env)

    def mirrored(self):
        return sorted(str(p.relative_to(self.files)) for p in self.files.rglob("*") if p.is_file()) if self.files.exists() else []

    def phone_file(self, domain, rel):
        p = self.files / domain / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def records(self, source):
        f = self.corpus / "normalized" / f"{source}.jsonl"
        return {x["id"]: x for x in map(json.loads, f.read_text().splitlines())} if f.exists() else {}

    def manifest(self):
        f = self.corpus / "manifest.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def notes(self, source):
        return self.manifest().get(source, {}).get("notes", {})


SMS_FILE = ("HomeDomain", "Library/SMS/sms.db")
CALLS_FILE = ("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata")
HEALTH_FILE = ("HealthDomain", "Health/healthdb_secure.sqlite")


# ---------------------------------------------------------------- backups

class BackupTests(Phone):
    def sms_bytes(self, messages=(("m1", "Leeks are up", 0),)):
        self.made = getattr(self, "made", 0) + 1
        return sms_db(self.root / "scratch" / f"sms-{self.made}.db", messages).read_bytes()

    def test_the_latest_finished_backup_not_one_in_progress_or_interrupted(self):
        make_backup(self.backups / "OLDER", [(*SMS_FILE, b"older", 1)], when=dt.datetime(2026, 9, 1))
        make_backup(self.backups / "NEWER", [(*SMS_FILE, b"newer", 1)], when=dt.datetime(2026, 10, 1))
        make_backup(self.backups / "RUNNING", [(*SMS_FILE, b"running", 1)], state="uploading", when=dt.datetime(2026, 10, 2))
        interrupted = make_backup(self.backups / "CUT", [(*SMS_FILE, b"cut", 1)], when=dt.datetime(2026, 10, 3))
        (interrupted / "Info.plist").unlink()  # a first backup cut off before its end: no Info.plist
        for name, mtime in (("OLDER", 1000), ("NEWER", 2000), ("RUNNING", 3000), ("CUT", 4000)):
            for f in (self.backups / name).glob("*.plist"):
                os.utime(f, (mtime, mtime))
        r = self.run_py("import iphone_backup; print(iphone_backup.latest_backup().name)")
        self.assertEqual(r.stdout.strip(), "NEWER")
        # Asked for by name (the app passes --backup), one still in progress is said to be, and nothing is copied.
        r = self.mirror("--backup", str(self.backups / "RUNNING"), ok=False)
        self.assertIn("in progress", r.stderr + r.stdout)
        self.assertEqual(self.mirrored(), [])
        r = self.mirror("--backup", str(self.backups / "CUT"), ok=False)
        self.assertIn("isn't finished", r.stderr + r.stdout)

    def test_only_a_backup_in_progress_says_so(self):
        make_backup(self.backups / "RUNNING", [(*SMS_FILE, b"running", 1)], state="moving")
        r = self.mirror(ok=False)
        self.assertIn("in progress", r.stderr)

    def test_no_backup_folder_at_all(self):
        r = self.mirror(ok=False)
        self.assertIn("No finished backup", r.stderr)

    def test_an_unencrypted_backup_is_read_and_says_what_it_lacks(self):
        make_backup(self.backups / "PLAIN", [(*SMS_FILE, self.sms_bytes(), 1700000000)])
        r = self.mirror()
        self.assertIn("isn't encrypted", r.stdout)
        self.assertIn("Health", r.stdout)
        self.assertEqual(self.mirrored(), ["HomeDomain/Library/SMS/sms.db"])
        self.assertFalse(json.loads((self.corpus / "raw/iphone/backup.json").read_text())["encrypted"])
        # The readers of what it lacks say why, rather than "run iphone_backup.py first", and don't fail.
        out = self.run_py("import health, calls, imessage; health.main(); calls.main(); imessage.main()").stdout
        self.assertIn("isn't encrypted", out)
        self.assertNotIn("run connectors/iphone_backup.py first", out)
        self.assertIn("m1", self.records("imessage"))

    def test_an_encrypted_backup_with_the_right_wrong_or_no_password(self):
        sms = self.sms_bytes()
        make_backup(self.backups / "LOCKED", [(*SMS_FILE, sms, 1700000000), ("AppDomain-com.example.notes", "Documents/n.txt", b"x" * 33, 1)],
                    password=PASSWORD)
        r = self.mirror(password="not the password", ok=False)
        self.assertIn("Wrong password", r.stderr)
        self.assertEqual(self.mirrored(), [], "nothing written")
        r = self.mirror(ok=False)  # no password anywhere: the Keychain stand-in has none either
        self.assertIn("password you set", r.stderr)
        r = self.run_py("import iphone; iphone.main(['--password-stdin'])", ok=False, stdin="\n")  # an empty one, typed in the app
        self.assertIn("Wrong password", r.stderr)
        self.mirror(password=PASSWORD)
        self.assertEqual((self.files / "/".join(SMS_FILE)).read_bytes(), sms)
        self.assertEqual((self.files / "AppDomain-com.example.notes/Documents/n.txt").read_bytes(), b"x" * 33)

    def test_an_ios_10_0_backup_without_the_second_key_round(self):
        """iOS 10.0 and 10.1: no DPSL/DPIC in the keybag (one PBKDF2 round), and Manifest.db not encrypted yet."""
        sms = self.sms_bytes()
        make_backup(self.backups / "TEN", [(*SMS_FILE, sms, 1700000000)], ios="10.1", password=PASSWORD, ios10_2=False)
        self.mirror(password=PASSWORD)
        self.assertEqual((self.files / "/".join(SMS_FILE)).read_bytes(), sms)

    def test_a_missing_or_damaged_index(self):
        b = make_backup(self.backups / "B", [(*SMS_FILE, b"x", 1)])
        (b / "Manifest.db").write_bytes(b"not a database at all" * 300)
        r = self.mirror("--backup", str(b), ok=False)
        self.assertIn("damaged", r.stderr)
        (b / "Manifest.db").unlink()
        make_db(b / "Manifest.db", "create table Other (x)")  # a database, but not a backup's index
        self.assertIn("damaged", self.mirror("--backup", str(b), ok=False).stderr)
        (b / "Manifest.db").unlink()
        self.assertIn("Manifest.db", self.mirror("--backup", str(b), ok=False).stderr)
        locked = make_backup(self.backups / "L", [(*SMS_FILE, b"x", 1)], password=PASSWORD)
        (locked / "Manifest.db").write_bytes((locked / "Manifest.db").read_bytes()[:-7])  # cut short
        self.assertIn("damaged", self.mirror("--backup", str(locked), password=PASSWORD, ok=False).stderr)

    def test_a_backup_from_ios_9_or_earlier_is_too_old(self):
        old = self.backups / "OLD"
        make_backup(old, [], ios="9.3.5")
        (old / "Manifest.db").unlink()
        (old / "Manifest.mbdb").write_bytes(b"mbdb\x05\x00")
        for args in ([], ["--backup", str(old)]):
            r = self.mirror(*args, ok=False)
            self.assertIn("too old", r.stderr)
            self.assertIn("9.3.5", r.stderr)

    def test_an_ipads_backup(self):
        make_backup(self.backups / "TABLET", [(*SMS_FILE, self.sms_bytes(), 1700000000)], product="iPad16,3", device="Fixture iPad")
        r = self.mirror()
        self.assertIn("Fixture iPad (iPad16,3", r.stdout)
        self.assertEqual(json.loads((self.corpus / "raw/iphone/backup.json").read_text())["product"], "iPad16,3")
        # No calls, no Health: each reader says it has none and the others go on.
        self.run_py("import iphone; iphone.main(['--skip-decrypt', '--skip-ileapp'])")
        self.assertIn("m1", self.records("imessage"))

    def test_a_file_missing_from_the_backup_folder(self):
        b = make_backup(self.backups / "B", [(*SMS_FILE, b"one", 1), ("HomeDomain", "Library/Notes/n.db", b"two", 1)])
        self.mirror()
        make_backup(b, [(*SMS_FILE, b"one, again", 2), ("HomeDomain", "Library/Notes/n.db", b"two, again", 2)])
        fid = file_id("HomeDomain", "Library/Notes/n.db")
        (b / fid[:2] / fid).unlink()  # listed in Manifest.db, not on disk
        r = self.mirror()
        self.assertIn("1 failed", r.stdout)
        self.assertEqual((self.files / "/".join(SMS_FILE)).read_bytes(), b"one, again")
        self.assertEqual((self.files / "HomeDomain/Library/Notes/n.db").read_bytes(), b"two", "the copy from before is kept")
        self.assertFalse(list(self.files.rglob("*.part")))
        failures = json.loads((self.corpus / "raw/iphone/extract_failures.json").read_text())
        self.assertEqual([f[:2] for f in failures], [["HomeDomain", "Library/Notes/n.db"]])

    def test_a_damaged_entry_in_the_index_is_skipped(self):
        b = make_backup(self.backups / "B", [(*SMS_FILE, b"one", 1), ("HomeDomain", "Library/Notes/n.db", b"two", 1)])
        con = sqlite3.connect(b / "Manifest.db")
        con.execute("update Files set file = ? where relativePath = 'Library/Notes/n.db'", (b"bplist00 cut short",))
        con.commit()
        con.close()
        r = self.mirror()
        self.assertEqual(self.mirrored(), ["HomeDomain/Library/SMS/sms.db"])
        self.assertIn("1 failed", r.stdout)

    def test_files_removed_from_the_phone_leave_the_copy(self):
        b = make_backup(self.backups / "B", [(*SMS_FILE, b"db", 1), ("HomeDomain", "Library/SMS/sms.db-wal", b"wal", 1),
                                             ("AppDomain-com.example.gone", "Documents/app.db", b"app", 1)], password=PASSWORD)
        self.mirror(password=PASSWORD)
        self.assertEqual(len(self.mirrored()), 3)
        # The app deleted from the phone, the messages' write-ahead log folded in: the next backup has neither.
        make_backup(b, [(*SMS_FILE, b"db, newer", 2)], password=PASSWORD)
        r = self.mirror(password=PASSWORD)
        self.assertEqual(self.mirrored(), ["HomeDomain/Library/SMS/sms.db"], "an old log beside a newer database would corrupt it")
        self.assertIn("2 no longer in the backup", r.stdout)
        state = json.loads((self.corpus / "raw/iphone/mirror_state.json").read_text())
        self.assertEqual(set(state), {file_id(*SMS_FILE)})

    def test_an_unencrypted_backup_after_an_encrypted_one_keeps_what_it_leaves_out(self):
        b = make_backup(self.backups / "B", [(*SMS_FILE, b"db", 1), ("HomeDomain", "Library/SMS/sms.db-wal", b"wal", 1),
                                             (*HEALTH_FILE, b"health", 1), (*CALLS_FILE, b"calls", 1)], password=PASSWORD)
        self.mirror(password=PASSWORD)
        for f in b.iterdir():
            (f.unlink() if f.is_file() else [x.unlink() for x in f.iterdir()])
        make_backup(b, [(*SMS_FILE, b"db, newer", 2)])  # encryption turned off: no Health, no calls in it
        self.mirror()
        self.assertEqual(self.mirrored(), sorted(["/".join(SMS_FILE), "/".join(HEALTH_FILE), "/".join(CALLS_FILE)]),
                         "an unencrypted backup leaves them out by design: they weren't removed from the phone (the old "
                         "log beside the newer messages database goes all the same)")
        # A log the backup has, unchanged, stays beside its database copied anew.
        make_backup(b, [(*SMS_FILE, b"db, newest", 3), ("HomeDomain", "Library/SMS/sms.db-wal", b"wal", 3)])
        self.mirror()
        make_backup(b, [(*SMS_FILE, b"db, newest of all", 4), ("HomeDomain", "Library/SMS/sms.db-wal", b"wal", 3)])
        self.mirror()
        self.assertTrue((self.files / "HomeDomain/Library/SMS/sms.db-wal").exists())

    def test_a_backup_folder_on_an_external_disk(self):
        disk = self.root / "Volumes/Backups/MobileSync"
        make_backup(disk / "EXT", [(*SMS_FILE, self.sms_bytes(), 1700000000)])
        self.backups.parent.mkdir(parents=True)
        self.backups.symlink_to(disk)
        self.mirror()
        self.assertEqual(self.mirrored(), ["HomeDomain/Library/SMS/sms.db"])
        # The disk unplugged: said so, not a crash.
        disk.rename(self.root / "Volumes/Backups/elsewhere")
        r = self.mirror(ok=False)
        self.assertIn("isn't connected", r.stderr)
        r = self.mirror("--backup", str(self.backups / "EXT"), ok=False)
        self.assertIn("isn't there", r.stderr)


# ---------------------------------------------------------------- the phone's own databases

class MessagesTests(Phone):
    def test_an_sms_db_without_the_join_tables(self):
        sms_db(self.phone_file(*SMS_FILE), script="""
            create table handle (ROWID integer primary key, id text);
            create table chat (ROWID integer primary key, guid text, chat_identifier text);
            create table message (ROWID integer primary key, guid text, text text, handle_id int, is_from_me int, date int,
              service text, item_type int, associated_message_type int);
            create table chat_message_join (chat_id int, message_id int);
            insert into handle values (1, '+15555550123');
            insert into chat values (1, 'chat-bea', '+15555550123');""")
        self.run_py("import imessage; imessage.main()")
        got = self.records("imessage")
        self.assertEqual(got["m1"]["text"], "Leeks are up")
        self.assertEqual(got["m1"]["thread"], "chat-bea")
        self.assertEqual(got["m2"]["author"], "me")

    def test_an_sms_db_without_chats_at_all(self):
        sms_db(self.phone_file(*SMS_FILE), script="""
            create table handle (ROWID integer primary key, id text);
            create table message (ROWID integer primary key, guid text, text text, handle_id int, is_from_me int, date int,
              service text, item_type int, associated_message_type int);
            create table chat_message_join (chat_id int, message_id int);
            insert into handle values (1, '+15555550123');""")
        self.run_py("import imessage; imessage.main()")
        self.assertEqual(self.records("imessage")["m1"]["author"], "+15555550123")

    def test_an_attachment_under_var_mobile(self):
        db = sms_db(self.phone_file(*SMS_FILE))
        con = sqlite3.connect(db)
        con.execute("insert into attachment values (1, '/var/mobile/Library/SMS/Attachments/ab/12/A1/IMG_0001.jpeg', 'image/jpeg', "
                    "'IMG_0001.jpeg', 4)")
        con.execute("insert into attachment values (2, '~/Library/SMS/Attachments/cd/34/B2/IMG_0002.jpeg', 'image/jpeg', 'IMG_0002.jpeg', 4)")
        con.execute("insert into message_attachment_join values (1, 1), (1, 2)")
        con.commit()
        for rel in ("Library/SMS/Attachments/ab/12/A1/IMG_0001.jpeg", "Library/SMS/Attachments/cd/34/B2/IMG_0002.jpeg"):
            self.phone_file("MediaDomain", rel).write_bytes(b"jpeg")
        self.run_py("import imessage; imessage.main()")
        files = self.records("imessage")["m1"]["meta"]["files"]
        self.assertEqual([Path(f).name for f in files], ["IMG_0001.jpeg", "IMG_0002.jpeg"])

    def test_a_damaged_sms_db_still_reads_the_macs(self):
        self.phone_file(*SMS_FILE).write_bytes(b"not a database" * 500)
        sms_db(self.home / "Library/Messages/chat.db", (("mac1", "From the Mac", 1),))
        self.run_py("import imessage; imessage.main()")
        self.assertIn("mac1", self.records("imessage"))
        self.assertEqual(self.notes("imessage").get("unreadable"), ["iphone"])


CALLS = """
create table ZCALLRECORD (Z_PK integer primary key, ZUNIQUE_ID varchar, ZDATE real, ZDURATION real, ZADDRESS varchar, ZNAME varchar,
  ZORIGINATED int, ZANSWERED int, ZCALLTYPE int, ZSERVICE_PROVIDER varchar);
"""


class CallsTests(Phone):
    def call(self, pk, uid, when, address="+15555550123"):
        return ("insert into ZCALLRECORD values (?,?,?,60,?,null,1,1,1,'com.apple.Telephony')", (pk, uid, when, address))

    def test_calls_in_the_temporary_store_and_one_without_an_id(self):
        make_db(self.phone_file(*CALLS_FILE), CALLS, [self.call(1, "c1", T), self.call(2, None, T + 3600)])
        # Calls made while the phone was locked wait in CallHistoryTemp.storedata (iLEAPP reads it too).
        make_db(self.phone_file("HomeDomain", "Library/CallHistoryDB/CallHistoryTemp.storedata"), CALLS,
                [self.call(1, "c1", T), self.call(2, "c-temp", T + 7200, "+15555550142")])
        self.run_py("import calls; calls.main()")
        got = self.records("calls")
        self.assertEqual(sorted(got), ["c-temp", "c1", "iphone:2"])
        self.assertEqual(got["c-temp"]["meta"]["copy"], "iphone")

    def test_a_damaged_phone_store_still_reads_the_macs(self):
        self.phone_file(*CALLS_FILE).write_bytes(b"not a database" * 500)
        make_db(self.home / "Library/Application Support/CallHistoryDB/CallHistory.storedata", CALLS, [self.call(1, "mac-call", T)])
        self.run_py("import calls; calls.main()")
        self.assertIn("mac-call", self.records("calls"))
        self.assertEqual(self.notes("calls").get("unreadable"), ["iphone"])


AB = "Library/AddressBook/AddressBook.sqlitedb"


class ContactsTests(Phone):
    def test_an_older_address_book_without_guids_or_entry_tables(self):
        make_db(self.phone_file("HomeDomain", AB), """
            create table ABPerson (ROWID integer primary key, First text, Last text, Organization text, Birthday text,
              CreationDate real, ModificationDate real, Note text);
            create table ABMultiValue (UID integer primary key, record_id int, property int, label int, value text);
            insert into ABPerson values (1, 'Bea', 'Quill', null, 'not a date', 700000000, 700000001, null);
            insert into ABPerson values (2, null, null, 'Allotment Society', '-31579200.000000', 700000000, null, null);
            insert into ABMultiValue values (1, 1, 3, null, '(555) 555-0123');""")
        sms_db(self.phone_file(*SMS_FILE))
        self.run_py("import contacts, imessage; contacts.iphone_contacts(); imessage.main()")
        got = self.records("iphone_contacts")
        self.assertEqual(sorted(r["title"] for r in got.values()), ["Allotment Society", "Bea Quill"])
        self.assertEqual(self.records("imessage")["m1"]["author"], "Bea Quill", "the Resolver reads it")

    def test_an_empty_or_damaged_address_book_doesnt_stop_messages(self):
        sms_db(self.phone_file(*SMS_FILE))
        (self.corpus / "normalized").mkdir()
        (self.corpus / "normalized/iphone_contacts.jsonl").write_text(json.dumps({"id": "c1", "source": "iphone_contacts", "kind": "contact",
                                                                                  "title": "Bea Quill"}) + "\n")
        for contents in (b"", b"not a database" * 500):
            self.phone_file("HomeDomain", AB).write_bytes(contents)
            if not contents:
                sqlite3.connect(self.phone_file("HomeDomain", AB)).close()  # made, never written to
            self.run_py("import contacts, imessage; contacts.iphone_contacts(); imessage.main()")
            self.assertEqual(self.records("imessage")["m1"]["author"], "+15555550123")
            self.assertIn("c1", self.records("iphone_contacts"), "the contacts read before aren't wiped")


HEALTH = """
create table samples (data_id integer primary key, start_date real, end_date real, data_type int);
create table objects (data_id integer primary key, uuid blob, provenance int, type int, creation_date real);
create table data_provenances (ROWID integer primary key, tz_name text, origin_product_type text, source_id int);
create table quantity_samples (data_id integer primary key, quantity real, original_quantity real, original_unit int);
create table category_samples (data_id integer primary key, value int);
insert into data_provenances values (1, 'Europe/London', 'iPhone15,2', 1);
"""


class HealthTests(Phone):
    def health(self, script=HEALTH, samples=()):
        rows = []
        for did, kind, start, end, q, c, prov, otype in samples:
            rows.append(("insert into samples values (?,?,?,?)", (did, start, end, kind)))
            rows.append(("insert into objects (data_id, provenance, type) values (?,?,?)", (did, prov, otype)))
            if q is not None:
                rows.append(("insert into quantity_samples (data_id, quantity) values (?,?)", (did, q)))
            if c is not None:
                rows.append(("insert into category_samples values (?,?)", (did, c)))
        return make_db(self.phone_file(*HEALTH_FILE), script, rows)

    def test_samples_without_provenance_or_object_type(self):
        self.health(samples=[(1, 7, T, T + 60, 100, None, 1, 1), (2, 7, T + 120, T + 180, 50, None, None, 1),
                             (3, 7, T + 240, T + 300, 25, None, 9, 1), (4, 7, T + 360, T + 420, 10, None, 1, None),
                             (5, 7, T + 480, T + 540, 999, None, 1, 2)])  # 5: a deleted sample
        self.run_py("import health; health.main()")
        samples = self.records("health_samples")
        self.assertEqual(sorted(samples), ["sample:1", "sample:2", "sample:3", "sample:4"])
        self.assertIn("(UTC)", samples["sample:2"]["text"])
        self.assertIn("(Europe/London)", samples["sample:4"]["text"])
        self.assertTrue(any(r["kind"] == "health_day" for r in self.records("health").values()))

    def test_an_older_database_without_time_zones_or_category_samples(self):
        self.health("""
            create table samples (data_id integer primary key, start_date real, end_date real, data_type int);
            create table objects (data_id integer primary key, provenance int, type int);
            create table data_provenances (ROWID integer primary key, source_id int);
            create table quantity_samples (data_id integer primary key, quantity real);
            insert into data_provenances values (1, 1);""", [(1, 7, T, T + 60, 100, None, 1, 1)])
        self.run_py("import health; health.main()")
        self.assertEqual(self.records("health_samples")["sample:1"]["meta"]["value"], 100)

    def test_heart_rate_only_in_a_series(self):
        """iOS 15 on: a Watch's readings during a workout are one sample whose values are in quantity_series_data (as iLEAPP's
        health_heart_rate reads them), with no quantity of its own."""
        self.health(HEALTH + """
            create table quantity_sample_series (data_id integer primary key, count int, insertion_era int, hfd_key int, series_location int);
            create table quantity_series_data (series_identifier int, timestamp real, value real, duration real);""",
                    [(1, 5, T, T + 120, None, None, 1, 1), (2, 5, T + 600, T + 600, 1.25, None, 1, 1)])
        con = sqlite3.connect(self.files / "/".join(HEALTH_FILE))
        con.execute("insert into quantity_sample_series values (1, 3, 1, 77, 1)")
        con.executemany("insert into quantity_series_data values (77, ?, ?, 0)", [(T, 1.5), (T + 60, 2.0), (T + 120, 1.75)])
        con.commit()
        con.close()
        self.run_py("import health; health.main()")
        samples = self.records("health_samples")
        series = sorted((r["ts"], r["meta"]["value"]) for k, r in samples.items() if k.startswith("sample:1"))
        self.assertEqual([v for _, v in series], [90.0, 120.0, 105.0])
        self.assertEqual(samples["sample:2"]["meta"]["value"], 75.0, "a sample with its own value is read as before")
        day = next(r for r in self.records("health").values() if r["kind"] == "health_day")
        self.assertEqual(day["meta"]["heart_rate_bpm"], 97.5)
        self.assertEqual(self.notes("health_samples")["no_value"], 0)

    def test_an_empty_or_odd_database_keeps_what_was_read_before(self):
        (self.corpus / "normalized").mkdir()
        (self.corpus / "normalized/health.jsonl").write_text(json.dumps({"id": "day:2025-09-19", "source": "health", "kind": "health_day"}) + "\n")
        make_db(self.phone_file(*HEALTH_FILE))  # made, never written to
        out = self.run_py("import health; health.main()").stdout
        self.assertIn("day:2025-09-19", self.records("health"))
        self.assertIn("no samples", out)

    def test_app_names_missing_and_a_sample_without_an_end(self):
        self.health(samples=[(1, 7, T, None, 100, None, 1, 1), (2, 63, T, T + 3600, None, 4, 1, 1), (3, 7, None, None, 5, None, 1, 1)])
        make_db(self.phone_file("HealthDomain", "Health/healthdb.sqlite"), "create table source_devices (ROWID integer primary key, name text)")
        self.run_py("import health; health.main()")
        samples = self.records("health_samples")
        self.assertEqual(sorted(samples), ["sample:1", "sample:2"])
        self.assertEqual(samples["sample:2"]["text"][:12], "Sleep: deep,")
        self.assertEqual(self.notes("health_samples").get("no_time"), 1)


WA = ("AppDomainGroup-group.net.whatsapp.WhatsApp.shared", "ChatStorage.sqlite")


class WhatsAppTests(Phone):
    def test_an_empty_mac_database_and_a_phone_one_without_messages(self):
        make_db(self.home / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite")
        make_db(self.phone_file(*WA), "create table ZWACHATSESSION (Z_PK integer primary key, ZCONTACTJID text)")
        (self.corpus / "manifest.json").write_text(json.dumps({"phone_whatsapp": {"last": "2025-09-19T00:00:00Z", "kinds": {"message": 3}}}))
        out = self.run_py("import whatsapp; print(len(whatsapp.phone_stanzas())); whatsapp.main(); print(len(whatsapp.group_senders()))")
        self.assertEqual(out.stdout.split()[0], "0")
        self.assertEqual(self.records("whatsapp"), {})

    def test_a_mac_database_without_group_members(self):
        make_db(self.home / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite", """
            create table ZWACHATSESSION (Z_PK integer primary key, ZCONTACTJID text, ZPARTNERNAME text);
            create table ZWAMESSAGE (Z_PK integer primary key, ZCHATSESSION int, ZISFROMME int, ZMESSAGEDATE real, ZTEXT text, ZSTANZAID text);
            insert into ZWACHATSESSION values (1, '15555550123@s.whatsapp.net', 'Bea Quill');""",
                [("insert into ZWAMESSAGE values (1, 1, 0, ?, 'Leeks?', 'S1')", (T,))])
        self.run_py("import whatsapp; whatsapp.main()")
        self.assertEqual(self.records("whatsapp")["S1"]["text"], "Leeks?")


class MapsTests(Phone):
    def test_a_cut_off_line_in_the_phones_maps_doesnt_hide_the_rest(self):
        (self.corpus / "normalized").mkdir()
        good = {"id": "r2", "meta": {"fields": {"Timestamp": "2025-09-19T18:40:00Z", "Location Search": "allotments"}}}
        (self.corpus / "normalized/phone_mapssync.jsonl").write_text('{"id": "r1", "meta": {"fiel\n' + json.dumps(good) + "\n[]\n")
        out = self.run_py("import apple_maps; print(sorted(apple_maps.phone_recents()))").stdout
        self.assertIn("allotments", out)


# ---------------------------------------------------------------- iLEAPP's output

def lava(folder, tables, artifacts, media=()):
    """iLEAPP's kept output: _lava_artifacts.db (one table per artifact) and _lava_data.lava (each artifact's metadata)."""
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / "_lava_artifacts.db")
    for name, (cols, rows) in tables.items():
        con.execute(f'create table "{name}" ({", ".join(cols)})')
        con.executemany(f'insert into "{name}" values ({", ".join("?" * len(cols))})', rows)
    if media is not None:
        con.execute("create table _lava_media_items (id text, source_path text)")
        con.execute("create table _lava_media_references (id text, media_item_id text)")
        for ref, item, path in media:
            con.execute("insert into _lava_media_items values (?, ?)", (item, path))
            con.execute("insert into _lava_media_references values (?, ?)", (ref, item))
    con.commit()
    con.close()
    (folder / "_lava_data.lava").write_text(json.dumps({"parser_info": {"leapp_version": "fixture"}, "artifacts": artifacts}))
    (folder / "run.json").write_text(json.dumps({"ileapp": "fixture"}))
    return folder


def artifact(module, key, name, table, cols, types=None, count=1, conversation=None):
    a = {"artifact_key": key, "name": name, "tablename": table, "module": module, "column_map": {c: c.replace("_", " ").title() for c in cols},
         "record_count": count, "object_columns": [{"name": c, "type": t} for c, t in (types or {}).items()]}
    if conversation:
        a["data_views"] = {"conversation": conversation}
    return a


class IleappTests(Phone):
    def import_latest(self, folder, ok=True):
        return self.run_py(f"import ileapp; ileapp.import_latest({str(folder)!r})", ok=ok)

    def test_one_artifact_that_cant_be_read_doesnt_stop_the_others(self):
        out = lava(self.root / "latest", {
            "notes_a": (["id", "title", "created"], [("n1", "Seed order", 1700000000)]),
            "trips": (["trip_id", "city", "start"], [("t1", "Lisbon", 1700000000)])},
            {"Notes": [artifact("notesApp", "notesA", "Notes - Notes", "notes_a", ["id", "title", "created"], {"created": "datetime"}),
                       artifact("notesApp", "notesB", "Notes - Missing", "notes_missing", ["id"]),  # its table never written
                       {"name": "Notes - No metadata", "module": "notesApp", "record_count": 3}],
             "Travel": [artifact("travelApp", "trips", "Travel - Trips", "trips", ["trip_id", "city", "start"], {"start": "datetime"})]})
        self.import_latest(out)
        self.assertEqual(list(self.records("phone_notesapp")), ["notesA:n1"])
        self.assertEqual(list(self.records("phone_travelapp")), ["trips:t1"], "a module after the one that failed")
        unread = self.manifest()["_ileapp_left_out"]["couldn't be read"]
        self.assertEqual(sorted(unread), ["Notes - Missing", "Notes - No metadata"])

    def test_no_media_tables_media_lists_and_odd_values(self):
        conv = {"conversationDiscriminatorColumn": "chat", "textColumn": "body", "directionColumn": "dir", "directionSentValue": "out",
                "timeColumn": "sent", "senderColumn": "sender"}
        tables = {"msgs": (["msg_id", "chat", "body", "dir", "sent", "sender", "pics"],
                           [("1", "c1", "Look", "in", 1700000000, b"Bea Quill", '["r1", "r2"]'),
                            ("2", "c1", None, "in", "sometime in May", None, "r1")])}
        a = artifact("chatApp", "chatMessages", "Chat - Messages", "msgs", tables["msgs"][0], {"sent": "datetime", "pics": "media"},
                     conversation=conv)
        photo = self.phone_file("AppDomain-com.example.chat", "Documents/p1.jpg")
        photo.write_bytes(b"jpeg")
        self.phone_file("AppDomain-com.example.chat", "Documents/p2.jpg").write_bytes(b"jpeg")
        root = "private/var/mobile/Containers/Data/Application/com.example.chat/Documents/"
        out = lava(self.root / "latest", tables, {"Chats": [a]}, media=[("r1", "i1", root + "p1.jpg"), ("r2", "i2", root + "p2.jpg")])
        self.import_latest(out)
        got = self.records("phone_chatapp")
        self.assertEqual([Path(f).name for f in got["chatMessages:1"]["meta"]["files"]], ["p1.jpg", "p2.jpg"])
        self.assertEqual(got["chatMessages:1"]["author"], "Bea Quill")
        self.assertEqual(got["chatMessages:2"]["text"], "[1 attachment]")
        # Without the media tables (no module stored a file): read all the same.
        (out / "_lava_artifacts.db").unlink()
        lava(out, {"msgs": tables["msgs"]}, {"Chats": [a]}, media=None)
        self.import_latest(out)
        self.assertIn("chatMessages:2", self.records("phone_chatapp"))

    def test_a_datetime_column_holding_text_keeps_it(self):
        out = lava(self.root / "latest", {"t": (["order_id", "placed"], [("o1", "sometime in May")])},
                   {"Shopping": [artifact("shop", "orders", "Shop - Orders", "t", ["order_id", "placed"], {"placed": "datetime"})]})
        self.import_latest(out)
        self.assertEqual(self.records("phone_shop")["orders:o1"]["meta"]["fields"]["Placed"], "sometime in May")

    def test_a_large_artifact_keeps_its_ids_from_one_import_to_the_next(self):
        rows = [(f"v{i}", f"https://example.test/{i % 997}", 1600000000 + i) for i in range(30000)]
        rows += rows[:50]  # a join repeating rows
        out = lava(self.root / "latest", {"h": (["visit_id", "url", "visited"], rows)},
                   {"Browser": [artifact("browser", "history", "Browser - History", "h", ["visit_id", "url", "visited"], {"visited": "datetime"})]})
        self.import_latest(out)
        first = self.records("phone_browser")
        self.assertEqual(len(first), 30000)
        self.assertIn("history:v29999", first)
        self.import_latest(out)
        self.assertEqual(set(self.records("phone_browser")), set(first))

    def test_lava_metadata_that_cant_be_read_is_said_plainly(self):
        out = lava(self.root / "latest", {}, {})
        (out / "_lava_data.lava").write_text('{"artifacts": {"Notes": [')  # cut off
        r = self.import_latest(out, ok=False)
        self.assertIn("iLEAPP", r.stderr)

    def fake_ileapp(self, exit_code, log, write=True):
        """A stand-in for iLEAPP's Python: writes its kept output and log as iLEAPP would, then exits with exit_code."""
        script = self.root / "fake_ileapp.py"
        script.write_text(textwrap.dedent(f"""\
            #!{sys.executable}
            import json, sqlite3, sys
            from pathlib import Path
            args = sys.argv[1:]
            run = Path(args[args.index("-o") + 1]) / args[args.index("--custom_output_folder") + 1]
            run.mkdir(parents=True, exist_ok=True)
            if {write!r}:
                con = sqlite3.connect(run / "_lava_artifacts.db")
                con.execute("create table notes_a (id, title)")
                con.execute("insert into notes_a values ('n1', 'Seed order')")
                con.commit()
                art = {{"artifact_key": "notesA", "name": "Notes - Notes", "tablename": "notes_a", "module": "notesApp",
                        "column_map": {{"id": "ID", "title": "Title"}}, "record_count": 1}}
                (run / "_lava_data.lava").write_text(json.dumps({{"artifacts": {{"Notes": [art]}}}}))
            print({log!r})
            sys.exit({exit_code})
            """))
        script.chmod(0o755)
        return script

    def run_ileapp(self, script, ok=True):
        self.phone_file("HomeDomain", "Library/Notes/n.db").write_bytes(b"x")
        make_backup(self.backups / "B", [])
        return self.run_py(f"""
            import ileapp
            from pathlib import Path
            ileapp.VENV_PY = Path({str(script)!r})
            ileapp.write_profile = lambda path: 3
            ileapp.MIN_FREE = 0
            ileapp.import_latest(ileapp.run())""", ok=ok)

    def test_an_artifact_that_raises_inside_ileapp_and_an_error_after_it_finished(self):
        log = "Reading Notes artifact had errors!\nCrash [crashy] artifact failed after 0.1s\nProcesses completed.\nReport generation failed"
        self.run_ileapp(self.fake_ileapp(1, log))
        self.assertEqual(list(self.records("phone_notesapp")), ["notesA:n1"], "its output was complete: read")
        run = json.loads(next((self.home / "Library/Application Support/q1_user_model/ileapp").glob("*/latest/run.json")).read_text())
        self.assertEqual(run["failed_artifacts"], ["crashy/Crash"])

    def test_ileapp_stopping_early_is_said_plainly(self):
        r = self.run_ileapp(self.fake_ileapp(1, "Had an exception in Seeker", write=False), ok=False)
        self.assertIn("iLEAPP", r.stderr)
        r = self.run_ileapp(self.fake_ileapp(0, "Processes completed.", write=False), ok=False)  # finished, its output missing
        self.assertIn("iLEAPP", r.stderr)

    def test_ileapp_failing_doesnt_stop_the_phone_import(self):
        sms_db(self.phone_file(*SMS_FILE))
        make_backup(self.backups / "B", [])
        r = self.run_py("""
            import ileapp, iphone
            def broken(backup=None, force=False):
                raise SystemExit("[ileapp] iLEAPP exited 1 after 3s; see ileapp.log")
            ileapp.run = broken
            iphone.main(['--skip-decrypt'])""", ok=False)
        self.assertIn("m1", self.records("imessage"))
        self.assertTrue((self.corpus / "corpus.db").exists(), "the index is rebuilt")
        self.assertIn("other apps", r.stderr)


if __name__ == "__main__":
    unittest.main()
