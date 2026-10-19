"""Makes the release copy of Homecoming: the app and nothing else, checked for personal data.

    python3 desktop/scripts/release_copy.py OUT [--corpus PATH] [--allow TERM ...]

Copies the committed versions (git archive HEAD, so nothing uncommitted and nothing ignored) of README.md, WHAT_TO_TRY.md,
.gitignore, desktop/ and connectors/ into OUT, which must not exist yet. The research notes, the evals and the
experiments stay behind, and so does the demo (npm run demo).

Then it scans every text file in OUT for the names, emails, usernames and phone numbers in the corpus's
identity.json, and the full names of everyone with 20 or more messages in corpus.db, and exits 1 if any turn up.
Third-party data (vendored iLEAPP, the services directory, icons, coastlines) isn't scanned. --allow lets through
terms that belong there, such as the GitHub username in the clone URL. The corpus defaults to <repo>/corpus.

To update the release repo: clone it, replace everything but its .git with a new copy
(rsync -a --delete --exclude .git OUT/ CLONE/), then commit and push.
"""

import argparse
import getpass
import io
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATHS = ["README.md", "WHAT_TO_TRY.md", ".gitignore", "desktop", "connectors"]
DEMO_FILES = ["desktop/scripts/demo.mjs", "desktop/scripts/demo_library.py", "desktop/test/e2e/demo.test.ts", "desktop/test/unit/demo.test.ts"]
NOT_SCANNED = re.compile(r"(^|/)vendor/|services\.json$|service_icons\.json$|world_land\.json$|categories\.json$|link_check\.json$|THIRD_PARTY\.md$")


def export(out: Path):
    tar = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", "HEAD", *PATHS], check=True, capture_output=True).stdout
    out.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(out, filter="data")
    # The research repo commits its evals on purpose; the release has none.
    gi = out / ".gitignore"
    lines = gi.read_text().splitlines()
    gi.write_text("".join(f"{l}\n" for l in lines if "evals" not in l.lower()))
    # Nor the demo (npm run demo): its scripts, its test, its npm script and its part of desktop/README.md.
    for rel in DEMO_FILES:
        (out / rel).unlink()
    pkg = out / "desktop/package.json"
    text, n = re.subn(r'\n    "demo": "[^"\n]*",', "", pkg.read_text())
    readme = out / "desktop/README.md"
    doc, m = re.subn(r"To show the app without anyone's real data, run the demo:\n.*?\n(?=It uses the connectors)", "", readme.read_text(), flags=re.S)
    if n != 1 or m != 1:
        sys.exit("release_copy.py: couldn't take the demo out of desktop/package.json or desktop/README.md; update DEMO_FILES and these")
    pkg.write_text(text)
    readme.write_text(doc)


def terms(corpus: Path) -> set[str]:
    found: set[str] = set()
    ident = json.loads((corpus / "identity.json").read_text())
    for k in ("names", "emails", "usernames", "phones"):
        found.update(v.strip() for v in ident.get(k, []) if isinstance(v, str) and len(v.strip()) >= 3)
    db = sqlite3.connect(f"file:{corpus / 'corpus.db'}?mode=ro", uri=True)
    for (name,) in db.execute("""SELECT author FROM records WHERE kind = 'message' AND author LIKE '% %'
                                 AND (is_me IS NULL OR is_me = 0) GROUP BY author HAVING count(*) >= 20"""):
        name = (name or "").strip()
        if 5 <= len(name) <= 60 and "@" not in name:
            found.add(name)
    return found


def phone_pattern(p: str):
    """A phone number however it's written (+1 (415) 555-0100, 415.555.0100, 4155550100): its last 10 digits, with
    anything but digits allowed between them."""
    d = re.sub(r"\D", "", p)[-10:]
    return re.compile(r"\D{0,3}".join(d) + r"(?!\d)") if len(d) >= 7 else None  # with its country code before it, or not


def scan(out: Path, words: set[str], phones: set[str] = frozenset()) -> list[str]:
    pats = [(w, re.compile(r"(?<![\w@.])" + re.escape(w) + r"(?![\w@])", re.I)) for w in words]
    pats += [(f"phone {p[-4:]}", pat) for p in phones if (pat := phone_pattern(p))]
    hits = []
    for f in sorted(out.rglob("*")):
        rel = f.relative_to(out).as_posix()
        if not f.is_file() or NOT_SCANNED.search(rel):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            hits += [f"{rel}:{i}: {w}" for w, p in pats if p.search(line)]
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--corpus", type=Path, default=REPO / "corpus")
    ap.add_argument("--allow", nargs="*", default=[])
    ap.add_argument("--unchecked", action="store_true", help="make the copy with no corpus to check it against")
    a = ap.parse_args()
    if a.out.exists():
        sys.exit(f"{a.out} already exists")
    export(a.out)
    print(f"Copied {sum(1 for f in a.out.rglob('*') if f.is_file())} files into {a.out}")
    if not (a.corpus / "identity.json").exists():
        if a.unchecked:
            print(f"No corpus at {a.corpus}: not checked for personal data (--unchecked)")
            return
        sys.exit(f"No corpus at {a.corpus} to check the copy against: pass --corpus, or --unchecked to make it anyway")
    allowed = {t.lower() for t in a.allow}
    words = {w for w in terms(a.corpus) if w.lower() not in allowed}
    words.add(f"/Users/{getpass.getuser()}")  # a path with this Mac's account name in it
    ident = json.loads((a.corpus / "identity.json").read_text())
    phones = {p for p in ident.get("phones", []) if isinstance(p, str)}
    hits = scan(a.out, words, phones)
    if hits:
        print(f"{len(hits)} personal terms found; fix them (or --allow ones that belong):", *hits[:50], sep="\n  ")
        sys.exit(1)
    print(f"Checked against {len(words)} names, emails and usernames from the corpus: none found")


if __name__ == "__main__":
    main()
