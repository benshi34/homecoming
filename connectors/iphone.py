"""Everything from an iPhone backup, start to finish, with no agent involved:

    python3 connectors/iphone.py                  # decrypt new/changed files, run every phone parser, rebuild the index
    python3 connectors/iphone.py --all            # also decrypt photo thumbnails (passed to iphone_backup.py)
    python3 connectors/iphone.py --skip-decrypt   # re-parse the existing mirror only
    python3 connectors/iphone.py --only health    # just these parsers (substring match on module name)

1. iphone_backup.py decrypts the latest finished Finder backup into corpus/raw/iphone/files/<domain>/<path>.
   Incremental: after a new backup only changed files are rewritten. Password: see iphone_backup.py; only
   this step uses it.
2. Our parsers read the mirror: contacts, iMessage and calls (merged with the Mac's copies), Health (cleaned
   daily summaries and sleep). Each prints "no <path>" and moves on if the phone lacks the data.
3. ileapp.py runs iLEAPP (the maintained open-source iOS parser) on the backup and imports every other app and
   system artifact as phone_<module> sources; see ileapp.py for what is left out and why. WhatsApp and Apple Maps
   on this Mac, if read before, are read again: what the backup also has is then left to its phone_ source.
4. build_index.py rebuilds corpus/corpus.db.

One part failing never stops the others: iLEAPP stopping (or one of our parsers failing) leaves what the rest read in
the library, the index is rebuilt all the same, and the run ends by saying, in words, which parts weren't read.
"""

import argparse
import importlib
import sys
import time
import traceback

import ileapp
import iphone_backup
from common import NORM

# Our parsers (module, what it reads from the mirror). Order matters: contacts first, the name resolver reads them.
PARSERS = [
    ("contacts", "HomeDomain Library/AddressBook/AddressBook.sqlitedb"),
    ("imessage", "HomeDomain Library/SMS/sms.db, MediaDomain Library/SMS/Attachments/"),
    ("calls", "HomeDomain Library/CallHistoryDB/CallHistory.storedata"),
    ("health", "HealthDomain Health/healthdb_secure.sqlite, healthdb.sqlite"),
]
# Mac connectors that skip what iLEAPP's phone_whatsapp and phone_mapssync already have (whatsapp.py, apple_maps.py).
AFTER_ILEAPP = ["whatsapp", "apple_maps"]
# What each part is, said to someone reading why the run didn't read everything.
PLAIN = {"contacts": "contacts", "imessage": "messages", "calls": "calls", "health": "Health",
         "ileapp": "the other apps (iLEAPP)", "whatsapp": "WhatsApp on this Mac", "apple_maps": "Maps on this Mac"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-decrypt", action="store_true")
    ap.add_argument("--skip-ileapp", action="store_true", help="re-import the last iLEAPP run instead of running it")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--all", action="store_true", help="also decrypt photo derivatives")
    ap.add_argument("--backup", help="backup folder (default: the most recent finished one)")
    ap.add_argument("--password-stdin", action="store_true")
    a = ap.parse_args(argv)

    # The Finder backup is opened only to decrypt it or run iLEAPP on it: reading the copy already decrypted again (the
    # app's re-read after an update) works with the backup gone, or on another disk that isn't plugged in.
    bk = None if a.skip_decrypt and a.skip_ileapp else iphone_backup.Backup(a.backup)
    if not a.skip_decrypt:
        password = iphone_backup.get_password(a.password_stdin) if bk.encrypted else None
        iphone_backup.main([*(["--all"] if a.all else []), "--backup", str(bk.dir)], password=password)
    failed = []
    for name, _ in PARSERS:
        if a.only and not any(o in name for o in a.only):
            continue
        t = time.time()
        try:
            importlib.import_module(name).main()
        except Exception:
            failed.append(name)
            traceback.print_exc()
        print(f"  ({name}: {time.time() - t:.1f}s)")
    if not a.only or any(o in "ileapp" for o in a.only):
        t = time.time()
        try:
            ileapp.import_latest(None if a.skip_ileapp else ileapp.run(bk))
        except SystemExit as e:  # said in words (iLEAPP stopped, its results unreadable): no traceback to read
            failed.append("ileapp")
            print(e, file=sys.stderr)
        except Exception:
            failed.append("ileapp")
            traceback.print_exc()
        print(f"  (ileapp: {time.time() - t:.1f}s)")
        # Mac sources that leave what the backup also has to its phone_ source: read again now it's in, so nothing
        # is counted twice until their next read.
        for name in AFTER_ILEAPP:
            if not (NORM / f"{name}.jsonl").exists():
                continue
            try:
                importlib.import_module(name).main()
            except Exception:
                failed.append(name)
                traceback.print_exc()
    importlib.import_module("build_index").main()
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(f"The backup was read, except {', '.join(PLAIN.get(n, n) for n in failed)}: what was read is in your "
                 f"library, and what went wrong is in the log.")


if __name__ == "__main__":
    main()
