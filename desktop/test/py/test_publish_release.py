"""publish_release.py, end to end on throwaway repositories: a made-up private repo (with this repo's release_copy.py and
publish_release.py, and a made-up corpus), and a bare repository standing in for the public one on GitHub. Its tests are
a stand-in command; nothing is cloned from or pushed to anywhere real.
"""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test",
       "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com"}
CHANGELOG = """# What's new in Homecoming

## 0.3.0

- **Updating is one command:** `npm run update`.
- **What's new, once.**

## 0.2.0

The first public release.
"""


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def write(root: Path, rel: str, text: str):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)


class PublishRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        # The private repo: what release_copy.py expects, and a corpus with someone in it.
        p = self.private = self.tmp / "private"
        for name in ("release_copy.py", "publish_release.py"):
            write(p, f"desktop/scripts/{name}", (SCRIPTS / name).read_text())
        write(p, "README.md", "# Homecoming\n\nThis is version 0.3. Clone it from github.com/benshi34/homecoming.\n")
        write(p, "WHAT_TO_TRY.md", "Try it.\n")
        write(p, "CHANGELOG.md", CHANGELOG)
        write(p, ".gitignore", "corpus/\nevals/\n")
        write(p, "desktop/package.json", '{\n  "name": "homecoming-desktop",\n  "version": "0.3.0",\n  "scripts": {\n'
              '    "demo": "node build.mjs && node scripts/demo.mjs",\n    "start": "node build.mjs"\n  }\n}\n')
        write(p, "desktop/README.md", "# Desktop\n\nTo show the app without anyone's real data, run the demo:\n\nnpm run demo\n\n"
              "It uses the connectors.\n")
        for rel in ("desktop/scripts/demo.mjs", "desktop/scripts/demo_library.py", "desktop/test/e2e/demo.test.ts", "desktop/test/unit/demo.test.ts"):
            write(p, rel, "// the demo\n")
        write(p, "connectors/common.py", "# reads things\n")
        write(p, "notes/research.md", "private notes\n")
        corpus = p / "corpus"
        write(p, "corpus/identity.json", json.dumps({"names": ["Wren Altamira"], "emails": ["wren@example.net"], "usernames": [], "phones": []}))
        db = sqlite3.connect(corpus / "corpus.db")
        db.execute("create table records (kind, author, is_me)")
        db.executemany("insert into records values ('message', 'Juniper Okonkwo-Hale', 0)", [()] * 20)
        db.commit()
        db.close()
        subprocess.run(["git", "init", "-q", "-b", "main", str(p)], check=True, env=ENV)
        git(p, "add", "-A")
        git(p, "commit", "-q", "-m", "Homecoming, privately")
        # The public repo, at the version before.
        self.public = self.tmp / "public.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.public)], check=True, env=ENV)
        seed = self.tmp / "seed"
        subprocess.run(["git", "clone", "-q", str(self.public), str(seed)], check=True, env=ENV, capture_output=True)
        write(seed, "desktop/package.json", '{ "name": "homecoming-desktop", "version": "0.2.0" }\n')
        write(seed, "README.md", "old\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "Homecoming 0.2.0")
        git(seed, "push", "-q", "origin", "main")
        self.published = git(self.public, "rev-parse", "main")

    def publish(self, *args, test_command="true"):
        into = self.tmp / f"out{len(list(self.tmp.glob('out*')))}"
        r = subprocess.run([sys.executable, str(self.private / "desktop/scripts/publish_release.py"), "--ref", "main", "--no-fetch",
                            "--public", str(self.public), "--into", str(into), "--test-command", test_command, *args],
                           capture_output=True, text=True, env=ENV)
        return r.returncode, r.stdout + r.stderr, into

    def assertNotPushed(self):
        self.assertEqual(git(self.public, "rev-parse", "main"), self.published, "never pushed")

    def test_ready_to_push_and_not_pushed(self):
        (self.private / "README.md").write_text("uncommitted, and not published\n")
        code, out, clone = self.publish()
        self.assertEqual(code, 0, out)
        self.assertEqual(git(clone, "log", "-1", "--format=%B"),
                         "Homecoming 0.3.0\n\n- Updating is one command: `npm run update`.\n- What's new, once.")
        self.assertEqual(git(clone, "rev-parse", "HEAD~1"), self.published, "one commit on top of the public one")
        self.assertIn(f"git -C {clone} push origin main", out)
        self.assertIn("It isn't pushed", out)
        self.assertIn("Never force-push", out)
        self.assertNotPushed()
        files = set(git(clone, "ls-files").split("\n"))
        self.assertIn("CHANGELOG.md", files)
        self.assertNotIn("desktop/scripts/demo.mjs", files, "the demo never ships")
        self.assertNotIn("notes/research.md", files)
        self.assertNotIn("corpus/identity.json", files)
        self.assertIn("This is version 0.3", (clone / "README.md").read_text(), "the committed README, not what's uncommitted here")
        self.assertEqual(git(self.private, "worktree", "list").count("\n"), 0, "its worktree of main is gone")

    def test_personal_data_stops_it(self):
        write(self.private, "WHAT_TO_TRY.md", "Ask about Juniper Okonkwo-Hale.\n")
        git(self.private, "commit", "-q", "-am", "oops")
        code, out, clone = self.publish()
        self.assertEqual(code, 1)
        self.assertIn("WHAT_TO_TRY.md:1: Juniper Okonkwo-Hale", out)
        self.assertIn("Nothing was published", out)
        self.assertFalse(clone.exists())
        self.assertNotPushed()

    def test_the_version_must_be_newer_and_in_the_changelog(self):
        write(self.private, "desktop/package.json", (self.private / "desktop/package.json").read_text().replace("0.3.0", "0.2.0"))
        git(self.private, "commit", "-q", "-am", "not bumped")
        code, out, _ = self.publish()
        self.assertEqual(code, 1)
        self.assertIn("says 0.2.0, and the public repository has 0.2.0", out)

        write(self.private, "desktop/package.json", (self.private / "desktop/package.json").read_text().replace("0.2.0", "0.4.0"))
        git(self.private, "commit", "-q", "-am", "bumped, no notes")
        code, out, _ = self.publish()
        self.assertEqual(code, 1)
        self.assertIn('CHANGELOG.md doesn\'t say what\'s new in 0.4.0: add a "## 0.4.0" section', out)
        self.assertNotPushed()

    def test_failing_tests_stop_it_before_the_commit(self):
        code, out, clone = self.publish(test_command="exit 3")
        self.assertEqual(code, 1)
        self.assertIn("didn't pass", out)
        self.assertEqual(git(clone, "rev-parse", "HEAD"), self.published, "nothing committed")
        self.assertNotPushed()


if __name__ == "__main__":
    unittest.main()
