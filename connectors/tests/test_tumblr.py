"""Tumblr blog backups: made-up exports, run through the importer in a temporary corpus."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


CONNECTORS = Path(__file__).resolve().parents[1]


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class TumblrTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home, self.corpus = self.root / "home", self.root / "corpus"
        self.imports = self.corpus / "imports"
        self.home.mkdir()
        self.imports.mkdir(parents=True)
        (self.corpus / "identity.json").write_text(json.dumps({"names": [], "emails": [], "usernames": []}))

    def put_zip(self, rel, files):
        path = self.imports / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(zip_bytes(files))

    def run_import(self):
        env = {**os.environ, "HOME": str(self.home), "CORPUS_DIR": str(self.corpus), "TZ": "America/Los_Angeles"}
        result = subprocess.run([sys.executable, str(CONNECTORS / "imports.py")], cwd=CONNECTORS, env=env,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.recs = {f.stem: [json.loads(line) for line in f.read_text().splitlines()]
                     for f in (self.corpus / "normalized").glob("*.jsonl")}
        self.manifest = json.loads((self.corpus / "manifest.json").read_text())
        return self.recs

    def test_posts_index_and_media_are_claimed_by_tumblr_posts(self):
        posts = {
            "style.css": "body { color: navy; }",
            "posts_index.html": "<html><body>Index links only</body></html>",
            "html/8101.html": """<body>
              <p>First line becomes the title</p><p>Original words from the owner.</p>
              <div id="footer"><span id="timestamp"> November 10th, 2026 7:15pm </span>
              <span class="tag">sunset</span> <span class="tag">rock &amp; roll</span></div>
            </body>""",
            "html/8102.html": """<body>
              <p><a class="tumblr_blog" href="https://otherblog.tumblr.com/post/123/blue-hour">otherblog</a>:</p>
              <blockquote><figure><img src="../../media/8102_0.jpg" srcset="../../media/8102_0.jpg 1x"></figure>
              <p>A borrowed caption.</p></blockquote>
              <p>My note about this.</p>
              <div id="footer"><span id="timestamp"> November 11th, 2026 8:46pm </span>
              <span class="tag">photos</span> <span class="tag">robby m&uuml;ller</span></div>
            </body>""",
            "html/8104.html": """<body><h1></h1>
              <p><a href="https://www.tumblr.com/thirdblog/77/slug" class="tumblr_blog">thirdblog</a>:</p>
              <blockquote><p>Quoted with the link written href first.</p></blockquote><p>Mine.</p>
              <div id="footer"><span id="timestamp"> November 12th, 2026 9:30am </span></div></body>""",
            "html/8103.html": """<body><h1>Framed title</h1><p>Body under a heading.</p>
              <div id="footer"><span id="timestamp"> November 12th, 2026 9:00am </span></div></body>""",
        }
        self.put_zip("tumblr/sea-glass.tumblr.com.zip", {
            "posts.zip": zip_bytes(posts),
            "media/8102_0.jpg": b"fake-jpeg-bytes",
        })
        self.run_import()

        self.assertEqual(len(self.recs["tumblr"]), 4)
        by_id = {r["id"]: r for r in self.recs["tumblr"]}
        original = by_id["8101"]
        self.assertEqual((original["kind"], original["author"], original["is_me"]), ("post", "me", True))
        self.assertEqual(original["title"], "First line becomes the title")
        self.assertEqual(original["text"], "First line becomes the title\nOriginal words from the owner.")
        self.assertEqual(original["ts"], "2026-11-11T00:15:00Z")  # 7:15pm Eastern, whatever this Mac's zone
        self.assertEqual(original["url"], "https://sea-glass.tumblr.com/post/8101")
        self.assertEqual(original["meta"]["tags"], ["sunset", "rock & roll"])

        reblog = by_id["8102"]
        self.assertEqual(reblog["title"], "My note about this.")
        self.assertEqual(reblog["text"], "My note about this.\nReblogged from otherblog:\nA borrowed caption.")
        self.assertEqual(reblog["meta"]["reblogged_from"], {
            "blog": "otherblog", "url": "https://otherblog.tumblr.com/post/123/blue-hour"})
        self.assertEqual(reblog["meta"]["tags"], ["photos", "robby müller"])
        self.assertEqual(len(reblog["meta"]["files"]), 1)
        media = self.corpus / reblog["meta"]["files"][0]
        self.assertTrue(media.exists())
        self.assertEqual(media.read_bytes(), b"fake-jpeg-bytes")

        self.assertEqual(by_id["8103"]["title"], "Framed title")
        self.assertEqual(by_id["8104"]["meta"]["reblogged_from"], {"blog": "thirdblog", "url": "https://www.tumblr.com/thirdblog/77/slug"})
        self.assertEqual((by_id["8104"]["title"], by_id["8104"]["text"]), ("Mine.", "Mine.\nReblogged from thirdblog:\nQuoted with the link written href first."))
        self.assertEqual(by_id["8103"]["text"], "Body under a heading.")
        self.assertNotIn("imported_documents", self.recs)
        self.assertNotIn("tumblr_files", self.recs)
        self.assertFalse([source for source in self.recs if source.endswith("_files")], self.recs)
        self.assertFalse(self.manifest.get("_imports_unclaimed"), self.manifest)


if __name__ == "__main__":
    unittest.main()
