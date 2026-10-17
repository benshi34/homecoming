// Export Your Library: from Settings (and the app menu), what goes in with its size, the save dialog's place (here
// UMP_EXPORT_TO), progress, Stop leaving nothing, a whole .zip at the end with Show in Finder, and records alone.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, until } from './harness.ts';

const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
let sb: Sandbox;
let run: Running;
let drive: string;
let dest: string;

// A small library: a database, records, a photo, a download, something read from this Mac, and what isn't the
// library's (research beside it, the decrypted iPhone backup linked from elsewhere).
function fill(corpus: string, root: string) {
  execFileSync(PY, ['-c', `
import os, sqlite3, sys
from pathlib import Path
c, root = Path(sys.argv[1]), Path(sys.argv[2])
for d in ['normalized', 'stream', 'media/instagram', 'imports/x', 'raw/notes', 'training']:
    (c / d).mkdir(parents=True, exist_ok=True)
(c / 'normalized' / 'imessage.jsonl').write_text('{"text": "hi"}\\n' * 5000)
(c / 'stream' / '2026-10.jsonl').write_text('{"what": "a walk"}\\n')
(c / 'media' / 'instagram' / 'photo.jpg').write_bytes(os.urandom(200_000))
(c / 'imports' / 'x' / 'twitter-2026.zip').write_bytes(os.urandom(100_000))
(c / 'raw' / 'notes' / 'NoteStore.sqlite').write_bytes(b'notes' * 1000)
(c / 'training' / 'episodes.jsonl').write_text('{}\\n')
phone = root / 'elsewhere' / 'iphone'
phone.mkdir(parents=True)
(phone / 'sms.db').write_bytes(b'secret')
(c / 'raw' / 'iphone').symlink_to(phone)
(c / 'manifest.json').write_text('{"sources": {}}')
con = sqlite3.connect(c / 'corpus.db')
con.execute('CREATE TABLE records (id INTEGER PRIMARY KEY, text TEXT)')
con.executemany('INSERT INTO records (text) VALUES (?)', [(f'message {i}',) for i in range(2000)])
con.commit()
`, corpus, root]);
}

const zipNames = (f: string): string[] => JSON.parse(execFileSync(PY, ['-c', 'import json, sys, zipfile; print(json.dumps(zipfile.ZipFile(sys.argv[1]).namelist()))', f]).toString());

