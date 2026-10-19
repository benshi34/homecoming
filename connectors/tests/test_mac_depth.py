"""More from the Mac's own apps, on made-up databases: what Messages, Mail, Notes, Calendar, Photos and the browsers
keep besides the text.

Run: python3 -m unittest discover -s connectors/tests -p 'test_*.py'
"""
import sqlite3
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import imessage

NAMES = types.SimpleNamespace(label=lambda x: {'+15550100': 'Grace'}.get(x, x))


class MessagesTests(unittest.TestCase):
    def test_read_times_emoji_effects_subjects_and_unknown_senders(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.executescript('''
            create table handle(ROWID integer primary key, id text);
            create table chat_handle_join(chat_id, handle_id);
            create table chat(ROWID integer primary key, guid, style, display_name, chat_identifier, is_filtered);
            create table chat_message_join(message_id, chat_id);
            create table attachment(ROWID integer primary key, transfer_name, mime_type, filename, total_bytes);
            create table message_attachment_join(message_id, attachment_id);
            create table message(ROWID integer primary key, guid, text, attributedBody, handle_id, is_from_me, date, service,
              item_type, associated_message_type, associated_message_guid, thread_originator_guid, is_audio_message,
              balloon_bundle_id, date_edited, date_retracted, group_action_type, group_title, other_handle,
              date_read, date_delivered, associated_message_emoji, expressive_send_style_id, subject);
            insert into handle values (1, '+15550100'), (2, '+15550199');
            insert into chat values (1, 'chat-grace', 45, null, '+15550100', 0), (2, 'chat-unknown', 45, null, '+15550199', 1);
            insert into chat_handle_join values (1, 1), (2, 2);
            insert into message values (1, 'm1', 'See you at 6', null, 1, 1, 700000000000000000, 'iMessage', 0, 0, null, null, 0, null,
              0, 0, null, null, null, 700000060000000000, 700000001000000000, null, 'com.apple.MobileSMS.expressivesend.impact', 'Dinner');
            insert into message values (2, 'm2', 'Reacted 🎉 to "See you at 6"', null, 1, 0, 700000120000000000, 'iMessage', 0, 2006, 'p:0/m1', null, 0, null,
              0, 0, null, null, null, 0, 0, '🎉', null, null);
            insert into message values (3, 'm3', 'Your code is 123456', null, 2, 0, 700000200000000000, 'SMS', 0, 0, null, null, 0, null,
              0, 0, null, null, null, 0, 0, null, null, null);
            insert into chat_message_join values (1, 1), (2, 1), (3, 2);
        ''')
        rows = {r['id']: r for r in imessage.messages(con, NAMES, 'mac')}
        mine = rows['m1']['meta']
        self.assertEqual((mine['read'], mine['delivered'], mine['effect'], mine['subject']),
                         ('2023-03-08T20:27:40Z', '2023-03-08T20:26:41Z', 'slam', 'Dinner'), 'when they read it, with read receipts on')
        self.assertEqual((rows['m2']['kind'], rows['m2']['meta']['emoji']), ('reaction', '🎉'))
        self.assertNotIn('read', rows['m2']['meta'], 'not read yet: nothing said')
        self.assertEqual(rows['m3']['meta']['filtered'], 'unknown sender')
        self.assertNotIn('filtered', mine)


def run_connector(module, home, corpus):
    import os
    import subprocess
    env = {**os.environ, 'HOME': str(home), 'CORPUS_DIR': str(corpus)}
    r = subprocess.run([sys.executable, '-c', f'import {module}; {module}.main()'], cwd=Path(__file__).resolve().parents[1], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def records(corpus, source):
    import json
    return {x['id']: x for x in map(json.loads, (corpus / f'normalized/{source}.jsonl').read_text().splitlines())}


class Home(unittest.TestCase):
    def setUp(self):
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home, self.corpus = Path(t.name) / 'home', Path(t.name) / 'corpus'
        self.corpus.mkdir(parents=True)
        (self.corpus / 'identity.json').write_text('{"names":["Ada"],"emails":["ada@example.test"],"usernames":[],"phones":[]}')


class NotesTests(Home):
    def test_text_recognized_in_scans_and_handwriting_and_pinned(self):
        db = self.home / 'Library/Group Containers/group.com.apple.notes/NoteStore.sqlite'
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.executescript("""
            create table Z_PRIMARYKEY (Z_ENT int, Z_NAME text);
            insert into Z_PRIMARYKEY values (4, 'ICAttachment'), (13, 'ICFolder'), (12, 'ICNote');
            create table ZICNOTEDATA (ZNOTE int, ZDATA blob);
            create table ZICCLOUDSYNCINGOBJECT (Z_PK integer primary key, Z_ENT int, ZIDENTIFIER text, ZTITLE1 text, ZTITLE2 text, ZSNIPPET text,
              ZFOLDER int, ZFOLDERTYPE int, ZISPASSWORDPROTECTED int, ZISPINNED int, ZMARKEDFORDELETION int, ZCREATIONDATE1 real,
              ZMODIFICATIONDATE1 real, ZNOTE int, ZTYPEUTI text, ZTITLE text, ZURLSTRING text, ZOCRSUMMARY text, ZHANDWRITINGSUMMARY text,
              ZIMAGECLASSIFICATIONSUMMARY text);
            insert into ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZTITLE2, ZFOLDERTYPE) values (1, 13, 'Notes', 0);
            insert into ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZIDENTIFIER, ZTITLE1, ZSNIPPET, ZFOLDER, ZISPASSWORDPROTECTED, ZISPINNED,
              ZMARKEDFORDELETION, ZCREATIONDATE1, ZMODIFICATIONDATE1) values (2, 12, 'NOTE-1', 'Lease', 'Scanned the lease', 1, 0, 1, 0, 700000000, 700000100);
            insert into ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZNOTE, ZTYPEUTI, ZTITLE, ZOCRSUMMARY) values (3, 4, 2, 'com.apple.notes.gallery', 'Scanned Documents', 'Monthly rent is due on the first');
            insert into ZICCLOUDSYNCINGOBJECT (Z_PK, Z_ENT, ZNOTE, ZTYPEUTI, ZHANDWRITINGSUMMARY, ZIMAGECLASSIFICATIONSUMMARY) values (4, 4, 2, 'com.apple.drawing.2', 'call landlord', 'Handwriting');
        """)
        con.commit()
        con.close()
        run_connector('apple_notes', self.home, self.corpus)
        note = records(self.corpus, 'apple_notes')['NOTE-1']
        self.assertIn('Text in it: Monthly rent is due on the first', note['text'])
        self.assertIn('Text in it: call landlord', note['text'])
        self.assertIn('Shows: Handwriting', note['text'])
        self.assertTrue(note['meta']['pinned'])
        self.assertNotIn('text', note['meta']['attachments'][0], 'the text is in the note, once')


class CalendarTests(Home):
    def test_organizer_replies_and_repeats(self):
        db = self.home / 'Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb'
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.executescript("""
            create table Store (ROWID integer primary key, type int, name text);
            create table Calendar (ROWID integer primary key, title text, store_id int);
            create table Identity (ROWID integer primary key, display_name text, address text);
            create table Participant (ROWID integer primary key, owner_id int, status int, is_self int, entity_type int, identity_id int, email text);
            create table Location (ROWID integer primary key, title text, address text);
            create table Recurrence (ROWID integer primary key, owner_id int, frequency int, interval int);
            create table CalendarItem (ROWID integer primary key, UUID text, summary text, description text, start_date real, end_date real,
              all_day int, calendar_id int, location_id int, url text, has_recurrences int, status int, creation_date real, last_modified real,
              conference_url text, organizer_id int, self_attendee_id int, entity_type int);
            insert into Store values (1, 1, 'iCloud');
            insert into Calendar values (1, 'Work', 1);
            insert into Participant values (1, 1, 0, 0, 8, null, 'grace@example.test');
            insert into Participant values (2, 1, 2, 0, 7, null, 'alan@example.test');
            insert into Participant values (3, 1, 3, 0, 7, null, 'ada@example.test');
            insert into Recurrence values (1, 1, 2, 2);
            insert into CalendarItem values (1, 'EV-1', 'Standup', null, 700000000, 700001800, 0, 1, null, null, 1, 0, 699000000, 699000000, null, 1, 3, 2);
        """)
        con.commit()
        con.close()
        run_connector('calendar_events', self.home, self.corpus)
        ev = records(self.corpus, 'calendar')['EV-1']
        self.assertEqual((ev['meta']['organizer'], ev['meta']['my_reply'], ev['meta']['repeats']), ('grace@example.test', 'declined', 'every 2 weeks'))
        self.assertEqual(ev['participants'], ['alan@example.test', 'ada@example.test'], 'names only: the organizer apart')
        self.assertIn('Attendees: alan@example.test (accepted), ada@example.test (declined)', ev['text'])
        self.assertIn('You declined', ev['text'])
        self.assertIn('Repeats every 2 weeks', ev['text'])


if __name__ == '__main__':
    unittest.main()
