"""Run every local connector, then rebuild the search index.

    python3 run_all.py                 # all connectors
    python3 run_all.py imessage notes  # just these (substring match on module name)
"""

import importlib
import sys
import time
import traceback

CONNECTORS = ["contacts", "imessage", "apple_notes", "calendar_events", "reminders", "calls", "browser_history",
              "app_usage", "ai_coding", "editor_history", "shell_history", "podcasts", "photos", "voice_memos",
              "notion_local", "documents", "git_commits", "health", "imports"]  # health, the phone half of contacts/imessage/calls and iLEAPP's phone_*
                                     # sources come from connectors/iphone.py (decrypt + iLEAPP)


def main(only):
    failed = []
    for name in CONNECTORS:
        if only and not any(o in name for o in only):
            continue
        t = time.time()
        try:
            importlib.import_module(name).main()
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
