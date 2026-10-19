import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';
import { dirSize, FolderWatcher, importDirFor, isCandidate, isPartial, looksLikeExport, moveInto, uniquePath } from '../../src/main/downloads.ts';
import { mailSource } from '../../src/shared/status.ts';

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
    ['Complete_LinkedInDataExport_03-01-2025.zip.zip', false], ['takeout-20250301T120000Z-1-001.tgz', false], ['takeout-20250301T120000Z-1-001.tar.gz', false],
    // Unzipped by Safari: the folder at the top of the zip
    ['Takeout', true], ['Takeout 2', true], ['Spotify Account Data', true], ['Spotify Extended Streaming History', true]];
  const no: [string, boolean][] = [['report.pdf', false], ['photo.jpg', false], ['random folder', true], ['data.json', false], ['node_modules', true],
    ['Homecoming Library 2026-10-15.zip', false]]; // Export Your Library's own .zip, saved in Downloads
  for (const [n, d] of yes) assert.ok(isCandidate(n, d), n);
  for (const [n, d] of no) assert.ok(!isCandidate(n, d), n);
});

test('an unzipped export named after nothing in particular is known by what\'s at its top', () => {
  const make = (name: string, files: string[]) => {
    const d = path.join(tmp, name);
    for (const f of files) {
      fs.mkdirSync(path.dirname(path.join(d, f)), { recursive: true });
      fs.writeFileSync(path.join(d, f), '{}');
    }
    return d;
  };
  assert.ok(looksLikeExport(make('a1b2c3d4e5f6-2026-10-17-12-00-00', ['conversations.json', 'user.json'])), 'ChatGPT, or Claude.ai');
  assert.ok(looksLikeExport(make('Acme Slack export Oct 1 2025 - Oct 17 2026', ['users.json', 'channels.json', 'general/2026-10-01.json'])), 'Slack');
  assert.ok(looksLikeExport(make('archive', ['data/tweets.js', 'Your archive.html'])), 'X');
  assert.ok(!looksLikeExport(make('project', ['README.md', 'src/index.ts'])), 'any other folder');
  assert.ok(!looksLikeExport(path.join(tmp, 'gone')));
});

