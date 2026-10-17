#!/usr/bin/env python3
"""A stand-in for `codex exec --json`: runs the lookups in its plan with the ./ask command in its working folder (as
Codex's shell would) and prints Codex's JSON events. The plan is JSON {"steps": [...], "answer"} from the file
$FAKE_CODEX_PLAN (or $FAKE_CODEX_SCRIPT and $FAKE_CODEX_ANSWER). A step is {"tool", "input"}, {"shell": command} or
{"sleep": seconds}. {"fail": message, "reconnects": n} fails as Codex does when its sign-in has expired (reconnecting
first, then a failed turn). Its own permission profile isn't applied here. $FAKE_CODEX_LOG gets the arguments, the prompt, the
working folder and which sign-in variables it was given (never their values)."""

import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]
# `codex login`: the sign-in, as if done in the browser ($FAKE_SIGN_IN_FILE says it's done, a moment later).
if args == ["login"]:
    print("Starting local login server on http://localhost:1455. If your browser did not open: https://auth.openai.com/oauth/authorize?fake=1", file=sys.stderr, flush=True)
    time.sleep(float(os.environ.get("FAKE_SIGN_IN_SECONDS", "1")))
    if os.environ.get("FAKE_SIGN_IN_FILE"):
        open(os.environ["FAKE_SIGN_IN_FILE"], "w").write("in")
    sys.exit(0)
# `codex login status`: signed in with ChatGPT, or not ($FAKE_CODEX_AUTH=out, until a sign-in).
if args[:2] == ["login", "status"]:
    signed_in = os.environ.get("FAKE_CODEX_AUTH") != "out" or os.path.exists(os.environ.get("FAKE_SIGN_IN_FILE") or "/nonexistent")
    print("Logged in using ChatGPT" if signed_in else "Not logged in", file=sys.stderr)
    sys.exit(0 if signed_in else 1)
prompt = sys.stdin.read()
if os.environ.get("FAKE_CODEX_PLAN"):
    plan = json.load(open(os.environ["FAKE_CODEX_PLAN"]))
else:
    plan = {"steps": json.loads(os.environ.get("FAKE_CODEX_SCRIPT", "[]")), "answer": os.environ.get("FAKE_CODEX_ANSWER", "Done.")}
log = os.environ.get("FAKE_CODEX_LOG")
if log:
    with open(log, "w") as f:
        json.dump({"args": args, "prompt": prompt, "cwd": os.getcwd(), "codex_home": os.environ.get("CODEX_HOME"),
                   "oss_base_url": os.environ.get("CODEX_OSS_BASE_URL"),
                   "env": sorted(k for k in os.environ if k.startswith(("ANTHROPIC", "CLAUDE", "CODEX", "OPENAI")))}, f)


def out(o):
    print(json.dumps(o), flush=True)


out({"type": "thread.started", "thread_id": "t1"})
out({"type": "turn.started"})
if plan.get("fail"):
    for i in range(1, plan.get("reconnects", 0) + 1):
        out({"type": "error", "message": f"Reconnecting... {i}/5 ({plan['fail']})"})
    out({"type": "turn.failed", "error": {"message": plan["fail"]}})
    print(f"ERROR codex_exec: Turn failed: {plan['fail']}", file=sys.stderr)
    sys.exit(1)
out({"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "Looking."}})
lines = []
for n, step in enumerate(plan.get("steps", [])):
    if "sleep" in step:
        time.sleep(step["sleep"])
        continue
    cmd = step.get("shell") or f"./ask {step['tool']} <<'EOF'\n{json.dumps(step['input'])}\nEOF"
    item = {"id": f"item_{n + 1}", "type": "command_execution", "command": f"/bin/zsh -lc {json.dumps(cmd)}", "aggregated_output": "", "exit_code": None, "status": "in_progress"}
    out({"type": "item.started", "item": item})
    p = subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True, timeout=60)
    out({"type": "item.completed", "item": {**item, "aggregated_output": p.stdout + p.stderr, "exit_code": p.returncode, "status": "completed" if p.returncode == 0 else "failed"}})
    lines.append(p.stdout.strip().splitlines()[-1] if p.stdout.strip() else f"exit {p.returncode}")
answer = plan.get("answer", "Done.") + ("\n\n" + "\n".join(lines) if lines and plan.get("notes", True) else "")
out({"type": "item.completed", "item": {"id": "item_last", "type": "agent_message", "text": answer}})
out({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})
