"""Small synthetic fixtures for phone parsing, decryption, and iLEAPP normalization."""
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
import calls
import contacts
import health
import ileapp
import imessage
import iphone_backup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.keywrap import aes_key_wrap


class PhoneTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, value in [('NORM', self.root / 'normalized'), ('MANIFEST', self.root / 'manifest.json')]:
            p = patch.object(common, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(common, 'code_version', return_value='fixture')
        p.start()
        self.addCleanup(p.stop)
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def db(self, name='fixture.db'):
        con = sqlite3.connect(self.root / name)
        con.row_factory = sqlite3.Row
        self.addCleanup(con.close)
        return con

    def records(self, source):
        return [json.loads(line) for line in (common.NORM / f'{source}.jsonl').read_text().splitlines()]

    def test_encrypted_file_preserves_growth_beyond_manifest_size(self):
        key, class_key = b'k' * 32, b'c' * 32
        data = b'Synthetic contents grew while the backup was running.'
        pad = 16 - len(data) % 16
        enc = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
        encrypted = enc.update(data + bytes([pad]) * pad) + enc.finalize()
        file_id = 'ab' + '0' * 38
        (self.root / 'ab').mkdir()
        (self.root / 'ab' / file_id).write_bytes(encrypted)
        backup = iphone_backup.Backup.__new__(iphone_backup.Backup)
        backup.dir, backup.classes = self.root, {1: {'KEY': class_key}}
        target = self.root / 'decrypted' / 'sample'
        backup.extract(file_id, (1, aes_key_wrap(class_key, key)), 12, target)
        self.assertEqual(target.read_bytes(), data)
        self.assertFalse(target.with_name('sample.part').exists())

    def test_mirror_rejects_absolute_and_parent_paths(self):
        for path in ('/etc/passwd', '../outside', 'Library/../../outside'):
            self.assertFalse(iphone_backup.safe_rel(path))
        self.assertTrue(iphone_backup.safe_rel('Library/SMS/sms.db'))

    def test_calls_merge_phone_and_mac(self):
        cols = '(ZUNIQUE_ID, ZDATE, ZDURATION, ZADDRESS, ZNAME, ZORIGINATED, ZANSWERED, ZCALLTYPE, ZLOCATION)'
        phone, mac = self.db('phone.db'), self.db('mac.db')
        for con in (phone, mac):
            con.execute(f'create table ZCALLRECORD{cols}')
        phone.execute('insert into ZCALLRECORD values ("shared", 700000000, 60, "+15555550100", "Alex", 1, 1, 1, null)')
        mac.execute('insert into ZCALLRECORD values ("shared", 700000000, 60, "+15555550100", "Alex", 1, 1, 1, null)')
        # The two copies give the same call different ids: same number within 5 seconds is the same call.
        mac.execute('insert into ZCALLRECORD values ("mac-id", 700000002, 60, "(555) 555-0100", "Alex", 1, 1, 1, null)')
        mac.execute('insert into ZCALLRECORD values ("mac-only", 700003600, 0, "+15555550100", "Alex", 0, 0, 8, null)')
        names = types.SimpleNamespace(label=lambda x: x)
        written = {}
        with common.Writer('calls', 'fixture', parser='fixture', accumulate=False) as w:
            calls.add_calls(phone, names, w, 'iphone', written)
            calls.add_calls(mac, names, w, 'mac', written)
            self.assertEqual(w.notes['same_call_in_both_copies'], 1)
        rows = self.records('calls')
        self.assertEqual([r['id'] for r in rows], ['shared', 'mac-only'])
        self.assertEqual(rows[0]['meta']['copy'], 'iphone')
        self.assertEqual(rows[1]['meta']['direction'], 'missed')

    def test_imessage_merges_guids_and_supports_older_schema(self):
        def database(name, rows):
            con = self.db(name)
            con.executescript('''
                create table handle(id text);
                create table chat_handle_join(chat_id, handle_id);
                create table chat(guid, style, display_name, chat_identifier);
                create table chat_message_join(message_id, chat_id);
                create table attachment(transfer_name, mime_type, filename, total_bytes);
                create table message_attachment_join(message_id, attachment_id);
                create table message(guid, text, attributedBody, handle_id, is_from_me, date, service,
                  item_type, associated_message_type, associated_message_guid, thread_originator_guid,
                  is_audio_message, balloon_bundle_id);
                insert into handle values ('fixture@example.test');
                insert into chat values ('chat', 45, 'Alex', 'fixture@example.test');
                insert into chat_handle_join values (1,1);
            ''')
            for guid, text in rows:
                cur = con.execute('insert into message values (?,?,null,1,0,700000000,"iMessage",0,0,null,null,0,null)', (guid, text))
                con.execute('insert into chat_message_join values (?,1)', (cur.lastrowid,))
            con.commit()
            return self.root / name
        phone = database('phone.db', [('shared', 'phone copy')])
        mac = database('mac.db', [('shared', 'mac copy'), ('new', 'new message')])
        with patch.object(imessage, 'phone', return_value=phone), \
             patch.object(imessage, 'snapshot_sqlite', return_value=mac), \
             patch.object(imessage, 'Resolver', return_value=types.SimpleNamespace(label=lambda x: 'Alex')):
            imessage.main()
        rows = self.records('imessage')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['text'], 'phone copy')
        self.assertEqual(rows[1]['meta']['copy'], 'mac')

    def test_phone_contacts_map_multivalue_and_missing_birthday(self):
        con = self.db()
        con.executescript('''
          create table ABMultiValueLabel(value);
          create table ABMultiValueEntryKey(value);
          create table ABMultiValueEntry(parent_id, key, value);
          create table ABMultiValue(UID, record_id, property, label, value);
          create table ABPerson(guid, First, Middle, Last, Nickname, Organization, JobTitle, Department,
                               Birthday, CreationDate, ModificationDate, Note);
          insert into ABPerson values ('person', 'Alex', null, 'Example', null, 'Example Co', null, null,
                                       null, 700000000, 700000001, 'Synthetic contact');
          insert into ABMultiValueLabel values ('_$!<Mobile>!$_');
          insert into ABMultiValue values (1,1,3,1,'+15555550100');
        ''')
        con.commit()
        with patch.object(contacts, 'PHONE_AB', self.root / 'fixture.db'):
            rows = contacts.load_phone_contacts()
        self.assertEqual(rows[0]['name'], 'Alex Example')
        self.assertEqual(rows[0]['phones'], [('Mobile', '+15555550100')])
        self.assertIsNone(rows[0]['birthday'])

    def test_health_dedup_outliers_device_overlap_and_sleep(self):
        con = self.db()
        con.executescript('''
          create table samples(data_id, data_type, start_date, end_date);
          create table objects(data_id, provenance, type);
          create table data_provenances(tz_name, origin_product_type, source_id);
          create table quantity_samples(data_id, quantity);
          create table category_samples(data_id, value);
          insert into data_provenances values ('UTC','phone-a',1), ('UTC','phone-b',2);
        ''')
        for did, kind, quantity, category, provenance, duration in [
            (1,7,100,None,1,60), (2,7,100,None,1,60), (3,7,10000,None,1,60),
            (4,7,150,None,2,60), (5,63,None,3,1,3600), (6,63,None,3,1,3600)]:
            con.execute('insert into samples values (?,?,700000000,?)', (did,kind,700000000+duration))
            con.execute('insert into objects values (?,?,1)', (did, provenance))
            if quantity is not None:
                con.execute('insert into quantity_samples values (?,?)', (did,quantity))
            if category is not None:
                con.execute('insert into category_samples values (?,?)', (did,category))
        con.commit()
        with patch.object(health, 'DB', self.root / 'fixture.db'):
            health.main()  # an older database: no activity_caches table
        rows = self.records('health')
        self.assertEqual(next(r for r in rows if r['kind']=='health_day')['meta']['steps'], 150)
        self.assertEqual(next(r for r in rows if r['kind']=='sleep')['meta']['asleep_min'], 60)
        manifest = json.loads(common.MANIFEST.read_text())
        notes = manifest['health']['notes']
        self.assertEqual(notes['duplicates'], 2)
        self.assertEqual(notes['implausible'], 1)
        # Every live sample is kept too, apart from exact duplicates and impossible readings.
        samples = self.records('health_samples')
        self.assertEqual(sorted(r['meta']['type'] for r in samples), [7, 7, 63])
        self.assertEqual(manifest['health_samples']['notes'], {'duplicates': 2, 'implausible': 1, 'no_value': 0})
        self.assertTrue(next(r for r in samples if r['meta']['type'] == 63)['text'].startswith('Sleep: core'), 'stage 3 is core sleep')
        # Activity rings keep their numbers in activity_caches (some columns missing on some versions).
        con.executescript('''
          create table activity_caches(data_id, energy_burned, energy_burned_goal, brisk_minutes, steps);
          insert into samples values (7, 76, 700086400, 700086400);
          insert into objects values (7, 1, 1);
          insert into activity_caches values (7, 412, 500, 31, 9000);
        ''')
        con.commit()
        with patch.object(health, 'DB', self.root / 'fixture.db'):
            health.samples()
        ring = next(r for r in self.records('health_samples') if r['meta']['type'] == 76)
        self.assertEqual(ring['title'], 'Activity rings')
        self.assertTrue(ring['text'].startswith('Activity rings: move 412/500 kcal, exercise 31 min, 9000 steps'))

    def test_ileapp_retains_whatsapp_bursts_but_collapses_join_duplicates(self):
        con = self.db()
        con.execute('create table messages(conversation, direction, timestamp, message)')
        con.executemany('insert into messages values ("chat","out",1700000000,"[image]")', [(), ()])
        conv = {'conversationDiscriminatorColumn':'conversation', 'conversationLabelColumn':'conversation',
                'directionColumn':'direction', 'directionSentValue':'out', 'timeColumn':'timestamp', 'textColumn':'message'}
        for module, key, count in [('whatsApp','whatsAppMessages',2), ('Airbnb','airbnbMessages',1)]:
            artifact = {'name':'Messages', 'tablename':'messages', 'artifact_key':key,
                        'column_map':{}, 'object_columns':[{'name':'timestamp','type':'datetime'}],
                        'data_views':{'conversation':conv}}
            ileapp.write_module(module, [('Chats',artifact)], con, {}, 'fixture', {}, {})
            rows = self.records('phone_'+module.lower())
            self.assertEqual(len(rows), count)
            self.assertEqual(rows[0]['author'], 'me')
            self.assertEqual(rows[0]['thread'], 'chat')

    def test_wechat_group_sender_and_compressed_text(self):
        conv = ileapp.CONVERSATIONS['weChatMessages']
        row = {'type_as_stored':1, 'message':'wxid_test:\nHello', 'chat_partner':'group@chatroom'}
        self.assertEqual(ileapp.wechat_message(row, conv, {'wxid_test':'Alex'}), ('Alex','Hello'))
        row['message'] = b'\x28\xb5\x2f\xfdsynthetic'
        self.assertEqual(ileapp.wechat_message(row, conv, {})[1], '[text, compressed]')

    def load_artifact(self, name):
        # Exercise the custom parser itself without installing or invoking iLEAPP.
        helpers = types.ModuleType('scripts.ilapfuncs')
        helpers.artifact_processor = lambda fn: fn
        helpers.open_sqlite_db_readonly = lambda path: sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        from datetime import datetime, timezone
        helpers.convert_unix_ts_to_utc = lambda t: datetime.fromtimestamp(t, timezone.utc)
        path = Path(ileapp.CUSTOM) / (name + '.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'scripts':types.ModuleType('scripts'), 'scripts.ilapfuncs':helpers}):
            spec.loader.exec_module(module)
        return module

    def context(self, paths):
        return types.SimpleNamespace(get_files_found=lambda:paths, get_relative_path=lambda p:Path(p).name)

    def test_wallet_utf8_and_utf16_yield_one_row_per_pass(self):
        module = self.load_artifact('corpusWalletPasses')
        paths = []
        for n, encoding in enumerate(('utf-8-sig','utf-16')):
            path = self.root / f'{n}.pkpass' / 'pass.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'description':'Synthetic ticket', 'eventTicket':{
                'primaryFields':[{'label':'Event','value':'Example'}]}, 'barcode':{'message':'omitted'}}), encoding=encoding)
            paths.append(path)
        headers, rows, _ = module.corpusWalletPasses(self.context(paths))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][7], 'Event: Example')
        self.assertNotIn('omitted', repr(rows))

    def test_x_dm_parser_ignores_read_events_and_marks_outgoing(self):
        con = self.db('123-dmv2.db')
        con.executescript('''
          create table dm_user(id, screen_name, nickname);
          create table dm_conversation(conversation_id, custom_title);
          create table dm_entry(entry_id, conversation_id, timestamp, sender_id, sender_is_owner, plain_text,
                                has_attachment, attachment_types, message_status, entry_type);
          insert into dm_user values (123,'test_owner',null), (456,'test_other',null);
          insert into dm_conversation values ('123:456',null);
          insert into dm_entry values ('m1','123:456',1700000000,123,1,'Synthetic message',0,null,'sent','message');
          insert into dm_entry values ('r1','123:456',1700000001,456,0,null,0,null,'read','read');
        ''')
        con.commit()
        module = self.load_artifact('corpusXDirectMessages')
        _, rows, _ = module.corpusXDirectMessages(self.context([self.root / '123-dmv2.db']))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], 'test_other')
        self.assertEqual(rows[0][5], 'Outgoing')
        self.assertEqual(rows[0][7], 'Synthetic message')


if __name__ == '__main__':
    unittest.main()
