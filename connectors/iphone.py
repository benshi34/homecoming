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
   system artifact as phone_<module> sources; see ileapp.py for what is left out and why.
4. build_index.py rebuilds corpus/corpus.db.
"""

import argparse
import importlib
import sys
import time
import traceback

import ileapp
import iphone_backup

# Our parsers (module, what it reads from the mirror). Order matters: contacts first, the name resolver reads them.
PARSERS = [
    ("contacts", "HomeDomain Library/AddressBook/AddressBook.sqlitedb"),
    ("imessage", "HomeDomain Library/SMS/sms.db, MediaDomain Library/SMS/Attachments/"),
    ("calls", "HomeDomain Library/CallHistoryDB/CallHistory.storedata"),
    ("health", "HealthDomain Health/healthdb_secure.sqlite, healthdb.sqlite"),
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-decrypt", action="store_true")
    ap.add_argument("--skip-ileapp", action="store_true", help="re-import the last iLEAPP run instead of running it")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--all", action="store_true", help="also decrypt photo derivatives")
    ap.add_argument("--backup", help="backup folder (default: the most recent finished one)")
    ap.add_argument("--password-stdin", action="store_true")
    a = ap.parse_args(argv)

    bk = iphone_backup.Backup(a.backup)
    password = None
    if bk.encrypted and not a.skip_decrypt:
        password = iphone_backup.get_password(a.password_stdin)
    if not a.skip_decrypt:
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
            ileapp.import_latest(None if a.skip_ileapp else ileapp.run(bk.dir))
        except (Exception, SystemExit):
            failed.append("ileapp")
            traceback.print_exc()
        print(f"  (ileapp: {time.time() - t:.1f}s)")
    importlib.import_module("build_index").main()
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
