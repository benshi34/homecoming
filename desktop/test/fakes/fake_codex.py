#!/usr/bin/env python3
"""A stand-in for `codex exec --json`: runs the lookups in its plan with the ./ask command in its working folder (as
Codex's shell would) and prints Codex's JSON events. The plan is JSON {"steps": [...], "answer"} from the file
$FAKE_CODEX_PLAN (or $FAKE_CODEX_SCRIPT and $FAKE_CODEX_ANSWER). A step is {"tool", "input"}, {"shell": command} or
{"sleep": seconds}. Its own permission profile isn't applied here. $FAKE_CODEX_LOG gets the arguments, the prompt, the
working folder and which sign-in variables it was given (never their values)."""

import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]
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