before(async () => {
  sb = sandbox({ identity: true });
  fill(sb.corpus, sb.root);
  drive = path.join(sb.root, 'Backup Drive');
  fs.mkdirSync(drive);
  dest = path.join(drive, 'Homecoming Library 2026-10-15.zip');
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_EXPORT_TO: dest }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

async function openFromSettings() {
  const p = run.page;
  await p.locator('button[aria-label=Settings]').first().click();
  const settings = p.locator('[data-testid=settings]');
  await settings.waitFor();
  await settings.locator('button[data-action=settings-export]').click();
  await settings.waitFor({ state: 'detached' });
  const sheet = p.locator('[data-testid=export]');
  await sheet.waitFor();
  await sheet.locator('[data-testid=export-estimate]', { hasText: /About .* as a \.zip/ }).waitFor();
  return sheet;
}

test('Stop part-way: nothing is left behind, and it can be tried again', async () => {
  const big = path.join(sb.corpus, 'media', 'instagram', 'clip.bin');
  execFileSync(PY, ['-c', 'import os, sys; open(sys.argv[1], "wb").write(os.urandom(250 << 20))', big]); // slow enough to stop
  const p = run.page;
  const sheet = await openFromSettings();
  assert.match(await sheet.locator('[data-testid=export-part-media]').innerText(), /Photos and attachments[\s\S]*\d+ MB/);
  await sheet.locator('button[data-action=export-start]').click();
  await until(p, 'going', (x) => x.libraryExport?.state === 'running' && x.libraryExport.done > 0, 30_000);
  await sheet.locator('[data-testid=export-status]', { hasText: / of / }).waitFor();
  await shot(p, 'library-export-going');
  await sheet.locator('button[data-action=export-stop]').click();
  await until(p, 'stopped', (x) => x.libraryExport?.state === 'stopped', 30_000);
  await sheet.locator('[data-testid=export-failed]', { hasText: 'Stopped. Nothing was saved.' }).waitFor();
  assert.deepEqual(fs.readdirSync(drive), [], 'neither the zip nor its temporary file');
  await sheet.locator('button[data-action=export-again]').click();
  await sheet.locator('button[data-action=export-start]').waitFor();
  fs.rmSync(big);
  await p.keyboard.press('Escape');
  await sheet.waitFor({ state: 'detached' });
});

test('Everything, in one .zip where you said: the library, without what isn\'t its own; Show in Finder', async () => {
  const p = run.page;
  // From the app menu this time.
  await run.app.evaluate(({ Menu }) => Menu.getApplicationMenu()?.items[0].submenu?.items.find((i) => i.label === 'Export Your Library…')?.click());
  const sheet = p.locator('[data-testid=export]');
  await sheet.waitFor();
  await sheet.locator('[data-testid=export-estimate]', { hasText: /About .* as a \.zip/ }).waitFor();
  await shot(p, 'library-export-choose');
  await sheet.locator('button[data-action=export-start]').click();
  const s = await until(p, 'done', (x) => x.libraryExport?.state === 'done', 60_000);
  assert.equal(s.libraryExport!.path, dest);
  await sheet.locator('[data-testid=export-done]', { hasText: /Homecoming Library 2026-10-15\.zip, .* in Backup Drive/ }).waitFor();
  await shot(p, 'library-export-done');
  const names = zipNames(dest).map((n) => n.replace(/^Homecoming Library 2026-10-15\//, ''));
  for (const want of ['corpus.db', 'manifest.json', 'identity.json', 'normalized/imessage.jsonl', 'stream/2026-10.jsonl', 'media/instagram/photo.jpg',
    'imports/x/twitter-2026.zip', 'raw/notes/NoteStore.sqlite', 'README.txt']) assert.ok(names.includes(want), want);
  assert.deepEqual(names.filter((n) => n.startsWith('training') || n.startsWith('raw/iphone')), []);
  assert.match(await p.locator('[data-testid=toasts]').innerText(), /Your library is saved: Homecoming Library 2026-10-15\.zip/);
  await sheet.locator('button[data-action=export-reveal]').click();
  const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');
  for (let i = 0; i < 50 && !opened().includes(`finder: ${dest}`); i++) await p.waitForTimeout(100);
  assert.ok(opened().includes(`finder: ${dest}`), 'shown in Finder');
  await sheet.locator('button[data-action=export-done]').click();
  await sheet.waitFor({ state: 'detached' });
  await until(p, 'put away', (x) => x.libraryExport === null);
});

test('Records alone: photos and downloads left out, back and forth', async () => {
  const p = run.page;
  fs.rmSync(dest);
  const sheet = await openFromSettings();
  const est = async () => sheet.locator('[data-testid=export-estimate]').innerText();
  const all = await est();
  await sheet.locator('[data-testid=export-toggle-media]').click();
  await sheet.locator('[data-testid=export-toggle-originals]').click();
  const alone = await est();
  assert.notEqual(alone, all, 'the estimate follows what goes in');
  await sheet.locator('[data-testid=export-toggle-media]').click();
  assert.notEqual(await est(), alone);
  await sheet.locator('[data-testid=export-toggle-media]').click();
  assert.equal(await est(), alone, 'and back');
  await sheet.locator('button[data-action=export-start]').click();
  await until(p, 'done', (x) => x.libraryExport?.state === 'done', 60_000);
  const names = zipNames(dest);
  assert.ok(names.some((n) => n.endsWith('/corpus.db')));
  assert.deepEqual(names.filter((n) => /\/(media|imports|raw)\//.test(n)), []);
  await sheet.locator('button[data-action=export-done]').click();
});
