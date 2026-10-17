"""Decrypt a local iPhone backup (Finder → Back up all of the data on your iPhone to this Mac, ideally with
"Encrypt local backup" on: unencrypted backups leave out Health, call history, Safari and keychain data).

    python3 connectors/iphone_backup.py           # decrypt everything except photo derivatives and the keychain
    python3 connectors/iphone_backup.py --all     # also the camera-roll thumbnails (+11 GB here)
    python3 connectors/iphone_backup.py --list    # just print what's in the backup, per domain

The backup is mirrored as files/<domain>/<relativePath> under corpus/raw/iphone/ (a symlink to
~/Library/Application Support/q1_user_model/iphone, outside iCloud Drive: decrypted messages and health
data shouldn't sync, and the mirror is ~18 GB). Re-runs are incremental: a file is rewritten only if its
size or modification time in the backup changed, so after a new Finder backup only new files decrypt.
connectors/iphone.py runs this and then every parser that reads the mirror.

Password, first found wins (never written anywhere): --password-stdin, $IPHONE_BACKUP_PASSWORD, the macOS
Keychain item "q1_user_model iPhone backup" (security add-generic-password -s "q1_user_model iPhone backup"
-a "$USER" -w), then an interactive prompt.

Format (iOS 10.2+): Manifest.plist holds the BackupKeyBag (TLV records) and ManifestKey. The password goes
through PBKDF2-SHA256 (DPSL salt, DPIC rounds) then PBKDF2-SHA1 (SALT, ITER) to a key that AES-unwraps
(RFC 3394) each protection-class key. Manifest.db is AES-256-CBC with a zero IV under the ManifestKey;
each file's own key sits in its Files.file blob (NSKeyedArchiver plist, EncryptionKey = 4-byte class +
wrapped key), and the file is stored at <backup>/<id[:2]>/<id> with id = sha1("<domain>-<relativePath>"),
AES-256-CBC, zero IV, PKCS7-padded. Don't cut files to the manifest's Size: it is read when the backup starts,
and a file that grows while it is being copied is stored in full (here 167 files, mostly the X app's DMs, held up
to 2 MB more than Size said; trusting Size truncated them into "malformed" databases). Strip the padding instead
and fall back to Size only when there is none.
"""

import argparse
import getpass
import hashlib
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap

from common import HOME, IPHONE as FILES, RAW, phone

BACKUPS = HOME / "Library/Application Support/MobileSync/Backup"
OUT = RAW / "iphone"
LOCAL = HOME / "Library/Application Support/q1_user_model/iphone"
KEYCHAIN_ITEM = "q1_user_model iPhone backup"
CHUNK = 8 << 20

# Never decrypted: the keychain (saved website, Wi-Fi and mail passwords; its items unlock with the same
# backup password). No parser needs it and it must never reach the corpus.
NEVER = ("KeychainDomain",)
# Never decrypted either: apps' saved logins. Cookie stores and credential databases are live sessions (anyone
# with the file is signed in as you) and hold nothing about your life.
NEVER_FILES = re.compile(r"\.binarycookies$|(^|/)Library/Cookies/|(^|/)[^/]*\.cookies$|(^|/)credentials\.sqlite3?(-wal|-shm)?$", re.I)
# Regenerable copies of iCloud Photos (the Mac's Photos library has its own). Decrypted only with --all.
DERIVED = ("CameraRollDomain", ("Media/PhotoData/Thumbnails/", "Media/PhotoData/UBF/", "Media/PhotoData/internal/",
                                "Media/PhotoData/CPL/", "Media/PhotoData/Metadata/", "Media/MediaAnalysis/"))


def udid(info, folder):
    """The device a backup is of (an archived copy of one is a folder of its own, with the same device)."""
    return info.get("Target Identifier") or info.get("Unique Identifier") or folder.name


def latest_backup():
    """The newest finished backup of an iPhone (an iPad or an iPod's only when there's no iPhone's)."""
    done = [d for d in BACKUPS.iterdir() if (d / "Info.plist").exists() and (d / "Manifest.db").exists()]
    if not done:
        sys.exit(f"No finished backup in {BACKUPS}")
    def iphone(d):
        try:
            return str(plistlib.loads((d / "Info.plist").read_bytes()).get("Product Type", "")).startswith("iPhone")
        except Exception:
            return False
    return max(done, key=lambda d: (iphone(d), (d / "Info.plist").stat().st_mtime))


