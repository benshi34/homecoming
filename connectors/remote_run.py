"""Run on another machine by machines.py, from a copy of these connectors in a folder it then removes: the connectors
named on the command line, into CORPUS_DIR there. Prints only to stderr: stdout carries the results back.

    python3 remote_run.py imessage ai_coding shell_history ...
"""

import importlib
import os
import sys
import time
import traceback

os.environ.setdefault("UMP_READ_IN_PLACE", "1")  # no copies of a machine's databases on its own disk


def main(names):
    sys.stdout = sys.stderr
    for name in names:
        t = time.time()
        try:
            importlib.import_module(name).main()
        except Exception:  # a connector this machine can't run (a missing module, another OS) stops no other
            traceback.print_exc()
        print(f"  ({name}: {time.time() - t:.1f}s)")


if __name__ == "__main__":
    main(sys.argv[1:])
