"""Crafted exports can't write outside the corpus or pull in other files, and saved logins stay out.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import os
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
import ileapp
import iphone_backup


class ImportSafetyTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.imports, self.media = self.root / 'corpus/imports', self.root / 'corpus/media'
        self.imports.mkdir(parents=True)
        for name, value in (('IMPORTS', self.imports), ('MEDIA', self.media), ('CORPUS', self.imports.parent)):
            p = patch.object(imports, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_archive_entries_that_escape_are_dropped(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('export/ok.json', '{}')
            z.writestr('../../evil.txt', 'x')
            z.writestr('export/../../../evil2.txt', 'x')
            z.writestr('/etc/evil3', 'x')
        (self.imports / 'svc').mkdir()
        (self.imports / 'svc/export.zip').write_bytes(buf.getvalue())
        self.assertEqual([e.path for e in imports.entries()], ['export/ok.json'])

    def test_tar_exports_are_read_and_cannot_escape(self):
        import tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode='w:gz') as t:
            for name, data in (('repositories_000001.json', b'[{"name": "corpus"}]'), ('../../evil.txt', b'x'), ('/etc/evil2', b'x')):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo('notes.txt')
            link.type, link.linkname = tarfile.SYMTYPE, str(self.root / 'id_ed25519')
            t.addfile(link)
        (self.imports / 'github').mkdir()
        (self.imports / 'github/b7f1.tar.gz').write_bytes(buf.getvalue())
        es = imports.entries()
        self.assertEqual([(e.path, e.origin) for e in es], [('repositories_000001.json', 'github/b7f1.tar.gz')])
        self.assertEqual(es[0].json(), [{'name': 'corpus'}])
        self.assertFalse((self.root / 'evil.txt').exists())

    def test_nested_export_becomes_one_record_per_item_without_logins_or_ad_ids(self):
        """TikTok's export is one nested JSON file: each list in it is read item by item, and the login history,
        device ids and IP addresses next to the watch history stay out."""
        import json
        data = {'Your Activity': {
                    'Watch History': {'VideoList': [{'Date': '2026-06-13 07:51:55', 'Link': 'https://v/1'},
                                                    {'Date': '2026-06-12 07:51:33', 'Link': 'https://v/2'}]},
                    'Login History': {'LoginHistoryList': [{'Date': '2026-06-13 07:00:00', 'IP': '10.0.0.1'}]},
                    'Status': {'Status List': [{'Resolution': '1170x2532', 'IDFA': 'AAAA-BBBB'}]}},
                'Profile': {'userName': 'ada_l', 'IP': '10.0.0.2'},
                'metadata': {'columns': [{'name': 'SKU ID', 'description': 'The SKU'}]}}
        (self.imports / 'tiktok').mkdir()
        (self.imports / 'tiktok/user_data_tiktok.json').write_text(json.dumps(data))
        added = []

        class W:
            def has(self, key):
                return False

            def add(self, **r):
                added.append(r)
        imports.other_data(imports.entries(), lambda source: W(), set())
        self.assertEqual([r['title'] for r in added], ['Watch History / VideoList'] * 2 + ['user data tiktok'])
        self.assertEqual(added[0]['ts'][:10], '2026-06-13')
        text = ' '.join(r['text'] for r in added)
        self.assertIn('https://v/2', text)
        self.assertIn('ada_l', text)
        self.assertNotIn('SKU ID', text, "a file's description of its own columns isn't a record")
        for secret in ('10.0.0.1', '10.0.0.2', 'AAAA-BBBB'):
            self.assertNotIn(secret, text)

    def test_a_mapping_that_names_some_lists_keeps_the_rest(self):
        """A shipped mapping types the lists it knows; the catch-all still keeps the ones it doesn't name."""
        import json
        import mapped_exports
        (self.imports / 'tiktok').mkdir()
        (self.imports / 'tiktok/user_data_tiktok.json').write_text(json.dumps({
            'Your Activity': {'Watch History': {'VideoList': [{'Date': '2026-06-13 07:51:55', 'Link': 'https://v/1'}]},
                              'Hashtag': {'HashtagList': [{'HashtagName': 'cats'}]}}}))
        maps = self.root / 'corpus/mappings'
        maps.mkdir(parents=True)
        (maps / 'tiktok.json').write_text(json.dumps({'items': [{'file': 'user_data_tiktok.json', 'kind': 'watch',
            'path': 'Your Activity.Watch History.VideoList', 'time': 'Date', 'zone': 'UTC', 'url': 'Link', 'author': 'me'}]}))
        recs = {}

        class W:
            def __init__(self, source):
                self.source = source

            def has(self, key):
                return False

            def add(self, **r):
                recs.setdefault(self.source, []).append(r)
        es, used = imports.entries(), set()
        with patch.object(mapped_exports, 'MAPPINGS', maps), patch.dict(mapped_exports.MAPPED, clear=True):
            mapped_exports.mapped_exports(es, W, used)
            imports.other_data(es, W, used)
        self.assertEqual([(r['kind'], r['ts']) for r in recs['tiktok']], [('watch', '2026-06-13T07:51:55Z')])
        self.assertEqual([r['title'] for r in recs['tiktok_other']], ['Hashtag / HashtagList'], 'not the watch history twice')

    def test_media_names_cannot_leave_corpus_media(self):
        e = imports.Entry('a.jpg', lambda: io.BytesIO(b'img'), 3, 'svc')
        self.assertIsNone(imports.save_media(e, self.media / 'instagram' / '../../../../outside.jpg', None))
        self.assertFalse((self.root / 'outside.jpg').exists())
        self.assertTrue(imports.save_media(e, self.media / 'instagram' / 'photos/a.jpg', None).endswith('media/instagram/photos/a.jpg'))

    def test_links_in_an_export_folder_are_not_followed(self):
        secret = self.root / 'id_ed25519'
        secret.write_text('PRIVATE')
        (self.imports / 'svc').mkdir()
        os.symlink(secret, self.imports / 'svc/notes.txt')
        (self.imports / 'svc/real.txt').write_text('hello')
        self.assertEqual([e.path for e in imports.entries()], ['svc/real.txt'])


class SavedLoginsTests(unittest.TestCase):
    def test_cookie_and_credential_stores_are_never_decrypted(self):
        for path, skipped in (('Library/Cookies/Cookies.binarycookies', True), ('Documents/wxajs.cookies', True),
                              ('Library/Application Support/Google/credentials.sqlite3', True), ('Library/SMS/sms.db', False),
                              ('Library/Preferences/com.apple.MobileSMS.plist', False)):
            self.assertEqual(bool(iphone_backup.NEVER_FILES.search(path)), skipped, path)
        self.assertIn('KeychainDomain', iphone_backup.NEVER)

    def test_ileapp_never_runs_the_cookie_module(self):
        import re
        for module in ('appCookies', 'keychain', 'imeiImsi'):
            self.assertTrue(re.search(ileapp.EXCLUDE_MODULES, module), module)
        self.assertFalse(re.search(ileapp.EXCLUDE_MODULES, 'sms'))


if __name__ == '__main__':
    unittest.main()
