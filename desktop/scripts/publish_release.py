"""Gets a new version of Homecoming ready for its public repository, up to the push, which it leaves to you.

    python3 desktop/scripts/publish_release.py [--ref origin/main] [--into DIR] [--quick] [--allow TERM ...]

1. A clean worktree of private main (fetched, then --ref checked out on its own), so nothing uncommitted, and nothing
   another session is in the middle of, goes out.
2. Its release_copy.py makes the release copy, checked for personal data against this checkout's corpus/, with
   --allow benshi34 "Instagram User" "Facebook user" (the GitHub username in the clone URL; Meta's names for deleted
   accounts) and any terms given here.
3. A fresh clone of the public repository, and the copy in place of everything in it but .git
   (rsync -a --delete --exclude .git). Before that, a check: the public repository's commits since its last release
   (a community PR merged there, an edit made on GitHub) must be in private main, or that rsync would undo them. One
   is when private main cherry-picked it with -x (which names it), or when its change is already in the copy;
   --skip-public SHA names one you chose to leave out.
4. Checks: something changed; desktop/package.json's version is newer than the public one; CHANGELOG.md says what's
   new in it. Without a newer version, testers' What's New would have nothing to show.
5. Its tests, in the clone: npm ci, then npm test (--quick: the unit and Python suites, not the end-to-end ones).
6. A commit: "Homecoming 0.3.0", a blank line, then CHANGELOG.md's words for that version, as bullets.

Then it stops, and says what it would push and the command that pushes it. It never pushes, and never force-pushes:
every tester updates with git pull --ff-only (npm run update), which a rewritten history would break.
"""

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
PUBLIC = "https://github.com/benshi34/homecoming.git"
ALLOW = ["benshi34", "Instagram User", "Facebook user"]


def git(cwd: Path, *args: str, check=True) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and r.returncode:
        stop(f"git {' '.join(args)} didn't work:\n{r.stderr.strip()}")
    return r.stdout.strip()


def stop(why: str):
    sys.exit(f"\n{why}\nNothing was published.")