test('the watcher reports such a folder once it settles, and looks inside other folders only when they change', async () => {
  const got: string[] = [];
  const w = new FolderWatcher(tmp, (p) => got.push(path.basename(p)), 0, 1000);
  fs.mkdirSync(path.join(tmp, 'data-2026-10-17-batch-0000'));
  fs.writeFileSync(path.join(tmp, 'data-2026-10-17-batch-0000', 'conversations.json'), '[]');
  fs.mkdirSync(path.join(tmp, 'Holiday photos'));
  fs.writeFileSync(path.join(tmp, 'Holiday photos', 'a.jpg'), 'x');
  await w.scan(1);
  await w.scan(2);
  assert.deepEqual(got, ['data-2026-10-17-batch-0000']);
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

test("a mailbox never goes in another source's folder", () => {
  // Named Mail, its mail would replace what Mail on this Mac read; named Instagram, be mixed in with Instagram's messages.
  const box = (name: string) => importDirFor('mailbox', 'other_mail', { name: 'Inbox.mbox' }, name);
  for (const [name, dir] of [['Mail', 'mail_mail'], ['Instagram', 'instagram_mail'], ['Contacts', 'contacts_mail'], ['WhatsApp', 'whatsapp_mail'],
    ['Gmail', 'gmail_mail'], ['Takeout', 'takeout_mail'], ['phone_mail', 'phone_mail_mail'], ['Spotify files', 'spotify_files_mail'],
    ['Hotmail', 'hotmail'], ['Work', 'work'], ['Other mail', 'other_mail']]) assert.equal(box(name), dir, name);
  assert.equal(mailSource('Mail'), 'mail_mail', 'and its source is named the same way');
  assert.equal(mailSource(), 'other_mail');
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

test('the watcher reports a file once its size settles, and only once', async () => {
  const got: [string, number][] = [];
  const w = new FolderWatcher(tmp, (p, size) => got.push([p, size]), 1000, 1000);
  const f = path.join(tmp, 'package.zip');
  fs.writeFileSync(f, 'abc');
  fs.writeFileSync(path.join(tmp, 'notes.pdf'), 'x');
  fs.writeFileSync(path.join(tmp, 'takeout.zip.crdownload'), 'partial');
  let t = 1_000_000;
  await w.scan(t);
  assert.equal(got.length, 0, 'first sighting');
  await w.scan((t += 500));
  assert.equal(got.length, 0, 'not settled yet');
  fs.appendFileSync(f, 'def'); // still growing
  await w.scan((t += 1500));
  assert.equal(got.length, 0, 'grew, so the clock restarts');
  await w.scan((t += 1500));
  assert.deepEqual(got, [[f, 6]]);
  await w.scan((t += 5000));
  assert.equal(got.length, 1, 'reported once');
  fs.rmSync(f);
  await w.scan((t += 10));
  fs.writeFileSync(f, 'again');
  await w.scan((t += 10));
  await w.scan((t += 2000));
  assert.equal(got.length, 2, 'a new file under the same name counts again');
});

test('the watcher waits for a download Firefox is still writing, and looks again at a file that changed after it was reported', async () => {
  const got: [string, number][] = [];
  const w = new FolderWatcher(tmp, (p, size) => got.push([path.basename(p), size]), 0, 1000);
  // Firefox: an empty file under the final name, the data in <name>.part, moved over it at the end
  fs.writeFileSync(path.join(tmp, 'takeout-1.zip'), '');
  fs.writeFileSync(path.join(tmp, 'takeout-1.zip.part'), 'half');
  fs.writeFileSync(path.join(tmp, 'package.zip'), '');
  await w.scan(1);
  await w.scan(2);
  assert.deepEqual(got, [], 'not while it is written, nor an empty file');
  fs.renameSync(path.join(tmp, 'takeout-1.zip.part'), path.join(tmp, 'takeout-1.zip'));
  await w.scan(3);
  await w.scan(4);
  assert.deepEqual(got, [['takeout-1.zip', 4]]);
  fs.writeFileSync(path.join(tmp, 'takeout-1.zip'), 'whole file');
  await w.scan(5);
  await w.scan(6);
  assert.deepEqual(got, [['takeout-1.zip', 4], ['takeout-1.zip', 10]], 'changed after it was reported: reported again, once settled');
  await w.scan(7);
  assert.equal(got.length, 2);
  assert.ok(isCandidate('Outlook for Mac Archive.olm', false), "Outlook for Mac's export is mail");
});

test('the watcher also takes what the app says is wanted, in any format, once finished', async () => {
  const got: string[] = [];
  const wanted = (n: string) => n.toLowerCase().includes('goodreads');
  const w = new FolderWatcher(tmp, (p) => got.push(path.basename(p)), 0, 1000, wanted);
  for (const n of ['goodreads_library_export.csv', 'goodreads_library_export (1).csv.crdownload', 'library_export.csv']) fs.writeFileSync(path.join(tmp, n), 'x');
  await w.scan(1);
  await w.scan(2);
  assert.deepEqual(got, ['goodreads_library_export.csv'], 'not a half-downloaded one, nor one the app has no reason to want');
});

test('with Watch Downloads off, the watcher waits: what landed meanwhile is reported once it is on again', async () => {
  const got: string[] = [];
  let on = false;
  const w = new FolderWatcher(tmp, (p) => got.push(path.basename(p)), 0, 1000, () => false, () => on);
  fs.writeFileSync(path.join(tmp, 'package.zip'), 'x');
  await w.scan(1);
  await w.scan(2);
  await w.scan(3);
  assert.deepEqual(got, [], 'off: nothing reported');
  on = true;
  await w.scan(4);
  assert.deepEqual(got, ['package.zip'], 'on: the file that was waiting');
  await w.scan(5);
  assert.deepEqual(got, ['package.zip'], 'and only once');
});

test('the watcher sizes folders and survives a missing directory', async () => {
  const box = path.join(tmp, 'Inbox.mbox');
  fs.mkdirSync(box);
  fs.writeFileSync(path.join(box, 'mbox'), '12345');
  fs.mkdirSync(path.join(box, 'sub'));
  fs.writeFileSync(path.join(box, 'sub', 'toc'), '12');
  assert.equal(await dirSize(box), 7);
  const got: number[] = [];
  const w = new FolderWatcher(tmp, (_p, size) => got.push(size), 0, 1000);
  await w.scan(1);
  await w.scan(2);
  assert.deepEqual(got, [7]);
  await new FolderWatcher(path.join(tmp, 'nope'), () => assert.fail('nothing to report')).scan();
});

test('a folder already reported is not sized again, and one scan runs at a time', async () => {
  const box = path.join(tmp, 'Inbox.mbox');
  fs.mkdirSync(box);
  fs.writeFileSync(path.join(box, 'mbox'), '12345');
  const got: number[] = [];
  const sized: string[] = [];
  const w = new FolderWatcher(tmp, (_p, size) => got.push(size), 0, 1000);
  w.sizeOf = (d) => {
    sized.push(path.basename(d));
    return dirSize(d);
  };
  await w.scan(1);
  await w.scan(2);
  assert.deepEqual(got, [5]);
  assert.equal(sized.length, 2, 'sized until it settled');
  fs.writeFileSync(path.join(box, 'more'), 'xx');
  await w.scan(3);
  await w.scan(4);
  assert.equal(sized.length, 2, 'not after');
  assert.deepEqual(got, [5], 'and reported once');
  const a = w.scan(5);
  assert.equal(w.scan(6), a, 'asked again while one runs: the same scan');
  await a;
  fs.rmSync(box, { recursive: true });
  await w.scan(7);
  fs.mkdirSync(box);
  fs.writeFileSync(path.join(box, 'mbox'), 'abc');
  await w.scan(8);
  await w.scan(9);
  assert.deepEqual(got, [5, 3], 'gone and back: a new one, sized again');
});

test('a burst of changes in the folder is one scan, once it pauses', async () => {
  const w = new FolderWatcher(tmp, () => {}, 0, 60_000);
  let scans = 0;
  const scan = w.scan.bind(w);
  w.scan = (now?: number) => {
    scans++;
    return scan(now);
  };
  w.start();
  await new Promise((r) => setTimeout(r, 300));
  const before = scans;
  const f = path.join(tmp, 'takeout-1.zip.crdownload');
  for (let i = 0; i < 40; i++) {
    fs.appendFileSync(f, 'x'.repeat(1000));
    await new Promise((r) => setTimeout(r, 10));
  }
  await new Promise((r) => setTimeout(r, 1200));
  w.stop();
  assert.ok(scans - before <= 2, `${scans - before} scans for 40 writes`);
});
