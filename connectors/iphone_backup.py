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
and fall back to Size only when there is none. iOS 10.0 and 10.1 have neither the first PBKDF2 round (no DPSL/DPIC in
the keybag) nor an encrypted Manifest.db (no ManifestKey); iOS 9 and earlier keep Manifest.mbdb instead, too old to read.

Which backup: the newest finished one (Status.plist's SnapshotState "finished", as the app reads it), an iPhone's before
an iPad's. Finder backs up into the same folder, so one in progress or cut off is half old and half new: it isn't read.
The copy follows the backup: a file an encrypted backup no longer has (an app deleted from the phone) is taken out of
it, and a database copied anew loses an old -wal/-shm beside it that the backup doesn't have (SQLite would read the
old log as part of the new database). An unencrypted backup takes nothing out but those logs: it leaves out Health,
call history and more by design, not because the phone lost them.
"""

import argparse
import errno
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
import unicodedata
from collections import Counter
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap

from common import HOME, IPHONE as FILES, RAW, phone, read_json, write_atomic

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
SQLITE = b"SQLite format 3\x00"
SIDECARS = ("-wal", "-shm", "-journal")
DAMAGED = "This backup's index (Manifest.db) is damaged, so its files can't be found. Back up again in Finder."
NOT_ENCRYPTED = ("This backup isn't encrypted, so it has no Health, call history, Safari history or saved Wi-Fi networks: "
                 "in Finder, turn on \"Encrypt local backup\" and back up again to have them too.")


def udid(info, folder):
    """The device a backup is of (an archived copy of one is a folder of its own, with the same device)."""
    return info.get("Target Identifier") or info.get("Unique Identifier") or folder.name


def read_plist(path):
    """A plist as a dict, or None when it's missing or can't be read."""
    try:
        d = plistlib.loads(Path(path).read_bytes())
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def problem(d):
    """Why folder d can't be read as a backup, in words, or None. A backup in progress, or cut off, says so in
    Status.plist (SnapshotState other than "finished"); with no Status.plist it counts as finished, as the app counts it."""
    try:
        return _problem(d)
    except PermissionError:
        return "macOS keeps iPhone backups behind Full Disk Access: turn it on for this app, then try again."


def _problem(d):
    if not d.is_dir():
        return f"The backup folder {d} isn't there" + (": it's on a disk that isn't connected?" if d.is_symlink() else ".")
    if not (d / "Info.plist").exists():
        return "This backup isn't finished: it has no Info.plist (Finder was interrupted?). Back up again in Finder."
    info = read_plist(d / "Info.plist")
    if info is None:
        return "This backup's Info.plist is damaged. Back up again in Finder."
    if not (d / "Manifest.db").exists() and (d / "Manifest.mbdb").exists():
        return (f"This backup is from iOS {info.get('Product Version') or '9 or earlier'}: too old to read (iOS 10 on). "
                f"Back up the phone again in Finder.")
    state = (read_plist(d / "Status.plist") or {}).get("SnapshotState")
    if state not in (None, "finished"):
        return f"This backup is still in progress, or was interrupted (\"{state}\"): let Finder finish, or back up again."
    if not (d / "Manifest.db").exists():
        return "This backup isn't finished: it has no Manifest.db. Back up again in Finder."
    return None


def latest_backup():
    """The newest finished backup of an iPhone (an iPad or an iPod's only when there's no iPhone's)."""
    if BACKUPS.is_symlink() and not BACKUPS.exists():
        sys.exit(f"The backups folder links to {os.readlink(BACKUPS)}, which isn't connected: plug in that disk.")
    try:
        folders = [d for d in BACKUPS.iterdir() if d.is_dir()]
    except (FileNotFoundError, NotADirectoryError):
        folders = []
    except PermissionError:
        sys.exit("macOS keeps iPhone backups behind Full Disk Access: turn it on for this app, then try again.")
    done = [d for d in folders if not problem(d)]
    if not done:
        # The likeliest reason there's none: one in progress, else one too old, else none at all.
        why = sorted((problem(d) for d in folders), key=lambda w: ("in progress" not in w, "too old" not in w))
        sys.exit(f"No finished backup in {BACKUPS}" + (f". {why[0]}" if why else ""))
    def iphone(d):
        return str((read_plist(d / "Info.plist") or {}).get("Product Type", "")).startswith("iPhone")
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
    key = password
    if "DPSL" in attrs:  # iOS 10.2 on: a first, slow round; 10.0 and 10.1 have only the second
        key = hashlib.pbkdf2_hmac("sha256", key, attrs["DPSL"], attrs["DPIC"], 32)
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
    sys.exit(f"This backup is encrypted: it needs the password you set when you turned on \"Encrypt local backup\" "
             f"(--password-stdin, $IPHONE_BACKUP_PASSWORD or the Keychain item \"{KEYCHAIN_ITEM}\").")


class Backup:
    def __init__(self, path=None):
        self.dir = Path(path) if path else latest_backup()
        why = problem(self.dir)
        if why:
            sys.exit(why)
        self.info = read_plist(self.dir / "Info.plist")
        self.manifest = read_plist(self.dir / "Manifest.plist")
        if self.manifest is None:
            if (self.dir / "Manifest.plist").exists():
                sys.exit("This backup's Manifest.plist is damaged. Back up again in Finder.")
            self.manifest = {}  # none: nothing says it's encrypted, and Manifest.db shows whether it is
        self.encrypted = bool(self.manifest.get("IsEncrypted", False))
        self.classes = {}
        self.unreadable = []  # (domain, relativePath, why) of index entries that can't be read

    def describe(self):
        i = self.info
        return (f"{i.get('Device Name')} ({i.get('Product Type')}, iOS {i.get('Product Version')}), "
                f"backed up {i.get('Last Backup Date')}, {'encrypted' if self.encrypted else 'not encrypted'}")

    def open(self, password=None):
        """Unlock (if encrypted) and write a readable copy of Manifest.db, the backup's file index."""
        ensure_out()
        raw = (self.dir / "Manifest.db").read_bytes()
        if self.encrypted:
            try:
                attrs, self.classes = parse_keybag(self.manifest["BackupKeyBag"])
                unlock(attrs, self.classes, (password or "").encode())
            except InvalidUnwrap:
                sys.exit("Wrong password: the backup's keys didn't unwrap. Nothing was written.")
            except (KeyError, TypeError, ValueError):
                sys.exit("This backup's keys (in Manifest.plist) are damaged. Back up again in Finder.")
            if not raw.startswith(SQLITE):  # iOS 10.2 on: the index is encrypted too
                try:
                    mk = self.manifest["ManifestKey"]
                    d = decryptor(aes_key_unwrap(self.classes[int.from_bytes(mk[:4], "little")]["KEY"], mk[4:]))
                    raw = d.update(raw) + d.finalize()
                except (KeyError, TypeError, ValueError, InvalidUnwrap):
                    sys.exit(DAMAGED)
        if not raw.startswith(SQLITE):
            sys.exit(DAMAGED)
        tmp = OUT / "Manifest.db.tmp"
        tmp.write_bytes(raw)
        try:
            con = sqlite3.connect(tmp)
            try:
                con.execute("select fileID, domain, relativePath, flags, file from Files limit 1").fetchall()
            finally:
                con.close()
        except sqlite3.DatabaseError:
            tmp.unlink(missing_ok=True)
            sys.exit(DAMAGED)
        tmp.replace(OUT / "Manifest.db")
        return self

    def files(self):
        """(fileID, domain, relativePath, size, mtime, file key or None) for every regular file. An entry whose
        description can't be read is left out and listed in self.unreadable."""
        con = sqlite3.connect(OUT / "Manifest.db")
        try:
            for file_id, domain, rel, blob in con.execute(
                    "select fileID, domain, relativePath, file from Files where flags = 1 order by domain, relativePath"):
                try:
                    root, objs = file_info(blob)
                    key = None
                    if self.encrypted and "EncryptionKey" in root:
                        ek = objs[root["EncryptionKey"].data]["NS.data"]
                        key = (root["ProtectionClass"], ek[4:])
                    yield file_id, domain, rel, int(root.get("Size") or 0), int(root.get("LastModified") or 0), key
                except Exception:
                    self.unreadable.append((domain, rel, "unreadable entry in Manifest.db"))
        except sqlite3.DatabaseError:
            sys.exit(DAMAGED)
        finally:
            con.close()

    def listed(self):
        """Every regular file the backup has, as (domain, relativePath), its description readable or not."""
        con = sqlite3.connect(OUT / "Manifest.db")
        try:
            return {(d, r) for d, r in con.execute("select domain, relativePath from Files where flags = 1")}
        finally:
            con.close()

    def extract(self, file_id, key, size, dest):
        src = self.dir / file_id[:2] / file_id
        tmp = dest.with_name(dest.name + ".part")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(src, "rb") as f, open(tmp, "wb") as out:
                d = decryptor(aes_key_unwrap(self.classes[key[0]]["KEY"], key[1])) if key else None
                while chunk := f.read(CHUNK):
                    out.write(d.update(chunk) if d else chunk)
                if d:
                    out.write(d.finalize())  # ValueError: cut short in the backup (not whole AES blocks)
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
        except BaseException:
            tmp.unlink(missing_ok=True)  # never a half-written copy left behind
            raise


def ensure_out():
    """corpus/raw/iphone -> ~/Library/Application Support/q1_user_model/iphone, so decrypted data stays out of
    iCloud Drive even when the corpus itself is in an iCloud-synced folder."""
    if OUT.is_symlink() and not OUT.exists():  # the folder it links to is gone
        if Path(os.readlink(OUT)) != LOCAL:
            sys.exit(f"The decrypted copy's folder ({os.readlink(OUT)}) isn't there: is it on a disk that isn't connected?")
        LOCAL.mkdir(parents=True, exist_ok=True)
    if OUT.exists() or OUT.is_symlink():
        return
    LOCAL.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.symlink_to(LOCAL)


def safe_rel(rel):
    p = Path(rel)
    return not p.is_absolute() and ".." not in p.parts


def same_name(domain, rel):
    """A mirror path as the Mac's disk compares names: without case, and é the same however it's written."""
    return unicodedata.normalize("NFC", f"{domain}/{rel}").casefold()


def take_out(root, rewritten, fresh, listed, everything):
    """Files of the copy the backup doesn't have now, taken out: with everything, any of them (an encrypted backup has
    all the phone has); else only the -wal/-shm/-journal beside a database copied anew this time, which SQLite would
    read as part of it. A log the backup has unchanged stays with it. Returns how many went."""
    gone = 0
    if everything:
        for dirpath, _, names in os.walk(root):
            for name in names:
                p = Path(dirpath, name)
                domain, *rest = p.relative_to(root).parts
                if not rest or same_name(domain, "/".join(rest)) not in listed:
                    p.unlink(missing_ok=True)
                    gone += 1
    for dest in rewritten:
        for suffix in SIDECARS:
            side = dest.with_name(dest.name + suffix)
            if side not in fresh and side.exists():
                side.unlink()
                gone += 1
    return gone


def main(argv=None, password=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backup", help="backup folder (default: the most recent finished one)")
    ap.add_argument("--all", action="store_true", help="also decrypt photo thumbnails and other derivatives")
    ap.add_argument("--list", action="store_true", help="only write inventory.json (files and bytes per domain)")
    ap.add_argument("--password-stdin", action="store_true", help="read the backup password from stdin")
    a = ap.parse_args(argv)

    bk = Backup(a.backup)
    print("Backup of", bk.describe())
    if not bk.encrypted:
        print(NOT_ENCRYPTED)
    bk.open((password if password is not None else get_password(a.password_stdin)) if bk.encrypted else None)
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
    state = read_json(state_file, {})  # unreadable (cut off by a crash): every file is copied again
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
    t, done, skipped, failed, written = time.time(), 0, 0, list(bk.unreadable), 0
    rewritten, fresh = set(), set()  # mirror paths copied anew this time; those plus the ones unchanged
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
            fresh.add(dest)
            continue
        try:
            bk.extract(file_id, key, n, dest)
            os.utime(dest, (mtime, mtime))
            state[file_id] = [stored, int(mtime)]
            done += 1
            written += n
            rewritten.add(dest)
            fresh.add(dest)
        except (OSError, KeyError, ValueError, InvalidUnwrap) as e:
            if isinstance(e, OSError) and e.errno == errno.ENOSPC:
                write_atomic(state_file, json.dumps(state))  # what's copied stays copied
                sys.exit(f"The disk is full: {written / 1e9:.1f} GB of the backup copied. Free some space and read it again.")
            failed.append((domain, rel, type(e).__name__))  # its copy from before, if any, stays
        if done and done % 5000 == 0:
            print(f"  {done:,} files, {written / 1e9:.1f} GB, {time.time() - t:.0f}s")
    listed = {same_name(d, r) for d, r in bk.listed()} if bk.encrypted else set()
    gone = take_out(FILES, rewritten, fresh, listed, everything=bk.encrypted)
    if bk.encrypted:
        ids = {f[0] for f in rows}
        state = {k: v for k, v in state.items() if k in ids}
    write_atomic(state_file, json.dumps(state))
    print(f"Decrypted {done:,} files ({written / 1e9:.1f} GB), {skipped:,} unchanged, {len(failed)} failed "
          f"in {time.time() - t:.0f}s → {FILES}")
    if gone:
        print(f"{gone:,} no longer in the backup, taken out of the copy")
    if failed:
        (OUT / "extract_failures.json").write_text(json.dumps(failed, indent=1))
        print("Failures by reason:", dict(Counter(f[2] for f in failed)), "(listed in extract_failures.json)")
    else:
        (OUT / "extract_failures.json").unlink(missing_ok=True)
    shutil.copy2(bk.dir / "Info.plist", OUT / "Info.plist")  # unencrypted device + installed-apps metadata
    write_atomic(OUT / "backup.json", json.dumps({
        "backup": bk.dir.name, "udid": this, "device": bk.info.get("Device Name"), "product": bk.info.get("Product Type"),
        "ios": bk.info.get("Product Version"), "backed_up": str(bk.info.get("Last Backup Date")),
        "encrypted": bk.encrypted, "decrypted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "derivatives_included": a.all}, indent=1))


if __name__ == "__main__":
    main()
