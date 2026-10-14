"""Terminal history: the commands you typed in zsh, bash and fish.

zsh only writes times when EXTENDED_HISTORY is on, and keeps SAVEHIST commands (1,000 by default), so daily
runs accumulate what the file drops. Commands that look like they carry a secret (tokens, passwords, keys in
URLs) are kept with the secret replaced by [redacted]."""

import hashlib
import re

from common import HOME, Writer, from_unix

AVENUE = ("Local text files: ~/.zsh_history and ~/.zsh_sessions/*.history (Terminal's per-window history), "
          "~/.bash_history and ~/.bash_sessions/*.history, ~/.local/share/fish/fish_history. zsh lines are "
          "': <unix time>:<seconds>;<command>' with EXTENDED_HISTORY, else bare commands with no time.")

# Values that must never reach the corpus, whatever the command. Each keeps its label and redacts the value;
# a quoted value may hold spaces.
VALUE = r"(\"[^\"]*\"|'[^']*'|[^\s'\"]+)"
SECRET_NAME = r"[\w.-]*(?:token|secret|passw(?:or)?d|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|credential)[\w.-]*"
SECRETS = [
    (re.compile(r"(?i)(authorization:\s*(?:bearer|basic|token|digest)?\s*)[^\s'\"]+"), r"\1[redacted]"),
    (re.compile(rf"(?i)\b({SECRET_NAME}\s*[=:]\s*){VALUE}"), r"\1[redacted]"),  # NAME=value, name: value
    (re.compile(rf"(?i)(\s--?(?:password|passwd|pass|token|api-?key|secret|auth-token|access-token)(?:=|\s+)){VALUE}"),
     r"\1[redacted]"),  # --password value
    (re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{16,}"), r"\1[redacted]"),
    (re.compile(r"(://[^/\s:@]+:)[^/\s@]+@"), r"\1[redacted]@"),  # https://user:pass@host
    (re.compile(r"\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|"
                r"xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|"
                r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,})"), "[redacted]"),
]


def redact(cmd):
    for pat, repl in SECRETS:
        cmd = pat.sub(repl, cmd)
    return cmd


def unmetafy(data):
    """zsh stores bytes >= 0x83 as 0x83 followed by the byte XOR 0x20."""
    out, i = bytearray(), 0
    while i < len(data):
        if data[i] == 0x83 and i + 1 < len(data):
            out.append(data[i + 1] ^ 0x20)
            i += 2
        else:
            out.append(data[i])
            i += 1
    return out.decode("utf-8", "replace")


def zsh_entries(text):
    """(unix time or None, command) per entry; a trailing backslash continues the command on the next line."""
    entries, cur = [], None
    for line in text.split("\n"):
        if cur is not None and cur[1].endswith("\\"):
            cur = (cur[0], cur[1][:-1] + "\n" + line)
            entries[-1] = cur
            continue
        m = re.match(r"^: (\d{9,11}):\d+;(.*)$", line)
        cur = (int(m.group(1)), m.group(2)) if m else (None, line)
        entries.append(cur)
    return [(t, c) for t, c in entries if c.strip()]


def bash_entries(text):
    entries, when = [], None
    for line in text.split("\n"):
        if re.fullmatch(r"#\d{9,11}", line):  # HISTTIMEFORMAT writes '#<unix time>' before each command
            when = int(line[1:])
        elif line.strip():
            entries.append((when, line))
            when = None
    return entries


def fish_entries(text):
    entries, cmd = [], None
    for line in text.split("\n"):
        if line.startswith("- cmd: "):
            cmd = line[7:].replace("\\n", "\n").replace("\\\\", "\\")
            entries.append((None, cmd))
        elif line.strip().startswith("when: ") and entries and entries[-1][0] is None and cmd is not None:
            entries[-1] = (int(line.split(":", 1)[1]), cmd)
    return entries


FILES = [
    ("zsh", lambda: [HOME / ".zsh_history", *sorted((HOME / ".zsh_sessions").glob("*.history"))], zsh_entries, True),
    ("bash", lambda: [HOME / ".bash_history", *sorted((HOME / ".bash_sessions").glob("*.history"))], bash_entries, False),
    ("fish", lambda: [HOME / ".local/share/fish/fish_history"], fish_entries, False),
]


def main():
    with Writer("shell_history", AVENUE) as w:
        for shell, paths, parse, metafied in FILES:
            for p in paths():
                if not p.is_file():
                    continue
                data = p.read_bytes()
                text = unmetafy(data) if metafied else data.decode("utf-8", "replace")
                seen = {}
                for when, cmd in parse(text):
                    cmd = redact(cmd.strip())
                    # The nth time a command appears in a file is the same record in every file and every run:
                    # Terminal's per-window files repeat ~/.zsh_history, and a trimmed file rewrites it.
                    key = f"{shell}:{when or ''}:{cmd}"
                    seen[key] = seen.get(key, 0) + 1
                    rid = hashlib.sha1(f"{key}#{seen[key]}".encode()).hexdigest()[:16]
                    if w.has(rid):
                        continue
                    w.add(id=rid, kind="command", ts=from_unix(when) if when else None, author="me", is_me=True,
                          text=cmd, meta={"shell": shell, "file": p.name})


if __name__ == "__main__":
    main()
