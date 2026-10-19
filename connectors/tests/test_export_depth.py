"""What the readers used to leave to the catch-all, or leave out, on made-up exports: YouTube's own files, Google
Tasks, Saved and Chrome bookmarks, Spotify's account data, Claude.ai's attachments and projects, Meta's reactions,
Reddit's chats and votes, X's long posts, deleted posts, Grok and group names.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import csv
import io
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
    """Stands in for the writer, and checks what the writer would: known fields, an id, no id twice."""
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


def csv_text(header, rows):
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.imports = Path(t.name) / 'corpus/imports'
        for name, value in (('IMPORTS', self.imports), ('MEDIA', Path(t.name) / 'corpus/media')):
            p = patch.object(imports, name, value)
            p.start()
            self.addCleanup(p.stop)
        me = patch.dict(imports.ME, {'names_l': {'ada lovelace'}, 'usernames_l': {'ada_l'}})
        me.start()
        self.addCleanup(me.stop)
        Collect.recs = {}

    def write(self, rel, data):
        p = self.imports / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p

    def got(self, source, kind=None):
        return [r for r in Collect.recs.get(source, []) if kind is None or r['kind'] == kind]


class YouTubeTests(Base):
    def test_comments_uploads_subscriptions_and_playlists(self):
        yt = 'takeout-20261001/Takeout/YouTube and YouTube Music/'
        self.write(yt + 'history/watch-history.json', [
            {'header': 'YouTube', 'title': 'Watched How tides work', 'titleUrl': 'https://www.youtube.com/watch?v=vid00000001', 'time': '2026-09-01T10:00:00Z'}])
        self.write(yt + 'comments/comments.csv', csv_text(
            ['Comment ID', 'Channel ID', 'Comment Create Timestamp', 'Price', 'Parent Comment ID', 'Post ID', 'Video ID', 'Comment Text', 'Top-Level Comment ID'],
            [['c1', 'UCada', '2026-09-02T10:00:00.123+00:00', '0', '', '', 'vid00000001', '{"text":"Great explanation"}', ''],
             ['c2', 'UCada', '2026-09-03T11:00:00.5+00:00', '0', 'c0', '', 'vid00000002',
              '{"text":"@Grace","mention":{"externalChannelId":"UCgrace"}},{"text":" see "},'
              '{"text":"2:30","videoLink":{"externalVideoId":"vid00000002","startTimeSeconds":150}},{"text":" for the answer\\nthanks"}', 'c0'],
             ['c3', 'UCada', '2026-09-04T09:00:00+00:00', '0', '', 'post0001', '', '{"text":"Nice post"}', '']]))
        self.write(yt + 'live chats/live chats.csv', csv_text(
            ['Live Chat ID', 'Channel ID', 'Live Chat Create Timestamp', 'Price', 'Video ID', 'Live Chat Text'],
            [['lc1', 'UCada', '2026-09-05T20:00:00.25+00:00', '0', 'vid00000003', '{"text":"hello chat"}']]))
        self.write(yt + 'video metadata/videos.csv', csv_text(
            ['Video ID', 'Approx Duration (ms)', 'Video Audio Language', 'Video Category', 'Video Description (Original)', 'Channel ID',
             'Tag 1', 'Tag 2', 'Tag 3', 'Tag 4', 'Tag 5', 'Tag 6', 'Tag 7', 'Video Title (Original)', 'Privacy', 'Video State',
             'Video Create Timestamp', 'Video Publish Timestamp'],
            [['up00000001', '61000', '', 'People', 'Filmed at the beach', 'UCada', 'beach', 'waves', '', '', '', '', '', 'My first upload',
              'Public', 'Uploaded', '2026-08-01T12:00:00+00:00', '2026-08-01T13:00:00+00:00']]))
        self.write(yt + 'video metadata/video recordings.csv', csv_text(
            ['Video ID', 'Video Recording Altitude', 'Video Recording Latitude', 'Video Recording Longitude'], [['up00000001', '0', '37.1', '-122.2']]))
        self.write(yt + 'subscriptions/subscriptions.csv', csv_text(
            ['Channel Id', 'Channel Url', 'Channel Title'], [['UCtides', 'http://www.youtube.com/channel/UCtides', 'Tide Science']]))
        head = ['Playlist ID', 'Add new videos to top', 'Playlist Image 1 Create Timestamp', 'Playlist Image 1 URL', 'Playlist Image 1 Height',
                'Playlist Image 1 Width', 'Playlist Title (Original)', 'Playlist Title (Original) Language', 'Playlist Create Timestamp',
                'Playlist Update Timestamp', 'Playlist Video Order', 'Playlist Visibility']
        self.write(yt + 'playlists/playlists.csv', csv_text(head, [
            ['WLplaylist0001', 'False', '', '', '', '', 'Watch later', '', '2020-01-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00', 'Manual', 'Private'],
            ['PLroadtrip0001', 'False', '', '', '', '', 'Road trip', '', '2026-07-01T00:00:00+00:00', '2026-07-02T00:00:00+00:00', 'Manual', 'Public']]))
        self.write(yt + 'playlists/Watch later-videos.csv', csv_text(['Video ID', 'Playlist Video Creation Timestamp'],
                                                                      [['vid00000001', '2026-09-06T08:00:00+00:00'], ['vid00000009', '2026-09-06T08:01:00+00:00']]))
        self.write(yt + 'playlists/Road trip-videos.csv', csv_text(['Video ID', 'Playlist Video Creation Timestamp'], [['up00000001', '2026-07-01T00:05:00+00:00']]))
        # A playlist in the older layout (before 2023): its details, a blank line, its videos.
        self.write(yt + 'playlists/Old mix.csv', 'Playlist Id,Channel Id,Time Created,Time Updated,Title,Description,Visibility\n'
                                                 'PLold0001,UCada,2019-01-01 00:00:00 UTC,2019-01-02 00:00:00 UTC,Old mix,,Private\n\n'
                                                 'Video Id,Time Added\nvid00000001,2019-01-02 00:00:00 UTC\n')
        used = set()
        es = imports.entries()
        imports.google(es, Collect, used)
        imports.youtube(es, Collect, used)
        by = {r['id']: r for r in self.got('youtube')}
        self.assertEqual(sorted(r['kind'] for r in by.values()),
                         ['comment'] * 4 + ['playlist'] * 2 + ['post', 'saved', 'saved', 'saved', 'saved', 'subscription'])
        self.assertEqual(by['comment:c1']['text'], 'Great explanation')
        self.assertEqual(by['comment:c1']['thread_name'], 'How tides work', 'the video named from the watch history')
        self.assertEqual(by['comment:c1']['url'], 'https://www.youtube.com/watch?v=vid00000001&lc=c1')
        self.assertEqual(by['comment:c2']['text'], '@Grace see 2:30 for the answer\nthanks', 'every segment, as plain text')
        self.assertTrue(by['comment:c2']['meta']['reply'])
        self.assertEqual(by['comment:c3']['url'], 'https://www.youtube.com/post/post0001')
        self.assertEqual((by['chat:lc1']['text'], by['chat:lc1']['meta']['file']), ('hello chat', 'live chats.csv'))
        up = by['upload:up00000001']
        self.assertEqual((up['title'], up['ts']), ('My first upload', '2026-08-01T12:00:00Z'))
        self.assertIn('Filmed at the beach', up['text'])
        self.assertEqual({k: up['meta'][k] for k in ('seconds', 'tags', 'privacy', 'lat', 'lon')},
                         {'seconds': 61, 'tags': ['beach', 'waves'], 'privacy': 'Public', 'lat': '37.1', 'lon': '-122.2'})
        sub = by['subscription:UCtides']
        self.assertEqual((sub['title'], sub['url']), ('Tide Science', 'http://www.youtube.com/channel/UCtides'))
        later = sorted((r for r in by.values() if r['kind'] == 'saved' and r['thread_name'] == 'Watch later'), key=lambda r: r['ts'])
        self.assertEqual([r['title'] for r in later], ['How tides work', 'A video (vid00000009)'])
        self.assertEqual((later[0]['thread'], later[0]['meta']['list']), ('WLplaylist0001', 'Watch later'))
        road = next(r for r in by.values() if r['kind'] == 'saved' and r['thread_name'] == 'Road trip')
        self.assertEqual(road['title'], 'My first upload', 'an upload of yours named from its own file')
        old = next(r for r in by.values() if r['kind'] == 'saved' and r['thread_name'] == 'Old mix')
        self.assertEqual((old['thread'], old['ts']), ('PLold0001', '2019-01-02T00:00:00Z'))
        self.assertEqual(by['playlist:WLplaylist0001']['meta']['visibility'], 'Private')
        for f in ('comments/comments.csv', 'live chats/live chats.csv', 'video metadata/videos.csv', 'video metadata/video recordings.csv',
                  'subscriptions/subscriptions.csv', 'playlists/playlists.csv', 'playlists/Watch later-videos.csv', 'playlists/Old mix.csv'):
            self.assertIn(f'takeout-20261001/Takeout/YouTube and YouTube Music/{f}', used, f'{f} is read, not left to the catch-all')


class GoogleTests(Base):
    def test_tasks_saved_lists_and_bookmarks(self):
        t = 'takeout-20261001/Takeout/'
        self.write(t + 'Tasks/Tasks.json', {'kind': 'tasks#taskLists', 'items': [{
            'kind': 'tasks#tasks', 'id': 'L1', 'title': 'Errands', 'create_time': '2026-09-01T00:00:00.000000Z', 'items': [
                {'kind': 'tasks#task', 'id': 't1', 'title': 'Buy stamps', 'notes': 'Post office on Main St', 'status': 'needsAction',
                 'due': '2026-10-03T00:00:00.000Z', 'created': '2026-10-01T09:00:00.000Z', 'updated': '2026-10-01T09:00:00.000000Z',
                 'task_type': 'PERSONAL_TASK'},
                {'kind': 'tasks#task', 'id': 't2', 'title': 'Return library books', 'status': 'completed', 'completed': '2026-10-02T15:00:00Z',
                 'created': '2026-10-01T09:05:00.000Z', 'updated': '2026-10-02T15:00:00.000000Z', 'parent': 't1',
                 'scheduled_time': [{'current': True, 'start': '2026-10-02T17:00:00Z'}]}]}]})
        self.write(t + 'Saved/Want to go.csv', 'Title,Note,URL,Tags,Comment\n'
                                               'Tide pools,Go at low tide,https://www.google.com/maps/place/Tide+Pools/data=!4m2!3m1,,\n')
        self.write(t + 'Saved/Saved links.csv', 'Title,Note,URL,Tags,Comment\nA bread recipe,,https://example.com/bread,baking,Try this\n')
        self.write(t + 'Chrome/Bookmarks.html', """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1790000000" LAST_MODIFIED="1790000100">Bookmarks bar</H3>
    <DL><p>
        <DT><A HREF="https://example.com/tides" ADD_DATE="1790000200" LAST_MODIFIED="1790000300">Tides &amp; currents</A>
        <DT><H3 ADD_DATE="1790000000" LAST_MODIFIED="0">Recipes</H3>
        <DL><p>
            <DT><A HREF="https://example.com/bread" ADD_DATE="1790000400">Bread</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://example.com/other" ADD_DATE="0">Other one</A>