def parse_keybag(data):
    """BackupKeyBag TLV records -> (header attributes, {protection class: class record})."""
    attrs, classes, cur, i = {}, {}, None, 0
    while i + 8 <= len(data):
        tag, n = data[i:i + 4].decode("ascii"), int.from_bytes(data[i + 4:i + 8], "big")
        val, i = data[i + 8:i + 8 + n], i + 8 + n
        num = int.from_bytes(val, "big") if n == 4 else None
        if tag == "UUID":
            if "UUID" not in attrs:
                attrs["UUID"] = val  # the keybag's own uuid; each later UUID starts a class record
                continue
            if cur and "CLAS" in cur:
                classes[cur["CLAS"]] = cur
            cur = {"UUID": val}
        elif cur is not None:
            cur[tag] = num if tag in ("CLAS", "WRAP", "KTYP") else val
        else:
            attrs[tag] = num if tag in ("VERS", "TYPE", "WRAP", "ITER", "DPIC") else val
    if cur and "CLAS" in cur:
        classes[cur["CLAS"]] = cur
    return attrs, classes


def unlock(attrs, classes, password):
    key = hashlib.pbkdf2_hmac("sha256", password, attrs["DPSL"], attrs["DPIC"], 32)
    key = hashlib.pbkdf2_hmac("sha1", key, attrs["SALT"], attrs["ITER"], 32)
    for c in classes.values():
        if "WPKY" in c and c.get("WRAP", 0) & 2:  # 2 = wrapped with the passcode-derived key
            c["KEY"] = aes_key_unwrap(key, c["WPKY"])  # InvalidUnwrap here means a wrong password


def decryptor(key):
    return Cipher(algorithms.AES(key), modes.CBC(b"\0" * 16)).decryptor()


def file_info(blob):
    """Files.file is an NSKeyedArchiver plist -> (root dict, $objects)."""
    p = plistlib.loads(blob)
    objs = p["$objects"]
    return objs[p["$top"]["root"].data], objs


def get_password(stdin=False):
    if stdin:
        return sys.stdin.readline().rstrip("\n")
    if os.environ.get("IPHONE_BACKUP_PASSWORD"):
        return os.environ["IPHONE_BACKUP_PASSWORD"]
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_ITEM, "-w"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.rstrip("\n")
    if sys.stdin.isatty():
        return getpass.getpass("Backup password (not shown as you type): ")
    sys.exit(f"Encrypted backup: set IPHONE_BACKUP_PASSWORD, pipe it with --password-stdin, or add the Keychain "
             f"item \"{KEYCHAIN_ITEM}\".")


