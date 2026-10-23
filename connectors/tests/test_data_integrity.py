"""Exports read again, twice, or alongside another: every chat export, a second Takeout (the same account's or another's),
Discord downloaded twice, both Spotify downloads, times without a zone, mappings taken out. All on made-up exports.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

CONNECTORS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONNECTORS))
import common

with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'CORPUS', Path(tmp)):
    (Path(tmp) / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
    import imports


class Collect:
    """Stands in for the writer, and refuses what the writer would: an unknown field, no id, an id twice."""
    recs = {}

    def __init__(self, source):
        self.source = source

    def has(self, key):
        return any(r['id'] == str(key) for r in Collect.recs.get(self.source, []))

    def add(self, **r):
        assert set(r) <= set(common.FIELDS), set(r) - set(common.FIELDS)
        assert r.get('id') is not None and not self.has(r['id']), f"missing or duplicate id {r.get('id')!r} in {self.source}"
        json.dumps(r)
        Collect.recs.setdefault(self.source, []).append({**r, 'id': str(r['id'])})


def zipped(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, (str, bytes)) else json.dumps(data))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.imports = self.root / 'corpus/imports'
        self.imports.mkdir(parents=True)
        for name, value in (('IMPORTS', self.imports), ('MEDIA', self.root / 'corpus/media')):
            p = patch.object(imports, name, value)
            p.start()
            self.addCleanup(p.stop)
        me = patch.dict(imports.ME, {'names_l': {'ada lovelace'}, 'usernames_l': set(), 'emails_l': set()})
        me.start()
        self.addCleanup(me.stop)
        # Times without a zone are this Mac's clock: one zone for every run of the tests.
        old = os.environ.get('TZ')
        os.environ['TZ'] = 'America/New_York'
        time.tzset()
        self.addCleanup(lambda: (os.environ.__setitem__('TZ', old) if old else os.environ.pop('TZ', None), time.tzset()))
        Collect.recs = {}

    def write(self, rel, data):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def got(self, source, kind=None):
        return [r for r in Collect.recs.get(source, []) if kind is None or r['kind'] == kind]


def chat(*lines):
    return '\n'.join(f'[{d}, {t}] {who}: {text}' for d, t, who, text in lines)


class WhatsAppExportTests(Base):
    ALICE = [('1/1/24', '10:00:00 AM', 'Alice', 'Morning!'), ('1/1/24', '10:01:00 AM', 'Ada Lovelace', 'Hello'),
             ('1/1/24', '10:01:00 AM', 'Ada Lovelace', 'Hello'),  # the same thing twice in the same minute: two messages
             ('1/2/24', '9:00:00 PM', 'Alice', 'Night')]

    def test_every_chat_and_a_chat_exported_again(self):
        zipped(self.imports / 'whatsapp/WhatsApp Chat - Alice.zip', {'_chat.txt': chat(*self.ALICE)})
        zipped(self.imports / 'whatsapp/WhatsApp Chat - Bob.zip', {'_chat.txt': chat(('1/3/24', '8:00:00 AM', 'Bob', 'Hi'),
                                                                                      ('1/3/24', '8:05:00 AM', 'Bob', 'Lunch?'),
                                                                                      ('1/3/24', '8:06:00 AM', 'Ada Lovelace', 'Sure'))})
        # Alice's chat, exported again later: macOS called the download "... (1).zip"; it has one more message.
        zipped(self.imports / 'whatsapp/WhatsApp Chat - Alice (1).zip', {'_chat.txt': chat(*self.ALICE, ('1/5/24', '7:00:00 AM', 'Alice', 'Newer'))})
        imports.whatsapp(imports.entries(), Collect, set())
        msgs = self.got('whatsapp_export')
        self.assertEqual(sorted({m['thread'] for m in msgs}), ['Alice', 'Bob'], 'every export, named without " (1)" or ".zip"')
        alice = sorted((m for m in msgs if m['thread'] == 'Alice'), key=lambda m: (m['ts'], m['id']))
        self.assertEqual([m['text'] for m in alice], ['Morning!', 'Hello', 'Hello', 'Night', 'Newer'], 'each message once')
        self.assertEqual(alice[0]['ts'], '2024-01-01T15:00:00Z', "10 AM on this Mac's clock (New York), in UTC")
        self.assertEqual(alice[3]['ts'], '2024-01-03T02:00:00Z')
        self.assertTrue(alice[1]['is_me'])
        self.assertEqual(len(self.got('whatsapp_export')), 8)
        # Read again from the newer export alone: the same ids, so nothing moves.
        first = {m['id'] for m in alice}
        (self.imports / 'whatsapp/WhatsApp Chat - Alice.zip').unlink()
        Collect.recs = {}
        imports.whatsapp(imports.entries(), Collect, set())
        self.assertEqual({m['id'] for m in self.got('whatsapp_export') if m['thread'] == 'Alice'}, first)


class CalendarTests(Base):
    def test_times_in_their_own_zone_or_this_macs(self):
        ics = '\r\n'.join(['BEGIN:VCALENDAR', 'BEGIN:VEVENT', 'UID:paris', 'SUMMARY:Call from Paris',
                           'DTSTART;TZID=Europe/Paris:20240601T100000', 'DTEND;TZID=Europe/Paris:20240601T110000', 'END:VEVENT',
                           'BEGIN:VEVENT', 'UID:floating', 'SUMMARY:Dentist', 'DTSTART:20240601T100000', 'END:VEVENT',
                           'BEGIN:VEVENT', 'UID:outlook', 'SUMMARY:Standup', 'DTSTART;TZID="Pacific Standard Time":20240601T100000', 'END:VEVENT',
                           'BEGIN:VEVENT', 'UID:day', 'SUMMARY:Holiday', 'DTSTART;VALUE=DATE:20240601', 'END:VEVENT',
                           'BEGIN:VEVENT', 'UID:utc', 'SUMMARY:Launch', 'DTSTART:20240601T100000Z', 'END:VEVENT', 'END:VCALENDAR'])
        self.write('takeout-1/Takeout/Calendar/ada@example.com.ics', ics)
        imports.google(imports.entries(), Collect, set())
        ev = {r['title']: r for r in self.got('google_calendar')}
        self.assertEqual((ev['Call from Paris']['ts'], ev['Call from Paris']['ts_end']), ('2024-06-01T08:00:00Z', '2024-06-01T09:00:00Z'))
        self.assertEqual(ev['Dentist']['ts'], '2024-06-01T14:00:00Z', 'floating: as this Mac shows it')
        self.assertEqual(ev['Standup']['ts'], '2024-06-01T14:00:00Z', 'a zone named some other way: this Mac\'s')
        self.assertEqual(ev['Holiday']['ts'], '2024-06-01', 'a whole day stays a date')
        self.assertEqual(ev['Launch']['ts'], '2024-06-01T10:00:00Z')


class SecondTakeoutTests(Base):
    def takeout(self, folder, files):
        return zipped(self.imports / folder / f'{folder}-001.zip', {f'Takeout/{k}': v for k, v in files.items()})

    def test_the_same_account_twice_and_another_account(self):
        note = {'title': 'Groceries', 'textContent': 'milk', 'createdTimestampUsec': 1700000000000000, 'userEditedTimestampUsec': 1700000000000000}
        photo = {'title': 'IMG_0001.JPG', 'photoTakenTime': {'timestamp': '1700000000'}, 'url': 'https://photos.google.com/photo/AAA'}
        self.takeout('takeout-20240101T000000Z', {
            'Keep/Groceries.json': note, 'Google Photos/Photos from 2023/IMG_0001.JPG.json': photo,
            'Google Photos/Seaside/IMG_0001.JPG.json': photo, 'Google Photos/Tasks/IMG_0002.JPG.json': {**photo, 'title': 'IMG_0002.JPG', 'url': 'https://photos.google.com/photo/BBB'},
            'Drive/Report.txt': 'Quarterly report', 'Drive/Plan.txt': 'First plan'})
        # A year later, the same account: the note edited since, the same photo, the same report, the plan changed.
        self.takeout('takeout-20250101T000000Z', {
            'Keep/Groceries.json': {**note, 'textContent': 'milk, eggs', 'userEditedTimestampUsec': 1730000000000000},
            'Google Photos/Photos from 2023/IMG_0001.JPG.json': photo, 'Drive/Report.txt': 'Quarterly report', 'Drive/Plan.txt': 'Second plan'})
        # Another account: a note of the same name, a photo of the same name.
        self.takeout('takeout-20250601T000000Z', {
            'Keep/Groceries.json': {'title': 'Groceries', 'textContent': 'tea', 'createdTimestampUsec': 1710000000000000},
            'Google Photos/Photos from 2023/IMG_0001.JPG.json': {**photo, 'url': 'https://photos.google.com/photo/CCC'}})
        es = imports.entries()
        imports.google(es, Collect, set())  # no "duplicate id": the whole of Google is read
        imports.other_documents(es, Collect, set())
        keep = sorted(r['text'] for r in self.got('google_keep'))
        self.assertEqual(keep, ['Groceries\nmilk, eggs', 'Groceries\ntea'], 'the latest edit of the note, and the other account\'s')
        photos = {r['url']: r for r in self.got('google_photos')}
        self.assertEqual(sorted(photos), ['https://photos.google.com/photo/AAA', 'https://photos.google.com/photo/BBB',
                                          'https://photos.google.com/photo/CCC'])
        self.assertEqual(photos['https://photos.google.com/photo/AAA']['thread'], 'Seaside', 'its album, not the year\'s folder')
        self.assertEqual(photos['https://photos.google.com/photo/AAA']['meta']['albums'], ['Photos from 2023', 'Seaside'])
        self.assertEqual(photos['https://photos.google.com/photo/BBB']['thread'], 'Tasks', 'an album named Tasks is photos, not Google Tasks')
        docs = sorted(r['text'] for r in self.got('imported_documents'))
        self.assertEqual(docs, ['First plan', 'Quarterly report', 'Second plan'], 'the same file once; a changed one is its own')

    def test_youtube_from_two_accounts(self):
        head = 'Comment ID,Channel ID,Comment Create Timestamp,Price,Parent Comment ID,Post ID,Video ID,Comment Text\n'
        yt = 'YouTube and YouTube Music/comments/comments.csv'
        self.takeout('takeout-personal', {yt: head + 'c1,UCa,2026-09-02T10:00:00+00:00,0,,,v1,"{""text"":""from the personal account""}"\n'})
        self.takeout('takeout-school', {yt: head + 'c2,UCb,2026-09-03T10:00:00+00:00,0,,,v2,"{""text"":""from the school account""}"\n'})
        imports.youtube(imports.entries(), Collect, set())
        self.assertEqual(sorted(r['text'] for r in self.got('youtube')), ['from the personal account', 'from the school account'])


class DiscordTwiceTests(Base):
    def test_a_package_downloaded_again_adds_its_newer_messages(self):
        base = {'Messages/index.json': {'111': 'Direct Message with grace'}, 'Account/user.json': {'id': '42', 'relationships': []},
                'Messages/c111/channel.json': {'id': '111', 'type': 'DM', 'recipients': ['42', '7']}}
        old = [{'ID': '1', 'Timestamp': '2024-01-01 10:00:00', 'Contents': 'older message', 'Attachments': ''}]
        zipped(self.imports / 'discord/package.zip', {**base, 'Messages/c111/messages.json': old})
        # "package (1).zip" sorts first: it must not be the only one read, nor the older one win.
        zipped(self.imports / 'discord/package (1).zip', {**base, 'Messages/c111/messages.json': old + [
            {'ID': '2', 'Timestamp': '2026-09-01 10:00:00', 'Contents': 'newer message', 'Attachments': ''}]})
        imports.discord(imports.entries(), Collect, set())
        self.assertEqual(sorted(r['text'] for r in self.got('discord')), ['newer message', 'older message'])


class SmallerFixesTests(Base):
    def js(self, part, items):
        return f'window.YTD.{part}.part0 = ' + json.dumps(items)

    def test_a_deleted_post_is_deleted(self):
        x = 'x/data/'
        self.write(x + 'account.js', self.js('account', [{'account': {'accountId': '42'}}]))
        self.write(x + 'tweets.js', self.js('tweets', [{'tweet': {'id_str': '1', 'full_text': 'kept', 'created_at': 'Tue Sep 01 10:00:00 +0000 2026'}}]))
        self.write(x + 'deleted-tweets.js', self.js('deleted_tweets', [{'tweet': {
            'id_str': '99', 'full_text': 'oops typo', 'created_at': 'Wed Sep 02 10:00:00 +0000 2026', 'deleted_at': 'Wed Sep 02 10:05:00 +0000 2026'}}]))
        imports.x_archive(imports.entries(), Collect, set())
        posts = {r['id']: r for r in self.got('x', 'post')}
        self.assertEqual(posts['99']['meta']['tier'], 'deleted', 'left out where deleted mail is')
        self.assertNotIn('tier', posts['1']['meta'])

    def test_reddit_chats_are_the_owners_without_their_username(self):
        self.write('reddit/export_20261001/chat_history.csv',
                   'message_id,created_at,updated_at,username,message,thread_parent_message_id,channel_url,subreddit,channel_name,conversation_type\n'
                   'm1,2026-09-01 10:00:00 UTC,,grace_h,hi there,,ch1,,,direct\n'
                   'm2,2026-09-01 10:01:00 UTC,,ada_l,hello!,m1,ch1,,,direct\n'
                   'm3,2026-09-02 10:01:00 UTC,,ada_l,anyone?,,ch2,,,direct\n'
                   'm4,2026-09-02 10:02:00 UTC,,alan_t,yes,,ch2,,,direct\n')
        imports.csv_exports(imports.entries(), Collect, set())
        msgs = {r['id']: r for r in self.got('reddit', 'message')}
        self.assertEqual({k: (v['author'], v['is_me']) for k, v in msgs.items()},
                         {'m1': ('grace_h', False), 'm2': ('me', True), 'm3': ('me', True), 'm4': ('alan_t', False)},
                         'ada_l is in every chat: the export is hers')
        self.assertEqual((msgs['m1']['thread_name'], msgs['m4']['thread_name']), ('grace_h', 'alan_t'))

    def test_spotify_plays_in_both_downloads_count_once(self):
        zipped(self.imports / 'spotify/my_spotify_data.zip', {'Spotify Account Data/StreamingHistory_music_0.json': [
            {'endTime': '2026-09-01 10:03', 'artistName': 'Band A', 'trackName': 'Song A', 'msPlayed': 200000},
            {'endTime': '2026-10-01 09:00', 'artistName': 'Band B', 'trackName': 'Song B', 'msPlayed': 200000}]})  # after Extended's last
        zipped(self.imports / 'spotify/my_spotify_data (1).zip', {'Spotify Extended Streaming History/Streaming_History_Audio_2026.json': [
            {'ts': '2026-09-01T10:03:21Z', 'ms_played': 200000, 'master_metadata_track_name': 'Song A', 'master_metadata_album_artist_name': 'Band A'}]})
        imports.spotify(imports.entries(), Collect, set())
        self.assertEqual(sorted((r['title'], r['ts']) for r in self.got('spotify', 'media')),
                         [('Song A', '2026-09-01T10:03:21Z'), ('Song B', '2026-10-01T09:00:00Z')])

    def test_a_projects_json_that_isnt_json_stops_nothing(self):
        self.write('claude/data-2026-10-01/conversations.json', [{'uuid': 'c1', 'name': 'x', 'chat_messages': [
            {'uuid': 'm1', 'sender': 'human', 'created_at': '2026-09-01T10:00:00Z', 'text': 'hello'}]}])
        self.write('takeout-1/Takeout/Drive/app/projects.json', '{"a": 1,}')  # some other app's file of that name
        imports.ai_exports(imports.entries(), Collect, set())
        self.assertEqual([r['text'] for r in self.got('claude_ai')], ['hello'])

    def test_a_tar_export_is_unpacked_once(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as t:
            data = b'[{"name": "corpus"}]'
            info = tarfile.TarInfo('repositories_000001.json')
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        tgz = self.write('github/b7f1.tar.gz', buf.getvalue())
        es = imports.entries()
        self.assertEqual(es[0].json(), [{'name': 'corpus'}])
        unpacked = self.root / 'corpus/raw/unpacked'
        self.assertEqual(len(list(unpacked.iterdir())), 1, 'in the library, not a temporary folder')
        with patch.object(tarfile, 'open', side_effect=AssertionError('unpacked again')):
            self.assertEqual([e.json() for e in imports.entries()], [[{'name': 'corpus'}]], 'read from where it was unpacked')
        tgz.unlink()
        self.assertEqual(imports.entries(), [])
        self.assertEqual(list(unpacked.iterdir()), [], 'taken out with its export')


class MappedExportTests(unittest.TestCase):
    """A mapping whose id field isn't unique, and a mapping taken out: run as the app runs imports."""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.corpus = Path(t.name) / 'corpus'
        for d in ('imports/goodreads', 'imports/letterboxd', 'mappings'):
            (self.corpus / d).mkdir(parents=True)
        (self.corpus / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
        (self.corpus / 'imports/goodreads/library.json').write_text(json.dumps({'books': [{'shelf': 'read', 'title': 'A'}, {'shelf': 'read', 'title': 'B'}]}))
        (self.corpus / 'imports/letterboxd/films.json').write_text(json.dumps({'films': [{'slug': 'f1', 'name': 'Film 1'}]}))
        (self.corpus / 'mappings/goodreads.json').write_text(json.dumps({'service': 'Goodreads', 'items': [
            {'file': 'library.json', 'path': 'books', 'kind': 'read', 'title': 'title', 'id': 'shelf'}]}))
        (self.corpus / 'mappings/letterboxd.json').write_text(json.dumps({'service': 'Letterboxd', 'items': [
            {'file': 'films.json', 'path': 'films', 'kind': 'watch', 'title': 'name', 'id': 'slug'}]}))

    def imports_run(self):
        env = {**os.environ, 'CORPUS_DIR': str(self.corpus)}
        r = subprocess.run([sys.executable, '-c', 'import imports; imports.main()'], cwd=CONNECTORS, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads((self.corpus / 'manifest.json').read_text())

    def records(self, source):
        f = self.corpus / f'normalized/{source}.jsonl'
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def test_repeats_are_skipped_and_a_mapping_taken_out_takes_its_records(self):
        m = self.imports_run()
        self.assertEqual([r['title'] for r in self.records('letterboxd')], ['Film 1'], 'one mapping\'s mistake stops no other')
        self.assertEqual([r['title'] for r in self.records('goodreads')], ['A'])
        self.assertEqual(m['goodreads']['notes'], {'same_id_as_another': 1})
        (self.corpus / 'mappings/goodreads.json').unlink()
        m = self.imports_run()
        self.assertNotIn('goodreads', m)
        self.assertFalse((self.corpus / 'normalized/goodreads.jsonl').exists(), 'not kept beside the catch-all\'s copy')
        self.assertEqual(len(self.records('goodreads_other')), 2, 'its file is the catch-all\'s again')

    def test_overlapping_bank_downloads_are_kept_once_and_not_counted_as_a_mistake(self):
        here = Path(__file__).resolve().parent
        (self.corpus / 'imports/chase').mkdir()
        for f in (here / 'fixtures/ofx/chase').iterdir():
            (self.corpus / 'imports/chase' / f.name).write_bytes(f.read_bytes())
        (self.corpus / 'mappings/chase.json').write_bytes((here.parents[1] / 'desktop/data/mappings/chase.json').read_bytes())
        for run in (1, 2):
            m = self.imports_run()
            recs = self.records('chase')
            self.assertEqual(len(recs), 10, f'run {run}: March and April overlap by two; each once')
            self.assertEqual(len({r['id'] for r in recs}), 10)
            self.assertEqual(m['chase']['notes'], {'in_another_file': 2}, 'not same_id_as_another: no mistake to report')

    def test_a_broken_file_in_a_mapped_export_stops_no_other(self):
        """A download too deep to read, or a CSV field longer than csv allows: skipped, and every other export is read."""
        here = Path(__file__).resolve().parent
        (self.corpus / 'imports/chase').mkdir()
        (self.corpus / 'imports/chase/Chase1234_Activity_20260331.QFX').write_text('<OFX>' + '<AGG>\n' * 200_000)
        (self.corpus / 'imports/chase/Chase1234_Activity_20260415.CSV').write_text('Details,Posting Date,Description\n"' + 'x' * 200_000 + '",03/01/2026,A\n')
        shutil.copy(here / 'fixtures/ofx/chase/Chase5678_Activity_20260331.QBO', self.corpus / 'imports/chase')
        (self.corpus / 'mappings/chase.json').write_bytes((here.parents[1] / 'desktop/data/mappings/chase.json').read_bytes())
        self.imports_run()
        self.assertEqual([r['title'] for r in self.records('letterboxd')], ['Film 1'], 'another export: read')
        self.assertTrue(self.records('chase'), 'the same export\'s good download: read')


class LeftoverDateTests(unittest.TestCase):
    """A CSV no parser knows still gets its dates when they're written 2024/01/13 (Goodreads), not only 2024-01-13."""

    def test_slash_dates(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        corpus = Path(t.name) / 'corpus'
        (corpus / 'imports/shelf').mkdir(parents=True)
        (corpus / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
        (corpus / 'imports/shelf/library_export.csv').write_text(
            'Book Id,Title,Date Read,Date Added\n1,A,2024/08/02,2024/7/20\n2,B,,2024/09/01\n3,C,,not a date\n')
        r = subprocess.run([sys.executable, '-c', 'import imports; imports.main()'], cwd=CONNECTORS,
                           env={**os.environ, 'CORPUS_DIR': str(corpus)}, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        rs = [json.loads(x) for x in (corpus / 'normalized/shelf_other.jsonl').read_text().splitlines()]
        self.assertEqual([r.get('ts') for r in rs], ['2024-08-02T00:00:00', '2024-09-01T00:00:00', None])


if __name__ == '__main__':
    unittest.main()
