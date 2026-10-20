"""Real producer/consumer mismatches: calendar dates, Health days, and Discord DM labels."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_glance import library
import glance

DESKTOP = Path(__file__).resolve().parents[2]


class ShapeBoundaries(unittest.TestCase):
    def database(self, rows):
        db = library(rows)
        self.addCleanup(shutil.rmtree, db.parent)
        return db

    def explore(self, db, *args):
        p = subprocess.run([sys.executable, str(DESKTOP / 'py/explore.py'), *args],
                           env={**os.environ, 'CORPUS_DIR': str(db.parent), 'UMP_REPO': str(DESKTOP.parent),
                                'UMP_TZ': 'America/Los_Angeles', 'UMP_EXPLORE_CACHE': str(db.parent / 'cache')},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr[-2000:])
        return json.loads(p.stdout)

    def test_google_calendar_date_stays_on_its_day(self):
        # Google Takeout's DTSTART;VALUE=DATE:20240601 becomes ts='2024-06-01'.
        # This is also a shape present in the existing library, not a made-up malformed value.
        db = self.database([{'source': 'google_calendar', 'kind': 'event', 'ts': '2024-06-01',
                             'ts_end': '2024-06-02', 'title': 'Holiday'}])
        out = self.explore(db, 'on-this-day', '06-01')
        self.assertEqual([e['title'] for y in out['years'] for e in y['events']], ['Holiday'])
        out = self.explore(db, 'on-this-day', '05-31')
        self.assertEqual([e['title'] for y in out['years'] for e in y['events']], [])

    def test_whole_days_do_not_move_to_the_previous_month_in_charts(self):
        # Health writes local dates at midnight without a zone. Takeout uses date-only all-day events.
        db = self.database([{'source': 'health', 'kind': 'health_day', 'ts': '2024-06-01T00:00:00', 'meta': {'steps': 10000}},
                            {'source': 'google_calendar', 'kind': 'event', 'ts': '2024-06-01', 'title': 'Holiday'},
                            {'source': 'calendar', 'kind': 'event', 'ts': '2024-06-01T00:00:00Z',
                             'title': 'Day off', 'meta': {'all_day': True}},
                            {'source': 'calendar', 'kind': 'event', 'ts': '2024-06-01T01:00:00Z', 'title': 'Late meeting'}])
        self.addCleanup(time.tzset)
        with patch.dict(os.environ, {'TZ': 'America/Los_Angeles'}):
            time.tzset()
            g = glance.glance(db, ['health', 'google_calendar', 'calendar'])
            self.assertEqual(g['months'], {'2024-05': 1, '2024-06': 3})
            self.assertEqual(sum(g['hours']), 1, 'only the timed meeting has an hour')
        time.tzset()

    def test_health_zoned_day_uses_the_timezone_it_was_recorded_in(self):
        db = self.database([{'source': 'health', 'kind': 'health_day', 'ts': '2024-05-31T18:00:00Z',
                             'meta': {'steps': 10000, 'timezone': 'Asia/Tokyo'}}])
        self.addCleanup(time.tzset)
        with patch.dict(os.environ, {'TZ': 'America/Los_Angeles'}):
            time.tzset()
            self.assertEqual(glance.glance(db, ['health'])['months'], {'2024-06': 1})
        time.tzset()

    def test_stream_date_only_calendar_event_is_all_day(self):
        db = self.database([{'source': 'google_calendar', 'kind': 'event', 'ts': '2024-06-01',
                             'ts_end': '2024-06-02', 'title': 'Holiday'}])
        p = subprocess.run([sys.executable, str(DESKTOP.parent / 'connectors/stream.py'), 'month', '2024-06'],
                           env={**os.environ, 'CORPUS_DIR': str(db.parent), 'UMP_TZ': 'America/Los_Angeles'},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        events = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]['all_day'])
        self.assertTrue(events[0]['start'].startswith('2024-06-01T00:00:00'))

    def test_discord_dm_with_unknown_index_name_still_counts_as_one_person(self):
        # imports.discord emits 'DM with ...' when index.json says Unknown Participant;
        # channel.json type DM and the recipient identify the one-on-one chat.
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / 'corpus'
            root = corpus / 'imports/discord/package'
            files = {
                'Messages/index.json': {'11': 'Direct Message with Unknown Participant', '12': None},
                'Account/user.json': {'id': '100', 'relationships': [
                    {'id': '300', 'user': {'id': '300', 'global_name': 'Grace'}}]},
                'Messages/c11/channel.json': {'id': '11', 'type': 'DM', 'recipients': ['100', '300']},
                'Messages/c12/channel.json': {'id': '12', 'type': 'GROUP_DM', 'recipients': ['100', '300', '400']},
                'Messages/c12/messages.json': [{'ID': '121', 'Timestamp': '2024-06-01 18:00:00',
                                               'Contents': 'hello group', 'Attachments': ''}],
                'Messages/c11/messages.json': [{'ID': '111', 'Timestamp': '2024-06-01 18:00:00',
                                               'Contents': 'hello', 'Attachments': ''}],
            }
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
            env = {**os.environ, 'CORPUS_DIR': str(corpus), 'UMP_REPO': str(DESKTOP.parent)}
            for script in ('imports.py', 'build_index.py'):
                p = subprocess.run([sys.executable, str(DESKTOP.parent / 'connectors' / script)],
                                   env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            out = self.explore(corpus / 'corpus.db', 'people')
            self.assertEqual(['Grace'], [p['name'] for p in out['people']], 'the group DM remains a group')
            p = subprocess.run([sys.executable, str(DESKTOP.parent / 'connectors/stream.py'), 'month', '2024-06'],
                               env={**env, 'UMP_TZ': 'America/Los_Angeles'}, capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stderr[-2000:])
            events = [json.loads(line) for line in p.stdout.splitlines()]
            self.assertTrue(any(e.get('people') == ['Grace'] and e['title'] == 'Messaged Grace' for e in events), events)


if __name__ == '__main__':
    unittest.main()
