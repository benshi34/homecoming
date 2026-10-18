"""Coding-assistant transcripts: Claude Code (CLI + desktop), OpenAI Codex, Cursor and VS Code chat.

Keeps the user's prompts, the assistant's visible replies, and tool calls the user rejected
(with their stated reason), which are direct preference signals. Thinking blocks and tool
I/O are dropped."""

import json
import sqlite3
from pathlib import Path

from common import HOME, LIB, Writer, from_unix, snapshot_sqlite

AVENUE = ("Local JSONL. Claude Code: ~/.claude/projects/<cwd-slug>/<session>.jsonl (CLI and the desktop "
          "app's Code tab share this). Codex: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl, thread names in "
          "~/.codex/session_index.jsonl; a forked session's file (forked_from_id) begins with a copy of its parent's "
          "conversation, kept once, from the parent's own file. Cursor: ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb, "
          "table cursorDiskKV: composerData:<id> (conversation order in fullConversationHeadersOnly, or the whole "
          "conversation in older versions) and bubbleId:<composer>:<bubble> (type 1 = you, 2 = the assistant). "
          "VS Code chat (Copilot and others): User/workspaceStorage/*/chatSessions/*.json, or *.jsonl change logs "
          "(kind 0 = the session, 1 = set, 2 = append, 3 = delete at path k). Cursor and VS Code follow the formats "
          "documented by cursor-history and cursor-chat-bulk-export; neither had a conversation on this Mac to verify.")

REJECTED = "The user doesn't want to proceed with this tool use"
NOISE_PREFIXES = ("<command-", "<local-command", "<task-notification", "<system-reminder", "Caveat: The messages",
                  "[Request interrupted", "<environment_context", "<user_instructions", "# AGENTS.md",
                  "<permissions instructions", "<turn_aborted")


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if b.get("type") in ("text", "input_text", "output_text"))


def claude_code(w):
    for f in sorted((HOME / ".claude/projects").glob("*/*.jsonl")):
        lines = [json.loads(l) for l in f.open() if l.strip().startswith("{")]
        title = next((r.get("customTitle") or r.get("title") for r in reversed(lines) if r.get("type") == "custom-title"), None)
        tool_names = {}
        for r in lines:
            if r.get("type") not in ("user", "assistant") or r.get("isMeta") or r.get("isSidechain"):
                continue
            if w.has(r.get("uuid")):
                continue  # resumed sessions repeat earlier messages
            msg = r.get("message") or {}
            content = msg.get("content")
            base = dict(ts=r.get("timestamp"), thread=r.get("sessionId") or f.stem, thread_name=title,
                        meta={"cwd": r.get("cwd"), "tool": "claude-code", "branch": r.get("gitBranch")})
            if r["type"] == "assistant":
                for b in content if isinstance(content, list) else []:
                    if b.get("type") == "tool_use":
                        tool_names[b.get("id")] = b.get("name")
                text = _text(content)
                if text.strip():
                    w.add(id=r["uuid"], kind="ai_turn", author="claude-code", is_me=False, text=text,
                          **{**base, "meta": {**base["meta"], "model": msg.get("model")}})
                continue
            if isinstance(content, list):
                for b in content:
                    if b.get("type") == "tool_result" and REJECTED in json.dumps(b.get("content")):
                        detail = _text(b["content"]) if isinstance(b["content"], list) else str(b["content"])
                        reason = detail.split("the user said:", 1)[1].strip() if "the user said:" in detail else ""
                        tool = tool_names.get(b.get("tool_use_id"), "tool")
                        rid = f"{r['uuid']}:{b.get('tool_use_id')}"
                        if w.has(rid):
                            continue  # a forked or resumed session repeats the turn in another transcript
                        w.add(id=rid, kind="ai_turn", author="me", is_me=True,
                              text=f"[rejected {tool} call] {reason}".strip(),
                              **{**base, "meta": {**base["meta"], "decision": "rejected_tool", "tool_name": tool}})
            text = _text(content)
            if text.strip() and not text.lstrip().startswith(NOISE_PREFIXES):
                w.add(id=r["uuid"], kind="ai_turn", author="me", is_me=True, text=text, **base)


