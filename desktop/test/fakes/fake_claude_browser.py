#!/usr/bin/env python3
"""A stand-in for `claude -p --chrome --output-format stream-json` driving Chrome for Do It for Me: prints Claude Code's
stream-json events (init with the Claude in Chrome server, a line of text per step, a RESULT line) without a browser.
The plan is JSON from $FAKE_BROWSER_PLAN: {"request": [first run, the run after Continue, ...], "download": [...]}; a
run is {"steps": [...], "result": "requested" | "needs_you Sign in." | ..., "sleep": seconds between steps}. The prompt
says which list; each new run takes the next one, and so does each --resume of a session. $FAKE_BROWSER_LOG gets one JSON line per run
(its arguments and prompt). $FAKE_CHROME_STATUS: how the Claude in Chrome extension is ("connected" unless set)."""

import json
import os
import sys
import time

args = sys.argv[1:]
prompt = sys.stdin.read()
if "--no-session-persistence" in args:
    # The app checking whether the Claude in Chrome extension is there (main.ts chromeStatus): it reads the first event and
    # stops. Not a run, so it isn't logged and takes nothing from the plan.
    print(json.dumps({"type": "system", "subtype": "init", "session_id": "chrome-check", "tools": [],
                      "mcp_servers": [{"name": "claude-in-chrome", "status": os.environ.get("FAKE_CHROME_STATUS", "connected")}]}), flush=True)
    sys.exit(0)
plan = json.load(open(os.environ["FAKE_BROWSER_PLAN"]))
log = os.environ.get("FAKE_BROWSER_LOG")
runs = [json.loads(l) for l in open(log) if l.strip()] if log and os.path.exists(log) else []
if "--resume" in args:
    # Carrying on: the same session, its next run.
    session = args[args.index("--resume") + 1]
    before = [r for r in runs if r["session"] == session]
    mode, n = before[0]["mode"], len(before)
else:
    # A new run: the next one in its list after the new runs of that kind so far.
    mode = "request" if "Request a full export" in prompt else "visit" if "Open each of these pages in turn" in prompt else "download"
    session, n = f"fake-session-{len(runs) + 1}", sum(1 for r in runs if r["mode"] == mode and not r["resume"])
runs_for = plan.get(mode) or [{"steps": [], "result": "requested", "sleep": 0.1}]  # a visit, when the plan has none: done
run = runs_for[min(n, len(runs_for) - 1)]
if log:
    with open(log + ".pid", "w") as f:  # the run now, for a test that checks it's gone
        f.write(str(os.getpid()))
    with open(log, "a") as f:
        f.write(json.dumps({"args": args, "prompt": prompt, "mode": mode, "session": session, "resume": "--resume" in args}) + "\n")


def out(o):
    print(json.dumps(o), flush=True)


out({"type": "system", "subtype": "init", "session_id": session, "tools": ["mcp__claude-in-chrome__navigate"],
     "mcp_servers": [{"name": "claude-in-chrome", "status": os.environ.get("FAKE_CHROME_STATUS", "connected")}]})
for line in run.get("steps", []):
    time.sleep(run.get("sleep", 0.3))
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": line}]}})
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "mcp__claude-in-chrome__computer", "input": {"action": "left_click"}}]}})
time.sleep(run.get("sleep", 0.3))
final = "Done.\n" + (f"EMAIL: {run['email']}\n" if run.get("email") else "") + f"RESULT: {run['result']}"
out({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": session})
