// AI (or Do It for Me) turned off while it's at work, and what still happens without it: Do It for Me stops quietly and
// what it was doing is set aside; an answer under way in Ask stops; a ready email still says so, but nothing downloads by itself.
// Stand-ins for Claude Code (test/fakes): in Chrome, and answering in Ask.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { after, before, test } from 'node:test';
import { act, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const file = (n: string) => path.join(sb.home, n);
const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');
const runs = () => (fs.existsSync(file('agent.log')) ? fs.readFileSync(file('agent.log'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []);
const settings = (x: object) => run.page.evaluate((v) => (window as unknown as { api: { settings(x: object): Promise<unknown> } }).api.settings(v), x);
const on = () => settings({ aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true, agentDownloads: true });
const working = (x: Parameters<typeof find>[0]) => find(x, 'instagram').status === 'Opening Instagram\'s export page'; // its first step, under way
const saved = () => JSON.parse(fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8'));

before(async () => {
  sb = sandbox({ identity: true });
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'ask-corpus', sb.corpus]);
  // Slow on purpose, so there's time to turn AI off while it works.
  fs.writeFileSync(file('plan.json'), JSON.stringify({ request: [{ steps: ['Opening Instagram\'s export page', 'Choosing everything', 'Choosing JSON', 'Choosing all time', 'Starting the export'], result: 'requested', sleep: 3 }],
    download: [{ steps: ['Opening the download link'], result: 'downloading', sleep: 0.2 }] }));
  fs.writeFileSync(file('claude-plan.json'), JSON.stringify({ answer: 'Never.', steps: [{ tool: 'sql', input: { query: 'select 1' } }, { sleep: 30 }] }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'), FAKE_BROWSER_LOG: file('agent.log'),
    UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: file('claude-plan.json'),
    UMP_MAIL_DB: path.join(sb.home, 'Mail/V10/MailData/Envelope Index'), UMP_NOTIFICATIONS_DB: file('no-notifications/db'), UMP_SIGNAL_MS: '500',
  }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('turning AI off stops Do It for Me quietly, and sets aside what it was doing', async () => {
  const p = run.page;
  await on();
  await act(p, 'instagram', 'agent-request');
  await until(p, 'working', working, 15_000);
  await settings({ aiOn: false });
  const s = await until(p, 'set aside', (x) => find(x, 'instagram').status === 'Not requested yet', 10_000);
  assert.ok(!find(s, 'instagram').actions.some((a) => a.id.startsWith('agent-')), 'and nothing offers to do it');
  assert.equal(find(s, 'instagram').actions.find((a) => a.primary)?.id, 'open');
  await new Promise((r) => setTimeout(r, 1500));
  assert.doesNotMatch(opened(), /Couldn't finish/, 'stopping it isn\'t news');
  assert.equal(saved().sources.instagram?.agent, undefined);
  assert.equal(saved().sources.instagram?.requestedAt, undefined, 'and it wasn\'t counted as requested');
});

test('the Stop button stops it quietly too', async () => {
  const p = run.page;
  await on();
  await act(p, 'instagram', 'agent-request');
  await until(p, 'working', working, 15_000);
  await act(p, 'instagram', 'agent-stop');
  const s = await until(p, 'stopped', (x) => find(x, 'instagram').status === 'Not requested yet', 10_000);
  assert.match(find(s, 'instagram').detail ?? '', /^You stopped Claude just now\. If it had already asked Instagram for your data, choose I've Requested It\./, 'and what to do if it got that far');
  await new Promise((r) => setTimeout(r, 1000));
  assert.doesNotMatch(opened(), /Couldn't finish/);
});

test('turning Do It for Me off (AI staying on) stops it quietly too', async () => {
  const p = run.page;
  await on();
  await act(p, 'instagram', 'agent-request');
  await until(p, 'working', working, 15_000);
  await settings({ agentExports: false });
  await until(p, 'set aside', (x) => find(x, 'instagram').status === 'Not requested yet' && !x.jobs.length, 10_000);
  await new Promise((r) => setTimeout(r, 1500));
  assert.equal(saved().sources.instagram?.agent, undefined, 'stopped, and nothing left of it');
  assert.equal(saved().sources.instagram?.requestedAt, undefined);
  assert.doesNotMatch(opened(), /Couldn't finish/);
  await on();
});

test('a run cut short by quitting is set aside while AI is off, and back when it is on', async () => {
  const p = run.page;
  await settings({ aiOn: true });
  // As Homecoming leaves one when it quits mid-run.
  await p.evaluate(() => (window as unknown as { api: { action(id: string, a: string, p?: unknown): Promise<unknown> } }).api.action('instagram', 'agent-request'));
  await until(p, 'working', working, 15_000);
  const pid = Number(fs.readFileSync(`${file('agent.log')}.pid`, 'utf8'));
  await run.close();
  const state = saved();
  assert.equal(state.sources.instagram.agent.status, 'running', 'killed with it running');
  // Claude in Chrome went with it, rather than going on with nobody to hear from it.
  await new Promise((r) => setTimeout(r, 500));
  assert.throws(() => process.kill(pid, 0), /ESRCH/, 'the run is gone');
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'),
    FAKE_BROWSER_LOG: file('agent.log'), UMP_MAIL_DB: path.join(sb.home, 'Mail/V10/MailData/Envelope Index'), UMP_NOTIFICATIONS_DB: file('no-notifications/db'), UMP_SIGNAL_MS: '500',
    UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: file('claude-plan.json') }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  let s = await until(run.page, 'interrupted', (x) => find(x, 'instagram').status === 'Interrupted when Homecoming quit', 15_000);
  assert.deepEqual(find(s, 'instagram').actions.map((a) => [a.label, !!a.ai]), [['Carry On', true], ['Start Over', true], ['I\'ll Do It Myself', false]], 'carrying on is AI, and says so');
  await selectSource(run.page, 'instagram');
  assert.equal(await run.page.locator('[data-testid=agent-reply]').count(), 0, 'nothing to answer');
  await settings({ aiOn: false });
  s = await until(run.page, 'set aside', (x) => find(x, 'instagram').status === 'Not requested yet', 10_000);
  await settings({ aiOn: true });
  s = await until(run.page, 'back', (x) => find(x, 'instagram').status === 'Interrupted when Homecoming quit', 10_000);
  await act(run.page, 'instagram', 'agent-dismiss');
});

test('with AI off, a ready email still says so, and nothing downloads by itself', async () => {
  const p = run.page;
  await settings({ aiOn: false });
  await act(p, 'instagram', 'mark-requested');
  const before = runs().length;
  mailArrives('no-reply@mail.instagram.com', 'Instagram', 'Your Instagram information is ready to download',
    '<a href="https://accountscenter.instagram.com/info_and_permissions/dyi/?id=42">Download your information</a>');
  let s = await until(p, 'ready', (x) => find(x, 'instagram').status.startsWith('Ready'), 20_000);
  await new Promise((r) => setTimeout(r, 2500));
  assert.equal(runs().length, before, 'Claude wasn\'t started');
  s = await snap(p);
  assert.ok(!find(s, 'instagram').actions.some((a) => a.ai), 'nothing AI');
  assert.ok(find(s, 'instagram').actions.some((a) => a.id === 'open-ready'), 'the download page, to do it yourself');
  // On again: it's offered, not started.
  await settings({ aiOn: true });
  s = await until(p, 'offered', (x) => find(x, 'instagram').actions.some((a) => a.id === 'agent-download' && a.ai));
  await new Promise((r) => setTimeout(r, 1500));
  assert.equal(runs().length, before);
});

test('turning AI off stops an answer under way in Ask', async () => {
  const p = run.page;
  await settings({ aiOn: true });
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-input]').fill('Tell me everything');
  await p.locator('[data-testid=ask-send]').click();
  // The first question to Claude Code asks you to check its data settings, then goes.
  await p.locator('[data-testid=ask-stop], [data-testid=ask-retention]').first().waitFor();
  const sheet = p.locator('[data-testid=ask-retention]');
  if (await sheet.isVisible()) {
    await sheet.locator('input[type=checkbox]').check();
    await sheet.locator('button[data-action=confirm-retention]').click();
  }
  await p.locator('[data-testid=ask-stop]').waitFor();
  const id = (await p.evaluate(() => (window as unknown as { api: { ask(x: object): Promise<{ id: string }[]> } }).api.ask({ op: 'list' })))[0].id;
  await settings({ aiOn: false });
  await p.locator('[data-testid=ask-ai-off]').waitFor();
  const got = async () => p.evaluate((x) => (window as unknown as { api: { ask(x: object): Promise<{ running: boolean; conversation: { turns: { stopped?: boolean }[] } }> } })
    .api.ask({ op: 'get', id: x }), id);
  for (let i = 0; i < 50 && (await got()).running; i++) await new Promise((r) => setTimeout(r, 200));
  const c = await got();
  assert.equal(c.running, false, 'stopped');
  assert.equal(c.conversation.turns.at(-1)?.stopped, true);
  // And while it's off, Ask itself refuses.
  const r = await p.evaluate(() => (window as unknown as { api: { ask(x: object): Promise<{ error?: string }> } }).api.ask({ op: 'ask', question: 'Hello?' }));
  assert.match(r.error ?? '', /AI is off/);
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
  db.prepare('insert into messages (ROWID, sender, subject, summary, date_received, mailbox) values (1, 1, 1, 1, ?, 1)').run(Math.floor(Date.now() / 1000) + 2);
  db.close();
  const box = path.join(root, 'ACCOUNT-1/INBOX.mbox/0A1B/Data/Messages');
  fs.mkdirSync(box, { recursive: true });
  const msg = Buffer.from(`From: ${name} <${from}>\r\nSubject: ${subject}\r\nContent-Type: text/html; charset=utf-8\r\n\r\n${html}\r\n`);
  fs.writeFileSync(path.join(box, '1.emlx'), Buffer.concat([Buffer.from(`${msg.length}\n`), msg, Buffer.from('<?xml version="1.0"?><plist version="1.0"><dict/></plist>')]));
}
