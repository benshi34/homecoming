"""Run on another machine by machines.py, from a copy of these connectors in a folder it then removes: the connectors
named on the command line, into CORPUS_DIR there. Prints only to stderr: stdout carries the results back.

    python3 remote_run.py imessage ai_coding shell_history ...
"""

import importlib
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("UMP_READ_IN_PLACE", "1")  # no copies of a machine's databases on its own disk
sys.path.insert(0, str(Path(__file__).resolve().parent / "_deps"))  # the plain-Python packages sent along


def said(name, why):
    from common import read_manifest, write_manifest
    m = read_manifest()
    m[name] = {**(m.get(name) if isinstance(m.get(name), dict) else {}), "not_read": why}
    write_manifest(m)


# What macOS keeps behind Full Disk Access: there but unreadable means Remote Login wasn't given it.
PROTECTED = ("Library/Messages/chat.db", "Library/Safari/History.db", "Library/Mail")


def full_disk_access():
    if sys.platform != "darwin":
        return
    for rel in PROTECTED:
        p = Path.home() / rel
        try:
            if p.is_dir():
                os.listdir(p)
            elif p.exists():
                open(p, "rb").close()
        except PermissionError:
            said("machines", "this Mac's Messages, Mail and Safari need Full Disk Access for Remote Login (System Settings > "
                             "Privacy & Security > Full Disk Access: sshd-keygen-wrapper)")
            return


def main(names):
    sys.stdout = sys.stderr
    full_disk_access()
    for name in names:
        t = time.time()
        try:
            importlib.import_module(name).main()
        except ImportError as e:  # a package this machine's Python doesn't have (and couldn't be sent: a compiled one)
            traceback.print_exc()
            said(name, f"needs {e.name or e} on this machine's Python")
        except Exception as e:  # a connector this machine can't run (another OS, a file it can't open) stops no other
            traceback.print_exc()
            said(name, f"{type(e).__name__}: {e}"[:200])
        print(f"  ({name}: {time.time() - t:.1f}s)")


if __name__ == "__main__":
    main(sys.argv[1:])
