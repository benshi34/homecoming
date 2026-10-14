// The Ask page, driven like a person would: pick who answers, ask, read the lookups, open a cited record, confirm a
// cloud provider's data settings first, stop an answer, and find the conversation again after a restart. Claude Code
// and Codex are stand-ins (test/fakes) scripted per question; their lookups run the real tools over a small made-up
// corpus.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap } from './harness.ts';

let sb: Sandbox;
let run: Running;
let env: Record<string, string>;
let dinner: number;
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const plan = (who: 'claude' | 'codex', p: unknown) => fs.writeFileSync(path.join(sb.root, `${who}-plan.json`), JSON.stringify(p));

before(async () => {
  sb = sandbox({ identity: true });
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'ask-corpus', sb.corpus]);
  dinner = Number(execFileSync(PY, ['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(path.join(sb.corpus, 'corpus.db'))}).execute("select rowid from records where text like '%Tasca%'").fetchone()[0])`]).toString());
  env = sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_ASK_ANTHROPIC_KEY: 'sk-ant-test',
    UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: path.join(sb.root, 'claude-plan.json'),
    UMP_CODEX_CMD: path.join(DESKTOP, 'test/fakes/fake_codex.py'), FAKE_CODEX_PLAN: path.join(sb.root, 'codex-plan.json'),
  });
  run = await launch(env);
  // Page changes animate as view transitions, which stall in a window another covers (tests run four at once);
  // with Reduce Motion they happen at once, as in Explore's tests.
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

const askState = async () => (await snap(run.page)).ask;

test('Ask starts empty, and says the default (Claude Code) needs its data settings checked', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-empty]').waitFor();
  assert.match(await p.locator('[data-testid=ask-privacy]').innerText(), /check that it won't be kept/);
  await shot(p, 'ask-empty');
});

test('Codex on a local model answers with no confirmation, shows its lookups, and cites a record you can open', async () => {
  const p = run.page;
  await p.locator('[data-testid=ask-provider]').click();
  await p.locator('[data-testid=provider-local]').click();
  await p.locator('[data-testid=ask-local-server]').selectOption('lmstudio');
  await p.waitForFunction(() => (document.querySelector('[data-testid=ask-local-url]') as HTMLInputElement | null)?.value.includes(':1234'));
  await p.locator('[data-testid=ask-model]').fill('qwen-test');
  await shot(p, 'ask-provider-sheet');
  await p.locator('[data-testid=ask-provider-sheet] button', { hasText: 'Done' }).click();
  const s = await askState();
  assert.equal(s.settings.provider, 'local');
  assert.equal(s.settings.localServer, 'lmstudio');
  assert.equal(s.settings.localUrl, 'http://localhost:1234/v1');
  assert.equal(s.settings.models.local, 'qwen-test');
  assert.match(await p.locator('[data-testid=ask-privacy]').innerText(), /nothing leaves it/);
  assert.match(await p.locator('[data-testid=ask-provider]').innerText(), /Codex\s*local model · qwen-test/);

  plan('codex', { notes: false, steps: [{ tool: 'search', input: { query: 'dinner', source: 'imessage' } }],
    answer: `## Dinner\nYou had dinner with **Grace** at Tasca.\n\n**How I know**\n- She asked about it [in your chat](record:${dinner}).` });
  await p.locator('[data-testid=ask-input]').fill('Who did I have dinner with?');
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-answer]', { hasText: 'Grace' }).waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-send]').waitFor();
  assert.equal(await p.locator('[data-testid=ask-input]').inputValue(), '');
  assert.equal(await p.locator('[data-testid=ask-answer] h4').innerText(), 'Dinner');
  assert.equal(await p.locator('[data-testid=ask-answer] strong').first().innerText(), 'Grace');
  assert.match(await p.locator('[data-testid=ask-lookups]').innerText(), /Looked up 1 thing/);
  await p.locator('.lookups-head').click();
  assert.match(await p.locator('[data-testid=ask-lookup]').first().innerText(), /Search\s+"dinner" · source imessage/);
  await p.locator('.lookup-row').first().click();
  assert.match(await p.locator('.lookup-detail').innerText(), /Tasca/);
  assert.match(await p.locator('.turn-meta').innerText(), /Codex \(local model\) · qwen-test/);
  await shot(p, 'ask-answer');

  await p.locator('[data-testid=ask-cite]').click();
  await p.locator('[data-testid=ask-record] h2').waitFor();
  const rec = await p.locator('[data-testid=ask-record]').innerText();
  assert.match(rec, /Are we still on for dinner at Tasca on Friday\?/);
  assert.match(rec, /Message in Grace Hopper/);
  assert.match(rec, /From\s+Messages · message/);
  assert.match(rec, /By\s+Grace Hopper/);
  await shot(p, 'ask-record');
  await p.locator('[data-testid=ask-record] button', { hasText: 'Done' }).click();
  assert.equal(await p.locator('[data-testid=ask-row]').count(), 1);
});