def _codex_file(f):
    """A rollout file: its session (the first session_meta: a fork's file has its parent's after it), the session it
    was forked from, when it started, where it ran, and its messages in order, as (role, text, timestamp)."""
    sid = cwd = forked = start = None
    msgs = []
    for l in f.open():
        r = json.loads(l)
        p = r.get("payload") or {}
        if r.get("type") == "session_meta":
            if sid is None:
                sid, cwd, forked, start = p.get("id"), p.get("cwd"), p.get("forked_from_id"), r.get("timestamp")
            continue
        if r.get("type") != "response_item" or p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
            continue
        text = _text(p.get("content"))
        if text.strip() and not text.lstrip().startswith(NOISE_PREFIXES):
            msgs.append((p["role"], text, r.get("timestamp")))
    return sid or f.stem, cwd, forked, start, msgs


def _copied(msgs, earlier, until=None):
    """How many of msgs' first messages are a copy of earlier ones (a fork's of its parent's conversation, a resumed
    session's of its own): each turns up next in earlier, by role and text. The copy can leave some out. Only what
    was said before until counts, so the session's own first message isn't taken for one its parent said later."""
    earlier = [m for m in earlier if not (until and m[2] and m[2] > until)]
    j = k = 0
    while k < len(msgs):
        j = next((i for i in range(j, len(earlier)) if earlier[i][:2] == msgs[k][:2]), None)
        if j is None:
            break
        j, k = j + 1, k + 1
    return k


def codex(w):
    names = {}
    idx = HOME / ".codex/session_index.jsonl"
    if idx.exists():
        for l in idx.open():
            d = json.loads(l)
            names[d["id"]] = d.get("thread_name")
    files = [(f, *_codex_file(f)) for f in sorted((HOME / ".codex/sessions").rglob("rollout-*.jsonl"))]
    # A forked session's file starts with a copy of its parent's conversation, read already from the parent's own
    # file: those are skipped, and its own messages are numbered from 1. Parents are read first. A session in more
    # than one file (resumed) goes on from what's been read. The n-th message of a session is codex:<session>:<n>.
    sessions = {sid for _, sid, *_ in files}
    said = {}  # session -> its messages read so far, (role, text, timestamp)
    done = set()
    while len(done) < len(files):
        ready = [x for x in files if x[0] not in done and (not x[3] or x[3] not in sessions or x[3] in said or x[3] == x[1])]
        for f, sid, cwd, forked, start, msgs in ready or [x for x in files if x[0] not in done]:
            done.add(f)
            skip = _copied(msgs, said.get(forked, []), start) if forked and forked != sid else 0
            mine = said.setdefault(sid, [])
            rest = msgs[skip:]
            for role, text, ts in rest[_copied(rest, mine, start):]:
                mine.append((role, text, ts))
                me = role == "user"
                w.add(id=f"codex:{sid}:{len(mine)}", kind="ai_turn", ts=ts, author="me" if me else "codex",
                      is_me=me, thread=sid, thread_name=names.get(sid), text=text, meta={"cwd": cwd, "tool": "codex"})


CURSOR_DB = LIB / "Application Support/Cursor/User/globalStorage/state.vscdb"
VSCODE_FAMILY = {"vscode": "Code", "vscode-insiders": "Code - Insiders", "vscodium": "VSCodium", "cursor": "Cursor",
                 "windsurf": "Windsurf"}


def _ms(v):
    if isinstance(v, (int, float)):
        return from_unix(v, "ms" if v > 1e11 else "s")
    return v if isinstance(v, str) else None