</DL><p>
""")
        self.write(t + 'Chrome/Reading List.html', '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<TITLE>Reading List</TITLE>\n<H1>Reading List</H1>\n'
                                                   '<DL><p>\n    <DT><A HREF="https://example.com/later" ADD_DATE="1790000500">Read later</A>\n</DL><p>\n')
        used = set()
        imports.google(imports.entries(), Collect, used)
        tasks = {r['id']: r for r in self.got('google_tasks')}
        self.assertEqual((tasks['t1']['kind'], tasks['t1']['thread_name'], tasks['t1']['ts']), ('reminder', 'Errands', '2026-10-01T09:00:00Z'))
        self.assertIn('Post office on Main St', tasks['t1']['text'])
        self.assertEqual((tasks['t1']['meta']['completed'], tasks['t1']['meta']['due']), (False, '2026-10-03T00:00:00Z'))
        self.assertEqual({k: tasks['t2']['meta'][k] for k in ('completed', 'completed_at', 'due', 'subtask_of')},
                         {'completed': True, 'completed_at': '2026-10-02T15:00:00Z', 'due': '2026-10-02T17:00:00Z', 'subtask_of': 't1'})
        saved = {r['title']: r for r in self.got('google_saved')}
        self.assertEqual(set(saved), {'Tide pools', 'A bread recipe'})
        self.assertEqual((saved['Tide pools']['kind'], saved['Tide pools']['meta']['list'], saved['Tide pools']['meta']['what']), ('saved', 'Want to go', 'place'))
        self.assertIn('Go at low tide', saved['Tide pools']['text'])
        self.assertEqual((saved['A bread recipe']['meta']['tags'], saved['A bread recipe']['meta']['what']), ('baking', 'link'))
        marks = {r['title']: r for r in self.got('chrome_synced', 'bookmark')}
        self.assertEqual(set(marks), {'Tides & currents', 'Bread', 'Other one', 'Read later'})
        self.assertEqual((marks['Tides & currents']['meta']['folder'], marks['Tides & currents']['ts']), ('Bookmarks bar', '2026-09-21T14:16:40Z'))
        self.assertEqual(marks['Bread']['meta']['folder'], 'Bookmarks bar › Recipes')
        self.assertNotIn('ts', {k for k, v in marks['Other one'].items() if v}, 'no date when Chrome wrote none')
        self.assertEqual((marks['Read later']['meta']['folder'], marks['Read later']['meta']['list']), ('Reading list', 'Reading list'))
        for f in ('Tasks/Tasks.json', 'Saved/Want to go.csv', 'Chrome/Bookmarks.html', 'Chrome/Reading List.html'):
            self.assertIn(t + f, used, f'{f} is read, not left to the catch-all or kept as a page')


class SpotifyTests(Base):
    def test_account_data_and_extended_history(self):
        a = 'spotify/my_spotify_data/Spotify Account Data/'
        self.write(a + 'Playlist1.json', {'playlists': [{'name': 'Road trip', 'lastModifiedDate': '2026-09-01', 'description': 'Songs for the car',
                                                         'numberOfFollowers': 0, 'collaborators': [], 'items': [
            {'track': {'trackName': 'Song A', 'artistName': 'Band A', 'albumName': 'Album A', 'trackUri': 'spotify:track:abc123'},
             'episode': None, 'audiobook': None, 'localTrack': None, 'addedDate': '2026-08-01'},
            {'track': None, 'episode': {'episodeName': 'Ep 1', 'showName': 'Show S', 'episodeUri': 'spotify:episode:ep1'},
             'audiobook': None, 'localTrack': None, 'addedDate': '2026-08-02'}]}]})
        self.write(a + 'YourLibrary.json', {
            'tracks': [{'artist': 'Band A', 'album': 'Album A', 'track': 'Song A', 'uri': 'spotify:track:abc123'}],
            'albums': [{'artist': 'Band B', 'album': 'Album B', 'uri': 'spotify:album:b1'}],
            'shows': [{'name': 'Show S', 'publisher': 'Pub', 'uri': 'spotify:show:s1'}], 'episodes': [],
            'bannedTracks': [], 'artists': [{'name': 'Band C', 'uri': 'spotify:artist:c1'}],
            'bannedArtists': [{'name': 'Band D', 'uri': 'spotify:artist:d1'}], 'other': []})
        self.write(a + 'SearchQueries.json', [{'platform': 'IPHONE', 'searchTime': '2026-09-05T12:00:00.000Z[UTC]', 'searchQuery': 'lofi beats',
                                               'searchInteractionURIs': ['spotify:playlist:p1']}])
        self.write(a + 'Inferences.json', {'inferences': ['1P_Custom_Night_Owls', '3P_Coffee_Drinkers']})
        self.write(a + 'Marquee.json', [{'artistName': 'Band A', 'segment': 'Light listeners'}])
        self.write('spotify/my_spotify_data (1)/Spotify Extended Streaming History/Streaming_History_Audio_2026.json', [
            {'ts': '2026-09-01T10:00:00Z', 'platform': 'ios', 'ms_played': 200000, 'conn_country': 'PT', 'ip_addr': '203.0.113.9',
             'master_metadata_track_name': 'Song A', 'master_metadata_album_artist_name': 'Band A', 'master_metadata_album_album_name': 'Album A',
             'spotify_track_uri': 'spotify:track:abc123', 'reason_start': 'clickrow', 'reason_end': 'trackdone', 'shuffle': True,
             'skipped': False, 'offline': False, 'incognito_mode': True},
            {'ts': '2026-09-02T22:00:00Z', 'platform': 'ios', 'ms_played': 600000, 'conn_country': 'US', 'master_metadata_track_name': None,
             'master_metadata_album_artist_name': None, 'episode_name': None, 'audiobook_title': 'The Long Book',
             'audiobook_chapter_title': 'Chapter 3', 'audiobook_uri': 'spotify:audiobook:x1', 'reason_end': 'endplay', 'shuffle': False}])
        used = set()
        imports.spotify(imports.entries(), Collect, used)
        plays = sorted(self.got('spotify', 'media'), key=lambda r: r['ts'])
        self.assertEqual([r['title'] for r in plays], ['Song A', 'The Long Book — Chapter 3'], 'audiobook plays are kept')
        self.assertEqual({k: plays[0]['meta'].get(k) for k in ('conn_country', 'reason_end', 'shuffle', 'incognito_mode')},
                         {'conn_country': 'PT', 'reason_end': 'trackdone', 'shuffle': True, 'incognito_mode': True})
        self.assertNotIn('203.0.113.9', json.dumps(plays), 'the IP address stays out')
        self.assertEqual((plays[1]['meta']['audiobook'], plays[1]['meta'].get('artist')), ('The Long Book', None))
        pl = self.got('spotify', 'playlist')
        self.assertEqual([(r['title'], r['meta']['items']) for r in pl], [('Road trip', 2)])
        on = sorted((r for r in self.got('spotify', 'saved') if r['meta'].get('list') == 'Road trip'), key=lambda r: r['ts'])
        self.assertEqual([(r['title'], r['meta']['what'], r['ts']) for r in on], [('Song A', 'song', '2026-08-01T00:00:00'), ('Ep 1', 'episode', '2026-08-02T00:00:00')])
        self.assertEqual(on[0]['url'], 'https://open.spotify.com/track/abc123')
        lib = {(r['kind'], r['title']): r for r in Collect.recs['spotify'] if (r.get('meta') or {}).get('file') == 'YourLibrary.json'}
        self.assertEqual(set(lib), {('saved', 'Song A'), ('saved', 'Album B'), ('subscription', 'Show S'), ('follow', 'Band C'), ('saved', 'Band D')})
        self.assertTrue(lib[('saved', 'Band D')]['meta']['hidden'])
        s = self.got('spotify', 'search')
        self.assertEqual([(r['title'], r['ts'], r['meta']['product']) for r in s], [('lofi beats', '2026-09-05T12:00:00Z', 'Spotify')])
        inf = {r['title']: r for r in self.got('spotify', 'inference')}
        self.assertEqual(set(inf), {'Night Owls', 'Coffee Drinkers', 'Band A: Light listeners'})
        self.assertEqual((inf['Coffee Drinkers']['meta'].get('partner'), inf['Night Owls']['meta'].get('partner')), (True, None))
        self.assertEqual((inf['Coffee Drinkers']['is_me'], inf['Coffee Drinkers']['meta']['service']), (False, 'Spotify'))
        self.assertEqual(inf['Band A: Light listeners']['meta']['what'], 'artist listener')
        self.assertEqual(len([p for p in used if 'Account Data' in p]), 5)

    def test_account_data_with_only_short_plays_reads_to_nothing(self):
        self.write('spotify/my_spotify_data/Spotify Account Data/StreamingHistory_music_0.json',
                   [{'endTime': '2026-01-01 00:00', 'trackName': 'Skip', 'artistName': 'Band', 'msPlayed': 2000}])
        imports.spotify(imports.entries(), Collect, set())
        self.assertEqual(self.got('spotify'), [])


class ClaudeTests(Base):
    def test_attachments_and_projects(self):
        long = 'x' * (imports.ATTACHMENT_CAP + 500)
        self.write('claude/data-2026-10-01/conversations.json', [{'uuid': 'c1', 'name': 'Tide tables', 'created_at': '2026-09-01T10:00:00Z', 'chat_messages': [
            {'uuid': 'm1', 'sender': 'human', 'created_at': '2026-09-01T10:00:00Z', 'text': 'Summarize these',
             'attachments': [{'file_name': 'notes.txt', 'file_size': 20, 'file_type': 'txt', 'extracted_content': 'High tide at 6am'},
                             {'file_name': '', 'file_size': len(long), 'file_type': 'txt', 'extracted_content': long}],
             'files': [{'file_name': 'photo.png'}]},
            {'uuid': 'm2', 'sender': 'assistant', 'created_at': '2026-09-01T10:00:05Z', 'text': 'Here is a summary', 'attachments': [], 'files': []}]}])
        self.write('claude/data-2026-10-01/projects.json', [
            {'uuid': 'p1', 'name': 'Garden plans', 'description': 'Planting schedule', 'is_private': True, 'is_starter_project': False,
             'prompt_template': 'Answer briefly', 'created_at': '2026-08-01T00:00:00Z', 'updated_at': '2026-08-02T00:00:00Z',
             'creator': {'uuid': 'u1', 'full_name': 'Ada Lovelace'},
             'docs': [{'uuid': 'd1', 'filename': 'beds.md', 'content': 'Tomatoes in bed 2', 'created_at': '2026-08-01T01:00:00Z'}]},
            {'uuid': 'p2', 'name': 'How to use Claude', 'description': 'An example project', 'is_private': False, 'is_starter_project': True,
             'prompt_template': '', 'created_at': '2026-07-01T00:00:00Z', 'docs': []}])
        used = set()
        imports.ai_exports(imports.entries(), Collect, used)
        turns = {r['id']: r for r in self.got('claude_ai', 'ai_turn')}
        m1 = turns['m1']['text']
        self.assertTrue(m1.startswith('Summarize these\n[attachment: notes.txt]\nHigh tide at 6am\n[attachment: pasted text]\nxxx'), m1[:120])
        self.assertTrue(m1.endswith(' […]\n[attachment: photo.png]'), 'a long paste is cut, and says so')
        self.assertLess(len(m1), imports.ATTACHMENT_CAP + 200)
        self.assertEqual(turns['m1']['meta']['attachments'], ['notes.txt', 'pasted text', 'photo.png'])
        notes = {r['title']: r for r in self.got('claude_ai', 'note')}
        self.assertIn('Instructions: Answer briefly', notes['Garden plans']['text'])
        self.assertTrue(notes['Garden plans']['is_me'])
        self.assertEqual((notes['How to use Claude']['is_me'], notes['How to use Claude']['meta']['starter']), (False, True))
        doc = self.got('claude_ai', 'document')
        self.assertEqual([(d['title'], d['text'], d['thread_name']) for d in doc], [('beds.md', 'Tomatoes in bed 2', 'Garden plans')])
        self.assertIn('claude/data-2026-10-01/projects.json', used, 'not left to the catch-all')

    def test_chatgpt_web_page_is_not_a_second_copy(self):
        self.write('chatgpt/export/conversations.json', [{'title': 'Engines', 'create_time': 1790000000, 'current_node': 'a', 'mapping': {
            'a': {'id': 'a', 'parent': None, 'message': {'id': 'a', 'author': {'role': 'user'}, 'create_time': 1790000000,
                                                         'content': {'parts': ['How do engines work?']}}}}}])
        self.write('chatgpt/export/chat.html', '<html><body>How do engines work?</body></html>')
        self.write('notes/chat.html', '<html><body>Something else</body></html>')
        used = set()
        imports.ai_exports(imports.entries(), Collect, used)
        self.assertEqual(len(self.got('chatgpt')), 1)
        self.assertIn('chatgpt/export/chat.html', used)
        self.assertNotIn('notes/chat.html', used, 'a chat.html anywhere else is still a document')


class MetaTests(Base):
    def test_reactions_calls_shares_and_unsent(self):
        self.write('instagram/instagram-ada_l-2026-10-01/your_instagram_activity/messages/inbox/grace_1/message_1.json', {
            'participants': [{'name': 'Grace Hopper'}, {'name': 'Ada Lovelace'}], 'title': 'Grace Hopper', 'messages': [
                {'sender_name': 'Grace Hopper', 'timestamp_ms': 1790000000000, 'content': 'Look at this',
                 'reactions': [{'reaction': 'â\u009d¤', 'actor': 'Ada Lovelace', 'timestamp': 1790000100}, {'reaction': 'ð\u009f\u0098\u0082', 'actor': 'Grace Hopper'}],
                 'share': {'link': 'https://www.instagram.com/p/xyz/', 'share_text': 'Sunset at the pier', 'original_content_owner': 'pier_photos'}},
                {'sender_name': 'Ada Lovelace', 'timestamp_ms': 1790000200000, 'content': 'You called Grace Hopper.', 'call_duration': 125},
                {'sender_name': 'Ada Lovelace', 'timestamp_ms': 1790000250000, 'content': 'You missed a call from Grace Hopper.', 'call_duration': 0},
                {'sender_name': 'Ada Lovelace', 'timestamp_ms': 1790000300000, 'is_unsent': True},
                {'sender_name': 'Grace Hopper', 'timestamp_ms': 1790000400000, 'share': {'share_text': 'A caption only'}}]})
        imports.meta(imports.entries(), Collect, set())
        msgs = {r['ts']: r for r in self.got('instagram', 'message')}
        self.assertEqual(len(msgs), 5)
        first = msgs['2026-09-21T14:13:20Z']
        self.assertEqual(first['meta']['reactions'], [{'who': 'Ada Lovelace', 'reaction': '❤', 'ts': '2026-09-21T14:15:00Z'},
                                                      {'who': 'Grace Hopper', 'reaction': '😂'}])
        self.assertEqual((first['meta']['share_text'], first['meta']['shared_from']), ('Sunset at the pier', 'pier_photos'))
        self.assertEqual(first['text'], 'Look at this\n[shared: https://www.instagram.com/p/xyz/]', 'the text as before')
        self.assertEqual(msgs['2026-09-21T14:16:40Z']['meta']['call_duration'], 125)
        self.assertEqual(msgs['2026-09-21T14:17:30Z']['meta']['call_duration'], 0, 'a call nobody answered')
        unsent = msgs['2026-09-21T14:18:20Z']
        self.assertEqual((unsent['text'], unsent['meta']['unsent'], unsent['is_me']), ('[unsent]', True, True))
        self.assertEqual(msgs['2026-09-21T14:20:00Z']['text'], '[shared: A caption only]')


class RedditTests(Base):
    def test_chats_votes_saved_and_subscriptions(self):
        r = 'reddit/export_ada_l_20261001/'
        self.write(r + 'chat_history.csv', csv_text(
            ['message_id', 'created_at', 'updated_at', 'username', 'message', 'thread_parent_message_id', 'channel_url', 'subreddit', 'channel_name', 'conversation_type'],
            [['m1', '2026-09-01 10:00:00 UTC', '', 'grace_h', 'hi there', '', 'sendbird_group_channel_1', '', '', 'direct'],
             ['m2', '2026-09-01 10:01:00 UTC', '', 'ada_l', 'hello!', 'm1', 'sendbird_group_channel_1', '', '', 'direct'],
             ['m3', '2026-09-02 09:00:00 UTC', '', 'alan_t', 'meeting at 5', '', 'sendbird_group_channel_2', 'tides', 'Book club', 'group']]))
        self.write(r + 'post_votes.csv', 'id,permalink,direction\n'
                                         'p1,https://www.reddit.com/r/tides/comments/p1/why_are_tides_higher_in_spring/,up\n'
                                         'p2,https://www.reddit.com/r/baking/comments/p2/my_first_loaf/,down\n')
        self.write(r + 'comment_votes.csv', 'id,permalink,direction\nc9,https://www.reddit.com/r/tides/comments/p1/why_are_tides_higher_in_spring/c9/,up\n')
        self.write(r + 'saved_posts.csv', 'id,permalink\np3,https://www.reddit.com/r/baking/comments/p3/sourdough_tips/\n')
        self.write(r + 'saved_comments.csv', 'id,permalink\nc8,https://www.reddit.com/r/tides/comments/p1/why_are_tides_higher_in_spring/c8/\n')
        self.write(r + 'subscribed_subreddits.csv', 'subreddit\ntides\nbaking\n')
        used = set()
        imports.csv_exports(imports.entries(), Collect, used)
        msgs = {x['id']: x for x in self.got('reddit', 'message')}
        self.assertEqual((msgs['m1']['author'], msgs['m1']['is_me'], msgs['m1']['thread_name']), ('grace_h', False, 'grace_h'))
        self.assertEqual((msgs['m2']['author'], msgs['m2']['is_me'], msgs['m2']['ts']), ('me', True, '2026-09-01T10:01:00Z'))
        self.assertEqual(msgs['m2']['participants'], ['ada_l', 'grace_h'], 'both sides')
        self.assertEqual(msgs['m3']['thread_name'], 'Book club')
        votes = {x['id']: x for x in self.got('reddit', 'vote')}
        self.assertEqual({k: (v['meta']['vote'], v['meta']['on'], v['thread_name']) for k, v in votes.items()},
                         {'post_votes.csv:p1': ('up', 'post', 'r/tides'), 'post_votes.csv:p2': ('down', 'post', 'r/baking'),
                          'comment_votes.csv:c9': ('up', 'comment', 'r/tides')})
        self.assertEqual(votes['post_votes.csv:p1']['title'], 'why are tides higher in spring')
        self.assertTrue(votes['post_votes.csv:p2']['text'].startswith('You downvoted a post in r/baking: my first loaf'))
        self.assertEqual(sorted(x['title'] for x in self.got('reddit', 'saved')), ['sourdough tips', 'why are tides higher in spring'])
        self.assertEqual(sorted(x['title'] for x in self.got('reddit', 'subscription')), ['r/baking', 'r/tides'])
        self.assertEqual(len([p for p in used if p.startswith(r)]), 6)


class XTests(Base):
    def js(self, name, part, items):
        return f'window.YTD.{part}.part0 = ' + json.dumps(items)

    def test_long_posts_deleted_posts_grok_and_group_names(self):
        x = 'x/twitter-2026-10-01/data/'
        long = ('Here is a long thought about tides and the moon and how they pull on the oceans of the world, every day, twice a day, '
                'and why the spring tides are higher than the neap tides, which surprised me when I first read about it. ' * 2).strip()
        self.write(x + 'account.js', self.js('account', 'account', [{'account': {'accountId': '42', 'username': 'ada_l'}}]))
        self.write(x + 'tweets.js', self.js('tweets', 'tweets', [
            {'tweet': {'id_str': '1', 'full_text': long[:270] + '… https://t.co/abc', 'created_at': 'Tue Sep 01 10:00:00 +0000 2026'}},
            {'tweet': {'id_str': '2', 'full_text': 'Tides &amp; currents', 'created_at': 'Tue Sep 01 10:00:00 +0000 2026'}}]))
        self.write(x + 'note-tweet.js', self.js('noteTweet', 'note_tweet', [
            {'noteTweet': {'noteTweetId': 'n1', 'createdAt': '2026-09-01T10:00:00.000Z', 'updatedAt': '2026-09-01T10:00:00.000Z',
                           'lifecycle': {'value': '1', 'name': 'Active'}, 'core': {'text': long, 'urls': [], 'mentions': []}}},
            {'noteTweet': {'noteTweetId': 'n2', 'createdAt': '2026-09-03T08:00:00.000Z', 'core': {'text': 'A long post with no short copy'}}}]))
        self.write(x + 'deleted-tweets.js', self.js('deletedTweets', 'deleted_tweets', [
            {'tweet': {'id_str': '99', 'full_text': 'oops typo', 'created_at': 'Wed Sep 02 10:00:00 +0000 2026', 'deleted_at': 'Wed Sep 02 10:05:00 +0000 2026'}}]))
        self.write(x + 'grok-chat-item.js', self.js('grokChatItem', 'grok_chat_item', [
            {'grokChatItem': {'chatId': 'g1', 'accountId': '42', 'createdAt': '2026-09-04T10:00:00.000Z', 'message': 'What causes tides?',
                              'sender': {'value': '1', 'name': 'User'}, 'grokMode': {'value': '1', 'name': 'Normal'}}},
            {'grokChatItem': {'chatId': 'g1', 'accountId': '42', 'createdAt': '2026-09-04T10:00:05.000Z', 'message': "Mostly the moon's gravity.",
                              'sender': {'value': '2', 'name': 'Agent'}, 'grokMode': {'value': '1', 'name': 'Normal'}}},
            {'grokChatItem': {'chatId': 'g1', 'accountId': '42', 'createdAt': '2026-09-04T10:01:00.000Z', 'message': 'And spring tides?',
                              'sender': {'value': '1', 'name': 'User'}, 'grokMode': {'value': '1', 'name': 'Normal'}}}]))
        self.write(x + 'direct-messages-group.js', self.js('directMessagesGroup', 'direct_messages_group', [{'dmConversation': {
            'conversationId': 'conv1', 'messages': [
                {'messageCreate': {'id': 'dm3', 'senderId': '7', 'text': 'see you there', 'createdAt': '2026-09-06T10:00:00.000Z', 'reactions': [], 'urls': [], 'mediaUrls': []}},
                {'conversationNameUpdate': {'initiatingUserId': '42', 'name': 'Tide watchers 2', 'createdAt': '2026-09-05T12:00:00.000Z'}},
                {'messageCreate': {'id': 'dm2', 'senderId': '42', 'text': 'hi all', 'createdAt': '2026-09-05T11:00:00.000Z', 'reactions': [], 'urls': [], 'mediaUrls': []}},
                {'conversationNameUpdate': {'initiatingUserId': '7', 'name': 'Tide watchers', 'createdAt': '2026-09-05T10:00:00.000Z'}},
                {'joinConversation': {'initiatingUserId': '7', 'participantsSnapshot': ['42', '7'], 'createdAt': '2026-09-05T09:00:00.000Z'}}]}}]))
        used = set()
        imports.x_archive(imports.entries(), Collect, used)
        posts = {r['id']: r for r in self.got('x', 'post')}
        self.assertEqual(posts['1']['text'], long, 'the whole long post, not its first 280 characters')
        self.assertTrue(posts['1']['meta']['long'])
        # another post the same second is left as it was (but for the &amp; the archive writes for &)
        self.assertEqual(posts['2']['text'], 'Tides & currents', 'another post the same second is left as it was')
        self.assertEqual((posts['note:n2']['text'], posts['note:n2']['ts']), ('A long post with no short copy', '2026-09-03T08:00:00Z'))
        self.assertEqual((posts['99']['text'], posts['99']['meta']['deleted']), ('oops typo', '2026-09-02T10:05:00Z'))
        grok = sorted(self.got('x', 'ai_turn'), key=lambda r: r['ts'])
        self.assertEqual([(r['author'], r['is_me']) for r in grok], [('me', True), ('grok', False), ('me', True)])
        self.assertEqual({r['thread_name'] for r in grok}, {'What causes tides?'})
        self.assertEqual(grok[0]['meta']['product'], 'Grok')
        dms = self.got('x', 'message')
        self.assertEqual({r['thread_name'] for r in dms}, {'Tide watchers 2'}, 'the group\'s latest name')
        self.assertEqual({r['thread'] for r in dms}, {'conv1'})
        for f in ('note-tweet.js', 'deleted-tweets.js', 'grok-chat-item.js'):
            self.assertIn(x + f, used)


if __name__ == '__main__':
    unittest.main()