test('Claude Code with an API key waits for its data settings to be confirmed, then sends the question', async () => {
  const p = run.page;
  await p.locator('[data-testid=ask-new]').click();
  await p.locator('[data-testid=ask-provider]').click();
  await p.locator('[data-testid=provider-anthropic]').click();
  assert.match(await p.locator('[data-testid=provider-anthropic]').innerText(), /An Anthropic API key\s*Key saved/);
  await p.locator('[data-testid=ask-provider-sheet] button', { hasText: 'Done' }).click();

  plan('claude', { notes: false, answer: 'You have 2 calendar events.', steps: [{ tool: 'sql', input: { query: "select count(*) from records where source = 'calendar'" } }] });
  await p.locator('[data-testid=ask-input]').fill('How many calendar events do I have?');
  await p.locator('[data-testid=ask-send]').click();
  const sheet = p.locator('[data-testid=ask-retention]');
  await sheet.waitFor();
  assert.match(await sheet.innerText(), /Make sure Anthropic doesn't keep your data/);
  assert.match(await sheet.innerText(), /deletes API requests and responses within 30 days/);
  const go = sheet.locator('button[data-action=confirm-retention]');
  assert.equal(await go.isDisabled(), true);
  assert.equal(await p.locator('[data-testid=ask-turn]').count(), 0, 'nothing sent yet');
  await shot(p, 'ask-retention');
  await sheet.locator('input[type=checkbox]').check();
  await go.click();
  await p.locator('[data-testid=ask-answer]', { hasText: 'You have 2 calendar events.' }).waitFor({ timeout: 30_000 });
  assert.ok((await askState()).settings.retention.anthropic);
  await p.locator('[data-testid=ask-privacy]', { hasText: 'keeps API requests up to 30 days' }).waitFor();
  assert.match(await p.locator('.turn-meta').innerText(), /Claude Code \(API key\) · Sonnet 5\.5/);
  await p.locator('.lookups-head').click();
  assert.match(await p.locator('[data-testid=ask-lookup]').first().innerText(), /Database/);
});

test('stopping an answer', async () => {
  const p = run.page;
  plan('claude', { answer: 'Never.', steps: [{ tool: 'sql', input: { query: 'select 1' } }, { sleep: 30 }] });
  await p.locator('[data-testid=ask-input]').fill('Tell me everything');
  await p.locator('[data-testid=ask-send]').click();
  await p.locator('[data-testid=ask-stop]').waitFor();
  await p.locator('[data-testid=ask-turn]').nth(1).locator('[data-testid=ask-lookups]').waitFor();
  await p.locator('[data-testid=ask-stop]').click();
  await p.locator('[data-testid=ask-turn]').nth(1).locator('.notice', { hasText: 'Stopped.' }).waitFor({ timeout: 10_000 });
  await p.locator('[data-testid=ask-send]').waitFor();
});

test('conversations are there after a restart', async () => {
  await run.close();
  run = await launch(env);
  // Page changes animate as view transitions, which stall in a window another covers (tests run four at once);
  // with Reduce Motion they happen at once, as in Explore's tests.
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  const p = run.page;
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-row]').nth(1).waitFor();
  assert.deepEqual(await p.locator('[data-testid=ask-row] .n').allInnerTexts(), ['How many calendar events do I have?', 'Who did I have dinner with?']);
  await p.locator('[data-testid=ask-row]').nth(1).click();
  await p.locator('[data-testid=ask-answer]', { hasText: 'Grace' }).waitFor();
  await p.locator('[data-testid=ask-delete]').click();
  await p.locator('[data-testid=ask-empty]').waitFor();
  assert.equal(await p.locator('[data-testid=ask-row]').count(), 1);
  assert.deepEqual(run.errors, []);
});
