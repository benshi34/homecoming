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
PROTECTED = {"Messages": "Library/Messages/chat.db", "Safari": "Library/Safari/History.db", "Mail": "Library/Mail"}
VOLUMES = Path(os.environ.get("UMP_VOLUMES") or "/Volumes")


def fix_steps(macos):
    """Where Remote Login gets Full Disk Access on this macOS: its own switch since macOS 15, the list before."""
    try:
        major = int(str(macos).split(".")[0])
    except ValueError:
        major = 0
    if major >= 15:
        return ("System Settings > General > Sharing, click (i) next to Remote Login, and turn on Allow full disk "
                "access for remote users. It asks for this Mac's password.")
    return ("System Settings > Privacy & Security > Full Disk Access: turn on sshd-keygen-wrapper (if it isn't listed, "
            "click +, press Command-Shift-G, and choose /usr/libexec/sshd-keygen-wrapper).")


def blocked(p):
    try:
        if p.is_dir():
            os.listdir(p)
        elif p.exists():
            open(p, "rb").close()
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def access():
    """What Remote Login can't read on this Mac, and how to fix it: {full_disk_access, blocked, drives_blocked, macos,
    fix}. Each external drive is tried too: macOS keeps them behind the same permission (ssh gets "operation not
    permitted")."""
    if sys.platform != "darwin":
        return None
    import platform
    macos = platform.mac_ver()[0]
    apps = [name for name, rel in PROTECTED.items() if blocked(Path.home() / rel)]
    try:
        drives = sorted(d.name for d in VOLUMES.iterdir() if d.is_dir() and not d.is_symlink() and blocked(d))
    except OSError:
        drives = []
    out = {"full_disk_access": not (apps or drives), "blocked": apps, "drives_blocked": drives, "macos": macos}
    if apps or drives:
        out["fix"] = fix_steps(macos)
    return out


def full_disk_access():
    from common import NORM, read_manifest, write_manifest
    NORM.mkdir(parents=True, exist_ok=True)  # so a check that reads nothing still sends its manifest back
    a = access()
    if a is None:
        return
    m = read_manifest()
    m["_access"] = a
    write_manifest(m)


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
