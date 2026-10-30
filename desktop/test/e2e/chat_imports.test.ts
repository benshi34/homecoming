// Chats from exports, end to end: a slackdump export added by hand, and a Telegram Desktop export found where Telegram
// saves it (Downloads/Telegram Desktop, a folder down, beside files people sent you). Each is imported by the real
// imports.py into a throwaway corpus, and a cited message opens in its conversation with what it replies to and who
// reacted. Claude Code is the stand-in (test/fakes); nothing here reaches the network or a real AI.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, claudeChecked, clickAction, DESKTOP, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const SHOTS = process.env.UMP_SHOTS;
const look = async (name: string) => {
  await run.page.locator('[data-testid=celebration]').waitFor({ state: 'detached', timeout: 15_000 }).catch(() => {}); // "is home" passes first
  await shot(run.page, name);
  if (SHOTS) await run.page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};
const rowid = (where: string) => Number(execFileSync(PY, ['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(path.join(sb.corpus, 'corpus.db'))}).execute(${JSON.stringify(`select rowid from records where ${where}`)}).fetchone()[0])`]).toString());

before(async () => {
  sb = sandbox({ identity: true });
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, ask: claudeChecked(), onboarding: { done: true },
    settings: { aiOn: true, aiAgreedAt: new Date().toISOString() } }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: path.join(sb.root, 'claude-plan.json'),
  }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

const closeSheets = async () => {
  for (let i = 0; i < 3 && await run.page.locator('.sheet-backdrop').count(); i++) await run.page.keyboard.press('Escape');
};

async function openCited(question: string, record: number) {
  const p = run.page;
  await closeSheets();
  fs.writeFileSync(path.join(sb.root, 'claude-plan.json'), JSON.stringify({ steps: [{ tool: 'search', input: { query: 'x' } }], answer: `[This one](record:${record}).` }));
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-new]').click();
  await p.locator('[data-testid=ask-input]').fill(question);
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-cite]').last().waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-cite]').last().click();
  const convo = p.locator('[data-testid=conversation] [data-testid=convo]');
  await convo.locator('.msg-row.anchor').waitFor();
  return convo;
}

test('Slack: a slackdump export added by hand, its thread and reactions', async () => {
  await selectSource(run.page, 'slack');
  assert.match(await run.page.locator('[data-testid=detail]').innerText(), /slackdump export -member-only/, 'how to export without being an admin');
  const r = await act(run.page, 'slack', 'add-file', { paths: [sb.exports.slack] });
  assert.equal(r.ok, true);
  const s = await until(run.page, 'slack imported', (x) => find(x, 'slack').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, 'slack').records, 2);
  const recs = fs.readFileSync(path.join(sb.corpus, 'normalized/slack.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  const first = recs.find((x) => x.text.startsWith('The mill turns'));
  assert.ok(fs.existsSync(path.isAbsolute(first.meta.files[0]) ? first.meta.files[0] : path.join(sb.corpus, first.meta.files[0])), 'the file slackdump downloaded, copied out');

  const convo = await openCited('What did Charles say about the mill?', rowid("source = 'slack' and text like 'Then the notes%'"));
  assert.match(await run.page.locator('[data-testid=conversation] .convo-head').innerText(), /#engine\s*Slack · group conversation/, 'a channel, not one on one');
  const reply = convo.locator('.msg-row.anchor');
  assert.match(await reply.locator('[data-testid=msg-reply]').innerText(), /The mill turns at last/, 'what it answers, the day before');
  const parent = convo.locator('.msg-row', { hasText: 'The mill turns at last' }).filter({ has: run.page.locator('[data-testid=msg-reactions]') });
  assert.equal(await parent.locator('[data-testid=msg-reactions]').getAttribute('title'), 'You: 🎉');
  await look('slack-thread');
  await closeSheets();
});

test('Telegram: an export in Downloads/Telegram Desktop is found, imported on a yes, and the rest of that folder stays', async () => {
  const folder = path.join(sb.downloads, 'Telegram Desktop');
  fs.mkdirSync(folder, { recursive: true });
  fs.writeFileSync(path.join(folder, 'photo_2025-02-11.jpg'), 'a photo someone sent');
  fs.cpSync(sb.exports.telegram, path.join(folder, path.basename(sb.exports.telegram)), { recursive: true });
  let s = await until(run.page, 'found', (x) => find(x, 'telegram').status.startsWith('Found'), 60_000);
  await selectSource(run.page, 'telegram');
  await clickAction(run.page, 'import-found');
  s = await until(run.page, 'telegram imported', (x) => find(x, 'telegram').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, 'telegram').records, 2);
  assert.equal(readJson(path.join(sb.corpus, 'manifest.json')).telegram.count, 2);
  assert.ok(fs.existsSync(path.join(folder, 'photo_2025-02-11.jpg')), 'only the export moved');
  assert.ok(!fs.existsSync(path.join(folder, 'DataExport_2025-03-01')));

  const convo = await openCited('When is tea?', rowid("source = 'telegram' and text = 'Four it is'"));
  assert.match(await run.page.locator('[data-testid=conversation] .convo-head').innerText(), /Charles Babbage\s*Telegram · one on one/);
  assert.match(await convo.locator('.msg-row.anchor [data-testid=msg-reply]').innerText(), /Tea at four\?/);
  assert.equal(await convo.locator('.msg-row', { hasText: 'Tea at four?' }).filter({ has: run.page.locator('[data-testid=msg-reactions]') }).locator('[data-testid=msg-reactions]').getAttribute('title'), 'You: ❤');
  await look('telegram-chat');
  await closeSheets();
});

test('the UI stayed error-free', () => {
  assert.deepEqual(run.errors, []);
});
