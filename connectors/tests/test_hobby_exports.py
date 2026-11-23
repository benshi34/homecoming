"""Letterboxd and Goodreads, read with the mappings the app ships (desktop/data/mappings/), from made-up
exports laid out as the real ones are (connectors/tests/fixtures/<service>/; see PARSERS.md for where each layout
comes from), checked against real exports of a new Letterboxd and Goodreads account (2026-10-21): their headers,
CRLF and empty deleted/ and orphaned/ files are as those were. IMDb, The StoryGraph, MyAnimeList, Trakt, Instapaper,
Raindrop.io, Pocket, PayPal, Venmo, Cash App, Snapchat, Telegram, Amazon, Netflix, Uber, Tinder, Hinge, Trello, Day One,
Evernote, Todoist, Lyft, DoorDash, Apple Card, Coinbase, Robinhood, Chase, Bank of America, Capital One, Apple (Apple Music),
Microsoft (Bing searches), Fitbit and Garmin are built from public samples only (open-source importers' fixtures, help pages) and not yet checked
against a real export. So are the banks' and Apple Card's OFX, QFX and QBO downloads (fixtures/ofx/<service>/), laid out as
the OFX 1.02 and 2.x specs and public samples (ofxparse's and beancount-reds-importers' test files) have them.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common

with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'CORPUS', Path(tmp)):
    (Path(tmp) / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
    import imports
import mapped_exports as mx

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
SHIPPED = Path(__file__).resolve().parents[2] / 'desktop/data/mappings'


class Entry:
    def __init__(self, path, data):
        self.path, self.origin, self._data = path, 'svc', data

    def text(self):
        return self._data


class HobbyExportTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.imports, self.maps = self.root / 'corpus/imports', self.root / 'corpus/mappings'
        self.imports.mkdir(parents=True)
        self.maps.mkdir(parents=True)
        for name, value in (('IMPORTS', self.imports), ('MEDIA', self.root / 'corpus/media'), ('CORPUS', self.imports.parent)):
            p = patch.object(imports, name, value)
            p.start()
            self.addCleanup(p.stop)

    def read(self, service, zip_name=None, part=None, fixture=None):
        """The fixture (fixtures/<service>/, or the folder fixture names) as the app would have it: in
        corpus/imports/<service>/ (zipped, as downloaded, when zip_name; only the files in its folder part, when part),
        with the shipped mapping saved for that folder. Every record each source gets."""
        src, dest = FIXTURES / (fixture or service), self.imports / service
        if zip_name:
            dest.mkdir()
            self.zip(src, dest / zip_name, part)
        else:
            shutil.copytree(src, dest)
        shutil.copy(SHIPPED / f'{service}.json', self.maps / f'{service}.json')
        return self.run_parsers([mx.mapped_exports, imports.fitbit_days, imports.other_data])

    def zip(self, src, to, part=None):
        with zipfile.ZipFile(to, 'w') as z:
            for f in sorted((src / part if part else src).rglob('*')):
                if f.is_file():
                    z.write(f, f.relative_to(src).as_posix())

    def run_parsers(self, parsers):
        """Every record each source gets from these parsers, over everything in corpus/imports/."""
        recs = {}

        class W:
            def __init__(self, source):
                self.source, self.notes = source, {}

            def has(self, key):
                return any(r['id'] == key for r in recs.get(self.source, []))

            def add(self, **r):
                recs.setdefault(self.source, []).append(r)
        es, used = imports.entries(), set()
        with patch.object(mx, 'MAPPINGS', self.maps), patch.dict(mx.MAPPED, clear=True):
            for parser in parsers:
                parser(es, W, used)
        return recs

    def by(self, recs, what):
        return [r for r in recs if r['meta'].get('mapped') == what]

    def test_letterboxd(self):
        recs = self.read('letterboxd', 'letterboxd-rileyp-2026-10-21-17-02-utc.zip')
        lb = recs['letterboxd']
        diary = self.by(lb, 'Films you logged in your diary')
        self.assertEqual([(r['title'], r['ts'], r['meta'].get('tier')) for r in diary], [
            ('Night Ferry', '2023-12-29T00:00:00', 'deleted'),  # deleted/diary.csv: kept, marked
            ('The Long Quiet', '2024-01-05T00:00:00', None),  # when it was watched, not logged
            ('Paper Moons, Again', '2024-02-10T00:00:00', None),
            ('Harbor Lights', '2024-03-01T00:00:00', None)])  # no watched date: when it was logged
        self.assertTrue(all(r['kind'] == 'watch' and r['is_me'] and r['url'].startswith('https://boxd.it/') for r in diary))
        self.assertEqual(diary[1]['text'], 'The Long Quiet\n2011\nrainy day, with sam')
        [review] = self.by(lb, 'Your reviews')
        self.assertEqual((review['kind'], review['title']), ('review', 'The Long Quiet'))
        self.assertIn('pier', review['text'])
        self.assertEqual(review['meta']['fields']['Rating'], '4.5')
        [liked] = self.by(lb, 'Reviews you liked')
        self.assertEqual((liked['kind'], liked['text']), ('like', 'https://boxd.it/fake2x'), 'likes/reviews.csv is not your reviews')
        self.assertEqual(len(self.by(lb, 'Films you rated')), 2)
        self.assertEqual(len(self.by(lb, 'Films you marked as watched')), 3)
        self.assertEqual([r['kind'] for r in self.by(lb, 'Films on your watchlist')], ['saved'])
        self.assertEqual(len(self.by(lb, 'Films you liked')), 1)
        [made] = self.by(lb, 'Lists you made')
        self.assertEqual((made['kind'], made['title'], made['ts'], made['url']),
                         ('post', 'Films for rainy Sundays', '2024-04-01T00:00:00', 'https://boxd.it/fakelist'))
        films = self.by(lb, 'Films in your lists')
        self.assertEqual([(r['title'], r['thread_name']) for r in films],
                         [('The Long Quiet', 'films-for-rainy-sundays'), ('Salt Flats', 'films-for-rainy-sundays')])
        self.assertEqual(films[1]['text'], 'Salt Flats\n2019\nWatch it with the lights off')
        self.assertEqual(len({r['id'] for r in lb}), len(lb), 'every record its own id')
        # What the mapping doesn't name is still kept, by the catch-all.
        other = {r['title'] for r in recs['letterboxd_other']}
        self.assertTrue(any('comments' in t for t in other) and any('profile' in t for t in other), other)
        self.assertFalse(any('diary' in t or 'lists' in t for t in other), 'mapped files not kept twice')

    def test_goodreads(self):
        recs = self.read('goodreads')
        gr = recs['goodreads']
        self.assertEqual(len(gr), 5, 'every row of the library, once')
        self.assertEqual([(r['title'], r['ts']) for r in self.by(gr, 'Books you read')],
                         [("The Lighthouse Keeper's Year", '2024-03-14T00:00:00'), ('Old Rivers', '2022-08-19T00:00:00')])
        [reading] = self.by(gr, "Books you're reading")
        self.assertEqual((reading['kind'], reading['ts']), ('read', '2024-05-02T00:00:00'))
        self.assertEqual([r['kind'] for r in self.by(gr, 'Books you want to read')], ['saved'])
        [dnf] = self.by(gr, 'Books on your other shelves')
        self.assertIn('did-not-finish', dnf['text'])
        read = self.by(gr, 'Books you read')[0]
        self.assertEqual(read['text'], "The Lighthouse Keeper's Year\nAda Marlow\nSlow, warm, and the ending earns it.\nLent to Sam")
        self.assertEqual((read['meta']['fields']['My Rating'], read['id'].rsplit('#', 1)[1]), ('4.75', '90000001'), 'quarter stars')
        self.assertNotIn('goodreads_other', recs)

    def test_imdb(self):
        recs = self.read('imdb')
        im = recs['imdb']
        rated = self.by(im, 'Titles you rated')
        self.assertEqual([(r['title'], r['ts'], r['meta']['fields']['Your Rating']) for r in rated], [
            ('Amélie of the Docks', '2019-08-09T00:00:00', '7'),  # 2018-2023: Windows-1252, no Original Title, CRLF
            ('The Long Quiet', '2024-06-10T00:00:00', '9'),
            ('Harbor Lights', '2025-01-03T00:00:00', '6'),
            ('Harbor Lights: The Pier', '2025-02-11T00:00:00', '8')])
        self.assertTrue(all(r['kind'] == 'review' and r['url'].startswith('https://www.imdb.com/title/tt') for r in rated))
        self.assertEqual(rated[2]['text'], 'Harbor Lights\n2019\nTV Mini Series\nJo Brandt, Sam Ortiz')
        self.assertEqual([(r['title'], r['ts']) for r in self.by(im, 'Titles on your watchlist')],
                         [('Salt Flats', '2024-03-02T00:00:00'), ('The Long Quiet', '2024-04-15T00:00:00')])
        [listed] = self.by(im, 'Titles in your lists')
        self.assertEqual((listed['kind'], listed['thread_name']), ('saved', 'Films for rainy Sundays'))
        self.assertTrue(listed['text'].endswith('Watch it with the lights off'))
        [old] = self.by(im, 'Titles on your watchlist and lists (exports from before 2018)')
        self.assertEqual((old['title'], old['kind'], old['ts'][:10]), ('Night Ferry', 'saved', '2013-08-09'), 'ctime, a padded day')
        self.assertEqual((len(im), len({r['id'] for r in im})), (8, 8), 'every row once, each its own id')
        self.assertNotIn('imdb_other', recs)

    def test_storygraph(self):
        recs = self.read('the-storygraph')
        sg = recs['the_storygraph']
        self.assertEqual(len(sg), 5, 'every row of the library, once')
        self.assertEqual([(r['title'], r['ts']) for r in self.by(sg, 'Books you read')],
                         [("The Lighthouse Keeper's Year", '2024-03-10T00:00:00'), ('Old Rivers', '2022-08-19T00:00:00')])
        first = self.by(sg, 'Books you read')[0]
        self.assertEqual(first['text'], "The Lighthouse Keeper's Year\nAda Marlow, Ben Tor\nSlow, warm, and the ending earns it.\ncomfort")
        self.assertEqual((first['meta']['fields']['Star Rating'], first['meta']['fields']['Dates Read']),
                         ('4.25', '2024/01/02-2024/01/10, 2024/03/01-2024/03/10'), 'both reads, in its fields')
        [reading] = self.by(sg, "Books you're reading")
        self.assertEqual((reading['kind'], reading['ts']), ('read', '2024-05-02T00:00:00'))
        [want] = self.by(sg, 'Books you want to read')
        self.assertEqual((want['kind'], want['id'].rsplit('#', 1)[1]), ('saved', 'sg-fake-0001'), "a StoryGraph id, not an ISBN")
        [dnf] = self.by(sg, 'Books you stopped or put down')
        self.assertIn('did-not-finish', dnf['text'])
        self.assertNotIn('the_storygraph_other', recs)

    def test_instapaper(self):
        recs = self.read('instapaper')
        ip = recs['instapaper']
        self.assertEqual([(r['title'], r['ts']) for r in ip], [
            ('On Slow Reading', '2024-05-29T16:26:40Z'), ('Tides, Explained', '2024-05-18T02:40:00Z'),
            ('A Year of Bread', '2023-11-14T22:13:20Z'), ('Note to self', '2023-07-22T04:26:40Z')])  # Unix seconds
        self.assertTrue(all(r['kind'] == 'saved' and r['is_me'] for r in ip))
        self.assertEqual(ip[1]['text'], 'Tides, Explained\nThe moon does most of the work.\nStarred', 'the folder it was in')
        self.assertEqual((ip[1]['url'], ip[1]['meta']['fields']['Tags']), ('https://example.org/tides', '["science","sea"]'))
        self.assertNotIn('instapaper_other', recs)

    def test_raindrop(self):
        recs = self.read('raindrop-io')
        fog, bread = recs['raindrop_io']
        self.assertEqual((fog['title'], fog['ts'], fog['thread_name'], fog['url']),
                         ('Fog Atlas', '2024-01-05T18:30:00Z', 'Design/Maps', 'https://example.com/fog'))
        self.assertEqual(fog['text'], 'Fog Atlas\nLook at the coastal maps\nMaps of fog by season\n'
                                      'Highlight: fog follows the cold water\nmaps, weather\nDesign/Maps')
        self.assertEqual((bread['kind'], bread['thread']), ('saved', 'Unsorted'))
        self.assertNotIn('raindrop_io_other', recs)

    def test_pocket(self):
        recs = self.read('pocket', 'pocket.zip')
        pk = recs['pocket']
        self.assertEqual(sorted((r['title'], r['ts']) for r in pk), [
            ('How Lighthouses Work', '2024-02-03T22:40:00Z'), ('Notes on Tides', '2020-09-13T12:26:40Z'),
            ('https://example.org/untitled', '2024-04-01T19:33:20Z')])  # 2025's part_000000.csv, and the older one without cursor
        lh = next(r for r in pk if r['title'] == 'How Lighthouses Work')
        self.assertEqual(lh['text'], 'How Lighthouses Work\nsea|history\narchive')
        self.assertNotIn('pocket_other', recs)

    def test_myanimelist(self):
        recs = self.read('myanimelist')
        mal = recs['myanimelist']
        watched = self.by(mal, 'Anime you watched or are watching')
        self.assertEqual([(r['title'], r.get('ts')) for r in watched], [
            ('Harbor Lights: Second Season', '2024-03-20T00:00:00'),  # gzipped, as it downloads: the day it was finished
            ('Paper Moons & Stars', None)])  # started in 2023-00-00: no day, so no time
        self.assertEqual(watched[0]['text'], 'Harbor Lights: Second Season\nTV\nCompleted\nBetter than the first.<br />The finale!\nsea, rewatch')
        self.assertEqual((watched[0]['kind'], watched[0]['meta']['fields']['my_score'], watched[0]['id'].rsplit('#', 1)[1]),
                         ('watch', '8', '99901'))
        self.assertEqual([r['title'] for r in self.by(mal, 'Anime you plan to watch')], ['Salt Flats'])
        [reading] = self.by(mal, 'Manga you read or are reading')  # unpacked by the browser: .xml
        self.assertEqual((reading['title'], reading['kind'], reading['ts']), ('The Long Quiet', 'read', '2024-05-01T00:00:00'))
        self.assertEqual([r['kind'] for r in self.by(mal, 'Manga you plan to read')], ['saved'])
        totals = self.by(mal, "Your list's totals")
        self.assertEqual(len(totals), 2)
        self.assertIn('user_total_anime: 3', totals[0]['text'])
        self.assertNotIn('myanimelist_other', recs)

    def test_xml_with_entities_or_a_gz_bomb_is_not_read(self):
        bad = '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "xx">]><myanimelist><anime><series_title>&x;</series_title></anime></myanimelist>'
        with self.assertRaises(ValueError):
            mx.xml_data(bad)
        import gzip

        class Gz:
            path = 'animelist_1_-_1.xml.gz'

            def read(self):
                return gzip.compress(b'<a>' + b' ' * (80 << 20) + b'</a>')
        with self.assertRaises(ValueError):
            mx.parse(Gz())

    def test_broken_files_are_skipped_quickly(self):
        """What can't be read is passed over, file by file and in good time: the next file is still read."""
        import time
        m = mx.validate(json.loads((SHIPPED / 'chase.json').read_text()))
        good = (FIXTURES / 'ofx/chase/Chase5678_Activity_20260331.QBO').read_text(encoding='cp1252')
        for name, bad in (('never closed', '<OFX>' + '<A' * 1_000_000), ('too deep', '<OFX>' + '<AGG>\n' * 200_000),
                          ('bogus end tags', '<OFX>' + '<AGG>\n' * 50_000 + '</NOPE>' * 50_000)):
            t = time.monotonic()
            recs = list(mx.records(m, [Entry('chase/bad.qfx', bad), Entry('chase/good.qbo', good)]))
            self.assertLess(time.monotonic() - t, 5, name)
            self.assertEqual({e.path for _, e, _ in recs}, {'chase/good.qbo'}, name)
        deep = {'file': '*', 'path': '', 'kind': 'record'}
        for path, bad in (('a.xml', '<r>' + '<a>' * 100_000 + '</a>' * 100_000 + '</r>'), ('a.json', '[' * 100_000 + ']' * 100_000),
                          ('a.csv', 'a,b\n"' + 'x' * 200_000 + '",1\n')):
            self.assertEqual(list(mx.records(mx.validate({'items': [deep]}), [Entry(path, bad)])), [], path)

    def test_trakt(self):
        recs = self.read('trakt', 'trakt-export.zip')
        tr = recs['trakt']
        self.assertEqual([(r['title'], r['ts']) for r in self.by(tr, 'Films you watched')],
                         [('The Long Quiet', '2024-01-05T20:11:39Z'), ('Night Ferry', '2023-12-29T23:59:00Z')])  # every page of history
        [ep] = self.by(tr, 'Episodes you watched')
        self.assertEqual((ep['title'], ep['text'], ep['kind']), ('Harbor Lights', 'Harbor Lights\nThe Pier', 'watch'))
        self.assertEqual([(r['title'], r['meta']['fields']['rating']) for r in self.by(tr, 'Films you rated')], [('The Long Quiet', 9)])
        self.assertEqual([r['title'] for r in self.by(tr, 'Shows, seasons and episodes you rated')], ['Harbor Lights'])
        self.assertEqual([r['title'] for r in self.by(tr, 'Films on your watchlist')], ['Salt Flats'])
        [show] = self.by(tr, 'Shows on your watchlist')
        self.assertEqual(show['text'], 'Fog Atlas\nAfter the first season')
        self.assertEqual([r['kind'] for r in self.by(tr, 'Films you made favorites')], ['like'])
        [listed] = self.by(tr, 'Films in your lists')
        self.assertEqual((listed['title'], listed['thread']), ('Paper Moons', 'lists-list-9000001-rainy-sundays'))
        [made] = self.by(tr, 'Lists you made')
        self.assertEqual((made['title'], made['url'], made['kind']), ('Rainy Sundays', 'https://trakt.tv/lists/9000001', 'post'))
        [c] = self.by(tr, 'Your comments on films')
        self.assertEqual((c['kind'], c['title'], c['ts']), ('comment', 'The Long Quiet', '2024-01-07T10:00:00Z'))
        self.assertEqual((len(tr), len({r['id'] for r in tr})), (11, 11), 'every item once, each its own id')
        # The totals and the account's files are still kept, by the catch-all.
        self.assertEqual({r['title'] for r in recs['trakt_other']}, {'user-profile', 'watched-movies'})

    def test_paypal(self):
        recs = self.read('paypal')
        pp = recs['paypal']
        self.assertEqual([(r['title'], r['ts'], r['id'].rsplit('#', 1)[1]) for r in pp], [
            ('Example Shop', '2025-03-14T00:00:00', '1AB23456CD789012E'),  # Download.CSV: a BOM, every field quoted, CRLF
            ('Lighthouse poster', '2025-03-14T00:00:00', '9ZY87654XW321098V'),  # the bank deposit paying for it: no name
            ('Sam Ortiz', '2025-04-02T00:00:00', '3CD45678EF901234G'),
            ('Pat Example', '2025-07-02T00:00:00', '5XY12345AB678901C')])  # 2025's personal layout: Amount, Fees, Total
        self.assertEqual(pp[2]['text'], 'Sam Ortiz\nGeneral Payment\nThanks for dinner\n10.00\nUSD\nCompleted')
        self.assertEqual((pp[2]['meta']['fields']['Time'], pp[2]['meta']['fields']['Fee']), ('18:20:44', '-0.59'))
        self.assertIn('-40.00', pp[3]['text'])
        self.assertTrue(all(r['kind'] == 'transaction' for r in pp))
        self.assertNotIn('paypal_other', recs)

    def test_venmo(self):
        recs = self.read('venmo')
        vm = recs['venmo']
        self.assertEqual([(r['meta']['fields'].get('Datetime'), r['title']) for r in vm], [
            ('2017-06-01T20:00:00', 'Pizza'),  # 2017: quoted, " ID", no lines before the header
            ('2025-03-08T19:42:10', 'Tacos 🌮\nand churros'),  # a note over two lines
            ('2025-03-09T02:15:33', 'Utilities March'),
            ('2025-03-10T15:00:01', 'Standard Transfer')])  # no note: its type
        self.assertEqual(len(vm), 4, "the balance rows (no ID) and the statement's title aren't payments")
        self.assertEqual((vm[1]['author'], vm[1]['text']), ('Riley Park', 'Tacos 🌮\nand churros\nPayment\nRiley Park\nJordan Example\n- $14.00\nComplete'))
        self.assertNotIn('venmo_other', recs)

    def test_cash_app(self):
        recs = self.read('square-cash')
        ca = recs['square_cash']
        self.assertEqual(sorted((r['title'], r['ts'], r['meta']['fields']['Transaction ID']) for r in ca), [
            ('Jordan Example', '2026-02-03T00:00:00', '#D-AB12CD3EF'),  # 2025 on: Date first, quoted
            ('Sam Ortiz', '2024-11-03T00:00:00', 'abc123'),  # before: Transaction ID first
            ('Withdrawal', '2026-02-04T00:00:00', '#D-XY98ZW7VU')])
        self.assertEqual(next(r for r in ca if r['title'] == 'Sam Ortiz')['text'], 'Lunch\nSent P2P\nSam Ortiz\n-$12.00')
        self.assertNotIn('square_cash_other', recs)

    def test_snapchat(self):
        recs = self.read('snapchat', 'mydata~1763707928316.zip')
        sc = recs['snapchat']
        chats = self.by(sc, 'Your chats')
        self.assertEqual([(r.get('text'), r['ts'], r['thread_name'], r['is_me']) for r in chats], [
            ('see you at 7', '2024-01-20T06:33:05Z', 'jordan.example', False),
            ('on my way', '2024-01-20T06:35:12Z', 'jordan.example', True),  # IsSender
            (chats[2]['text'], '2024-02-01T12:00:00Z', 'Weekend Plans', True)])  # a group: its title, its id the thread
        self.assertEqual(chats[2]['thread'], '0b9e2c1a-1111-2222-3333-444455556666')
        self.assertIn('Media Type: MEDIA', chats[2]['text'], 'a photo with no words: what it was')
        [got] = self.by(sc, 'Chats you got (exports from before 2024)')
        [sent] = self.by(sc, 'Chats you sent (exports from before 2024)')
        self.assertEqual((got['author'], got['is_me'], sent['is_me'], sent['thread']), ('jordan.example', False, True, 'jordan.example'))
        self.assertEqual(len(self.by(sc, 'Your chats')), 3, "the older file's lists aren't read as chats with friends named that")
        self.assertEqual([r['text'] for r in self.by(sc, 'Snaps you sent and got')], ['IMAGE'])
        [friend] = self.by(sc, 'Your friends')
        self.assertEqual((friend['kind'], friend['title'], friend['ts']), ('follow', 'Jordan', '2021-03-04T10:00:00Z'))
        [memory] = self.by(sc, 'Memories you saved')
        self.assertEqual((memory['kind'], memory['text']), ('photo', 'Video\nLatitude, Longitude: 45.95817, -66.6471'))
        self.assertEqual({r['title'] for r in recs['snapchat_other']}, {'account'}, 'the rest is still kept')

    def test_telegram(self):
        recs = self.read('telegram')
        tg = recs['telegram']
        msgs = self.by(tg, "Your chats' messages")
        self.assertEqual([(r.get('text'), r['ts'], r['author'], r['thread_name']) for r in msgs], [
            ('Hi there', '2025-01-05T18:30:00Z', 'Jordan Example', 'Jordan Example'),
            ('Look at this map!', '2025-01-05T18:31:00Z', 'Riley Park', 'Jordan Example'),  # text in parts, a link among them
            ('(File not included. Change data exporting settings to download.)', '2025-02-01T08:00:00Z', 'Riley Park', 'saved_messages')])
        self.assertEqual({r['thread'] for r in msgs}, {'456', '123'})
        [call] = self.by(tg, 'Calls and other events in your chats')
        self.assertEqual((call['kind'], call['text'], call['meta']['fields']['duration_seconds']), ('event', 'phone_call', 65))
        [left] = self.by(tg, 'Your messages in groups you left')
        self.assertEqual((left['text'], left['thread_name']), ('Thanks, all!', 'Old Book Club'))
        [contact] = self.by(tg, 'Your contacts')
        self.assertEqual((contact['kind'], contact['text']), ('contact', 'Jordan\nExample\n+1 555 0101'))
        [alone] = self.by(tg, 'A chat you exported on its own')
        self.assertEqual((alone['text'], alone['thread'], alone['thread_name']), ('Meet at the pier', '999', 'Harbor Club'))
        self.assertEqual((len(tg), len({r['id'] for r in tg})), (7, 7))
        other = recs['telegram_other']
        self.assertFalse(any('Hi there' in r['text'] for r in other), "a chat's messages aren't kept twice")
        self.assertTrue(any('frequent_contacts' in r['title'] for r in other))

    def test_amazon(self):
        recs = self.read('amazon-audible', 'Your Orders.zip')
        am = recs['amazon_audible']
        ordered = self.by(am, 'Things you ordered')
        self.assertEqual([(r['title'], r.get('ts'), r['thread']) for r in ordered], [
            ('Lighthouse Mug, Blue', '2024-01-05T18:30:00Z', '112-0000000-0000001'),  # a row an item, the order its thread
            ('Tide Chart Poster', '2024-01-05T18:30:00Z', '112-0000000-0000001'),
            ('Fog Lamp', None, '112-0000000-0000002'),  # cancelled: its date Not Available
            ('Harbor Notebook', '2023-08-01T02:00:00Z', '503-0000000-0000003')])  # another Amazon site: .3, not .1
        self.assertEqual(ordered[0]['text'], 'Lighthouse Mug, Blue\n14.06\nUSD\nClosed\nAmazon.com')
        [newer] = self.by(am, "Things you ordered (2026's layout)")
        self.assertEqual((newer['title'], newer['kind']), ('Sea Salt Grinder', 'purchase'))
        [digital] = self.by(am, 'Books, music, films and apps you bought')
        self.assertEqual((digital['title'], digital['ts']), ("The Lighthouse Keeper's Year", '2024-12-29T15:28:18Z'))
        [reading] = self.by(am, 'Your Kindle reading')
        self.assertEqual((reading['kind'], reading['title'], reading['ts'][:16]), ('read', "The Lighthouse Keeper's Year", '2025-01-04T21:40'))
        [session] = self.by(am, 'Your Kindle reading sessions, by device')
        self.assertEqual((session['title'], session['ts']), ('B0K0000001', '2025-01-03T21:00:00Z'), 'no title in that file: its ASIN')
        self.assertNotIn('amazon_audible_other', recs)

    def test_netflix(self):
        recs = self.read('netflix', 'netflix-report.zip')
        nf = recs['netflix']
        watched = self.by(nf, 'What you watched')
        self.assertEqual([(r['title'], r['ts'], r['author']) for r in watched], [
            ('Harbor Lights: Season 1: The Pier (Episode 2)', '2024-01-05T18:30:00Z', 'Riley'),  # Start Time is UTC
            ('Paper Moons', '2024-02-10T09:00:00Z', 'Kids')])  # another profile: its name the author
        self.assertEqual(watched[0]['text'], 'Harbor Lights: Season 1: The Pier (Episode 2)\n00:42:10\nChrome PC (Cadmium)')
        [hook] = self.by(nf, 'Trailers and previews that played')
        self.assertIn('HOOK', hook['text'])
        self.assertEqual([r['title'] for r in self.by(nf, 'Your list')], ['Fog Atlas'])
        [rated] = self.by(nf, 'What you rated')
        self.assertEqual((rated['kind'], rated['text']), ('review', 'Harbor Lights\nthumb\n2'))
        searches = self.by(nf, 'Your searches')
        self.assertEqual([(r['title'], r.get('ts')) for r in searches], [('harbor', '2024-01-05T18:28:00Z'), ('fog', None)])
        self.assertEqual([r['kind'] for r in self.by(nf, "Shows you said you'd like")], ['like'])
        self.assertEqual({r['title'] for r in recs['netflix_other']}, {'Profiles'}, 'the rest is still kept')

    def test_uber(self):
        recs = self.read('uber')
        ub = recs['uber']
        trips = self.by(ub, 'Your trips')
        self.assertEqual([(r['title'], r['ts']) for r in trips], [
            ('2 Pier St, San Francisco', '2025-05-29T21:06:21Z'),  # when it began, where it ended
            ('UberX', '2025-06-01T08:00:00Z')])  # cancelled: when it was asked for
        self.assertIn('rider_canceled', trips[1]['text'])
        [old] = self.by(ub, 'Your trips (older exports)')
        self.assertEqual((old['title'], old['ts'], old['kind']), ('3 Harbor Way', '2020-11-07T18:35:00Z', 'trip'))  # "+0000 UTC"
        eats = self.by(ub, 'What you ordered on Uber Eats')
        self.assertEqual([(r['title'], r['ts'], r['thread']) for r in eats],
                         [('Tacos', '2022-05-14T18:25:00Z', 'o-0001'), ('Churros', '2022-05-14T18:25:00Z', 'o-0001')])
        self.assertEqual({r['title'] for r in recs['uber_other']}, {'eats restaurant names'})

    def test_tinder(self):
        recs = self.read('tinder', 'myData.zip')
        tn = recs['tinder']
        sent = self.by(tn, 'Messages you sent')
        self.assertEqual([(r['text'], r['ts'], r['thread']) for r in sent], [
            ('Hi, how&rsquo;s your week?', '2024-01-06T18:30:00Z', 'Match 1'),  # "Sat, 06 Jan 2024 18:30:00 GMT"
            ('gif\nhttps://media.example/a.gif', '2024-01-06T18:31:10Z', 'Match 1')])
        self.assertTrue(all(r['is_me'] for r in sent), 'only what you sent is in the export')
        opens = self.by(tn, 'Days you opened Tinder')
        self.assertEqual([(r['ts'], r['text']) for r in opens], [('2024-01-05T00:00:00', 'value: 3'), ('2024-01-06T00:00:00', 'value: 1')])
        self.assertEqual(len(self.by(tn, 'Messages you got, by day')), 1)
        [rest] = recs['tinder_other']
        self.assertNotIn('app_opens', rest['text'], 'the counts a mapping read are not kept twice')
        self.assertIn('Fog, tide charts', rest['text'], 'your profile is still kept')

    def test_hinge(self):
        recs = self.read('hinge')
        hg = recs['hinge']
        chats = self.by(hg, 'Messages you sent')
        self.assertEqual(sorted((r['ts'], r['text'], r['thread']) for r in chats), [
            ('2024-01-05T20:05:40Z', 'Hi!', '0'), ('2024-01-07T09:00:00Z', 'See you Friday', '0')])  # not in order in the file
        [liked] = self.by(hg, 'Profiles you liked')
        self.assertEqual((liked['kind'], liked['text']), ('like', 'Great hiking photo!'))
        self.assertEqual([r['thread'] for r in self.by(hg, 'Your matches')], ['0', '2'])
        [met] = self.by(hg, 'People you said you met')
        self.assertEqual((met['text'], met['thread']), ('Yes', '2'))
        [prompt] = self.by(hg, 'Your prompts')
        self.assertIn('Fog is a cloud', prompt['text'])
        new = self.by(hg, 'Your chats (2025 on)')
        self.assertEqual([(r['text'], r['is_me'], r['thread']) for r in new],
                         [('Hi,\nthere', True, 'c0ffee01'), ('Hello!', False, 'c0ffee01')])  # the 2025 CSV: both sides
        self.assertEqual([r['text'] for r in self.by(hg, 'Profiles you liked (2025 on)')], ['Love the dog'])

    def test_trello(self):
        recs = self.read('trello')
        tr = recs['trello']
        [card] = self.by(tr, 'Cards on your boards')
        self.assertEqual((card['title'], card['text'], card['thread_name'], card['url']),
                         ('Fix fence', 'Fix fence\nTwo loose boards', 'Home projects', 'https://trello.com/c/abcd1234/3-fix-fence'))
        [comment] = self.by(tr, 'Comments on cards')
        self.assertEqual((comment['kind'], comment['text'], comment['author'], comment['thread_name']),
                         ('comment', 'Bought screws', 'Riley Park', 'Fix fence'))
        [made] = self.by(tr, 'Other things done on your boards')
        self.assertTrue(made['text'].startswith('createCard'))
        self.assertEqual([r['title'] for r in self.by(tr, 'Checklists')], ['Supplies'])
        self.assertEqual({r['title'] for r in recs['trello_other']}, {'lists', 'members', 'home-projects'})

    def test_day_one(self):
        recs = self.read('day-one', 'Export-Journal.zip')
        d1 = recs['day_one']
        self.assertEqual([(r['ts'], r['thread_name']) for r in d1], [('2024-01-05T18:30:00Z', 'Journal'), ('2024-02-01T07:00:00Z', 'Journal')])
        self.assertTrue(d1[0]['text'].startswith('# Ridge trail'))
        self.assertTrue(d1[0]['text'].endswith('hiking, fog\nSample Ridge\nSpringfield\nPartly Cloudy'), d1[0]['text'])
        self.assertNotIn('richText', d1[0]['text'], 'the text, not its rich-text copy')

    def test_evernote(self):
        recs = self.read('evernote')
        ev = recs['evernote']
        self.assertEqual([(r['title'], r['ts'], r['thread_name']) for r in ev], [
            ('Old idea', '2018-12-01T12:00:00Z', 'Notebook'), ('Second', '2018-12-02T12:00:00Z', 'Notebook'),
            ('Packing list', '2024-01-05T18:30:00Z', 'Travel')])  # an .enex a notebook; its DOCTYPE only names its DTD
        self.assertEqual(ev[2]['text'], 'Packing list\nPack light.\nPassport\nTide chart\ntravel, lists', 'the note as words: &nbsp; read')
        self.assertEqual(ev[0]['text'], 'Old idea\nA lamp for fog.\nSketch it')
        self.assertNotIn('evernote_other', recs)

    def test_xml_that_declares_entities_is_refused_one_that_names_its_dtd_is_read(self):
        with self.assertRaises(ValueError):
            mx.xml_data('<?xml version="1.0"?><!DOCTYPE a SYSTEM "a.dtd" [<!ELEMENT a ANY>]><a/>')
        self.assertEqual(mx.xml_data('<?xml version="1.0"?>\n<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export4.dtd">'
                                     '<en-export><note><title>x</title></note></en-export>'), {'note': {'title': 'x'}})
        self.assertEqual(mx.html_text('<en-note><div>a&nbsp;b</div><div>c &amp; d</div></en-note>'), 'a b\nc & d')

    def test_todoist(self):
        recs = self.read('todoist')
        td = recs['todoist']
        tasks = self.by(td, 'Your tasks')
        self.assertEqual([(r['title'], r.get('ts'), r['thread_name']) for r in tasks], [
            ('Buy stamps @errands', None, 'Home [6Xmpl1Fq]'),  # a due date in words ("Jan 5") isn't a time
            ('Fix fence', '2024-03-31T00:00:00', 'Home [6Xmpl1Fq]')])  # a deadline is
        [note] = self.by(td, 'Comments on your tasks')
        self.assertEqual((note['text'], note['author']), ('Post office closes at 5,\nnot 6', 'Riley Park (1000001)'))
        self.assertEqual([r['title'] for r in self.by(td, 'Sections of your projects')], ['Errands'])

    def test_lyft(self):
        recs = self.read('lyft')
        ly = recs['lyft']
        rides = self.by(ly, 'Your rides')
        self.assertEqual([(r['title'], r['ts']) for r in rides], [
            ('200 Sample Ave, San Jose, CA', '2024-05-01T17:09:40Z'), ('3 Harbor Way, San Francisco, CA', '2024-05-03T08:00:00Z')])
        self.assertIn('canceled', rides[1]['text'])
        [paid] = self.by(ly, 'What you paid Lyft')
        self.assertEqual((paid['kind'], paid['text']), ('transaction', '23.45\nUSD\ncard'))
        texts = self.by(ly, 'Texts with your drivers')
        self.assertEqual([(r['text'], r['is_me']) for r in texts], [("I'm by the blue door", True), ('On my way!', False)])
        self.assertEqual({r['title'] for r in recs['lyft_other']}, {'user profile'})

    def test_doordash(self):
        recs = self.read('doordash')
        items = recs['doordash']
        self.assertEqual([(r['title'], r['ts'][:19], r['thread_name']) for r in items], [
            ('Veggie Burrito', '2024-02-10T01:15:22', 'Sample Taqueria'), ('Horchata', '2024-02-10T01:15:22', 'Sample Taqueria')])
        self.assertEqual(items[0]['thread'], items[1]['thread'], 'one order: its items share when it was placed')

    def test_money_exports(self):
        apple = self.read('apple-card')['apple_card']
        self.assertEqual([(r['title'], r['ts'], r['author']) for r in apple], [
            ('Sample Coffee', '2026-03-14T00:00:00', 'Riley Park'), ('Payment', '2026-03-20T00:00:00', 'Riley Park')])
        cb = self.read('coinbase')['coinbase']
        self.assertEqual(sorted((r['ts'], r['title']) for r in cb), [
            ('2022-03-01T10:00:00Z', 'Received 0.1 ETH from an external account'),  # after a tax note and blank lines
            ('2025-01-15T14:05:09Z', 'Bought 0.0005 BTC for 49.49 USD')])  # 2024 on: an ID first
        rh = self.read('robinhood')['robinhood']
        self.assertEqual([(r['ts'], r['meta']['fields']['Trans Code']) for r in rh], [('2026-03-03T00:00:00', 'Buy'), ('2026-03-10T00:00:00', 'CDIV')])
        self.assertIn('CUSIP: 000000000', rh[0]['text'], 'a description over two lines')
        chase = self.read('chase')['chase']
        self.assertEqual(sorted((r['ts'], r['title'], r['meta']['mapped']) for r in chase), [
            ('2026-03-01T00:00:00', 'EXAMPLE PAYROLL PPD ID: 0000000000', 'Your checking and savings activity'),
            ('2026-03-02T00:00:00', 'SAMPLE GROCERY 41', 'Your checking and savings activity'),  # 8 fields to a row, 7 in the header
            ('2026-03-05T00:00:00', 'SAMPLE BOOKSHOP', 'Your card activity'),
            ('2026-03-20T00:00:00', 'Payment Thank You-Mobile', 'Your card activity')])
        boa = self.read('bank-of-america')['bank_of_america']
        self.assertEqual(sorted((r['ts'], r['title']) for r in boa), [
            ('2026-03-02T00:00:00', 'SAMPLE GROCERY 41'),  # the summary above and the beginning balance aren't payments
            ('2026-03-04T00:00:00', 'SAMPLE HARDWARE'), ('2026-03-18T00:00:00', 'PAYMENT - THANK YOU')])
        c1 = self.read('capital-one')['capital_one']
        self.assertEqual([(r['ts'], r['title'], r['thread']) for r in c1], [
            ('2026-03-02T00:00:00', 'SAMPLE GROCERY', '1234'), ('2026-03-15T00:00:00', 'CAPITAL ONE MOBILE PYMT', '1234')])  # "Card No."

    def test_ofx_downloads(self):
        old = os.environ.get('TZ')  # Capital One 360's times have no zone: this Mac's, here New York's
        os.environ['TZ'] = 'America/New_York'
        time.tzset()
        self.addCleanup(lambda: (os.environ.__setitem__('TZ', old) if old else os.environ.pop('TZ', None), time.tzset()))
        bank, card = (f'Your {x}, from a QFX, QBO or OFX download' for x in ('checking and savings activity', 'card activity'))
        recs = self.read('chase', fixture='ofx/chase')
        self.assertEqual(set(recs), {'chase'}, 'nothing left to the catch-all')
        chase = recs['chase']
        self.assertEqual(sorted((r['ts'], r['title'], r['meta']['mapped'], r['thread']) for r in chase), [
            ('2026-03-01T12:00:00Z', 'EXAMPLE PAYROLL PPD ID: 0000000000', bank, '1234'),
            ('2026-03-02T12:00:00Z', 'SAMPLE GROCERY 41', bank, '1234'),
            ('2026-03-05T12:00:00Z', 'SAMPLE BOOKSHOP', card, '5678'),  # the .QBO: the day bought (DTUSER), not posted
            ('2026-03-10T12:00:00Z', 'CHECK 1001', bank, '1234'),  # in both checking downloads: once
            ('2026-03-12T12:00:00Z', 'CAFÉ SAMPLE', bank, '1234'),  # Windows-1252, as its header says; once too
            ('2026-03-20T12:00:00Z', 'Payment Thank You-Mobile', card, '5678'),
            ('2026-04-02T12:00:00Z', 'SAMPLE PHARMACY', bank, '1234'),
            ('2026-04-03T12:00:00Z', 'SAMPLE PARKING', bank, '1234'),  # two the bank gave one FITID: both kept
            ('2026-04-03T12:00:00Z', 'SAMPLE TOLL', bank, '1234'),
            ('2026-04-05T12:00:00Z', 'SAMPLE ATM FEE', bank, '1234')])  # no FITID
        cafe = next(r for r in chase if r['title'] == 'CAFÉ SAMPLE')
        self.assertEqual(cafe['text'], 'CAFÉ SAMPLE\nRiley’s lunch & tip\nDEBIT\n-9.80')
        self.assertEqual((cafe['id'], cafe['meta']['file']), ('BANKMSGSRSV1#1234#202603120', 'chase/Chase1234_Activity_20260331.QFX'),
                         'its id is its FITID in its account, not its file: the first download it was in keeps it')
        self.assertTrue(cafe['is_me'])
        by_title = {r['title']: r['id'] for r in chase}
        self.assertEqual((by_title['SAMPLE PARKING'], by_title['SAMPLE TOLL']), ('BANKMSGSRSV1#1234#202604030', 'BANKMSGSRSV1#1234#202604030#2'))
        self.assertEqual(by_title['SAMPLE ATM FEE'], 'chase/Chase1234_Activity_20260415.QFX#BANKMSGSRSV1#5', 'no FITID: its place in its file')
        self.assertEqual(cafe['meta']['fields'], {'TRNTYPE': 'DEBIT', 'DTPOSTED': '2026-03-12T12:00:00+00:00', 'TRNAMT': '-9.80',
                                                  'FITID': '202603120', 'NAME': 'CAFÉ SAMPLE', 'MEMO': 'Riley’s lunch & tip',
                                                  'CURDEF': 'USD', 'account': '1234'})
        self.assertTrue(next(r for r in chase if r['title'] == 'CHECK 1001')['text'].endswith('\n1001'), 'its CHECKNUM')
        self.assertNotIn('000000001234', json.dumps(chase), 'an account number: only its last four')
        boa = self.read('bank-of-america', fixture='ofx/bank-of-america')['bank_of_america']
        self.assertEqual([(r['ts'], r['title']) for r in boa], [
            ('2026-03-02T17:00:00Z', 'SAMPLE GROCERY 41'),  # noon in New York
            ('2026-03-04T00:00:00', 'SAMPLE HARDWARE')])  # midnight in New York: the day, not the 3rd's evening further west
        c1 = self.read('capital-one', fixture='ofx/capital-one')['capital_one']
        self.assertEqual(sorted((r['ts'], r['title'], r['thread'], r['meta']['mapped']) for r in c1), [
            ('2026-03-02T00:00:00', 'SAMPLE GROCERY', '1234', card),  # XXXXXXXXXXXX1234: its CSV's Card No.
            ('2026-03-02T10:00:00Z', 'Deposit from EXAMPLE PAYROLL', '9876', bank),  # 360 Checking: no NAME, so its MEMO
            ('2026-03-15T00:00:00', 'CAPITAL ONE MOBILE PYMT', '1234', card),
            ('2026-03-31T08:00:00Z', 'Monthly Interest Paid', '9876', bank)])
        apple = self.read('apple-card', fixture='ofx/apple-card')['apple_card']
        self.assertEqual([(r['ts'], r['title'], r['author'], r['thread']) for r in apple], [
            ('2026-03-15T01:30:00Z', 'Café Sample', 'me', '4321'),  # 6:30 pm on the 14th in California; its NAME in CDATA
            ('2026-03-20T00:00:00', 'Payment & Thanks', 'me', '4321')])

    def test_ofx_reader(self):
        sgml = ('OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\n\n<OFX><BANKMSGSRSV1>' + ''.join(
            f'<STMTTRNRS><STMTRS><BANKACCTFROM><ACCTID>{a}</BANKACCTFROM><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT'
            f'<DTPOSTED>20260305<TRNAMT>-1.00<FITID>{a}-1<MEMO><NAME>After an empty MEMO</STMTTRN></BANKTRANLIST></STMTRS></STMTTRNRS>'
            for a in ('11112222', '33334444')) + '</BANKMSGSRSV1></OFX>')
        one, two = mx.ofx_data(sgml)['BANKMSGSRSV1']
        self.assertEqual(one, {'TRNTYPE': 'DEBIT', 'DTPOSTED': '2026-03-05', 'TRNAMT': '-1.00', 'FITID': '11112222-1', 'MEMO': '',
                               'NAME': 'After an empty MEMO', 'account': '2222'})  # a MEMO never closed is empty: NAME is beside it
        self.assertEqual((two['FITID'], two['account']), ('33334444-1', '4444'), "two accounts' statements in one file")
        xml = ('<?xml version="1.0"?><?OFX OFXHEADER="200"?><OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><CURDEF>EUR</CURDEF>'
               '<BANKTRANLIST><STMTTRN><FITID>9</FITID><MEMO/><NAME>A &lt;B&gt;</NAME><!-- <MEMO>no</MEMO> --></STMTTRN>'
               '</BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>')
        self.assertEqual(mx.ofx_data(xml), {'CREDITCARDMSGSRSV1': [{'FITID': '9', 'MEMO': '', 'NAME': 'A <B>', 'CURDEF': 'EUR'}]})
        with self.assertRaises(ValueError):
            mx.ofx_data('Date,Description\n03/05/2026,Not OFX\n')
        for v, iso in (('20260305', '2026-03-05'), ('20260305120000.000[-5:EST]', '2026-03-05T12:00:00-05:00'),
                       ('20260305120000[0:GMT]', '2026-03-05T12:00:00+00:00'), ('20260305123000.000[+5.30:IST]', '2026-03-05T12:30:00+05:30'),
                       ('20260305000000.000[-5:EST]', '2026-03-05'), ('20260305050000.000', '2026-03-05T05:00:00'),
                       ('202603051230', '2026-03-05T12:30:00'), ('n/a', 'n/a')):
            self.assertEqual(mx.ofx_time(v), iso, v)

        class Raw:
            def __init__(self, b):
                self.b = b

            def read(self):
                return self.b
        head = 'OFXHEADER:100\nENCODING:{}\nCHARSET:{}\n\n<OFX></OFX> Café’'
        self.assertTrue(mx.ofx_text(Raw(head.format('USASCII', '1252').encode('cp1252'))).endswith('Café’'))
        self.assertTrue(mx.ofx_text(Raw(head.format('UTF-8', '1252').encode('utf-8'))).endswith('Café’'), 'UTF-8 says so')
        self.assertTrue(mx.ofx_text(Raw(head.format('USASCII', 'NONE').encode('cp1252'))).endswith('Café’'), 'not UTF-8: Windows-1252')

    def test_overlap_ids(self):
        """An overlap rule's id is its FITID in its account: the same in another file, another in another account."""
        def ofx(*accounts):
            return '<OFX><BANKMSGSRSV1>' + ''.join(
                f'<STMTTRNRS><STMTRS><BANKACCTFROM><ACCTID>{a}</BANKACCTFROM><BANKTRANLIST>'
                + ''.join(f'<STMTTRN><TRNAMT>-1<FITID>{f}<NAME>{a}/{f}</STMTTRN>' for f in fitids)
                + '</BANKTRANLIST></STMTRS></STMTTRNRS>' for a, fitids in accounts) + '</BANKMSGSRSV1></OFX>'
        m = mx.validate(json.loads((SHIPPED / 'chase.json').read_text()))
        es = [Entry('chase/march.qfx', ofx(('1111', ['1']), ('2222', ['1']))), Entry('chase/april.qfx', ofx(('1111', ['1', '7', '7'])))]
        self.assertEqual([rec['id'] for _, _, rec in mx.records(m, es)], [
            'BANKMSGSRSV1#1111#1', 'BANKMSGSRSV1#2222#1',  # one FITID in two accounts: two transactions
            'BANKMSGSRSV1#1111#1',  # March's again in April's download: the same id, so kept once
            'BANKMSGSRSV1#1111#7', 'BANKMSGSRSV1#1111#7#2'])  # twice in one file: two
        plain = {**m, 'items': [{k: v for k, v in r.items() if k != 'overlap'} for r in m['items']]}
        self.assertEqual([rec['id'] for _, _, rec in mx.records(plain, es[1:])][0], 'chase/april.qfx#BANKMSGSRSV1#1', 'without overlap: by file')

    def test_apple_music(self):
        recs = self.read('apple-account-itunes')
        am = recs['apple_account_itunes']
        plays = self.by(am, 'Songs you played on Apple Music')
        self.assertEqual([(r['title'], r['ts'][:19]) for r in plays], [
            ('Paper Boats', '2025-03-01T18:30:42'),  # PLAY_END rows only: not PLAY_START, not lyrics shown
            ('Low Tide', '2025-03-01T18:34:11'), ('Fog Song', '2016-02-01T08:00:00')])  # 2016: no Event Type
        self.assertIn('TRACK_SKIPPED_FORWARDS', plays[1]['text'])
        fields = plays[0]['meta']['fields']
        self.assertEqual(fields['Play Duration Milliseconds'], '208394')
        self.assertFalse({'Client IP Address', 'IP City', 'IP Latitude', 'Apple ID Number', 'Device Identifier'} & set(fields), 'left out')
        daily = self.by(am, 'Your Apple Music plays, a track a day')
        self.assertEqual([(r['title'], r['ts']) for r in daily], [
            ('The Example Band - Paper Boats', '2025-03-01T00:00:00'), ('Harbor Radio', '2025-03-02T00:00:00')])
        [loved] = self.by(am, 'Songs you loved or disliked')
        self.assertEqual((loved['kind'], loved['text']), ('like', 'The Example Band - Paper Boats\nLOVE'))
        [song] = self.by(am, 'Songs in your Apple Music library')
        self.assertEqual((song['kind'], song['text']), ('saved', 'Paper Boats\nThe Example Band\nHarbor Lights\nIndie'))
        self.assertNotIn('apple_account_itunes_other', recs)

    def test_microsoft_searches(self):
        ms = self.read('microsoft-account')['microsoft_account']
        self.assertEqual(sorted((r['ts'][:19], r['title'], r.get('url')) for r in ms), [
            ('2018-01-12T03:48:24', 'tide tables', 'https://example.com/'),  # JSON, before 2021
            ('2021-03-09T15:59:21', 'example docs', 'https://example.com/docs'),  # CSV: "3/9/2021 3:59:21 PM +00:00"
            ('2021-03-09T16:05:10', 'weather tomorrow', None)])

    def test_fitbit(self):
        recs = self.read('fitbit', 'MyFitbitData.zip', 'MyFitbitData')
        fb = recs['fitbit']
        walks = self.by(fb, 'Your workouts and walks')
        self.assertEqual([(r['ts'], r['meta']['fields']['activityName']) for r in walks],
                         [('2024-03-02T16:30:00Z', 'Walk'), ('2024-03-04T01:00:00Z', 'Weights')])  # 03/02/24, UTC
        self.assertIn('activityName: Walk', walks[0]['text'], 'its fields, by name')
        [sleep] = self.by(fb, 'How you slept')
        self.assertIn('minutesAsleep: 412', sleep['text'])
        self.assertEqual(len(self.by(fb, 'Your sleep scores')), 1)
        [weight] = self.by(fb, 'Your weight')
        self.assertEqual((weight['ts'], weight['meta']['fields']['weight']), ('2024-03-01T00:00:00', 155.2))
        [rhr] = self.by(fb, 'Your resting heart rate')
        self.assertEqual((rhr['ts'], rhr['text']), ('2024-03-01T00:00:00', '54.01'), 'not the empty day padded on after it')
        self.assertTrue(any(r['title'] == 'Profile' for r in recs['fitbit_other']), 'the rest is still kept')
        # The series by the minute: a record a day, on the clock of Profile.csv's zone (America/Los_Angeles)
        days = lambda s: {r['meta']['day']: r for r in fb if r['meta'].get('series') == s}  # noqa: E731
        steps = days('steps')
        self.assertEqual({d: r['meta']['steps'] for d, r in steps.items()}, {
            '2024-02-29': 5,  # 07:59 UTC on the 1st is still the 29th in California
            '2024-03-01': 42,
            '2024-03-11': 7,  # 07:30 UTC: half past midnight once the clocks went forward (half past eleven before)
            '2024-03-30': 40,  # the reading both batches have at their edge, once
            '2024-03-31': 100})
        self.assertEqual({k: steps['2024-03-01'][k] for k in ('kind', 'ts', 'title', 'text', 'is_me')}, {
            'kind': 'activity', 'ts': '2024-03-01T00:00:00', 'title': 'Steps', 'text': 'Steps on Friday 1 March 2024: 42',
            'is_me': True})
        self.assertEqual(steps['2024-03-01']['meta'], {'series': 'steps', 'day': '2024-03-01', 'steps': 42, 'readings': 3,
                                                       'zone': 'America/Los_Angeles'})
        hr = days('heart_rate')
        self.assertEqual({d: [r['meta'][k] for k in ('bpm_lowest', 'bpm_average', 'bpm_highest', 'readings')] for d, r in hr.items()},
                         {'2024-02-29': [64, 64, 64, 1], '2024-03-01': [58, 83.5, 140, 4]})
        self.assertEqual(hr['2024-03-01']['text'], 'Heart rate on Friday 1 March 2024: 58 to 140 bpm, 84 on average (4 readings)')
        self.assertEqual(hr['2024-02-29']['text'], 'Heart rate on Thursday 29 February 2024: 64 bpm (1 reading)')
        cal = days('calories')  # written in local time: each reading on its own date
        self.assertEqual({d: r['meta']['calories'] for d, r in cal.items()}, {'2024-03-01': 2.8, '2024-03-02': 2})
        self.assertNotIn('zone', cal['2024-03-01']['meta'])
        [dist] = days('distance').values()
        self.assertEqual((dist['meta']['distance_cm'], dist['text']), (16390.5, 'Distance on Friday 1 March 2024: 0.16 km'))
        alt = days('altitude')  # written in local time, in feet
        self.assertEqual({d: r['meta']['feet'] for d, r in alt.items()}, {'2024-03-01': 30, '2024-03-02': 10})
        self.assertEqual(alt['2024-03-01']['text'], 'Altitude climbed on Friday 1 March 2024: 30 ft (9 m)')
        self.assertFalse([r for r in recs['fitbit_other'] if imports.fitbit_file(r['meta']['file'])],
                         'no reading kept one by one')

    def test_fitbit_day(self):
        from zoneinfo import ZoneInfo
        self.assertEqual(imports.fitbit_day('03/01/24 07:59:00', ZoneInfo('America/Los_Angeles')), '2024-02-29')
        self.assertEqual(imports.fitbit_day('2024-03-01T18:30:00', ZoneInfo('Asia/Kolkata')), '2024-03-02')  # ISO too
        self.assertEqual(imports.fitbit_day('03/01/24 23:59:00', False), '2024-03-01', 'a series in local time: its own date')
        self.assertIsNone(imports.fitbit_day('02/30/24 08:00:00', False))
        self.assertIsNone(imports.fitbit_day('', None))

    def test_fitbit_in_takeout(self):
        """Takeout's Fitbit folder is read with Google's export, not the Fitbit mapping: its series by the minute are a
        record a day too, in takeout_other with the rest of the folder, on the clock of Your Profile/Profile.csv's zone."""
        dest = self.imports / 'takeout'
        dest.mkdir()
        self.zip(FIXTURES / 'fitbit', dest / 'takeout-20241101T090000Z-001.zip', 'Takeout')
        # An earlier Takeout has the same batch, then still short of its last reading: it's read once, the longer copy.
        with zipfile.ZipFile(dest / 'takeout-20240302T090000Z-001.zip', 'w') as z:
            z.writestr('Takeout/Fitbit/Global Export Data/steps-2024-03-01.json', '[{"dateTime": "03/01/24 18:29:00", "value": "20"}]')
        recs = self.run_parsers([imports.google, mx.mapped_exports, imports.fitbit_days, imports.other_data])
        other = recs['takeout_other']
        days = {(r['meta']['series'], r['meta']['day']): r for r in other if r['meta'].get('series') in ('steps', 'heart_rate')}
        self.assertEqual({k: r['meta'].get('steps', r['meta'].get('bpm_highest')) for k, r in days.items() if k[1] < '2024-03-05'}, {
            ('steps', '2024-03-01'): 20, ('steps', '2024-03-02'): 15,  # 18:30 UTC is midnight in India (UTC+5:30)
            ('heart_rate', '2024-03-01'): 66, ('heart_rate', '2024-03-02'): 70})
        self.assertEqual(days['steps', '2024-03-02']['meta']['zone'], 'Asia/Kolkata')
        self.assertFalse([r for r in other if imports.fitbit_file(r['meta'].get('file', ''))], 'no reading kept one by one')
        self.assertTrue(any(r['title'] == 'Profile' for r in other), 'the rest is still kept')
        self.assertFalse([r for r in other if imports.fitbit_reads(r['meta'].get('file', ''))], 'nor a route point')

    def test_fitbit_csvs_in_takeout(self):
        """Google's CSVs (Physical Activity_GoogleData/) and the older ones beside them (Minute SpO2, Heart Rate Variability
        Details, Wrist Temperature, Active Zone Minutes, estimated_oxygen_variation) are a record a series a day too, each
        on its own clock, the JSON's days first."""
        dest = self.imports / 'takeout'
        dest.mkdir()
        self.zip(FIXTURES / 'fitbit', dest / 'takeout-20241101T090000Z-001.zip', 'Takeout')
        recs = self.run_parsers([imports.google, mx.mapped_exports, imports.fitbit_days, imports.other_data])
        day = {(r['meta']['series'], r['meta']['day']): r for r in recs['takeout_other'] if 'series' in r['meta']}
        text = lambda s, d: day[s, d]['text'].split(': ', 1)[1]  # noqa: E731
        self.assertEqual({d: r['meta']['steps'] for (s, d), r in day.items() if s == 'steps'},
                         {'2024-03-01': 20, '2024-03-02': 15, '2024-03-05': 300}, 'the JSON has the 1st; the CSV the 5th, which it lacks')
        self.assertEqual(text('heart_rate', '2024-03-05'), '72 to 80 bpm, 76 on average (2 readings)')
        self.assertEqual(text('distance', '2024-03-05'), '0.25 km')  # metres
        self.assertEqual(day['distance', '2024-03-05']['meta']['distance_cm'], 25050)
        self.assertEqual(text('altitude', '2024-03-05'), '10 ft (3 m)')  # millimetres
        self.assertEqual(text('active_minutes', '2024-03-05'), '2 light, 1 moderate, 1 very active')
        azm = day['active_zone_minutes', '2024-03-05']
        self.assertEqual((azm['text'].split(': ', 1)[1], azm['meta']['zones']), ('5 (cardio 4, fat burn 1)', {'cardio': 4, 'fat burn': 1}))
        self.assertEqual(day['active_zone_minutes', '2024-03-04']['meta']['minutes'], 1, "the older file's, in local time, for a day Google's lacks")
        self.assertEqual(text('activity_level', '2024-03-05'), '3 minutes sedentary, 1 lightly active')
        self.assertEqual(text('body_temperature', '2024-03-05'), '33.5 to 34.1 °C, 33.8 on average (2 readings)')  # 20:00 UTC: 01:30 in India
        self.assertEqual(text('wrist_temperature', '2024-03-05'), '-0.4 to +0.2 °C, -0.1 on average (2 readings)')
        self.assertNotIn('zone', day['wrist_temperature', '2024-03-05']['meta'], 'written in local time')
        self.assertEqual(text('oxygen_saturation', '2024-03-05'), '96 to 97%, 96 on average (2 readings)')
        self.assertEqual(text('heart_rate_variability', '2024-03-05'), '31 to 41 ms, 36 on average (2 readings)')  # UTC, no zone mark
        self.assertIn('low_frequency_average', day['heart_rate_variability', '2024-03-05']['meta'])
        self.assertEqual(text('oxygen_variation', '2024-03-05'), '-2 to 3, 0.5 on average (2 readings)')
        self.assertEqual(day['steps', '2024-03-05']['title'], 'Steps')

    def test_fitbit_routes(self):
        """gps_location_<date>.csv, a point a second, is read as Location History's trips are: a record a route. A route
        runs on over a file's edge (UTC midnight) and through a pause in a workout, which names it."""
        dest = self.imports / 'takeout'
        dest.mkdir()
        self.zip(FIXTURES / 'fitbit', dest / 'takeout-20241101T090000Z-001.zip', 'Takeout')
        recs = self.run_parsers([imports.google, mx.mapped_exports, imports.fitbit_days, imports.other_data])
        route, walk = sorted((r for r in recs['takeout_other'] if r['kind'] == 'trip'), key=lambda r: r['ts'])
        self.assertEqual({k: route[k] for k in ('id', 'ts', 'ts_end', 'title', 'text', 'is_me')}, {
            'id': 'fitbit:route:2024-03-04T23:59:55Z', 'ts': '2024-03-04T23:59:55Z', 'ts_end': '2024-03-05T00:00:04Z', 'title': 'Route',
            'text': 'Route: 27 m in 9 s, from 12.97160°, 77.59460° to 12.97184°, 77.59460°', 'is_me': True})
        self.assertEqual({k: route['meta'][k] for k in ('points', 'seconds', 'meters', 'altitude_lowest', 'altitude_highest')},
                         {'points': 10, 'seconds': 9, 'meters': 27, 'altitude_lowest': 920.0, 'altitude_highest': 920.9},
                         "the point both files have once; 0,0 isn't a place")
        self.assertEqual(route['meta']['path'][0], [12.9716, 77.5946])
        self.assertNotIn('activity', route['meta'], 'no workout then')
        self.assertEqual((walk['title'], walk['meta']['activity'], walk['meta']['workout'], walk['meta']['points'], walk['meta']['seconds']),
                         ('Outdoor Walk', 'Outdoor Walk', '1001', 6, 902), 'its 15 minutes standing still are in one workout')
        self.assertTrue(walk['text'].startswith('Outdoor Walk: 0.1 km in 15 min, from 12.98000°, 77.60000° to '))
        self.assertFalse([r for r in recs['takeout_other'] if imports.fitbit_reads(r['meta'].get('file', ''))], 'no point kept one by one')

    def test_fitbit_route_thinned(self):
        """A long route keeps FITBIT_PATH points of its path, its first and last among them, and counts the rest; two
        devices' points at the same time are two routes."""
        dest = self.imports / 'takeout'
        dest.mkdir()
        rows = ''.join(f'2026-05-01T08:{i // 60:02d}:{i % 60:02d}Z,{51.5 + i * 1e-5:.5f},-0.12,,{dev}\n' for i in range(500)
                       for dev in ('Google Pixel Watch', 'Google Health App'))
        with zipfile.ZipFile(dest / 'takeout-20260502T090000Z-001.zip', 'w') as z:
            z.writestr('Takeout/Google Health/Physical Activity_GoogleData/GPS Location/gps_location_2026-05-01.csv',
                       'timestamp,latitude,longitude,altitude,data source\n' + rows)
        out = list(imports.fitbit_routes(imports.entries(), set(), set()))
        self.assertEqual(sorted(r['meta']['device'] for _, r, _ in out), ['Google Health App', 'Google Pixel Watch'])
        for source, r, dropped in out:
            self.assertEqual((source, len(r['meta']['path']), r['meta']['points'], dropped), ('takeout_other', imports.FITBIT_PATH, 500, 300))
            self.assertEqual((r['meta']['path'][0], r['meta']['path'][-1]), ([51.5, -0.12], [51.50499, -0.12]))
            self.assertNotIn('altitude_lowest', r['meta'], 'none written')
            self.assertTrue(r['id'].endswith(':' + r['meta']['device']))

    def test_fitbit_csvs_by_device(self):
        """Since 2026, Google's CSVs are in a folder a family and say which device each reading is from. The phone, the band
        and Health Connect count the same steps: the day's figure is the one that counted the most, and each is said."""
        dest = self.imports / 'takeout'
        dest.mkdir()
        with zipfile.ZipFile(dest / 'takeout-20260502T090000Z-001.zip', 'w') as z:
            g = 'Takeout/Google Health/Physical Activity_GoogleData/'
            z.writestr('Takeout/Google Health/Your Profile/Profile.csv', 'id,timezone\nX,Europe/London\n')
            z.writestr(g + 'Steps/steps_2026-05-01.csv', 'timestamp,steps,data source\n'
                       '2026-04-30T23:30:00Z,7,Google Health App\n'  # half past midnight in London (summer time)
                       '2026-05-01T08:00:00.123Z,100,Google Health App\n2026-05-01T08:00:00.123Z,90,Fit Health Connect\n'
                       '2026-05-01T09:00:00.000Z,50,Google Health App\n2026-05-01T09:00:00.000Z,45,Fit Health Connect\n'
                       '2026-05-01T09:00:00Z,12,Google Fitbit Air\n')
            z.writestr(g + 'Heart Rate/heart_rate_2026-05-01.csv', 'timestamp,beats per minute,data source\n'
                       '2026-05-01T08:00:00Z,70.0,Google Fitbit Air\n2026-05-01T08:00:05Z,74.0,Google Fitbit Air\n')
        recs = self.run_parsers([imports.google, mx.mapped_exports, imports.fitbit_days, imports.other_data])
        [steps] = [r for r in recs['takeout_other'] if r['meta'].get('series') == 'steps']
        self.assertEqual(steps['text'], 'Steps on Friday 1 May 2026: 157 '
                                        '(by device: Google Health App 157, Fit Health Connect 135, Google Fitbit Air 12)')
        self.assertEqual({k: steps['meta'][k] for k in ('steps', 'device', 'by_device', 'zone')}, {
            'steps': 157, 'device': 'Google Health App', 'zone': 'Europe/London',
            'by_device': {'Google Health App': 157, 'Fit Health Connect': 135, 'Google Fitbit Air': 12}})
        [hr] = [r for r in recs['takeout_other'] if r['meta'].get('series') == 'heart_rate']
        self.assertEqual(hr['text'], 'Heart rate on Friday 1 May 2026: 70 to 74 bpm, 72 on average (2 readings)')
        self.assertEqual([r['title'] for r in recs['takeout_other'] if 'series' not in r['meta']], ['Profile'], 'every row read a day at a time')

    def test_garmin(self):
        recs = self.read('garmin', '11111111-0000-0000-0000-000000000000_1.zip')
        gm = recs['garmin']
        acts = self.by(gm, 'Your activities')
        self.assertEqual([(r['title'], r['ts']) for r in acts], [
            ('Sampletown Running', '2024-06-01T07:00:00Z'), ('Strength', '2024-06-03T07:00:00Z')])  # beginTimestamp, epoch ms
        self.assertEqual(acts[0]['meta']['fields']['distance'], 502000.0, 'centimetres, as the export has them')
        [sleep] = self.by(gm, 'How you slept')
        self.assertEqual(sleep['ts'], '2024-06-01T05:40:00Z')
        self.assertIn('deepSleepSeconds: 5400', sleep['text'])
        [day] = self.by(gm, 'Your days: steps, heart rate, stress')
        self.assertIn('totalSteps: 11200', day['text'])
        self.assertTrue(any('gear' in r['title'] for r in recs['garmin_other']))

    def test_new_mapping_keys_survive_validation(self):
        m = mx.validate({'deleted': ['deleted/*', 3], 'items': [{'file': 'a.csv', 'time': ['x', 'y', 4], 'formats': '%Y/%m/%d',
                         'where': {'s': 'read', 'bad': []}, 'unless': {'t': ['a']}, 'header': 'Pos,', 'not': ['likes/*'], 'needs': 'ID', 'kind': 'saved'}]})
        self.assertEqual(m['deleted'], ['deleted/*'])
        self.assertEqual(m['items'][0], {'file': 'a.csv', 'path': '', 'describe': 'a.csv', 'kind': 'saved', 'header': 'Pos,',
                                         'formats': ['%Y/%m/%d'], 'not': ['likes/*'], 'needs': ['ID'], 'where': {'s': ['read']},
                                         'unless': {'t': ['a']}, 'time': ['x', 'y']})

    def test_shipped_mappings_are_valid(self):
        for p in SHIPPED.glob('*.json'):
            raw = json.loads(p.read_text())
            m = mx.validate(raw)
            for a, b in zip(raw['items'], m['items']):
                self.assertEqual(set(a) - set(b), set(), f'{p.name}: {a["describe"]} lost keys in validation')


if __name__ == '__main__':
    unittest.main()
