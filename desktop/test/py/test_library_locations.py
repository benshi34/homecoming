"""Libraries that aren't the one this was built on: packaged and renamed libraries, older file references, Photos
libraries found elsewhere, Git worktrees, exported WhatsApp chats.

Each process receives an empty synthetic home and library; these tests never read the developer's data.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]


class LibraryLocations(unittest.TestCase):
    def run_case(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'HOME': tmp, 'CORPUS_DIR': str(Path(tmp) / 'Homecoming'),
                   'UMP_REPO': str(REPO), 'UMP_TZ': 'UTC', 'UMP_EXPLORE_CACHE': str(Path(tmp) / 'cache')}
            env.pop('UMP_PHOTOS_LIBRARY', None)
            script = '''
import collections, io, json, os, pathlib, plistlib, sqlite3, sys
from unittest.mock import patch
root = pathlib.Path(os.environ['UMP_REPO'])
sys.path[:0] = [str(root/'desktop/py'), str(root/'connectors')]
import explore as e
import ask_tools as a
from common import CORPUS
CORPUS.mkdir(parents=True)
class Progress:
    def step(self, *args): pass
    def tick(self, *args): pass
con = sqlite3.connect(':memory:')
con.execute('create table records(source,id,kind,ts,ts_end,author,is_me,thread,thread_name,participants,title,text,url,meta)')
def add(**row):
    con.execute('insert into records ('+','.join(row)+') values ('+','.join('?' for _ in row)+')', tuple(row.values()))
def msg(source='imessage', thread='+12025550101', name='Alex Kim', meta=None):
    add(source=source, kind='message', ts='2020-01-01T12:00:00Z', is_me='0', thread=thread, thread_name=name, meta=json.dumps(meta or {}))
def people(): return e._people(con, set(), Progress())['people']
''' + body
            p = subprocess.run([sys.executable, '-c', script], env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)

    def test_media_roundtrip_for_packaged_and_legacy_paths(self):
        out = self.run_case('''
import imports
file = CORPUS/'media/photo.jpg'
imports.MEDIA = CORPUS/'media'
class Entry:
    origin = "export.zip"
    path = "photo.jpg"
    size = 5
    def open(self): return io.BytesIO(b'image')
stored = imports.save_media(Entry(), file, None)
results = []
for ref in (stored, 'Homecoming/'+stored, 'corpus/'+stored):
    with patch.object(a, '_record', return_value={'rowid':1, 'meta':json.dumps({'files':[ref]})}):
        path, err = a._record_file({'rowid':1})
    results.append([path == file.resolve(), err, e.preview_file('whatsapp_export','1',[ref]) == file])
print(json.dumps([stored, results]))
''')
        self.assertEqual(out, ['media/photo.jpg', [[True, None, True]] * 3])

    def test_library_named_media_prefers_its_own_relative_file(self):
        out = self.run_case('''from library_paths import record_path
library=pathlib.Path.home()/'media'; f=library/'media/photo.jpg'
f.parent.mkdir(parents=True); f.write_bytes(b'image')
print(json.dumps(record_path('media/photo.jpg',library)==f))
''')
        self.assertTrue(out)

    def test_thumbnails_follow_record_identity_and_image_changes(self):
        out = self.run_case('''
import base64
from types import SimpleNamespace
image = CORPUS/'media/photo.jpg'; image.parent.mkdir(); image.write_bytes(b'first image')
db = CORPUS/'corpus.db'
with sqlite3.connect(db) as records:
    records.execute('create table records(source,id,meta)')
    records.execute('insert into records values (?,?,?)', ('photos','original',json.dumps({'files':['Homecoming/media/photo.jpg']})))
calls = []
def convert(args, **kwargs):
    calls.append(args)
    pathlib.Path(args[-1]).write_bytes(pathlib.Path(args[-3]).read_bytes())
    return SimpleNamespace(returncode=0)
def thumb():
    return base64.b64decode(e.thumbs([1])['1'].split(',',1)[1]).decode()
with patch.object(e.subprocess, 'run', side_effect=convert):
    first=thumb(); again=thumb(); reused=len(calls)==1
    image.write_bytes(b'edited image')
    edited=thumb()
    # Model a legacy rebuild that assigned this row number to a different record, sharing the same original.
    with sqlite3.connect(db) as records:
        records.execute("update records set id='replacement'")
    replacement=thumb(); identity_checked=len(calls)==3
    with sqlite3.connect(db) as records:
        records.execute('delete from records')
    missing=e.thumbs([1])
print(json.dumps([first,again,reused,edited,replacement,identity_checked,missing]))
''')
        self.assertEqual(out, ['first image', 'first image', True, 'edited image', 'edited image', True, {}])

    def test_old_references_survive_renaming_the_library(self):
        out = self.run_case('''from library_paths import record_path
file=CORPUS/'media/photo.jpg'; file.parent.mkdir(); file.write_bytes(b'image')
ref='Homecoming/media/photo.jpg'; renamed=CORPUS.with_name('Memories'); CORPUS.rename(renamed)
print(json.dumps(record_path(ref,renamed)==renamed/'media/photo.jpg'))
''')
        self.assertTrue(out)

    def test_exported_whatsapp_direct_chat_is_in_people_but_group_is_not(self):
        out = self.run_case('''
msg(source='whatsapp_export',thread='Alex')
add(source='whatsapp_export',kind='message',ts='2020-01-01T12:00:00Z',thread='club',thread_name='club',participants='Alex,Blair,Casey')
print(json.dumps([(p['name'],p['messages']) for p in people()]))
''')
        self.assertEqual(out, [['Alex Kim', 1]])

    def test_git_owner_and_worktrees(self):
        out = self.run_case('''
import git_commits as g
with patch.object(g,'ME',{'usernames_l':{'ann'}}),patch.object(g,'is_me_name',return_value=False),patch.object(g,'is_me_email',return_value=False):
    owners=[g.mine('Joanne Example','joanne@example.test'),g.mine('Ann','ann@example.test'),g.mine('A','12345+ann@users.noreply.github.com'),g.mine('B','12345+joanne@users.noreply.github.com')]
r=pathlib.Path.home()/'Developer'; (r/'normal/.git').mkdir(parents=True); (r/'worktree').mkdir(); (r/'worktree/.git').write_text('gitdir: /tmp/example.git/worktrees/w')
g.ROOTS=[r]
print(json.dumps([owners,sorted(p.name for p in g.repos())]))
''')
        self.assertEqual(out, [[False, True, True, False], ['normal', 'worktree']])

    def test_renamed_and_external_photos_libraries_match_setup_probe(self):
        out = self.run_case('''
from library_paths import photos_libraries
home=pathlib.Path.home(); renamed=home/'Pictures/Family.photoslibrary'; external=home/'External Drive/Archive.photoslibrary'
for p in (renamed,external):
    (p/'database').mkdir(parents=True); (p/'database/Photos.sqlite').touch()
prefs=home/'Library/Containers/com.apple.photolibraryd/Data/Library/Preferences/com.apple.photolibraryd.plist'; prefs.parent.mkdir(parents=True)
prefs.write_bytes(plistlib.dumps({'SystemLibraryPath':str(external)}))
import bridge, photos
found=photos_libraries(home)
print(json.dumps([sorted(p.name for p in found),set(bridge.MAC_PATHS['photos'])=={p/'database/Photos.sqlite' for p in found},photos.LIBRARY in found]))
''')
        self.assertEqual(out, [['Archive.photoslibrary', 'Family.photoslibrary'], True, True])

    def test_photos_explicit_location(self):
        out = self.run_case('''
from library_paths import photos_libraries
p=pathlib.Path.home()/'Other/Chosen.photoslibrary'; os.environ['UMP_PHOTOS_LIBRARY']=str(p)
print(json.dumps(photos_libraries()==[p]))
''')
        self.assertTrue(out)


if __name__ == '__main__':
    unittest.main()
