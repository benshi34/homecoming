#!/usr/bin/env python3
"""A stand-in for `claude -p --chrome --output-format stream-json` driving Chrome for Do It for Me: prints Claude Code's
stream-json events (init with the Claude in Chrome server, a line of text per step, a RESULT line) without a browser.
The plan is JSON from $FAKE_BROWSER_PLAN: {"request": [first run, the run after Continue, ...], "download": [...]}; a
run is {"steps": [...], "result": "requested" | "needs_you Sign in." | ..., "sleep": seconds between steps}. The prompt
says which list; each new run takes the next one, and so does each --resume of a session. A run with "for": "<service>" is
only for that service's runs (several run at once, in no set order): each takes the next of its own. $FAKE_BROWSER_LOG
gets one JSON line per run (its arguments and prompt, and when it started), and $FAKE_BROWSER_LOG.ended one as each
ends. $FAKE_CHROME_STATUS: how the Claude in Chrome extension is ("connected" unless set).
As Claude Code does, a session is kept by the folder it ran in: --resume from another folder finds no conversation."""

import json
import os
import re
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


def lines(path):
    """Its JSON lines, but one another run is still writing."""
    out = []
    for l in open(path) if path and os.path.exists(path) else []:
        try:
            out.append(json.loads(l))
        except ValueError:
            pass
    return out


def append(path, o):
    """One line in one write, so runs at once don't mix theirs."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(o) + "\n").encode())
    finally:
        os.close(fd)


runs = lines(log)
# Which service it's for, as the prompt names it ("their Spotify data", "Their Spotify export is ready").
named = re.search(r"\b[Tt]heir (.+?) (?:data|export)\b", prompt)
service = named.group(1) if named else None
if "--resume" in args:
    # Carrying on: the same session, its next run.
    session = args[args.index("--resume") + 1]
    before = [r for r in runs if r["session"] == session]
    if before and before[0].get("cwd") and before[0]["cwd"] != os.getcwd():
        print(f"No conversation found with session ID: {session}", file=sys.stderr, flush=True)
        sys.exit(1)
    mode, n, service = before[0]["mode"], len(before), before[0].get("service")
else:
    # A new run: the next one in its list after the new runs of that kind (for that service, with "for") so far.
    mode = "request" if "Request a full export" in prompt else "visit" if "Open each of these pages in turn" in prompt else "download"
    mine = any(r.get("for") for r in plan.get(mode) or []) and service
    session = f"fake-session-{os.getpid()}"
    n = sum(1 for r in runs if r["mode"] == mode and not r["resume"] and (not mine or r.get("service") == service))
runs_for = plan.get(mode) or [{"steps": [], "result": "requested", "sleep": 0.1}]  # a visit, when the plan has none: done
if any(r.get("for") for r in runs_for):
    runs_for = [r for r in runs_for if r.get("for") == service] or [{"steps": [], "result": f"failed No plan for {service}.", "sleep": 0.1}]
run = runs_for[min(n, len(runs_for) - 1)]
if log:
    with open(log + ".pid", "w") as f:  # the run now, for a test that checks it's gone
        f.write(str(os.getpid()))
    append(log, {"args": args, "prompt": prompt, "mode": mode, "session": session, "resume": "--resume" in args, "cwd": os.getcwd(),
                 "service": service, "t": time.time()})


def out(o):
    print(json.dumps(o), flush=True)


out({"type": "system", "subtype": "init", "session_id": session, "tools": ["mcp__claude-in-chrome__navigate"],
     "mcp_servers": [{"name": "claude-in-chrome", "status": os.environ.get("FAKE_CHROME_STATUS", "connected")}]})
for line in run.get("steps", []):
    time.sleep(run.get("sleep", 0.3))
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": line}]}})
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "mcp__claude-in-chrome__computer", "input": {"action": "left_click"}}]}})
    # "tool": what the browser tool said back (the extension gone partway: "Browser extension is not connected").
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": run.get("tool", "Clicked.")}]}})
time.sleep(run.get("sleep", 0.3))
if run.get("limit"):  # Claude's usage limit, as Claude Code ends a run on it
    out({"type": "result", "subtype": "success", "is_error": True, "result": run["limit"], "session_id": session})
    sys.exit(1)
final = "Done.\n" + (f"EMAIL: {run['email']}\n" if run.get("email") else "") + f"RESULT: {run['result']}"
out({"type": "assistant", "message": {"content": [{"type": "text", "text": final}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": final, "session_id": session})
if log:
    append(log + ".ended", {"session": session, "t": time.time()})
