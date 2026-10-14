"""Makes the release copy of Homecoming: the app and nothing else, checked for personal data.

    python3 desktop/scripts/release_copy.py OUT [--corpus PATH] [--allow TERM ...]

Copies the committed versions (git archive HEAD, so nothing uncommitted and nothing ignored) of README.md, BETA.md,
.gitignore, desktop/ and connectors/ into OUT, which must not exist yet. The research notes, the evals and the
experiments stay behind.

Then it scans every text file in OUT for the names, emails, usernames and phone numbers in the corpus's
identity.json, and the full names of everyone with 20 or more messages in corpus.db, and exits 1 if any turn up.
Third-party data (vendored iLEAPP, the services directory, icons, coastlines) isn't scanned. --allow lets through
terms that belong there, such as the GitHub username in the clone URL. The corpus defaults to <repo>/corpus.

To update the release repo: clone it, replace everything but its .git with a new copy
(rsync -a --delete --exclude .git OUT/ CLONE/), then commit and push.
"""

import argparse
import io
import json
import re
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATHS = ["README.md", "BETA.md", ".gitignore", "desktop", "connectors"]
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


def scan(out: Path, words: set[str]) -> list[str]:
    pats = [(w, re.compile(r"(?<![\w@.])" + re.escape(w) + r"(?![\w@])", re.I)) for w in words]
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
    a = ap.parse_args()
    if a.out.exists():
        sys.exit(f"{a.out} already exists")
    export(a.out)
    print(f"Copied {sum(1 for f in a.out.rglob('*') if f.is_file())} files into {a.out}")
    if not (a.corpus / "identity.json").exists():
        print(f"No corpus at {a.corpus}: not checked for personal data")
        return
    allowed = {t.lower() for t in a.allow}
    words = {w for w in terms(a.corpus) if w.lower() not in allowed}
    hits = scan(a.out, words)
    if hits:
        print(f"{len(hits)} personal terms found; fix them (or --allow ones that belong):", *hits[:50], sep="\n  ")
        sys.exit(1)
    print(f"Checked against {len(words)} names, emails and usernames from the corpus: none found")


if __name__ == "__main__":
    main()
