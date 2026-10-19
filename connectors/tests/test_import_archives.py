"""Downloads as they really arrive: zips made on Windows (backslashes, the DOS code page) and on a Mac (UTF-8 names that don't
say so, __MACOSX/ and ._ files), zips in zips two deep or damaged, zips locked with a password or packed in a way Python
can't unpack, the same name twice, empty and cut-short zips, zip64, tars, zip and tar bombs, downloads still being written,
the same export twice; and mailboxes in a folder named as another source is. Everything is made up here, in temporary
folders; the importer runs as the app runs it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_import_archives.py'
"""
import io
import json
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[1]


def conversations(title="Hello", text="hi there"):
    """A ChatGPT export's conversations.json, one chat."""
    return json.dumps([{"title": title, "create_time": 1700000000, "current_node": "b", "mapping": {
        "a": {"id": "a", "parent": None, "children": ["b"], "message": {
            "author": {"role": "user"}, "create_time": 1700000000, "content": {"content_type": "text", "parts": [text]}}},
        "b": {"id": "b", "parent": "a", "children": [], "message": {
            "author": {"role": "assistant"}, "create_time": 1700000001, "content": {"content_type": "text", "parts": ["hello"]}}}}}])


def mbox(*mids):
    return "".join(f"From a@example.test Mon Jan 01 00:00:00 2024\nFrom: Grace <grace@example.test>\nTo: Ada <ada@example.test>\n"
                   f"Message-ID: <{m}@example.test>\nSubject: hi {m}\nDate: Mon, 01 Jan 2024 00:00:00 +0000\n\nHello.\n\n" for m in mids)


