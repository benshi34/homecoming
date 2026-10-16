"""Slack exports: who wrote each message comes from the export's own users.json, even with another export's beside it.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common

with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'CORPUS', Path(tmp)):
    (Path(tmp) / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
    import imports


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name, json.dumps(data))
    return buf.getvalue()


class Rec:
    def __init__(self):
        self.rows = []

    def has(self, key):
        return any(r['id'] == key for r in self.rows)

    def add(self, **r):
        self.rows.append(r)


class SlackTests(unittest.TestCase):
    def test_names_come_from_the_slack_exports_own_users(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for d, name, files in (
                ('claude', 'data-batch-0000.zip', {'users.json': [{'uuid': 'u1', 'full_name': 'Riley Park'}], 'conversations.json': []}),
                ('slack', 'Lumen Labs Slack export.zip', {
                    'users.json': [{'id': 'U01', 'real_name': 'Riley Park'}, {'id': 'U02', 'real_name': 'Theo Laurent'}],
                    'general/2026-01-05.json': [{'type': 'message', 'user': 'U01', 'text': 'standup in 5', 'ts': '1767600000.000100'},
                                                {'type': 'message', 'user': 'U02', 'text': 'ship it, <@U01>', 'ts': '1767600060.000200'}]})):
                (root / d).mkdir()
                (root / d / name).write_bytes(zipped(files))
            w = Rec()
            with patch.object(imports, 'IMPORTS', root), patch.object(imports, 'is_me_name', lambda n: n == 'Riley Park'):
                imports.slack(imports.entries(), lambda source: w, set())
        self.assertEqual([(r['author'], r['is_me'], r['text']) for r in w.rows],
                         [('me', True, 'standup in 5'), ('Theo Laurent', False, 'ship it, @Riley Park')])


if __name__ == '__main__':
    unittest.main()