def cursor(w):
    if not CURSOR_DB.exists():
        return
    try:
        con = sqlite3.connect(snapshot_sqlite(CURSOR_DB, "ai_coding/cursor-state.vscdb"))
        rows = dict(con.execute("select key, value from cursorDiskKV where key like 'composerData:%' or key like 'bubbleId:%'"))
    except sqlite3.Error:
        return
    for key, raw in rows.items():
        if not key.startswith("composerData:") or not raw:
            continue
        try:
            c = json.loads(raw)
        except ValueError:
            continue
        cid = c.get("composerId") or key.split(":", 1)[1]
        name, created = c.get("name"), _ms(c.get("createdAt"))
        bubbles = c.get("conversation") or []  # older versions keep the whole conversation here
        if not bubbles:
            for h in c.get("fullConversationHeadersOnly") or []:
                raw_b = rows.get(f"bubbleId:{cid}:{h.get('bubbleId')}")
                try:
                    bubbles.append(json.loads(raw_b) if raw_b else None)
                except ValueError:
                    bubbles.append(None)
        for n, b in enumerate(bubbles):
            if not isinstance(b, dict) or b.get("type") not in (1, 2) or not (b.get("text") or "").strip():
                continue
            me = b["type"] == 1
            w.add(id=f"cursor:{cid}:{b.get('bubbleId') or n}", kind="ai_turn", ts=_ms(b.get("createdAt")) or created,
                  author="me" if me else "cursor", is_me=me, thread=f"cursor:{cid}", thread_name=name, text=b["text"],
                  meta={"tool": "cursor", "model": (c.get("modelConfig") or {}).get("modelName")})


def _replay(lines):
    """A VS Code chat .jsonl change log -> the session it describes."""
    state = None
    for op in lines:
        kind, path, v = op.get("kind"), op.get("k") or [], op.get("v")
        if kind == 0:
            state = v
            continue
        if state is None or not path:
            continue
        parent = state
        for k in path[:-1]:
            parent = parent[k] if isinstance(parent, list) else parent.setdefault(k, {})
        last = path[-1]
        if kind == 1:
            parent[last] = v
        elif kind == 2:
            arr = parent[last] if isinstance(parent, list) else parent.setdefault(last, [])
            if isinstance(op.get("i"), int):
                del arr[op["i"]:]
            arr.extend(v or [])
        elif kind == 3:
            if isinstance(parent, list):
                del parent[last]
            else:
                parent.pop(last, None)
    return state or {}


def _response_text(parts):
    out = []
    for p in parts or []:
        if isinstance(p, dict):
            v = p.get("value")
            if isinstance(v, str):
                out.append(v)
            elif isinstance(p.get("content"), dict) and isinstance(p["content"].get("value"), str):
                out.append(p["content"]["value"])
    return "".join(out)


def vscode_chat(w):
    for tool, folder in VSCODE_FAMILY.items():
        user = LIB / "Application Support" / folder / "User"
        for f in sorted([*user.glob("workspaceStorage/*/chatSessions/*.json*"), *user.glob("globalStorage/emptyWindowChatSessions/*.json*")]):
            try:
                text = f.read_text(errors="replace")
                s = _replay([json.loads(l) for l in text.splitlines() if l.strip()]) if f.suffix == ".jsonl" else json.loads(text)
            except (ValueError, OSError, KeyError, IndexError, TypeError):
                continue
            sid = s.get("sessionId") or f.stem
            title = s.get("customTitle")
            for n, r in enumerate(s.get("requests") or []):
                ts = _ms(r.get("timestamp")) or _ms(s.get("creationDate"))
                rid = r.get("requestId") or str(n)
                ask = ((r.get("message") or {}).get("text") or "").strip()
                if ask:
                    w.add(id=f"{tool}:{sid}:{rid}:q", kind="ai_turn", ts=ts, author="me", is_me=True, thread=f"{tool}:{sid}",
                          thread_name=title, text=ask, meta={"tool": tool, "responder": s.get("responderUsername")})
                answer = _response_text(r.get("response")).strip()
                if answer:
                    w.add(id=f"{tool}:{sid}:{rid}:a", kind="ai_turn", ts=ts, author=s.get("responderUsername") or tool,
                          is_me=False, thread=f"{tool}:{sid}", thread_name=title, text=answer,
                          meta={"tool": tool, "responder": s.get("responderUsername")})


def main():
    with Writer("ai_coding", AVENUE) as w:
        claude_code(w)
        codex(w)
        cursor(w)
        vscode_chat(w)


if __name__ == "__main__":
    main()
