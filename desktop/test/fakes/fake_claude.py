#!/usr/bin/env python3
"""A stand-in for `claude -p --output-format stream-json`: starts the MCP server from --mcp-config, makes the tool
calls in its plan through it, and prints Claude Code's stream-json events. The plan is JSON {"steps": [...], "answer"}
from the file $FAKE_CLAUDE_PLAN (or $FAKE_CLAUDE_SCRIPT and $FAKE_CLAUDE_ANSWER). A step is {"tool", "input"}, {"probe":
path} (read a file directly, which the sandbox should stop, and say what happened), {"think": text} (a stretch of
thinking, streamed as Claude Code does: its words only when asked for with --thinking-display=summarized, as the API
leaves them out otherwise) or {"sleep": seconds}. With no --mcp-config (text in, text out) there are no tools.
{"error": text, "exit": n} fails as Claude Code does when it isn't signed in (the error as its last message and as an
error result); {"crash": true} dies with a traceback; {"old": true} is a Claude Code from before --thinking-display.
$FAKE_CLAUDE_LOG gets the arguments, the prompt, and which sign-in variables it was given (never their values)."""

import json
import os
import subprocess
import sys
import time

args = sys.argv[1:]
# `claude auth login`: as Claude Code does, it opens its page with $BROWSER (one that comes back to it on this Mac) and
# prints one that ends with a code to paste back. Signed in a moment later ($FAKE_SIGN_IN_SECONDS), as if done on the
# first page; or, with $FAKE_SIGN_IN_PASTE (the first page can't get back), only once the code is pasted.
if args[:2] == ["auth", "login"]:
    import select
    print("Opening browser to sign in…", flush=True)
    print("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback", flush=True)
    if os.environ.get("BROWSER"):
        subprocess.run([os.environ["BROWSER"], "https://claude.com/cai/oauth/authorize?code=true&redirect_uri=http%3A%2F%2Flocalhost%3A54545%2Fcallback"])
    print("Paste code here if prompted > ", flush=True)
    until = time.time() + (600 if os.environ.get("FAKE_SIGN_IN_PASTE") else float(os.environ.get("FAKE_SIGN_IN_SECONDS", "1")))
    while time.time() < until:
        ready, _, _ = select.select([sys.stdin], [], [], max(0, until - time.time()))
        if not ready:
            break
        code = sys.stdin.readline().strip()
        if not code:
            sys.exit(1)
        if code == "fake-code#state":
            break
        print("Invalid code. Please make sure the full code was copied.", file=sys.stderr, flush=True)
    if os.environ.get("FAKE_SIGN_IN_FILE"):
        open(os.environ["FAKE_SIGN_IN_FILE"], "w").write("in")
    print("Login successful.", flush=True)
    sys.exit(0)
# `claude auth status --json`: signed in with a made-up claude.ai account, or not ($FAKE_CLAUDE_AUTH=out, until a sign-in).
if args[:2] == ["auth", "status"]:
    signed_in = os.environ.get("FAKE_CLAUDE_AUTH") != "out" or os.path.exists(os.environ.get("FAKE_SIGN_IN_FILE") or "/nonexistent")
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "ada@example.com", "subscriptionType": "max"} if signed_in
                     else {"loggedIn": False, "authMethod": "none"}))
    sys.exit(0 if signed_in else 1)
prompt = sys.stdin.read()
if os.environ.get("FAKE_CLAUDE_PLAN"):
    plan = json.load(open(os.environ["FAKE_CLAUDE_PLAN"]))
else:
    plan = {"steps": json.loads(os.environ.get("FAKE_CLAUDE_SCRIPT", "[]")), "answer": os.environ.get("FAKE_CLAUDE_ANSWER", "Done.")}
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "w") as f:
        json.dump({"args": args, "prompt": prompt, "env": sorted(k for k in os.environ if k.startswith(("ANTHROPIC", "CLAUDE", "CODEX", "OPENAI")))}, f)
# An older Claude Code stops at an option it doesn't know, before anything else.
if plan.get("old") and any(a.startswith("--thinking-display") for a in args):
    print(f"error: unknown option '{next(a for a in args if a.startswith('--thinking-display'))}'", file=sys.stderr)
    sys.exit(1)
summarized = "--thinking-display=summarized" in args
mcp = None
if "--mcp-config" in args:
    cfg = json.loads(args[args.index("--mcp-config") + 1])["mcpServers"]["corpus"]
    mcp = subprocess.Popen([cfg["command"], *cfg["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                           env={**os.environ, **cfg.get("env", {})})


def rpc(i, method, params=None):
    mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
    mcp.stdin.flush()
    return json.loads(mcp.stdout.readline())["result"]


def out(o):
    print(json.dumps(o), flush=True)


def think(text):
    """A stretch of thinking as Claude Code streams it (a few words at a time), then as a whole block."""
    shown = text if summarized else ""
    out({"type": "stream_event", "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}})
    words = shown.split(" ") if shown else []
    for i in range(0, len(words), 3):
        piece = " ".join(words[i:i + 3]) + (" " if i + 3 < len(words) else "")
        out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": piece}}})
    out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "c2ln"}}})
    out({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
    out({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": shown, "signature": "c2ln"}]}})


if plan.get("crash"):
    raise RuntimeError("the fake Claude Code crashed")
if mcp:
    rpc(0, "initialize", {"protocolVersion": "2025-06-18"})
# As Claude Code says it: each tool server and whether it started. plan "mcp": the corpus server's status ("failed").
out({"type": "system", "subtype": "init", "tools": [t["name"] for t in rpc(1, "tools/list")["tools"]] if mcp else [],
     "mcp_servers": [{"name": "corpus", "status": plan.get("mcp", "connected")}] if mcp else []})
if plan.get("error"):
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": plan["error"]}]}})
    out({"type": "result", "subtype": "success", "is_error": True, "result": plan["error"]})
    sys.exit(plan.get("exit", 1))
notes = []
for n, step in enumerate(plan.get("steps", [])):
    if "sleep" in step:
        time.sleep(step["sleep"])
        continue
    if "think" in step:
        think(step["think"])
        continue
    if "probe" in step:
        try:
            open(step["probe"], "rb").read(10)
            notes.append("probe: read")
        except OSError:
            notes.append("probe: blocked")
        continue
    tid = f"toolu_{n}"
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": f"mcp__corpus__{step['tool']}", "input": step["input"]}]}})
    r = rpc(10 + n, "tools/call", {"name": step["tool"], "arguments": step["input"]})
    out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": r["content"], "is_error": r["isError"]}]}})
    notes.append(f"{step['tool']}: {r['content'][0]['text'].splitlines()[-1] if r['content'][0]['text'] else ''}")
answer = plan.get("answer", "Done.") + ("\n\n" + "\n".join(notes) if notes and plan.get("notes", True) else "") + \
    ("\n\n(had history)" if "Earlier question" in prompt else "")
out({"type": "assistant", "message": {"content": [{"type": "text", "text": answer}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": answer})
if mcp:
    mcp.stdin.close()
    mcp.wait(timeout=10)
