// Do It for Me, end to end with a stand-in for Claude Code in Chrome (test/fakes/fake_claude_browser.py): the first
// time it asks, then Claude requests the export, stops for a sign-in, carries on when told, and the clock starts. The
// service's "it's ready" email turns up in Apple Mail (a made-up Mail store), and the download starts by itself; the
// file landing in Downloads is read as usual.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { after, before, test } from 'node:test';
import { clickAction, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const file = (n: string) => path.join(sb.home, n);
const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');
const runs = () => (fs.existsSync(file('agent.log')) ? fs.readFileSync(file('agent.log'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []);

before(async () => {
  sb = sandbox({ identity: true });
  fs.writeFileSync(file('plan.json'), JSON.stringify({
    request: [
      { steps: ['Opening Instagram\'s export page', 'Instagram wants you to sign in first'], result: 'needs_you Sign in to Instagram in Chrome.', sleep: 1.5 },
      { steps: ['Choosing all your information, all time, JSON', 'Starting the export'], email: 'ada.work@example.com', result: 'requested', sleep: 0.4 },
    ],
    download: [{ steps: ['Opening the download link', 'Downloading part 1 of 1'], result: 'downloading', sleep: 0.3 }],
  }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'),
    FAKE_BROWSER_LOG: file('agent.log'), UMP_MAIL_DB: path.join(sb.home, 'Mail/V10/MailData/Envelope Index'),
    UMP_NOTIFICATIONS_DB: path.join(sb.home, 'no-notifications/db'), UMP_SIGNAL_MS: '500',
    UMP_URLS: JSON.stringify({ instagram: 'https://instagram.example/dyi' }),
  }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

// Apple Mail's index with one message, and the message itself, as Mail keeps them.
function mailArrives(from: string, name: string, subject: string, html: string) {
  const root = path.join(sb.home, 'Mail/V10');
  fs.mkdirSync(path.join(root, 'MailData'), { recursive: true });
  const db = new DatabaseSync(path.join(root, 'MailData/Envelope Index'));
  db.exec(`create table if not exists messages (ROWID integer primary key, sender integer, subject integer, summary integer, date_received integer, mailbox integer, deleted integer default 0);
    create table if not exists addresses (ROWID integer primary key, address text, comment text);
    create table if not exists subjects (ROWID integer primary key, subject text);
    create table if not exists summaries (ROWID integer primary key, summary text);
    create table if not exists mailboxes (ROWID integer primary key, url text);
    insert or ignore into mailboxes values (1, 'imap://ACCOUNT-1/INBOX');`);
  db.prepare('insert into addresses (ROWID, address, comment) values (1, ?, ?)').run(from, name);
  db.prepare('insert into subjects (ROWID, subject) values (1, ?)').run(subject);
  db.prepare('insert into summaries (ROWID, summary) values (1, ?)').run(subject);
  db.prepare('insert into messages (ROWID, sender, subject, summary, date_received, mailbox) values (1, 1, 1, 1, ?, 1)').run(Math.floor(Date.now() / 1000) + 2); // Mail keeps whole seconds: after the request, as it would be
  db.close();
  const box = path.join(root, 'ACCOUNT-1/INBOX.mbox/0A1B/Data/Messages');
  fs.mkdirSync(box, { recursive: true });
  const msg = Buffer.from(`From: ${name} <${from}>\r\nSubject: ${subject}\r\nContent-Type: text/html; charset=utf-8\r\n\r\n${html}\r\n`);
  fs.writeFileSync(path.join(box, '1.emlx'), Buffer.concat([Buffer.from(`${msg.length}\n`), msg, Buffer.from('<?xml version="1.0"?><plist version="1.0"><dict/></plist>')]));
}

test('Do It for Me asks once, requests in Chrome, stops for a sign-in, and carries on when told', async () => {
  const p = run.page;
  await selectSource(p, 'instagram');
  assert.equal(await p.locator('[data-testid=status]').innerText(), 'Not requested yet');
  await clickAction(p, 'agent-request');
  const sheet = p.locator('[data-testid=agent-opt-in]');
  await sheet.waitFor();
  assert.match(await sheet.innerText(), /stops and tells you when it needs you to sign in/);
  assert.match(await sheet.innerText(), /This turns on AI in Homecoming/, 'AI isn\'t on yet, and this turns it on');
  assert.equal(await sheet.locator('[data-testid=agent-downloads]').isChecked(), true, 'downloads start by themselves unless you say not');
  await shot(p, 'agent-opt-in');
  await sheet.locator('button[data-action=agent-on]').click();
  // It works in Chrome, a step at a time, then stops for the sign-in.
  await p.locator('[data-testid=status]', { hasText: 'Opening Instagram\'s export page' }).waitFor({ timeout: 10_000 });
  await shot(p, 'agent-working');
  let s = await until(p, 'needs you', (x) => find(x, 'instagram').status.startsWith('Needs you'), 20_000);
  assert.equal(find(s, 'instagram').status, 'Needs you: Sign in to Instagram in Chrome.');
  assert.equal(find(s, 'instagram').section, 'needs');
  await shot(p, 'agent-needs-you');
  const first = runs()[0];
  assert.ok(first.args.includes('--chrome'), 'it drives Chrome');
  assert.equal(first.args[first.args.indexOf('--tools') + 1], '', 'and has no tools of its own');
  const allowed = JSON.parse(first.args[first.args.indexOf('--settings') + 1]).permissions.allow as string[];
  assert.ok(allowed.includes('mcp__claude-in-chrome__navigate') && !allowed.some((t) => /file_upload|upload_image/.test(t)), 'nothing that sends files');
  assert.match(first.prompt, /https:\/\/instagram\.example\/dyi/);
  assert.match(first.prompt, /Format: JSON/, 'the service\'s own steps');
  assert.match(first.prompt, /Never type a password/);
  assert.ok(opened().includes('notify: Claude needs you for Instagram'), 'you hear about it');
  // Signed in, and a word for Claude: Continue picks up the same session with it, and the export is requested.
  await p.locator('[data-testid=agent-reply]').fill('I use my work account for Instagram');
  await clickAction(p, 'agent-continue');
  s = await until(p, 'requested', (x) => !!find(x, 'instagram').requestedAt, 20_000);
  const second = runs()[1];
  assert.equal(second.args[second.args.indexOf('--resume') + 1], first.session, 'the same session, carried on');
  assert.match(second.prompt, /They answered: "I use my work account for Instagram"/);
  const saved = () => JSON.parse(fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8')).sources.instagram?.notifyEmail;
  await until(p, 'where Instagram said it would email, kept', () => saved() === 'ada.work@example.com', 10_000);
  await p.locator('[data-testid=state] .wait-clock').waitFor({ timeout: 10_000 }); // its clock has started
  assert.equal(find(s, 'instagram').section, 'working');
});

test('the "it\'s ready" email in Apple Mail starts the download by itself, with the email\'s link, and the file is read', async () => {
  const p = run.page;
  mailArrives('no-reply@mail.instagram.com', 'Instagram', 'Your Instagram information is ready to download',
    '<a href="https://help.instagram.com/x">Help</a> <a href="https://accountscenter.instagram.com/info_and_permissions/dyi/?id=42">Download your information</a>');
  await until(p, 'download started', () => runs().some((r) => r.mode === 'download'), 30_000);
  const dl = runs().find((r) => r.mode === 'download');
  assert.match(dl.prompt, /https:\/\/accountscenter\.instagram\.com\/info_and_permissions\/dyi\/\?id=42/, 'the link from the email');
  let s = await until(p, 'downloading', (x) => find(x, 'instagram').status === 'Downloading in Chrome', 20_000);
  assert.equal(find(s, 'instagram').section, 'working');
  // Chrome's download lands in Downloads, twice (a link followed twice makes "name (1).zip"): one copy is filed.
  const name = path.basename(sb.exports.instagram);
  fs.copyFileSync(sb.exports.instagram, path.join(sb.downloads, name));
  fs.copyFileSync(sb.exports.instagram, path.join(sb.downloads, name.replace(/\.zip$/, ' (1).zip')));
  s = await until(p, 'imported', (x) => find(x, 'instagram').section === 'done' && !x.jobs.length, 90_000);
  assert.ok(find(s, 'instagram').records > 0);
  await new Promise((r) => setTimeout(r, 1500));
  assert.equal(fs.readdirSync(path.join(sb.corpus, 'imports/instagram')).filter((f) => f.endsWith('.zip')).length, 1, 'one copy filed, the other left alone');
  assert.deepEqual(run.errors, []);
});
