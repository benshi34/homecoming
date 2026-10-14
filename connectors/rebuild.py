"""Recompute every source from what is already on this Mac, then rebuild the index once.

    python3 connectors/rebuild.py              # everything
    python3 connectors/rebuild.py health ileapp  # just these (substring match)

Runs the Mac connectors and export importers (run_all.CONNECTORS; the phone parsers among them read the
decrypted iPhone mirror), then re-imports the latest iLEAPP run (ileapp.py --skip-run). Nothing is downloaded,
decrypted or re-run, so it is safe after any parser change and gives the same corpus from the same inputs.
For new data instead: run_all.py (Mac sources and new exports) and iphone.py (a new phone backup).
"""

import importlib
import sys
import time
import traceback

import run_all


def main(only=()):
    steps = [(name, lambda n=name: importlib.import_module(n).main()) for name in run_all.CONNECTORS]
    steps.append(("ileapp", lambda: importlib.import_module("ileapp").import_latest()))
    failed = []
    for name, step in steps:
        if only and not any(o in name for o in only):
            continue
        t = time.time()
        try:
            step()
        except Exception:
            failed.append(name)
            traceback.print_exc()
        print(f"  ({name}: {time.time() - t:.1f}s)")
    importlib.import_module("build_index").main()
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
