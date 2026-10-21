"""Git commits across every repo under ~/Documents, ~/Desktop, iCloud Drive and the usual code folders: all of them, with the user's
marked is_me. Nothing is dropped for not matching identity.json, so an address the user forgot to list costs a
label (fixed by re-running after identity changes), not the commit."""

import os
import subprocess
from pathlib import Path

from common import HOME, Writer, cloud_only, git_bin
from identity import ME, is_me_email, is_me_name

AVENUE = ("Local: find .git dirs under ~/Documents, ~/Desktop, iCloud Drive and code folders (~/Developer, ~/Code, "
          "~/Projects, ~/src...); `git log --all`. Every commit is kept; "
          "is_me from corpus/identity.json (emails, names, exact usernames/email local parts). A repository whose history is "
          "only in iCloud (Optimize Mac Storage) is skipped rather than downloaded; what an earlier run read of it stays.")

# Code folders outside iCloud are where repos belong (an iCloud-synced repo gets conflict copies inside .git).
CODE_DIRS = ("Developer", "Code", "code", "Projects", "projects", "src", "dev", "git", "repos", "workspace")
ROOTS = [HOME / "Documents", HOME / "Desktop", HOME / "Library/Mobile Documents/com~apple~CloudDocs",
         *(HOME / d for d in CODE_DIRS)]
SKIP = {"node_modules", ".venv", "venv", "site-packages", "Library"}
SEP = "\x1f"


def mine(name, email):
    # A username counts whole: the address's name part, or the one in GitHub's private address (<id>+<username>@users
    # .noreply.github.com). As a substring it was anyone's: "ann" in "joanne".
    local, _, domain = email.partition("@")
    if domain.casefold() == "users.noreply.github.com":
        local = local.split("+", 1)[-1]
    return is_me_email(email) or is_me_name(name) or local.casefold() in ME["usernames_l"]


def repos():
    for root in ROOTS:
        for dp, dns, fns in os.walk(root):
            if ".git" in dns or ".git" in fns:
                yield Path(dp)
            dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".") and len(Path(dp, d).relative_to(root).parts) <= 4]


def history_in_icloud_only(repo):
    """Whether any of a repository's history is only in iCloud: git would download it (and, offline, hang). Every
    file in .git is looked at, without opening any: a branch or a loose object can be in iCloud while HEAD isn't."""
    for dp, _, fns in os.walk(repo / ".git"):
        if any(cloud_only(os.path.join(dp, f)) for f in fns):
            return True
    return False


def main():
    git = git_bin()
    # A worktree or another clone of a repository repeats its history: each commit is kept once, under the first
    # path it's read from, and an earlier run's copies under the other paths go.
    seen = set()
    with Writer("git_commits", AVENUE, forget=lambda old: str(old.get("id")).rsplit(":", 1)[-1] in seen) as w:
        if not git:  # no git to read them with (and the stub would ask to install the developer tools)
            w.notes["no_git"] = 1
            return
        for repo in sorted(set(repos())):
            if history_in_icloud_only(repo):  # its commits from an earlier run carry over
                w.notes["in_icloud_only"] = w.notes.get("in_icloud_only", 0) + 1
                continue
            fmt = SEP.join(["%H", "%aI", "%an", "%ae", "%s", "%b"]) + "\x1e"
            # In UTF-8 whatever the person's git config asks for (i18n.logOutputEncoding), and a byte that isn't
            # replaced rather than stopping every repository's read.
            try:
                out = subprocess.run([git, "-C", str(repo), "-c", "i18n.logOutputEncoding=UTF-8", "log", "--all", f"--format={fmt}"],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
            except subprocess.TimeoutExpired:
                continue
            remote = subprocess.run([git, "-C", str(repo), "config", "--get", "remote.origin.url"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip() or None
            for chunk in out.split("\x1e"):
                chunk = chunk.strip("\n")
                if SEP not in chunk:
                    continue
                h, ts, name, email, subject, body = (chunk.split(SEP) + [""] * 6)[:6]
                me = mine(name, email)
                rid = f"{repo.name}:{h}"
                if w.has(rid) or h in seen:
                    continue
                seen.add(h)
                w.add(id=rid, kind="commit", ts=ts, author="me" if me else (name or email), is_me=me, thread=str(repo),
                      thread_name=repo.name,
                      title=subject, text="\n".join(x for x in (subject, body.strip()) if x),
                      meta={k: v for k, v in (("repo", str(repo)), ("remote", remote), ("email", email)) if v})


if __name__ == "__main__":
    main()
