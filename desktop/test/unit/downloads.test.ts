import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';
import { dirSize, FolderWatcher, importDirFor, isCandidate, isPartial, moveInto, uniquePath } from '../../src/main/downloads.ts';

let tmp: string;
beforeEach(() => (tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-dl-'))));
afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

test('partial and temporary names are never candidates', () => {
  for (const n of ['takeout.zip.crdownload', 'package.zip.download', 'x.zip.part', 'Inbox.partial.mbox', '.A1B2C3D4E5.com.example.browser.zip', 'Unconfirmed 123.crdownload', 'a.zip.opdownload']) {
    assert.ok(isPartial(n), n);
    assert.ok(!isCandidate(n, false), n);
  }
  assert.ok(!isPartial('takeout-20250301T120000Z-1-001.zip'));
});

test('which downloads are worth identifying', () => {
  const yes: [string, boolean][] = [['takeout-1.zip', false], ['All Contacts.vcf', false], ['Inbox.mbox', true], ['Inbox.mbox', false], ['meeting.vtt', false],
    ['Timeline.json', false], ['location-history.json', false], ['takeout-20250301T120000Z-1-001', true], ['instagram-ada-2026', true], ['Export-1a2b3c4d', true],
    ['Complete_LinkedInDataExport_03-01-2025.zip.zip', false]];
  const no: [string, boolean][] = [['report.pdf', false], ['photo.jpg', false], ['random folder', true], ['data.json', false], ['node_modules', true],
    ['Homecoming Library 2026-10-15.zip', false]]; // Export Your Library's own .zip, saved in Downloads
  for (const [n, d] of yes) assert.ok(isCandidate(n, d), n);
  for (const [n, d] of no) assert.ok(!isCandidate(n, d), n);
});

test('where each export goes', () => {
  assert.equal(importDirFor('google_takeout', 'google_takeout', { export_id: '20250301', name: 'x' }), 'takeout-20250301');
  assert.equal(importDirFor('google_photos_drive', 'google_photos_drive', { export_id: null, name: 'x' }), 'takeout');
  assert.equal(importDirFor('mailbox', 'other_mail', { name: 'Inbox.mbox' }, 'Work Mail'), 'work_mail');
  assert.equal(importDirFor('mailbox', 'other_mail', { name: 'Inbox.mbox' }), 'other_mail');
  assert.equal(importDirFor('discord', 'discord', { name: 'package.zip' }), 'discord');
  assert.equal(importDirFor('iphone_vcard', 'iphone_vcard', { name: 'a.vcf' }), 'iphone');
  assert.equal(importDirFor('claude_ai', 'claude_ai', { name: 'a.zip' }), 'claude');
});

test('uniquePath keeps compound extensions', () => {
  const taken = new Set(['/d/a.zip', '/d/a (2).zip', '/d/b.zip.zip', '/d/Inbox.mbox']);
  const exists = (p: string) => taken.has(p);
  assert.equal(uniquePath('/d/new.zip', exists), '/d/new.zip');
  assert.equal(uniquePath('/d/a.zip', exists), '/d/a (3).zip');
  assert.equal(uniquePath('/d/b.zip.zip', exists), '/d/b (2).zip.zip');
  assert.equal(uniquePath('/d/Inbox.mbox', exists), '/d/Inbox (2).mbox');
});

test('moveInto moves files and folders without overwriting', async () => {
  const src = path.join(tmp, 'Downloads');
  fs.mkdirSync(src);
  fs.writeFileSync(path.join(src, 'package.zip'), 'one');
  fs.mkdirSync(path.join(src, 'Inbox.mbox'));
  fs.writeFileSync(path.join(src, 'Inbox.mbox', 'mbox'), 'mail');
  const dest = path.join(tmp, 'corpus/imports/discord');
  const { dest: a, copied } = await moveInto(path.join(src, 'package.zip'), dest);
  assert.equal(a, path.join(dest, 'package.zip'));
  assert.equal(copied, false);
  assert.equal(fs.readFileSync(a, 'utf8'), 'one');
  assert.ok(!fs.existsSync(path.join(src, 'package.zip')));
  fs.writeFileSync(path.join(src, 'package.zip'), 'two');
  const { dest: b } = await moveInto(path.join(src, 'package.zip'), dest);
  assert.equal(path.basename(b), 'package (2).zip');
  assert.equal(fs.readFileSync(a, 'utf8'), 'one', 'the first copy is untouched');
  const { dest: m } = await moveInto(path.join(src, 'Inbox.mbox'), path.join(tmp, 'corpus/imports/hotmail'));
  assert.equal(fs.readFileSync(path.join(m, 'mbox'), 'utf8'), 'mail');
  await assert.rejects(moveInto(path.join(src, 'missing.zip'), dest));
});

test('from another volume, the original stays put', async () => {
  const ext = path.join(tmp, 'External');
  fs.mkdirSync(path.join(ext, 'Takeout parts'), { recursive: true });
  fs.writeFileSync(path.join(ext, 'takeout-1.zip'), 'big');
  fs.writeFileSync(path.join(ext, 'Takeout parts', 'a'), '1');
  const exdev = async () => { throw Object.assign(new Error('cross-device link'), { code: 'EXDEV' }); };
  const r = await moveInto(path.join(ext, 'takeout-1.zip'), path.join(tmp, 'corpus/imports/takeout'), exdev);
  assert.equal(r.copied, true);
  assert.equal(fs.readFileSync(r.dest, 'utf8'), 'big');
  assert.ok(fs.existsSync(path.join(ext, 'takeout-1.zip')), 'original kept');
  const d = await moveInto(path.join(ext, 'Takeout parts'), path.join(tmp, 'corpus/imports/takeout'), exdev);
  assert.equal(fs.readFileSync(path.join(d.dest, 'a'), 'utf8'), '1');
  const other = async () => { throw Object.assign(new Error('nope'), { code: 'EACCES' }); };
  await assert.rejects(moveInto(path.join(ext, 'takeout-1.zip'), path.join(tmp, 'x'), other), /nope/);
});

test('the watcher reports a file once its size settles, and only once', () => {
  const got: [string, number][] = [];
  const w = new FolderWatcher(tmp, (p, size) => got.push([p, size]), 1000, 1000);
  const f = path.join(tmp, 'package.zip');
  fs.writeFileSync(f, 'abc');
  fs.writeFileSync(path.join(tmp, 'notes.pdf'), 'x');
  fs.writeFileSync(path.join(tmp, 'takeout.zip.crdownload'), 'partial');
  let t = 1_000_000;
  w.scan(t);
  assert.equal(got.length, 0, 'first sighting');
  w.scan((t += 500));
  assert.equal(got.length, 0, 'not settled yet');
  fs.appendFileSync(f, 'def'); // still growing
  w.scan((t += 1500));
  assert.equal(got.length, 0, 'grew, so the clock restarts');
  w.scan((t += 1500));
  assert.deepEqual(got, [[f, 6]]);
  w.scan((t += 5000));
  assert.equal(got.length, 1, 'reported once');
  fs.rmSync(f);
  w.scan((t += 10));
  fs.writeFileSync(f, 'again');
  w.scan((t += 10));
  w.scan((t += 2000));
  assert.equal(got.length, 2, 'a new file under the same name counts again');
});

test('the watcher also takes what the app says is wanted, in any format, once finished', () => {
  const got: string[] = [];
  const wanted = (n: string) => n.toLowerCase().includes('goodreads');
  const w = new FolderWatcher(tmp, (p) => got.push(path.basename(p)), 0, 1000, wanted);
  for (const n of ['goodreads_library_export.csv', 'goodreads_library_export (1).csv.crdownload', 'library_export.csv']) fs.writeFileSync(path.join(tmp, n), 'x');
  w.scan(1);
  w.scan(2);
  assert.deepEqual(got, ['goodreads_library_export.csv'], 'not a half-downloaded one, nor one the app has no reason to want');
});

test('with Watch Downloads off, the watcher waits: what landed meanwhile is reported once it is on again', () => {
  const got: string[] = [];
  let on = false;
  const w = new FolderWatcher(tmp, (p) => got.push(path.basename(p)), 0, 1000, () => false, () => on);
  fs.writeFileSync(path.join(tmp, 'package.zip'), 'x');
  w.scan(1);
  w.scan(2);
  w.scan(3);
  assert.deepEqual(got, [], 'off: nothing reported');
  on = true;
  w.scan(4);
  assert.deepEqual(got, ['package.zip'], 'on: the file that was waiting');
  w.scan(5);
  assert.deepEqual(got, ['package.zip'], 'and only once');
});

test('the watcher sizes folders and survives a missing directory', () => {
  const box = path.join(tmp, 'Inbox.mbox');
  fs.mkdirSync(box);
  fs.writeFileSync(path.join(box, 'mbox'), '12345');
  fs.mkdirSync(path.join(box, 'sub'));
  fs.writeFileSync(path.join(box, 'sub', 'toc'), '12');
  assert.equal(dirSize(box), 7);
  const got: number[] = [];
  const w = new FolderWatcher(tmp, (_p, size) => got.push(size), 0, 1000);
  w.scan(1);
  w.scan(2);
  assert.deepEqual(got, [7]);
  new FolderWatcher(path.join(tmp, 'nope'), () => assert.fail('nothing to report')).scan();
});