def version(repo: Path) -> str | None:
    try:
        return json.loads((repo / "desktop/package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def newer(a: str, b: str) -> bool:
    """0.10.0 is newer than 0.9.2 (as shared/version.ts compares them)."""
    pa, pb = ([int(n) if n.isdigit() else 0 for n in v.split(".")] for v in (a, b))
    n = max(len(pa), len(pb))
    return pa + [0] * (n - len(pa)) > pb + [0] * (n - len(pb))


def release_notes(changelog: str, v: str) -> tuple[list[str], list[str]] | None:
    """CHANGELOG.md's words and bullets for version v (shared/version.ts parseChangelog, the same way), or None."""
    text, bullets, on, inside = [], [], False, None
    for line in changelog.replace("\r\n", "\n").split("\n"):
        h = re.match(r"^##\s+v?(\d+(?:\.\d+)*)\b", line)
        if h:
            if on:
                break
            on, inside = h.group(1) == v, None
        elif not on or line.startswith("#"):
            continue
        elif re.match(r"^\s*[-*]\s+", line):
            bullets.append(re.sub(r"^\s*[-*]\s+", "", line).strip())
            inside = "bullet"
        elif not line.strip():
            inside = None
        elif inside == "bullet" and line[:1].isspace():
            bullets[-1] += f" {line.strip()}"
        elif inside == "text":
            text[-1] += f" {line.strip()}"
        else:
            text.append(line.strip())
            inside = "text"
    return (text, bullets) if on else None


RELEASE = re.compile(r"^Homecoming \d+(\.\d+)*$")  # a release's title, as commit_message writes it


def public_only(clone: Path, copy: Path, private_log: str, skip: list[str]) -> tuple[str | None, list[str], list[str]]:
    """The public repository's last release, and its commits since then that the copy would undo, as "sha author:
    subject": those private main hasn't, and those --skip-public leaves out. Private main has one when it cherry-picked
    it with -x (its log names it), or when its change is in the copy already (it comes off in reverse). Merges are
    left out: one brings its commits' changes, and a conflict it resolved only puts both sides together."""
    last = next((h for h, s in (l.split("\t", 1) for l in git(clone, "log", "--first-parent", "--format=%H\t%s").splitlines())
                 if RELEASE.match(s)), None)
    if not last:
        return None, [], []
    picked = set(re.findall(r"cherry picked from commit ([0-9a-f]{40})", private_log))
    missing, skipped = [], []
    for line in git(clone, "log", "--no-merges", "--reverse", "--format=%H\t%h %an: %s", f"{last}..HEAD").splitlines():
        h, what = line.split("\t", 1)
        if h in picked:
            continue
        patch = subprocess.run(["git", "-C", str(clone), "show", "--format=", "--binary", h], capture_output=True, text=True).stdout
        if not patch.strip() or not subprocess.run(["git", "apply", "--reverse", "--check", "-"], cwd=copy, input=patch,
                                                   capture_output=True, text=True).returncode:
            continue
        (skipped if any(h.startswith(s.lower()) for s in skip) else missing).append(what)
    return last, missing, skipped


def commit_message(v: str, text: list[str], bullets: list[str]) -> str:
    """A title line, a blank line, then the bullets (the words before them as bullets too), in plain text."""
    plain = lambda s: s.replace("**", "")
    return f"Homecoming {v}\n\n" + "".join(f"- {plain(s)}\n" for s in [*text, *bullets])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="origin/main", help="what to publish (default: GitHub's private main, fetched first)")
    ap.add_argument("--no-fetch", action="store_true", help="use --ref as it is here, without fetching it")
    ap.add_argument("--public", default=PUBLIC, help="the public repository to clone")
    ap.add_argument("--into", type=Path, help="where to clone it (default: a new folder in the temporary folder)")
    ap.add_argument("--corpus", type=Path, help="the corpus to check against (default: corpus/ in the main checkout)")
    ap.add_argument("--allow", nargs="*", default=[], help=f"more terms that belong in it, besides {', '.join(ALLOW)}")
    ap.add_argument("--skip-public", nargs="*", default=[], metavar="SHA",
                    help="public commits since its last release that you chose not to bring into private main: publishing undoes them")
    ap.add_argument("--quick", action="store_true", help="only the unit and Python tests, not the end-to-end ones")
    ap.add_argument("--test-command", help="run this in the clone's desktop/ instead of npm ci and npm test")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # in order with what git, release_copy.py and npm print

    # The main checkout (this may be a worktree of it): its corpus is the one to check against.
    main_checkout = Path(git(HERE, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    corpus = a.corpus or main_checkout / "corpus"
    work = Path(tempfile.mkdtemp(prefix="homecoming-publish-"))
    clone = a.into or work / "homecoming"
    if clone.exists():
        stop(f"{clone} already exists: pick another --into")

    print(f"== Private {a.ref}")
    if not a.no_fetch and "/" in a.ref:
        remote, branch = a.ref.split("/", 1)
        git(main_checkout, "fetch", "--quiet", remote, branch)
    src = work / "private"
    git(main_checkout, "worktree", "add", "--quiet", "--detach", str(src), a.ref)
    try:
        commit = git(src, "rev-parse", "--short", "HEAD")
        print(f"   at {commit}: {git(src, 'log', '-1', '--format=%s')}")
        private_log = git(src, "log", "--format=%B")  # which public commits it cherry-picked

        print("\n== The release copy, checked for personal data")
        copy = work / "copy"
        r = subprocess.run([sys.executable, str(src / "desktop/scripts/release_copy.py"), str(copy), "--corpus", str(corpus),
                            "--allow", *ALLOW, *a.allow])
        if r.returncode:
            shutil.rmtree(work, ignore_errors=True)
            stop("The release copy didn't pass (above): fix it in private main, merge, then run this again.")
    finally:
        git(main_checkout, "worktree", "remove", "--force", str(src), check=False)
        git(main_checkout, "worktree", "prune", check=False)

    print(f"\n== A fresh clone of {a.public}")
    r = subprocess.run(["git", "clone", "--quiet", a.public, str(clone)], capture_output=True, text=True)
    if r.returncode:
        stop(f"Couldn't clone {a.public}:\n{r.stderr.strip()}")
    branch = git(clone, "symbolic-ref", "--short", "-q", "HEAD", check=False) or "main"
    had = git(clone, "rev-parse", "--short", "HEAD", check=False)
    public_version = version(clone)
    # What was merged or edited on GitHub since the last release: the rsync below would undo it.
    last, missing, skipped = public_only(clone, copy, private_log, a.skip_public) if had else (None, [], [])
    if missing:
        stop(f"{a.public} has {len(missing)} commit{'s' * (len(missing) > 1)} since its last release ({last[:7]}) that private "
             f"{a.ref} doesn't, and publishing would undo:\n  " + "\n  ".join(missing) + "\nBring them into private main first "
             "(git cherry-pick -x, so this knows them), or name each one you're leaving out with --skip-public SHA.")
    if skipped:
        print("   undoing, as --skip-public says: " + "; ".join(skipped))
    subprocess.run(["rsync", "-a", "--delete", "--exclude", ".git", f"{copy}/", f"{clone}/"], check=True)
    shutil.rmtree(copy)
    git(clone, "add", "-A")
    if not git(clone, "status", "--porcelain"):
        print(f"\nNothing to publish: {a.public} already has exactly this ({public_version}).")
        return

    v = version(clone)
    if not v or (public_version and not newer(v, public_version)):
        stop(f"desktop/package.json says {v}, and the public repository has {public_version}. Give this release a newer\n"
             f"version (the last number for fixes, the middle one for something new), with what's new in it at the top of\n"
             f"CHANGELOG.md, in private main; then run this again.")
    notes = release_notes((clone / "CHANGELOG.md").read_text() if (clone / "CHANGELOG.md").exists() else "", v)
    if not notes or not (notes[0] or notes[1]):
        stop(f"CHANGELOG.md doesn't say what's new in {v}: add a \"## {v}\" section at its top, in private main.")

    print(f"\n== Its tests, in {clone}")
    desktop = clone / "desktop"
    if a.test_command:
        steps = [["/bin/sh", "-c", a.test_command]]
    else:
        # npm ci leaves Electron itself to be fetched when it's first needed (its own install.js, checked against the
        # checksums it comes with), as package_mac.mjs does.
        steps = [["npm", "ci", "--no-audit", "--no-fund"],
                 ["/bin/sh", "-c", "test -d node_modules/electron/dist/Electron.app || node node_modules/electron/install.js"],
                 ["npm", "run", "typecheck"],
                 *([["npm", "run", "test:unit"], ["npm", "run", "test:py"]] if a.quick else [["npm", "test"]])]
    for cmd in steps:
        print(f"$ {shlex.join(cmd)}")
        if subprocess.run(cmd, cwd=desktop).returncode:
            stop(f"{shlex.join(cmd)} didn't pass (above). The clone is left in {clone} to look at.")

    message = commit_message(v, *notes)
    r = subprocess.run(["git", "-C", str(clone), "commit", "--quiet", "-F", "-"], input=message, text=True, capture_output=True)
    if r.returncode:
        stop(f"Couldn't commit:\n{r.stderr.strip()}")
    head = git(clone, "rev-parse", "--short", "HEAD")
    # One commit on top of what GitHub has, so a tester's git pull --ff-only moves straight to it.
    if had and subprocess.run(["git", "-C", str(clone), "merge-base", "--is-ancestor", had, "HEAD"]).returncode:
        stop("The commit isn't on top of the public repository's: that can't be pushed without rewriting it.")
    print(f"""
Ready: Homecoming {v} (from private {commit}), one commit on top of {a.public} {branch}{f' ({had}, version {public_version})' if had else ''}.

{git(clone, "log", "-1", "--format=%h %s%n%n%b")}

{git(clone, "show", "--stat", "--format=", "HEAD").splitlines()[-1].strip()}

It isn't pushed. Look it over (git -C {shlex.quote(str(clone))} show --stat), then push it yourself:

  git -C {shlex.quote(str(clone))} push origin {branch}

Never force-push it: every tester's npm run update (git pull --ff-only) would stop working.""")


if __name__ == "__main__":
    main()
