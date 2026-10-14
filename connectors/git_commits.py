"""Git commits across every repo under ~/Documents, ~/Desktop, iCloud Drive and the usual code folders: all of them, with the user's
marked is_me. Nothing is dropped for not matching identity.json, so an address the user forgot to list costs a
label (fixed by re-running after identity changes), not the commit."""

import os
import subprocess
from pathlib import Path

from common import HOME, Writer
from identity import ME, is_me_email, is_me_name

AVENUE = ("Local: find .git dirs under ~/Documents, ~/Desktop, iCloud Drive and code folders (~/Developer, ~/Code, "
          "~/Projects, ~/src...); `git log --all`. Every commit is kept; "
          "is_me from corpus/identity.json (emails, names, usernames as substrings). Slow the first time if "
          "Documents is iCloud-synced (git objects get downloaded).")

# Code folders outside iCloud are where repos belong (an iCloud-synced repo gets conflict copies inside .git).
CODE_DIRS = ("Developer", "Code", "code", "Projects", "projects", "src", "dev", "git", "repos", "workspace")
ROOTS = [HOME / "Documents", HOME / "Desktop", HOME / "Library/Mobile Documents/com~apple~CloudDocs",
         *(HOME / d for d in CODE_DIRS)]
SKIP = {"node_modules", ".venv", "venv", "site-packages", "Library"}
SEP = "\x1f"


def mine(name, email):
    s = f"{name} {email}".lower()
    return is_me_email(email) or is_me_name(name) or any(u in s for u in ME["usernames_l"])


def repos():
    for root in ROOTS:
        for dp, dns, fns in os.walk(root):
            if ".git" in dns:
                yield Path(dp)
            dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".") and len(Path(dp, d).relative_to(root).parts) <= 4]


def main():
    with Writer("git_commits", AVENUE) as w:
        for repo in sorted(set(repos())):
            fmt = SEP.join(["%H", "%aI", "%an", "%ae", "%s", "%b"]) + "\x1e"
            try:
                out = subprocess.run(["git", "-C", str(repo), "log", "--all", f"--format={fmt}"],
                                     capture_output=True, text=True, timeout=120).stdout
            except subprocess.TimeoutExpired:
                continue
            remote = subprocess.run(["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
                                    capture_output=True, text=True).stdout.strip() or None
            for chunk in out.split("\x1e"):
                chunk = chunk.strip("\n")
                if SEP not in chunk:
                    continue
                h, ts, name, email, subject, body = (chunk.split(SEP) + [""] * 6)[:6]
                me = mine(name, email)
                rid = f"{repo.name}:{h}"
                if w.has(rid):
                    continue
                w.add(id=rid, kind="commit", ts=ts, author="me" if me else (name or email), is_me=me, thread=str(repo),
                      thread_name=repo.name,
                      title=subject, text="\n".join(x for x in (subject, body.strip()) if x),
                      meta={k: v for k, v in (("repo", str(repo)), ("remote", remote), ("email", email)) if v})


if __name__ == "__main__":
    main()
