"""What the readers got wrong, on made-up exports: Google's ads kept as ads, not as what you watched or visited.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common

with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'CORPUS', Path(tmp)):
    (Path(tmp) / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
    import imports


class Collect:
    """Stands in for the writer: what each source got."""
    recs = {}

    def __init__(self, source):
        self.source = source

    def has(self, key):
        return False

    def add(self, **r):
        Collect.recs.setdefault(self.source, []).append(r)


class GoogleActivityTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.imports = Path(t.name) / 'corpus/imports'
        p = patch.object(imports, 'IMPORTS', self.imports)
        p.start()
        self.addCleanup(p.stop)
        Collect.recs = {}

    def test_ads_are_ads(self):
        yt = self.imports / 'takeout-20261005/Takeout/My Activity/YouTube'
        yt.mkdir(parents=True)
        (yt / 'MyActivity.json').write_text(json.dumps([
            {'header': 'YouTube', 'title': 'Watched A lecture on tides', 'titleUrl': 'https://www.youtube.com/watch?v=1', 'time': '2026-10-01T10:00:00Z',
             'products': ['YouTube'], 'activityControls': ['YouTube watch history']},
            {'header': 'YouTube', 'title': 'Watched Buy this phone', 'titleUrl': 'https://www.youtube.com/watch?v=2', 'time': '2026-10-01T10:05:00Z',
             'products': ['YouTube'], 'details': [{'name': 'From Google Ads'}], 'activityControls': ['YouTube watch history']},
        ]))
        search = self.imports / 'takeout-20261005/Takeout/My Activity/Search'
        search.mkdir(parents=True)
        (search / 'MyActivity.json').write_text(json.dumps([
            {'header': 'Search', 'title': 'Visited Cheap flights', 'titleUrl': 'https://ads.example/1', 'time': '2026-10-02T09:00:00Z',
             'details': [{'name': 'From Google Ads'}]},
            {'header': 'Search', 'title': 'Searched for tide tables', 'time': '2026-10-02T09:01:00Z'},
        ]))
        imports.google(imports.entries(), Collect, set())
        got = sorted((r['kind'], r['title'], r['is_me']) for r in Collect.recs['google_activity'])
        self.assertEqual(got, [('ad', 'Buy this phone', False), ('ad', 'Cheap flights', False),
                               ('media', 'A lecture on tides', True), ('search', 'tide tables', True)])
        ad = next(r for r in Collect.recs['google_activity'] if r['title'] == 'Buy this phone')
        self.assertEqual((ad['author'], ad['meta']), ('Google Ads', {'product': 'YouTube', 'shown_as': 'media'}))


class DiscordTests(GoogleActivityTests):
    def test_two_packages_keep_both_names(self):
        """Two accounts' packages: each one's channel names and friends, not only the last one read."""
        for pkg, me, chans in (('package', '100', {'11': 'general in Book Club', '12': None}), ('package (2)', '200', {'21': 'random in Climbing'})):
            root = self.imports / 'discord' / pkg
            (root / 'Messages').mkdir(parents=True)
            (root / 'Account').mkdir(parents=True)
            (root / 'Messages/index.json').write_text(json.dumps(chans))
            (root / 'Account/user.json').write_text(json.dumps({'id': me, 'relationships': [{'id': '300', 'user': {'id': '300', 'global_name': 'Grace'}}] if me == '100' else []}))
            for cid in chans:
                (root / f'Messages/c{cid}').mkdir()
                info = {'id': cid, 'type': 'DM', 'recipients': [me, '300']} if chans[cid] is None else {'id': cid, 'type': 'GUILD_TEXT'}
                (root / f'Messages/c{cid}/channel.json').write_text(json.dumps(info))
                (root / f'Messages/c{cid}/messages.json').write_text(json.dumps([{'ID': f'{cid}1', 'Timestamp': '2026-10-01 10:00:00', 'Contents': 'hello', 'Attachments': ''}]))
        imports.discord(imports.entries(), Collect, set())
        names = sorted({r['thread_name'] for r in Collect.recs['discord']})
        self.assertEqual(names, ['DM with Grace', 'general in Book Club', 'random in Climbing'])


class IphoneWorkoutsTests(unittest.TestCase):
    def test_workouts_are_kept(self):
        """iLEAPP's Health - Workouts comes in (our health.py reads samples, and a workout isn't one); the rest of Health stays ours."""
        import ileapp
        self.assertIsNone(ileapp.left_out("Health", {"name": "Health - Workouts", "module": "health"}))
        self.assertEqual(ileapp.left_out("Health", {"name": "Health - Steps", "module": "health"}), "covered by our own parser")
        self.assertIsNone(ileapp.left_out("Health", {"name": "Health - Achievements", "module": "health"}))
        self.assertEqual(ileapp.kind_for("Health - Workouts", False), "workout")


class RemindersTests(unittest.TestCase):
    def test_a_subtask_names_its_parent_by_the_parents_id(self):
        import os
        import sqlite3
        import subprocess
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        home, corpus = Path(t.name) / 'home', Path(t.name) / 'corpus'
        stores = home / 'Library/Group Containers/group.com.apple.reminders/Container_v1/Stores'
        stores.mkdir(parents=True)
        corpus.mkdir()
        con = sqlite3.connect(stores / 'Data-1.sqlite')
        con.executescript("""
            create table ZREMCDBASELIST (Z_PK integer primary key, ZNAME text);
            create table ZREMCDREMINDER (Z_PK integer primary key, ZIDENTIFIER text, ZTITLE text, ZNOTES text, ZCOMPLETED int,
                ZCOMPLETIONDATE real, ZCREATIONDATE real, ZDUEDATE real, ZFLAGGED int, ZPRIORITY int, ZLIST int, ZPARENTREMINDER int,
                ZLASTMODIFIEDDATE real, ZMARKEDFORDELETION int);
            insert into ZREMCDBASELIST values (1, 'Trip');
            insert into ZREMCDREMINDER values (7, 'PARENT-UUID', 'Pack', null, 0, null, 700000000, null, 0, 0, 1, null, null, 0);
            insert into ZREMCDREMINDER values (8, 'CHILD-UUID', 'Passport', null, 0, null, 700000001, null, 0, 0, 1, 7, null, 0);
        """)
        con.commit()
        con.close()
        env = {**os.environ, 'HOME': str(home), 'CORPUS_DIR': str(corpus)}
        r = subprocess.run([sys.executable, '-c', 'import reminders; reminders.main()'], cwd=Path(__file__).resolve().parents[1], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        recs = {x['id']: x for x in map(json.loads, (corpus / 'normalized/reminders.jsonl').read_text().splitlines())}
        self.assertEqual(recs['CHILD-UUID']['meta']['subtask_of'], 'PARENT-UUID')
        self.assertNotIn('subtask_of', recs['PARENT-UUID']['meta'])


if __name__ == '__main__':
    unittest.main()
