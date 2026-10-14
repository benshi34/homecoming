"""Synthetic mbox fixtures, isolated from the user's identity and corpus.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common

# identity.py loads at import time; point it at synthetic data before importing the parsers.
with tempfile.TemporaryDirectory() as tmp, patch.object(common, 'CORPUS', Path(tmp)):
    (Path(tmp) / 'identity.json').write_text('{"names":[],"emails":[],"usernames":[]}')
    import imports
    import identity


class MailboxTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(identity, 'ME', {'names_l': set(), 'emails_l': set(), 'usernames_l': set()})
        p.start()
        self.addCleanup(p.stop)

    def entry(self, path, origin, mid='one', labels=''):
        raw = (f'From sender@example.test Mon Jan 01 00:00:00 2024\n'
               f'From: Sender <sender@example.test>\nTo: Other <other@example.test>\n'
               f'Message-ID: <{mid}@example.test>\nSubject: Synthetic example\n'
               f'Date: Mon, 01 Jan 2024 00:00:00 +0000\nX-Gmail-Labels: {labels}\n\nHello.\n').encode()
        return imports.Entry(path, lambda: io.BytesIO(raw), len(raw), origin)

    def parse(self, entries):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(common, 'NORM', Path(tmp) / 'normalized'), \
             patch.object(common, 'MANIFEST', Path(tmp) / 'manifest.json'), \
             patch.object(common, 'code_version', return_value='fixture'):
            from contextlib import ExitStack, redirect_stdout
            import json
            writers = {}
            with redirect_stdout(io.StringIO()), ExitStack() as stack:
                def writer(source):
                    if source not in writers:
                        writers[source] = stack.enter_context(common.Writer(source, 'fixture', parser='fixture', accumulate=False))
                    return writers[source]
                imports.google(entries, writer, set())
            return {name: [json.loads(line) for line in w.path.read_text().splitlines()] for name, w in writers.items()}

    def test_sent_and_drafts_mark_mail_as_mine(self):
        for folder in ('Sent Items', 'Sent Mail 2', 'Drafts'):
            with self.subTest(folder=folder):
                rows = self.parse([self.entry(f'{folder}.mbox/mbox', 'hotmail/export')])['hotmail']
                self.assertTrue(rows[0]['is_me'])
                self.assertEqual(rows[0]['author'], 'me')

    def test_junk_deleted_and_outbox_are_kept_and_tagged(self):
        # Kept so nothing is lost; meta.tier lets searches leave them out.
        for folder, tier, mine in (('Junk Email', 'spam', False), ('Deleted Items', 'deleted', False),
                                   ('Trash 2', 'deleted', False), ('Outbox', 'unsent', True)):
            with self.subTest(folder=folder):
                rows = self.parse([self.entry(f'{folder}.mbox/mbox', 'hotmail/export')])['hotmail']
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['meta']['tier'], tier)
                self.assertEqual(rows[0]['is_me'], mine, 'outbox mail is mail you wrote')
        inbox = self.parse([self.entry('Inbox.mbox/mbox', 'hotmail/export')])['hotmail']
        self.assertNotIn('tier', inbox[0]['meta'])

    def test_split_mailboxes_deduplicate_by_message_id(self):
        rows = self.parse([self.entry('Inbox.mbox/mbox', 'hotmail/export'),
                           self.entry('Inbox 2.mbox/mbox', 'hotmail/export'),
                           self.entry('Inbox 2.mbox/mbox', 'hotmail/export', mid='two')])['hotmail']
        self.assertEqual(len(rows), 2)
        self.assertFalse(rows[0]['is_me'])
        self.assertEqual(rows[1]['meta']['folder'], 'Inbox')

    def test_takeout_remains_gmail_and_tags_spam_and_trash(self):
        rows = self.parse([self.entry('Takeout/Mail/All mail.mbox', 'takeout.zip', labels='Sent'),
                           self.entry('Takeout/Mail/All mail.mbox', 'takeout.zip', mid='spam', labels='Spam'),
                           self.entry('Takeout/Mail/All mail.mbox', 'takeout.zip', mid='bin', labels='Trash')])['gmail']
        self.assertEqual([(r['meta'].get('tier'), r['is_me']) for r in rows], [(None, True), ('spam', False), ('deleted', False)])

    def test_standalone_mbox_uses_import_folder_name(self):
        rows = self.parse([self.entry('Archive.mbox', 'work-mail/export')])['work_mail']
        self.assertEqual(rows[0]['meta']['folder'], 'Archive')


if __name__ == '__main__':
    unittest.main()