class Backup:
    def __init__(self, path=None):
        self.dir = Path(path) if path else latest_backup()
        self.info = plistlib.loads((self.dir / "Info.plist").read_bytes())
        self.manifest = plistlib.loads((self.dir / "Manifest.plist").read_bytes())
        self.encrypted = self.manifest.get("IsEncrypted", False)
        self.classes = {}

    def describe(self):
        i = self.info
        return (f"{i.get('Device Name')} ({i.get('Product Type')}, iOS {i.get('Product Version')}), "
                f"backed up {i.get('Last Backup Date')}, {'encrypted' if self.encrypted else 'not encrypted'}")

    def open(self, password=None):
        """Unlock (if encrypted) and write a readable copy of Manifest.db, the backup's file index."""
        ensure_out()
        raw = (self.dir / "Manifest.db").read_bytes()
        if self.encrypted:
            attrs, self.classes = parse_keybag(self.manifest["BackupKeyBag"])
            try:
                unlock(attrs, self.classes, password.encode())
            except InvalidUnwrap:
                sys.exit("Wrong password: the backup's keys didn't unwrap. Nothing was written.")
            mk = self.manifest["ManifestKey"]
            d = decryptor(aes_key_unwrap(self.classes[int.from_bytes(mk[:4], "little")]["KEY"], mk[4:]))
            raw = d.update(raw) + d.finalize()
        tmp = OUT / "Manifest.db.tmp"
        tmp.write_bytes(raw)
        tmp.replace(OUT / "Manifest.db")
        return self

    def files(self):
        """(fileID, domain, relativePath, size, mtime, file key or None) for every regular file."""
        con = sqlite3.connect(OUT / "Manifest.db")
        for file_id, domain, rel, blob in con.execute(
                "select fileID, domain, relativePath, file from Files where flags = 1 order by domain, relativePath"):
            root, objs = file_info(blob)
            key = None
            if self.encrypted and "EncryptionKey" in root:
                ek = objs[root["EncryptionKey"].data]["NS.data"]
                key = (root["ProtectionClass"], ek[4:])
            yield file_id, domain, rel, root.get("Size", 0), root.get("LastModified", 0), key

    def extract(self, file_id, key, size, dest):
        src = self.dir / file_id[:2] / file_id
        tmp = dest.with_name(dest.name + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as f, open(tmp, "wb") as out:
            d = decryptor(aes_key_unwrap(self.classes[key[0]]["KEY"], key[1])) if key else None
            while chunk := f.read(CHUNK):
                out.write(d.update(chunk) if d else chunk)
            if d:
                out.write(d.finalize())
        n = tmp.stat().st_size
        if key and n:
            with open(tmp, "rb") as f:
                f.seek(max(0, n - 16))
                tail = f.read()
            pad = tail[-1]
            n = n - pad if 1 <= pad <= 16 and tail[-pad:] == bytes([pad]) * pad else min(size, n)
        with open(tmp, "r+b") as f:
            f.truncate(n)
        tmp.replace(dest)


def ensure_out():
    """corpus/raw/iphone -> ~/Library/Application Support/q1_user_model/iphone, so decrypted data stays out of
    iCloud Drive even when the corpus itself is in an iCloud-synced folder."""
    if OUT.exists() or OUT.is_symlink():
        return
    LOCAL.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.symlink_to(LOCAL)


def safe_rel(rel):
    p = Path(rel)
    return not p.is_absolute() and ".." not in p.parts


def main(argv=None, password=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backup", help="backup folder (default: the most recent finished one)")
    ap.add_argument("--all", action="store_true", help="also decrypt photo thumbnails and other derivatives")
    ap.add_argument("--list", action="store_true", help="only write inventory.json (files and bytes per domain)")
    ap.add_argument("--password-stdin", action="store_true", help="read the backup password from stdin")
    a = ap.parse_args(argv)

    bk = Backup(a.backup)
    print("Backup of", bk.describe())
    bk.open((password or get_password(a.password_stdin)) if bk.encrypted else None)
    rows = list(bk.files())
    print(f"{len(rows):,} files, {sum(r[3] for r in rows) / 1e9:.1f} GB")

    files, size = Counter(), Counter()
    for _, domain, _, n, _, _ in rows:
        files[domain] += 1
        size[domain] += n
    inv = [{"domain": d, "files": files[d], "bytes": size[d]} for d, _ in size.most_common()]
    (OUT / "inventory.json").write_text(json.dumps(inv, indent=1))
    if a.list:
        for d in inv[:40]:
            print(f"{d['bytes'] / 1e9:7.2f} GB {d['files']:7,}  {d['domain']}")
        return

    state_file = OUT / "mirror_state.json"  # fileID -> [stored bytes, mtime] of the copy in the mirror
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    # Another device than the one copied before (Your Setup picked a different iPhone): start the copy over, or the
    # other one's files would stay mixed in with this one's.
    try:
        before = json.loads((OUT / "backup.json").read_text())
    except (OSError, ValueError):
        before = None
    this = udid(bk.info, bk.dir)
    if before and (before.get("udid") or before.get("backup")) not in (this, bk.dir.name):
        print(f"A different device from last time ({before.get('device')}): copying this one from the start")
        shutil.rmtree(FILES, ignore_errors=True)
        state = {}
    t, done, skipped, failed, written = time.time(), 0, 0, [], 0
    for file_id, domain, rel, n, mtime, key in rows:
        if domain in NEVER or NEVER_FILES.search(rel) or (not a.all and domain == DERIVED[0] and rel.startswith(DERIVED[1])):
            continue
        if not safe_rel(rel) or not safe_rel(domain):
            failed.append((domain, rel, "unsafe path"))
            continue
        dest = phone(domain, rel)
        stored = (bk.dir / file_id[:2] / file_id).stat().st_size if (bk.dir / file_id[:2] / file_id).exists() else -1
        if dest.exists() and state.get(file_id) == [stored, int(mtime)]:
            skipped += 1
            continue
        try:
            bk.extract(file_id, key, n, dest)
            os.utime(dest, (mtime, mtime))
            state[file_id] = [stored, int(mtime)]
            done += 1
            written += n
        except (FileNotFoundError, KeyError, InvalidUnwrap, IsADirectoryError, NotADirectoryError) as e:
            failed.append((domain, rel, type(e).__name__))
        if done and done % 5000 == 0:
            print(f"  {done:,} files, {written / 1e9:.1f} GB, {time.time() - t:.0f}s")
    state_file.write_text(json.dumps(state))
    print(f"Decrypted {done:,} files ({written / 1e9:.1f} GB), {skipped:,} unchanged, {len(failed)} failed "
          f"in {time.time() - t:.0f}s → {FILES}")
    if failed:
        (OUT / "extract_failures.json").write_text(json.dumps(failed, indent=1))
        print("Failures by reason:", dict(Counter(f[2] for f in failed)), "(listed in extract_failures.json)")
    shutil.copy2(bk.dir / "Info.plist", OUT / "Info.plist")  # unencrypted device + installed-apps metadata
    (OUT / "backup.json").write_text(json.dumps({
        "backup": bk.dir.name, "udid": this, "device": bk.info.get("Device Name"), "product": bk.info.get("Product Type"),
        "ios": bk.info.get("Product Version"), "backed_up": str(bk.info.get("Last Backup Date")),
        "encrypted": bk.encrypted, "decrypted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "derivatives_included": a.all}, indent=1))


if __name__ == "__main__":
    main()