def zip_bytes(files, method=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", method) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return b.getvalue()


def patch_headers(raw, flags_off=0, flags_on=0, method=None, size=None):
    """A zip's bytes with every member's flags (and method, or uncompressed size) changed in both its headers, as zips made
    elsewhere have them."""
    raw = bytearray(raw)
    for sig, flags, meth, usize in ((b"PK\x03\x04", 6, 8, 22), (b"PK\x01\x02", 8, 10, 24)):
        i = 0
        while (i := raw.find(sig, i)) >= 0:
            struct.pack_into("<H", raw, i + flags, struct.unpack_from("<H", raw, i + flags)[0] & ~flags_off | flags_on)
            if method is not None:
                struct.pack_into("<H", raw, i + meth, method)
            if size is not None:
                struct.pack_into("<I", raw, i + usize, size)
            i += 4
    return bytes(raw)


def named_raw(files):
    """A zip whose names are written as given (bytes), without the UTF-8 flag, as Archive Utility and old Windows write them."""
    placeholders = {f"N{i:04d}" + "x" * (len(n) - 5): n for i, n in enumerate(files)}
    raw = zip_bytes({p: files[n] for p, n in placeholders.items()})
    for p, n in placeholders.items():
        raw = raw.replace(p.encode(), n)
    return patch_headers(raw, flags_off=0x800)


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus = self.root / "home", self.root / "corpus"
        self.imports = self.corpus / "imports"
        self.home.mkdir()
        self.imports.mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps({"names": ["Ada Lovelace"], "emails": ["ada@example.test"], "usernames": []}))

    def put(self, rel, data):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
        return p

    def run_import(self, extra_env=None):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "UTC", **(extra_env or {})}
        r = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], cwd=CONNECTORS, env=env, capture_output=True, text=True,
                           timeout=300)
        self.out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, self.out[-3000:])
        self.recs = {f.stem: [json.loads(line) for line in f.read_text().splitlines()] for f in (self.corpus / "normalized").glob("*.jsonl")}
        m = self.corpus / "manifest.json"  # (none when nothing could be read)
        self.manifest = json.loads(m.read_text()) if m.exists() else {}
        return self.recs

    def of(self, source, kind=None):
        return [r for r in self.recs.get(source, []) if kind is None or r["kind"] == kind]

    def ledger(self):
        return {g["group"]: g for g in self.manifest.get("_imports_unclaimed", [])}

    def entries(self, code="print(json.dumps([(e.origin, e.path) for e in imports.entries()]))"):
        """imports.entries() in a Python of its own, with how much memory it took at most (MB)."""
        script = ("import json, resource, sys; sys.path.insert(0, sys.argv[1]); import imports\n" + code +
                  "\nprint(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // (1 << 20))")
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus)}
        r = subprocess.run([sys.executable, "-c", script, str(CONNECTORS)], env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        lines = r.stdout.strip().splitlines()
        return json.loads(lines[-2]), int(lines[-1])


class NamesAndPaths(Base):
    def test_nothing_reads_or_writes_outside_its_folder(self):
        # Zip slip, the Unix and the Windows ways; a media file named to land outside corpus/media
        self.put("chatgpt/slip.zip", zip_bytes({"conversations.json": conversations(), "../../evil.txt": "x", "/abs.txt": "x",
                                                "..\\..\\evil2.txt": "x", "C:\\evil3.txt": "x", "a/../../evil4.txt": "x",
                                                "photos\\..\\..\\..\\evil5.jpg": b"\xff\xd8"}))
        self.run_import()
        self.assertEqual(len(self.of("chatgpt")), 2)
        self.assertEqual(sorted(p.name for p in self.root.rglob("evil*")), [])
        self.assertNotIn("evil", json.dumps(self.recs))

    def test_a_zip_made_on_windows_with_backslashes(self):
        self.put("chatgpt/win.zip", zip_bytes({"export\\conversations.json": conversations(), "export\\user.json": '{"email": "a@b.c"}'}))
        self.run_import()
        self.assertEqual(len(self.of("chatgpt")), 2, "read as the export it is, not left to the catch-all")

    def test_names_in_utf8_that_dont_say_so_and_in_the_dos_code_page(self):
        # Archive Utility writes UTF-8 (decomposed, as macOS names files) without the UTF-8 flag; old Windows the DOS code page.
        self.put("docs/mac.zip", named_raw({"notes/Cafe\u0301 notes.txt".encode(): "about the café",
                                             "notes/日本語.txt".encode(): "nihongo"}))
        self.put("docs/win.zip", named_raw({"Résumé.txt".encode("cp437"): "my résumé",
                                             "中文.txt".encode("gbk"): "zhongwen"}))
        self.run_import()
        titles = sorted(r["title"] for r in self.of("imported_documents"))
        self.assertIn("Café notes", titles)
        self.assertIn("日本語", titles)
        self.assertIn("Résumé", titles)
        self.assertEqual(len(titles), 4, "a name in a code page that can't be known is read as it is, not dropped")

    def test_what_a_mac_adds_to_a_zip_is_not_data(self):
        junk = b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        "
        self.put("chatgpt/mac.zip", zip_bytes({"conversations.json": conversations(), "__MACOSX/._conversations.json": junk,
                                               "._Inbox.mbox": junk, "._photo.jpg": junk, "._notes.txt": junk, "sub/.DS_Store": junk}))
        self.run_import()
        self.assertEqual(sorted(self.recs), ["chatgpt"], "no mail, photo or document made of Finder's details")
        self.assertEqual(self.ledger(), {}, "and nothing listed as unread")

    def test_the_same_name_twice_reads_the_last(self):
        # Zips appended to keep both copies; unzipping leaves the last
        b = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(b, "w") as z:
            warnings.simplefilter("ignore")
            z.writestr("conversations.json", conversations("Old", "old words"))
            z.writestr("conversations.json", conversations("New", "new words"))
        self.put("chatgpt/twice.zip", b.getvalue())
        self.run_import()
        self.assertEqual(sorted(r["text"] for r in self.of("chatgpt")), ["hello", "new words"])


class Nesting(Base):
    def test_zips_in_zips_two_deep_and_a_damaged_one(self):
        inner = zip_bytes({"conversations.json": conversations()})
        self.put("chatgpt/two.zip", zip_bytes({"mid.zip": zip_bytes({"inner.zip": inner})}))
        self.put("claude/broken.zip", zip_bytes({"inner.zip": inner[: len(inner) // 2], "notes.txt": "kept"}))
        self.run_import()
        self.assertEqual(len(self.of("chatgpt")), 2)
        self.assertIn("claude/broken.zip: inner.zip can't be opened", self.out)
        self.assertEqual([r["text"] for r in self.of("imported_documents")], ["kept"], "the rest of it is read")

    def test_zips_too_deep_or_bombs_are_left_out_and_listed(self):
        deep = zip_bytes({"conversations.json": conversations()})
        for n in range(4):
            deep = zip_bytes({f"level{n}.zip": deep})
        self.put("chatgpt/deep.zip", deep)
        # A member that says it unpacks to 2 GB from a few bytes, and a zip inside saying so too
        self.put("svc/bomb.zip", patch_headers(zip_bytes({"Records.json": "{}" * 50}), size=2 << 30))
        self.put("svc/nested-bomb.zip", zip_bytes({"a.zip": patch_headers(zip_bytes({"x.json": "{}" * 50}), size=2 << 30),
                                                   "ok.txt": "fine"}))
        self.run_import()
        self.assertNotIn("chatgpt", self.recs)
        self.assertIn("a zip inside zips more than 3 deep", self.out)
        self.assertIn("which only a zip bomb does", self.out)
        why = [w for g in self.ledger().values() for w in g.get("left_out", [])]
        self.assertTrue(any("deep" in w for w in why) and any("bomb" in w for w in why), why)
        self.assertEqual([r["text"] for r in self.of("imported_documents")], ["fine"])

    def test_a_big_zip_inside_is_never_all_in_memory(self):
        # Stored (Notion's parts): read in place. Packed and over 64 MB: copied to an unnamed file first.
        page = "Export-0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f/page 0123456789abcdef0123456789abcdef.md"
        big = os.urandom(150 << 20)
        part = zip_bytes({page: "# Page\nbody", "Export-0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f/big.bin": big}, zipfile.ZIP_STORED)
        self.put("notion/Export.zip", zip_bytes({"Export-0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f-Part-1.zip": part}, zipfile.ZIP_STORED))
        del big
        es, peak = self.entries()
        self.assertIn(["notion/Export.zip", f"Export-0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f-Part-1.zip/{page}"], es)
        self.assertLess(peak, 120, "a 150 MB part read in place, not into memory")
        (self.imports / "notion/Export.zip").unlink()
        self.put("notion/Packed.zip", zip_bytes({"part.zip": zip_bytes({page: "# Page\nbody", "pad.bin": os.urandom(2 << 20)})}))
        out, _ = self.entries("import common; common.IN_MEMORY = 1 << 20\n"
                              "es = imports.entries(); print(json.dumps([es[0].path, es[0].read().decode()[:6]]))")
        self.assertEqual(out, [f"part.zip/{page}", "# Page"], "read from its copy on disk")
        self.assertEqual([p.name for p in (self.corpus / "raw").iterdir() if p.is_file()], [], "and the copy is gone")


class LockedAndUnreadable(Base):
    def test_a_zip_locked_with_a_password_says_so(self):
        self.put("wechat/export.zip", patch_headers(zip_bytes({"moments.json": "[]", "chats.json": "[]"}), flags_on=0x1))
        self.put("chatgpt/data.zip", zip_bytes({"conversations.json": conversations()}))
        self.run_import()
        self.assertIn("wechat/export.zip: 2 file(s) in it left out: locked with a password", self.out)
        self.assertNotIn("Traceback", self.out)
        self.assertEqual(len(self.of("chatgpt")), 2, "the rest is read")
        self.assertEqual(self.ledger()["wechat :: "]["left_out"], ["locked with a password"])

    def test_packed_in_a_way_python_cant_unpack(self):
        # Windows packs big files with Deflate64 (method 9): Finder unpacks it, Python can't
        self.put("svc/win64.zip", patch_headers(zip_bytes({"notes.txt": "x"}), method=9))
        self.run_import()
        self.assertIn("left out: packed in a way that can't be read here. Double-click it in Finder", self.out)
        self.assertNotIn("imported_documents", self.recs)

    def test_empty_folders_only_cut_short_and_zip64(self):
        self.put("a/empty.zip", zip_bytes({}))
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr(zipfile.ZipInfo("a/"), b"")
            z.writestr(zipfile.ZipInfo("a/b/"), b"")
        self.put("a/dirs.zip", b.getvalue())
        whole = zip_bytes({"conversations.json": conversations()})
        self.put("chatgpt/cut.zip", whole[: len(whole) * 2 // 3])
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z, z.open("conversations.json", "w", force_zip64=True) as f:
            f.write(conversations("Big one").encode())
        self.put("claude/z64.zip", b.getvalue())
        self.run_import()
        self.assertIn("chatgpt/cut.zip can't be opened", self.out)
        self.assertEqual(sorted(r["text"] for r in self.of("chatgpt")), ["hello", "hi there"], "the zip64 one")
        self.assertEqual(sorted(self.recs), ["chatgpt"])

    def test_a_download_still_being_written(self):
        whole = zip_bytes({"conversations.json": conversations()})
        self.put("chatgpt/data.zip.crdownload", whole[:100])
        self.put("chatgpt/data.zip.download/data.zip", whole[:100])  # Safari's: a folder
        self.put("chatgpt/data.zip.part", whole[:100])
        self.run_import()
        self.assertNotIn("chatgpt", self.recs)
        self.assertEqual(self.out.count("left out: still downloading"), 3)
        self.assertNotIn("cut short", self.out)


class Tars(Base):
    def tgz(self, rel, members):
        b = io.BytesIO()
        with tarfile.open(fileobj=b, mode="w:gz") as t:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        return self.put(rel, b.getvalue())

    def test_a_tgz_is_read_without_what_a_mac_adds(self):
        self.tgz("takeout/takeout-20250101T000000Z-001.tgz", {"Takeout/Mail/All mail.mbox": mbox("t1").encode(),
                                                              "Takeout/Mail/._All mail.mbox": mbox("junk").encode()})
        self.run_import()
        self.assertEqual([r["id"] for r in self.of("gmail")], ["<t1@example.test>"])

    def test_a_tar_bomb_is_never_unpacked(self):
        # Its header says 50 GB; the data isn't there: it's left out on the header, before anything is unpacked
        head = tarfile.TarInfo("Records.json")
        head.size = 50 << 30
        import gzip
        self.put("svc/bomb.tar.gz", gzip.compress(head.tobuf() + b"\0" * 4096))
        self.run_import()
        self.assertIn("svc/bomb.tar.gz: it left out: unpacks to over 100 times its size", self.out)
        self.assertFalse(any((self.corpus / "raw" / "unpacked").rglob("Records.json")))


class Twice(Base):
    def test_the_same_export_twice_is_read_once(self):
        data = zip_bytes({"conversations.json": conversations()})
        self.put("chatgpt/data.zip", data)
        self.put("chatgpt/data (2).zip", data)
        self.run_import()
        self.assertEqual(len(self.of("chatgpt")), 2)


class MailboxFolders(Base):
    def test_a_mailbox_in_another_sources_folder_is_a_source_of_its_own(self):
        # Before: a mailbox in imports/mail/ replaced what Mail on this Mac read, one in imports/instagram/ joined its messages.
        norm = self.corpus / "normalized"
        norm.mkdir()
        (norm / "contacts.jsonl").write_text('{"id": "c1", "source": "contacts", "kind": "contact", "text": "from this Mac"}\n')
        (self.corpus / "manifest.json").write_text(json.dumps({"contacts": {"count": 1, "parser": "connectors/contacts.py:mac_contacts"}}))
        self.put("contacts/Inbox.mbox", mbox("c1"))
        who = '<emailAddress OPFContactEmailAddressAddress="grace@example.test" OPFContactEmailAddressName="Grace" OPFContactEmailAddressType="0"/>'
        self.put("mail/Outlook.olm", zip_bytes({"Accounts/a/com.microsoft.__Messages/Inbox/message_00001.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n<emails elementCount="1"><email xml:space="preserve"><OPFMessageCopySubject>Olm'
            '</OPFMessageCopySubject><OPFMessageCopyMessageID>&lt;o1@example.test&gt;</OPFMessageCopyMessageID>'
            f'<OPFMessageCopyFromAddresses>{who}</OPFMessageCopyFromAddresses><OPFMessageCopyToAddresses>{who}</OPFMessageCopyToAddresses>'
            '<OPFMessageCopySentTime>2024-01-01T00:00:00</OPFMessageCopySentTime><OPFMessageCopyHTMLBody>hi</OPFMessageCopyHTMLBody>'
            '</email></emails>')}))
        self.put("instagram/instagram-ada-2026-10-01-abc.zip", zip_bytes({
            "your_instagram_activity/messages/inbox/grace_1/message_1.json": json.dumps({
                "participants": [{"name": "Grace"}, {"name": "Ada Lovelace"}],
                "messages": [{"sender_name": "Grace", "timestamp_ms": 1700000000000, "content": "hey"}]})}))
        self.put("instagram/Inbox.mbox", mbox("i1"))
        self.put("hotmail/Inbox.mbox", mbox("h1"))
        self.put("gmail/Archive.mbox", mbox("g1"))
        self.put("whatsapp/receipt.eml", mbox("w1").split("\n", 1)[1])  # an attachment of a chat there: not mail
        self.run_import()
        self.assertEqual([r["text"] for r in self.of("contacts")], ["from this Mac"], "Contacts' records stay as they were")
        self.assertEqual([r["id"] for r in self.of("contacts_mail")], ["<c1@example.test>"])
        self.assertEqual([r["id"] for r in self.of("mail_mail")], ["<o1@example.test>"])
        self.assertNotIn("mail", self.recs)
        self.assertEqual({r["kind"] for r in self.of("instagram")}, {"message"}, "no mail mixed in with Instagram's messages")
        self.assertEqual([r["id"] for r in self.of("instagram_mail")], ["<i1@example.test>"])
        self.assertEqual([r["id"] for r in self.of("hotmail")], ["<h1@example.test>"], "hotmail and gmail are mail: as before")
        self.assertEqual([r["id"] for r in self.of("gmail")], ["<g1@example.test>"])
        self.assertNotIn("whatsapp_mail", self.recs)

    def test_a_mac_source_a_mailbox_replaced_before_goes_and_is_read_again(self):
        norm = self.corpus / "normalized"
        norm.mkdir()
        (norm / "mail.jsonl").write_text('{"id": "<m1@example.test>", "source": "mail", "kind": "email", "text": "the mailbox"}\n')
        (norm / "calls.jsonl").write_text('{"id": "k1", "source": "calls", "kind": "call"}\n')
        (self.corpus / "manifest.json").write_text(json.dumps({"mail": {"count": 1, "parser": "connectors/imports.py:google"},
                                                               "calls": {"count": 1, "parser": "connectors/calls.py:main"}}))
        self.put("mail/Inbox.mbox", mbox("m1"))
        self.run_import()
        self.assertFalse((norm / "mail.jsonl").exists(), "it held only the mailbox: Mail's own connector reads Mail again")
        self.assertNotIn("mail", self.manifest)
        self.assertEqual([r["id"] for r in self.of("mail_mail")], ["<m1@example.test>"], "its mail, under its own name, same ids")
        self.assertTrue((norm / "calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
