"""Who's one person (explore.py identities), on small made-up libraries: one person across their numbers, apps, calls
and photos; never two people because they share a name, or a first name, or Instagram's "Instagram User". And
the numbers and dates around it: a number abroad by its last digits only when that's one contact's, and times from
1900 on, a clock's first second left out. Each case runs in a process of its own, with an empty home and library."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]

PRELUDE = '''
import collections, json, os, pathlib, sqlite3, sys
from unittest.mock import patch
root = pathlib.Path(os.environ['UMP_REPO'])
sys.path[:0] = [str(root/'desktop/py'), str(root/'connectors')]
import explore as e
class Progress:
    def step(self, *args): pass
    def tick(self, *args): pass
con = sqlite3.connect(':memory:')
con.execute('create table records(source,id,kind,ts,ts_end,author,is_me,thread,thread_name,participants,title,text,url,meta)')
n = iter(range(10**6))
def add(**row):
    row.setdefault('id', str(next(n)))
    con.execute('insert into records ('+','.join(row)+') values ('+','.join('?' for _ in row)+')', tuple(row.values()))
def msg(source, thread, name, k=1, ts='2024-03-0{}T12:00:00Z', meta=None, participants=None):
    for i in range(k):
        add(source=source, kind='message', ts=ts.format(1 + i % 9), is_me='0' if i % 2 else '1', thread=thread, thread_name=name,
            participants=participants, meta=json.dumps(meta or {}))
def people():
    return {p['name'] + ('' if p['key'] == e.key(p['name']) else ' @' + p['key']): (p['messages'], p['calls'], p['photos'], dict(p['apps']))
            for p in e._people(con, set(), Progress())['people']}
'''


class PeopleIdentity(unittest.TestCase):
    def run_case(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'HOME': tmp, 'CORPUS_DIR': str(Path(tmp) / 'Homecoming'), 'UMP_REPO': str(REPO), 'UMP_TZ': 'UTC',
                   'UMP_EXPLORE_CACHE': str(Path(tmp) / 'cache')}
            p = subprocess.run([sys.executable, '-c', PRELUDE + body], env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)

    def test_one_person_across_numbers_apps_calls_and_photos(self):
        out = self.run_case('''
msg('imessage', 'iMessage;-;+14155550142', 'Maya Chen', 4)
msg('imessage', 'iMessage;-;maya@example.com', 'Maya Chen', 2)
msg('instagram', 'ig-maya', 'Maya Chen', 3)
msg('messenger', 'fb-maya', 'Maya Chen', 1)
add(source='calls', kind='call', ts='2024-03-02T10:00:00Z', thread='+14155550142', thread_name='Maya Chen', meta='{"seconds": 600}')
add(source='photos', kind='photo', ts='2024-03-03T10:00:00Z', text='Photo\\nPeople: Maya Chen', meta='{}')
print(json.dumps(people()))
''')
        self.assertEqual(out, {'Maya Chen': [10, 1, 1, {'imessage': 6, 'instagram': 3, 'messenger': 1}]})

    def test_instagram_user_and_same_names_in_one_app_are_different_people(self):
        out = self.run_case('''
for i in range(3): msg('instagram', f'deleted-{i}', 'Instagram User', 2)    # three deleted accounts, as Instagram shows them
msg('instagram', 'ig-oren-1', 'Oren Halvorsen', 2); msg('instagram', 'ig-oren-2', 'Oren Halvorsen', 1)   # two accounts, one name
msg('imessage', 'iMessage;-;+14155550199', 'Oren Halvorsen', 5)                     # and the Oren Halvorsen in your Contacts
print(json.dumps(sorted(people().items())))
''')
        self.assertEqual([(k.split(' @')[0], v[0], list(v[3])) for k, v in out],
                         [('Instagram User', 2, ['instagram'])] * 3 + [('Oren Halvorsen', 5, ['imessage']), ('Oren Halvorsen', 2, ['instagram']), ('Oren Halvorsen', 1, ['instagram'])],
                         "none of them merged: which Oren Halvorsen on Instagram is the one in your Contacts is anyone's guess")

    def test_a_first_name_joins_only_your_contact_by_that_name(self):
        out = self.run_case('''
msg('imessage', 'iMessage;-;+14155550111', 'Alex', 3)   # Alex, as your Contacts call them
msg('instagram', 'ig-alex', 'Alex', 2)                     # the one Alex on Instagram: them
msg('instagram', 'ig-jo', 'Jo', 1); msg('messenger', 'fb-jo', 'Jo', 1)   # a Jo in two apps, in neither your Contacts: two people
print(json.dumps(sorted((k.split(' @')[0], v[0]) for k, v in people().items())))
''')
        self.assertEqual(out, [['Alex', 5], ['Jo', 1], ['Jo', 1]])

    def test_initials_and_an_explicit_identity_still_join(self):
        out = self.run_case('''
msg('imessage', 'iMessage;-;+14155550123', 'Ada L', 3)
msg('instagram', 'ig-ada', 'Ada Lovelace', 2)
msg('discord', 'dm-1', 'Direct Message with charles', 2, participants='charles', meta={'person_id': 'babbage', 'person_name': 'Charles Babbage'})
msg('imessage', 'iMessage;-;+14155550124', 'Charles B.', 1, meta={'person_id': 'babbage', 'person_name': 'Charles Babbage'})
print(json.dumps(sorted((k.split(' @')[0], v[0]) for k, v in people().items())))
''')
        self.assertEqual(out, [['Ada Lovelace', 5], ['Charles Babbage', 3]])

    def test_on_this_day_trips_and_firsts_see_the_same_people(self):
        out = self.run_case('''
for d in range(1, 8):
    msg('imessage', 'iMessage;-;+14155550142', 'Maya Chen', 2, ts=f'2024-03-0{d}T12:00:00Z')
    msg('instagram', 'ig-maya', 'Maya Chen', 2, ts=f'2024-03-0{d}T13:00:00Z')
    msg('instagram', 'ig-u1', 'Instagram User', 2, ts=f'2024-03-0{d}T14:00:00Z')
    msg('instagram', 'ig-u2', 'Instagram User', 2, ts=f'2024-03-0{d}T15:00:00Z')
art = e._people(con, set(), Progress())
cached = lambda name, fn, *a: art if name == 'people' else fn(*a)
with patch.object(e, 'cached', cached), patch.object(e, 'connect', return_value=con), patch.object(e, 'me_names', return_value=set()):
    day = e.on_this_day('03-03')
    trip = e.trip_people(con, '2024-03-01', '2024-03-08')
    firsts = e._firsts(con, set(), Progress())
people_that_day = sorted((t['name'], t['messages']) for y in day['years'] for t in (y.get('messages') or {}).get('threads', []) if not t.get('group'))
print(json.dumps([people_that_day, sorted((p['name'], p['messages']) for p in trip), sorted(i['what'] for i in firsts['items'] if i['kind'] == 'person')]))
''')
        that_day, trip, firsts = out
        self.assertEqual(that_day, [['Instagram User', 2], ['Instagram User', 2], ['Maya Chen', 4]], 'Maya once, across both apps; the two accounts apart')
        self.assertEqual(trip, [['Instagram User', 14], ['Instagram User', 14], ['Maya Chen', 28]])
        self.assertEqual(firsts, ['Maya Chen'], 'one first for Maya, not one per app (the accounts have fewer than 20 messages: no first)')

    def test_a_number_abroad_by_its_last_digits_only_when_one_contact_has_them(self):
        out = self.run_case('''
from contacts import Resolver
with patch('contacts.load_phone_contacts', return_value=[]), patch('contacts.imported_vcards', return_value=[]), patch('contacts.load_contacts', return_value=[]):
    r = Resolver()
r.add('+44 1234 567890', 'UK Contact'); r.add('+49 1234 567890', 'German Contact')   # two numbers that end alike
r.add('020 7946 0958', 'Saved Without Code'); r.add('+44 20 7946 0958', 'Saved Without Code')
r.add('(415) 555-0142', 'Alan Turing')
print(json.dumps([r.name('+49 1234 567890'), r.name('+33 1234 567890'), r.name('+1 415 555 0142'), r.name('+61 4155 550142')]))
''')
        self.assertEqual(out, ['German Contact', None, 'Alan Turing', 'Alan Turing'],
                         'exactly; by the last digits when only one number ends so; no one when two do')

    def test_dates_from_1900_and_a_clocks_first_second_left_out(self):
        out = self.run_case('''
import stream
for i in range(20): add(source='photos', kind='photo', ts='1985-05-05T10:00:00Z', meta='{}')   # scanned from an album
for ts in ('1900-01-01T00:00:00Z', '1601-01-01T00:00:00Z', '0001-01-01T00:00:00Z', '1970-01-01T00:00:00Z', '2001-01-01T00:00:00Z'):
    for i in range(20): add(source='photos', kind='photo', ts=ts, meta='{}')
for i in range(25): add(source='health', kind='health_day', ts='1970-01-01', meta='{"steps": 99999}')   # a day read from 0
with patch.object(e, 'cached', return_value={'people': []}):
    firsts = e._firsts(con, set(), Progress())
print(json.dumps([e.years_present(con), [i['ts'][:4] for i in firsts['items'] if i['what'] == 'Your first photo'], [m['month'] for m in stream.months(con)],
                  [e.parse(t) is not None for t in ('1960-01-15T12:00:00Z', '1900-01-01T00:00:00Z', '1899-12-31T12:00:00Z', '1970-01-01T00:00:00Z')]]))
''')
        self.assertEqual(out, [['1985'], ['1985'], ['1985-05'], [True, False, False, False]])


if __name__ == '__main__':
    unittest.main()
