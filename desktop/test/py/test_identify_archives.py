"""bridge.py identify on downloads as they really arrive: zips made on Windows and on a Mac, zips in zips, locked or packed in a
way Python can't unpack, empty, cut short, zip64, still downloading (Chrome, Safari, Firefox), a part of a Meta download with
only its photos, Outlook's archive and a folder of messages, zip and tar bombs; and which mail sources the probe lists, named
as imports.py names them. Made up here, in temporary folders; the bridge runs as the app runs it."""

import gzip
import io
import json
import struct
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge import Sandbox, bridge, jsonout  # noqa: E402

CHATGPT = {"conversations.json": json.dumps([{"title": "Hi", "mapping": {}}]), "user.json": '{"email": "ada@example.com"}'}


def zip_bytes(files, method=zipfile.ZIP_DEFLATED):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", method) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return b.getvalue()


def patch_headers(raw, flags_off=0, flags_on=0, method=None, size=None):
    """Every member's flags (and method, or uncompressed size) changed in both its headers."""
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


class IdentifyArchiveTests(Sandbox):
    def make(self, name, data):
        p = self.tmp / "Downloads" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def identify(self, *paths):
        return {Path(r["path"]).name: r for r in jsonout(bridge(["identify", *map(str, paths)], self.home, self.corpus))}

    def test_names_as_windows_and_a_mac_write_them(self):
        mac = zip_bytes({"Cafe\u0301/conversations.json": CHATGPT["conversations.json"], "Cafe\u0301/user.json": "{}"})
        mac = patch_headers(mac, flags_off=0x800)  # Archive Utility's: UTF-8 names, without the flag that says so
        junk = b"\x00\x05\x16\x07junk"
        r = self.identify(
            self.make("win.zip", zip_bytes({"export\\conversations.json": CHATGPT["conversations.json"], "export\\user.json": "{}"})),
            self.make("mac.zip", mac),
            self.make("finder.zip", zip_bytes({**CHATGPT, "__MACOSX/._conversations.json": junk, "._Inbox.mbox": junk})),
            self.make("only-junk.zip", zip_bytes({"._Inbox.mbox": junk, "__MACOSX/._x": junk})))
        self.assertEqual(r["win.zip"]["kind"], "chatgpt", r["win.zip"])
        self.assertEqual(r["mac.zip"]["kind"], "chatgpt", r["mac.zip"])
        self.assertEqual(r["finder.zip"]["kind"], "chatgpt", "Finder's ._ files aren't a mailbox")
        self.assertEqual((r["only-junk.zip"]["kind"], r["only-junk.zip"].get("empty")), (None, True), "nothing but Finder's details")

    def test_zips_in_zips_two_deep_damaged_and_locked(self):
        inner = zip_bytes(CHATGPT)
        locked = patch_headers(inner, flags_on=0x1)
        r = self.identify(self.make("one.zip", zip_bytes({"a.zip": inner})), self.make("two.zip", zip_bytes({"b.zip": zip_bytes({"a.zip": inner})})),
                          self.make("broken.zip", zip_bytes({"a.zip": inner[: len(inner) // 2]})),
                          self.make("locked-inside.zip", zip_bytes({"a.zip": locked})),
                          self.make("stored.zip", zip_bytes({"a.zip": inner}, zipfile.ZIP_STORED)))
        self.assertEqual([r[n]["kind"] for n in ("one.zip", "two.zip", "stored.zip")], ["chatgpt"] * 3)
        self.assertFalse(r["broken.zip"]["valid"])
        self.assertIn("not a complete zip", r["broken.zip"]["reason"])
        self.assertTrue(r["locked-inside.zip"]["encrypted"], "a zip locked with a password inside another says so too")

    def test_what_cant_be_used_says_why(self):
        whole = zip_bytes(CHATGPT)
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr(zipfile.ZipInfo("a/"), b"")
            z.writestr(zipfile.ZipInfo("a/b/"), b"")
        z64 = io.BytesIO()
        with zipfile.ZipFile(z64, "w") as z:
            for n, d in CHATGPT.items():
                with z.open(n, "w", force_zip64=True) as f:
                    f.write(d.encode())
        (self.tmp / "Downloads" / "only-folders").mkdir(parents=True)
        (self.tmp / "Downloads" / "only-folders" / "inside").mkdir()
        r = self.identify(self.make("deflate64.zip", patch_headers(whole, method=9)), self.make("dirs.zip", b.getvalue()),
                          self.make("empty.zip", zip_bytes({})), self.make("cut.zip", whole[: len(whole) * 2 // 3]),
                          self.make("z64.zip", z64.getvalue()), self.tmp / "Downloads" / "only-folders")
        self.assertEqual((r["deflate64.zip"]["valid"], r["deflate64.zip"].get("needs_unzip")), (False, True))
        for n in ("dirs.zip", "empty.zip", "only-folders"):
            self.assertEqual((r[n]["kind"], r[n].get("empty"), r[n]["reason"]), (None, True, "empty"), f"{n}: not Zoom's transcripts")
        self.assertIn("not a complete zip", r["cut.zip"]["reason"])
        self.assertEqual(r["z64.zip"]["kind"], "chatgpt")

    def test_a_zip_bomb_inside_is_never_unpacked(self):
        # A lone zip inside that says it unpacks to 1 GB from a few bytes
        bomb = zip_bytes({"a.zip": zip_bytes({"x": "0" * 100})})
        info = zipfile.ZipFile(io.BytesIO(bomb)).getinfo("a.zip")
        raw = bytearray(bomb)
        cd = raw.rfind(b"PK\x01\x02")
        struct.pack_into("<I", raw, cd + 24, 1 << 30)
        struct.pack_into("<I", raw, raw.find(b"PK\x03\x04") + 22, 1 << 30)
        self.assertLess(info.compress_size, 1000)
        r = self.identify(self.make("bomb.zip", bytes(raw)))
        self.assertFalse(r["bomb.zip"]["valid"])
        self.assertIn("zip bomb", r["bomb.zip"]["reason"])

    def test_still_downloading(self):
        whole = zip_bytes(CHATGPT)
        d = self.tmp / "Downloads"
        safari = d / "data.zip.download"
        safari.mkdir(parents=True)
        (safari / "data.zip").write_bytes(whole[:50])
        self.make("ff.zip", b"")  # Firefox: the final name, empty, while it writes ff.zip.part
        r = self.identify(self.make("data.zip.crdownload", whole[:50]), self.make("Unconfirmed 812.crdownload", whole[:50]), safari,
                          self.make("ff.zip.part", whole[:50]), d / "ff.zip", self.make("Inbox.partial.mbox", b"From "))
        for n, x in r.items():
            self.assertEqual((x["valid"], x.get("partial"), x["reason"]), (False, True, "still downloading"), n)

    def test_kinds_told_by_more_than_their_files(self):
        olm = zip_bytes({"Accounts/ada@example.com/com.microsoft.__Messages/Inbox/message_00001.xml": "<emails/>"})
        d = self.tmp / "Downloads" / "Saved mail"
        d.mkdir(parents=True)
        for n in ("one.eml", "two.eml", "notes.txt"):
            (d / n).write_text("Subject: x\n\nhi\n")
        r = self.identify(self.make("Outlook for Mac Archive.olm", olm), d,
                          self.make("instagram-ada_l-2026-10-01-AbC-2.zip", zip_bytes({"media/posts/202401/1.jpg": b"\xff\xd8"})),
                          self.make("facebook-ada-2026-10-01-XyZ-3.zip", zip_bytes({"your_activity_across_facebook/messages/inbox/c_1/photos/1.jpg": b"\xff"})),
                          self.make("instagram-tips.zip", zip_bytes({"tips.pdf": b"%PDF"})))
        self.assertEqual(r["Outlook for Mac Archive.olm"]["kind"], "mailbox")
        self.assertEqual(r["Saved mail"]["kind"], "mailbox", "messages dragged out of a mail app")
        self.assertEqual(r["instagram-ada_l-2026-10-01-AbC-2.zip"]["kind"], "instagram", "a later part, only photos")
        self.assertEqual(r["facebook-ada-2026-10-01-XyZ-3.zip"]["kind"], "facebook")
        self.assertIsNone(r["instagram-tips.zip"]["kind"], "named so, but not a download from Meta")

    def test_a_tar_bomb_is_found_from_its_headers(self):
        head = tarfile.TarInfo("Takeout/Mail/All mail.mbox")
        head.size = 50 << 30
        p = self.make("takeout-20250301T120000Z-1-001.tgz", gzip.compress(head.tobuf() + b"\0" * 4096))
        r = self.identify(p)[p.name]
        self.assertFalse(r["valid"])
        self.assertIn("tar bomb", r["reason"])

    def test_the_probe_names_mail_sources_as_imports_does(self):
        imp = self.corpus / "imports"
        for rel in ("hotmail/Inbox.mbox", "mail/Inbox.mbox", "work/Saved/Archive.mbox", "instagram/Outlook.olm", "takeout-1/x.mbox"):
            (imp / rel).parent.mkdir(parents=True, exist_ok=True)
            (imp / rel).write_text("From x\n")
        self.assertEqual(sorted(self.probe()["mailbox_sources"]), ["hotmail", "instagram_mail", "mail_mail", "work"])


if __name__ == "__main__":
    import unittest
    unittest.main()
