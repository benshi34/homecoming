// The Ask page, driven like a person would: pick who does the work, ask, read the lookups, open a cited record, confirm
// a cloud provider's data settings first, stop an answer, and find the conversation again after a restart. What the
// agent still needs (a key, a local model's server) is said by the box, and sending waits for it; an agent's errors
// come in plain words with Try Again. Claude Code and Codex are stand-ins (test/fakes) scripted per question; their
// lookups run the real tools over a small made-up corpus. A stand-in model server answers on localhost.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { type FakeServer, fakeModelServer } from '../fakes/model_servers.ts';
import { DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap } from './harness.ts';

let sb: Sandbox;
let run: Running;
let env: Record<string, string>;
let dinner: number;
let photo: number;
let models: FakeServer;
const SHOTS = process.env.UMP_SHOTS; // also save the screens looked at here, to this folder
const look = async (name: string) => {
  await shot(run.page, name);
  if (SHOTS) await run.page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};
const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');
const askApi = (x: object) => run.page.evaluate((v) => (window as unknown as { api: { ask(x: object): Promise<unknown> } }).api.ask(v), x);
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const plan = (who: 'claude' | 'codex', p: unknown) => fs.writeFileSync(path.join(sb.root, `${who}-plan.json`), JSON.stringify(p));

before(async () => {
  sb = sandbox({ identity: true });
  models = await fakeModelServer(['qwen-test', 'gpt-oss:20b']);
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'ask-corpus', sb.corpus]);
  const rowid = (where: string) => Number(execFileSync(PY, ['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(path.join(sb.corpus, 'corpus.db'))}).execute("select rowid from records where ${where}").fetchone()[0])`]).toString());
  dinner = rowid("text like '%Tasca%'");
  photo = rowid("source = 'photos'");
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
  await models?.close();
  sb?.cleanup();
});

const askState = async () => (await snap(run.page)).ask;

test('Ask starts empty, and says the default (Claude Code) needs its data settings checked', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-ask]').click();
  // AI is agreed to once, here or on the AI page, before anything goes to one, with the agents to pick from under it.
  await p.locator('[data-testid=ai-agreement]').waitFor();
  assert.equal(await p.locator('[data-testid=ask-ai-gate] [data-testid^=ai-provider-]').count(), 5);
  await p.locator('[data-testid=ask-ai-gate] [data-testid=ai-provider-claude-code].selected').waitFor();
  await look('ask-ai-agreement');
  await p.locator('button[data-action=ai-on]').click();
  await p.locator('[data-testid=ask-empty]').waitFor();
  assert.match(await p.locator('[data-testid=ask-privacy]').innerText(), /check that it won't be kept/);
  await shot(p, 'ask-empty');
});

test('Codex on a local model answers with no confirmation, shows its lookups, and cites a record you can open', async () => {
  const p = run.page;
  await p.locator('[data-testid=ask-provider]').click();
  const sheet = p.locator('[data-testid=ask-provider-sheet]');
  assert.equal(await sheet.locator('h2').innerText(), 'Who does the work', 'the same name as on AI Settings');
  await p.locator('[data-testid=provider-local]').click();
  // What it needs is right under it: the server, its address, whether it answers, and the model.
  const detail = sheet.locator('[data-testid=provider-detail]');
  await p.locator('[data-testid=ask-local-server]').selectOption('lmstudio');
  await p.waitForFunction(() => (document.querySelector('[data-testid=ask-local-url]') as HTMLInputElement | null)?.value.includes(':1234'));
  assert.equal((await askState()).settings.localUrl, 'http://localhost:1234/v1', 'its usual address');
  // Only an address on this Mac.
  await p.locator('[data-testid=ask-local-url]').fill('http://192.168.1.5:1234/v1');
  await p.locator('[data-testid=ask-local-url]').press('Enter');
  await detail.getByText('Use an address on this Mac').waitFor();
  assert.equal((await askState()).settings.localUrl, 'http://localhost:1234/v1');
  await p.locator('[data-testid=ask-local-url]').fill(`${models.url}/v1`);
  await p.locator('[data-testid=ask-local-url]').press('Enter');
  await p.locator('[data-testid=ask-local-status]', { hasText: 'LM Studio is answering here.' }).waitFor();
  await p.locator('[data-testid=provider-local]', { hasText: /LM Studio is running at 127\.0\.0\.1:\d+/ }).waitFor();
  assert.equal(await p.locator('[data-testid=ask-model]').getAttribute('placeholder'), 'default (Codex chooses)', 'empty is the default, and says so');
  await p.locator('[data-testid=ask-model]').fill('qwen-test');
  await look('ask-provider-sheet');
  await p.locator('[data-testid=ask-provider-sheet] button', { hasText: 'Done' }).click();
  const s = await askState();
  assert.equal(s.settings.provider, 'local');
  assert.equal(s.settings.localServer, 'lmstudio');
  assert.equal(s.settings.localUrl, `${models.url}/v1`);
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
  await look('ask-answer');

  await p.locator('[data-testid=ask-cite]').click();
  await p.locator('[data-testid=ask-record] h2').waitFor();
  const rec = await p.locator('[data-testid=ask-record]').innerText();
  assert.match(rec, /Are we still on for dinner at Tasca on Friday\?/);
  assert.match(rec, /Message with Grace Hopper/);
  assert.match(rec, /What\s+Message\s+From\s+Messages/);
  assert.match(rec, /By\s+Grace Hopper/);
  await shot(p, 'ask-record');
  await p.locator('[data-testid=ask-record] button', { hasText: 'Done' }).click();
  assert.equal(await p.locator('[data-testid=ask-row]').count(), 1);
});

test('an answer can show the conversation and the photo it means, and the conversation opens whole', async () => {
  const p = run.page;
  plan('codex', { notes: false, steps: [{ tool: 'search', input: { query: 'Tasca' } }],
    answer: `You booked Tasca for Friday:\n[[chat:${dinner}]]\nThe photo from that dinner:\n\n[[photos:${photo}]]\n\nOr see [[chat:${dinner}]] again.` });
  await p.locator('[data-testid=ask-input]').fill('Show me the dinner plans');
  await p.locator('[data-testid=ask-input]').press('Enter');
  const chat = p.locator('[data-testid=ask-turn]').nth(1).locator('[data-testid=ask-chat-card]');
  await chat.waitFor({ timeout: 30_000 });
  assert.deepEqual(await chat.locator('.bubble').allInnerTexts(), ['Are we still on for dinner at Tasca on Friday?', 'Yes! 7:30, I booked a table.'], 'both sides, in order');
  assert.equal(await chat.locator('.msg-row.me .bubble').innerText(), 'Yes! 7:30, I booked a table.');
  assert.match(await chat.locator('.embed-chat-who').innerText(), /Grace Hopper\s*Messages · March 2, 2026/);
  const photos = p.locator('[data-testid=ask-turn]').nth(1).locator('[data-testid=ask-photos]');
  await photos.locator('img').waitFor();
  assert.match(await photos.innerText(), /Lisbon · March 7, 2026/);
  assert.equal(await p.locator('[data-testid=ask-turn]').nth(1).locator('[data-testid=ask-cite]', { hasText: 'the conversation' }).count(), 1, 'mid-sentence, a citation');
  await shot(p, 'ask-embeds');
  await chat.locator('[data-testid=ask-chat-open]').click();
  await p.locator('[data-testid=convo]').waitFor();
  assert.match(await p.locator('[data-testid=convo]').innerText(), /I booked a table/);
  await p.locator('[data-testid=conversation] button', { hasText: 'Done' }).click();
  await photos.locator('button').first().click();
  await p.locator('[data-testid=ask-record] h2').waitFor();
  assert.match(await p.locator('[data-testid=ask-record]').innerText(), /Place: Lisbon, Portugal/);
  await p.locator('[data-testid=ask-record] button', { hasText: 'Done' }).click();
});

test('Claude Code with an API key waits for its data settings to be confirmed, then sends the question', async () => {
  const p = run.page;
  await p.locator('[data-testid=ask-new]').click();
  await p.locator('[data-testid=ask-provider]').click();
  await p.locator('[data-testid=provider-anthropic]').click();
  assert.match(await p.locator('[data-testid=provider-anthropic]').innerText(), /An Anthropic API key\s*Key saved/);

  // Saved: the inline key field says so, and asks before taking it out.
  assert.match(await p.locator('[data-testid=ask-provider-sheet] [data-testid=key-anthropic]').innerText(), /Saved, encrypted with your Keychain/);
  await p.locator('[data-testid=ask-provider-sheet] button[data-action=key-remove]').click();
  await p.locator('[data-testid=key-remove-confirm]').getByText('Remove your Anthropic API key?').waitFor();
  await look('ask-key-remove-confirm');
  await p.locator('[data-testid=key-remove-confirm] button[data-action=confirm-cancel]').click();
  assert.equal((await askState()).keys.anthropic, true, 'kept');
  await p.locator('[data-testid=ask-provider-sheet]').waitFor();
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
  await look('ask-retention');
  await sheet.locator('input[type=checkbox]').check();
  await go.click();
  await p.locator('[data-testid=ask-answer]', { hasText: 'You have 2 calendar events.' }).waitFor({ timeout: 30_000 });
  assert.ok((await askState()).settings.retention.anthropic);
  // Checked: the line under the box reads as done.
  await p.locator('[data-testid=ask-privacy]', { hasText: /^Checked \w+ \d+: Anthropic keeps API requests 30 days at most\. Details$/ }).waitFor();
  assert.match(await p.locator('.turn-meta').innerText(), /Claude Code \(API key\) · Sonnet 5\.5/);
  // Its data settings, opened from the agent sheet, go back to the sheet.
  await p.locator('[data-testid=ask-provider]').click();
  await p.locator('[data-testid=ask-provider-sheet] .privacy button.link', { hasText: 'Details' }).click();
  await p.locator('[data-testid=ask-retention] button', { hasText: 'Done' }).click();
  await p.locator('[data-testid=ask-provider-sheet]').waitFor();
  await p.locator('[data-testid=ask-provider-sheet] button', { hasText: 'Done' }).click();
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
  assert.equal(await p.locator('[data-testid=ask-turn]').nth(1).locator('[data-action=ask-retry]', { hasText: 'Try Again' }).count(), 1);
});

test('without its key, the box says so and fixes it in place, and nothing is sent', async () => {
  const p = run.page;
  await p.locator('[data-testid=ask-new]').click();
  await p.locator('[data-testid=ask-provider]').click();
  await p.locator('[data-testid=provider-openai]').click();
  // Picked: its key field, right under it, with where to get one; focused to paste into.
  const sheet = p.locator('[data-testid=ask-provider-sheet]');
  await sheet.locator('[data-testid=provider-openai]', { hasText: 'Needs a key' }).waitFor();
  await sheet.locator('[data-testid=ask-key]').waitFor();
  assert.equal(await sheet.locator('[data-testid=ask-key]').evaluate((e) => e === document.activeElement), true);
  assert.match(await sheet.locator('[data-testid=key-openai]').innerText(), /Paste it here\. It's kept encrypted with your Mac's Keychain\. Make one at platform\.openai\.com\./);
  await look('ask-sheet-openai-key');
  await sheet.locator('button', { hasText: 'Done' }).click();
  const need = p.locator('[data-testid=agent-need]');
  assert.equal(await need.locator('[data-testid=agent-need-text]').innerText(), 'Codex needs your OpenAI API key to answer.');
  await need.locator('[data-testid=ask-key]').waitFor();
  await p.locator('[data-testid=ask-provider-needs]').waitFor();
  await p.locator('[data-testid=ask-input]').fill('How many photos?');
  assert.equal(await p.locator('[data-testid=ask-send]').isDisabled(), true);
  await p.locator('[data-testid=ask-input]').press('Enter');
  await new Promise((r) => setTimeout(r, 500));
  assert.equal(await p.locator('[data-testid=ask-turn]').count(), 0, 'nothing asked');
  assert.equal(await p.locator('[data-testid=ask-retention]').count(), 0, 'nor its data settings, yet');
  assert.equal(await p.locator('[data-testid=ask-input]').inputValue(), 'How many photos?', 'the question waits in the box');
  const r = await askApi({ op: 'ask', id: null, question: 'How many photos?' }) as { error?: string };
  assert.ok(r.error, 'and main refuses too');
  await look('ask-needs-key');
  // The link to make one opens in the browser.
  await need.getByRole('button', { name: 'platform.openai.com' }).click();
  for (let i = 0; i < 20 && !opened().includes('platform.openai.com'); i++) await new Promise((x) => setTimeout(x, 100));
  assert.match(opened(), /https:\/\/platform\.openai\.com\/api-keys/);
  // Choose Another… opens the list.
  await need.locator('button[data-action=agent-choose]').click();
  await p.locator('[data-testid=provider-claude-code]').click();
  await p.locator('[data-testid=ask-provider-sheet] button', { hasText: 'Done' }).click();
  await p.locator('[data-testid=agent-need]').waitFor({ state: 'detached' });
  assert.equal(await p.locator('[data-testid=ask-send]').isDisabled(), false);
  await p.locator('[data-testid=ask-input]').fill('');
});

test('a local model whose server isn\'t answering holds the question until it is', async () => {
  const p = run.page;
  await askApi({ op: 'settings', patch: { provider: 'local', localUrl: 'http://127.0.0.1:9/v1' } });
  const need = p.locator('[data-testid=agent-need]');
  await need.locator('[data-testid=agent-need-text]', { hasText: 'Nothing is answering at 127.0.0.1:9. Open LM Studio, then try again.' }).waitFor();
  await p.locator('[data-testid=ask-provider-needs]').waitFor();
  await p.locator('[data-testid=ask-input]').fill('Anything?');
  assert.equal(await p.locator('[data-testid=ask-send]').isDisabled(), true);
  await look('ask-local-down');
  await askApi({ op: 'settings', patch: { localUrl: `${models.url}/v1` } });
  await need.locator('button[data-action=agent-check]').click();
  await need.waitFor({ state: 'detached' });
  assert.equal(await p.locator('[data-testid=ask-send]').isDisabled(), false);
  await p.locator('[data-testid=ask-input]').fill('');
});

test('an agent\'s errors in plain words, its own under Details, with Try Again; nothing of it goes into the next question', async () => {
  const p = run.page;
  await askApi({ op: 'settings', patch: { provider: 'claude-code' } });
  await askApi({ op: 'confirm-retention', provider: 'claude-code' });
  await askApi({ op: 'confirm-retention', provider: 'codex' });
  await p.locator('[data-testid=ask-new]').click();
  plan('claude', { error: 'Invalid API key · Please run /login', exit: 1 });
  await p.locator('[data-testid=ask-input]').fill('Who did I text most?');
  await p.locator('[data-testid=ask-input]').press('Enter');
  const err = p.locator('[data-testid=ask-turn-error]');
  await err.waitFor({ timeout: 30_000 });
  const turn = p.locator('[data-testid=ask-turn]').last();
  assert.equal(await err.locator('[data-testid=ask-error-text]').innerText(), 'Claude Code isn\'t signed in. Sign In opens claude.ai\'s sign-in in your browser.');
  assert.doesNotMatch(await turn.innerText(), /sandbox-exec|Please run \/login/, 'not the wrapper, not the raw words');
  assert.equal(await turn.locator('[data-testid=ask-answer]').count(), 0, 'the error isn\'t an answer');
  await err.locator('[data-testid=ask-error-details]').click();
  assert.match(await err.locator('.error-detail').innerText(), /Invalid API key · Please run \/login/);
  await look('ask-error-not-signed-in');
  assert.equal(await err.locator('button[data-action=sign-in-claude-code]').count(), 1, 'Sign In, not Terminal');
  assert.match(await p.locator('[data-testid=ask-row]').first().innerText(), /Who did I text most\?\s*just now · Not answered/);

  // Signed in now: Try Again asks it again in its place.
  plan('claude', { answer: 'Grace, 214 messages.', notes: false, steps: [] });
  await err.locator('button[data-action=ask-retry]').click();
  await p.locator('[data-testid=ask-answer]', { hasText: 'Grace, 214 messages.' }).waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-send]').waitFor(); // done, not just shown
  assert.equal(await p.locator('[data-testid=ask-turn]').count(), 1);
  assert.equal(await p.locator('[data-testid=ask-turn-error]').count(), 0);

  // Codex, signed in long ago: reconnecting while it lasts, then what to do.
  await askApi({ op: 'settings', patch: { provider: 'codex' } });
  plan('codex', { fail: 'unexpected status 401 Unauthorized: Your authentication token has expired. Please try signing in again.', reconnects: 2 });
  await p.locator('[data-testid=ask-input]').fill('And last year?');
  await p.locator('[data-testid=ask-input]').press('Enter');
  await err.waitFor({ timeout: 30_000 });
  assert.equal(await err.locator('[data-testid=ask-error-text]').innerText(), 'Codex\'s sign-in has expired. Sign In opens ChatGPT\'s sign-in in your browser, to sign in again.');
  assert.doesNotMatch(await p.locator('[data-testid=ask-turn]').last().innerText(), /Reconnecting|401/);
  await look('ask-error-codex-expired');

  // A crash: no traceback in front of you.
  await askApi({ op: 'settings', patch: { provider: 'claude-code' } });
  plan('claude', { crash: true });
  await err.locator('button[data-action=ask-retry]').click();
  await err.locator('[data-testid=ask-error-text]', { hasText: 'Claude Code stopped before it answered.' }).waitFor({ timeout: 30_000 });
  assert.doesNotMatch(await p.locator('[data-testid=ask-turn]').last().innerText(), /Traceback|RuntimeError/);
  assert.equal(await p.locator('[data-testid=ask-turn]').count(), 2, 'tried again in place');
  await look('ask-error-crash');

  // The next question carries the answered turn (the failed ones stay out: see the unit tests).
  plan('claude', { answer: 'Mostly Grace.', notes: false, steps: [] });
  await p.locator('[data-testid=ask-input]').fill('Why?');
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-answer]', { hasText: /Mostly Grace\.\s*\(had history\)/ }).waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-send]').waitFor(); // done, not just shown
});

test('a question asked while scrolled up is shown; leaving Ask and coming back opens the same conversation', async () => {
  const p = run.page;
  const chat = p.locator('[data-testid=ask-chat]');
  plan('claude', { answer: Array.from({ length: 60 }, (_, i) => `Line ${i + 1} of a long answer.`).join('\n\n'), notes: false, steps: [] });
  await p.locator('[data-testid=ask-input]').fill('Tell me a lot');
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-answer]', { hasText: 'Line 60 of a long answer.' }).waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-send]').waitFor(); // done, not just shown
  await chat.evaluate((e) => (e.scrollTop = 0));
  plan('claude', { answer: 'Short.', notes: false, steps: [] });
  await p.locator('[data-testid=ask-input]').fill('And briefly?');
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-answer]', { hasText: /^Short\./ }).waitFor({ timeout: 30_000 });
  const q = p.locator('[data-testid=ask-turn]').last().locator('.q');
  const inView = async () => {
    const [b, c] = [await q.boundingBox(), await chat.boundingBox()];
    return !!b && !!c && b.y >= c.y && b.y + b.height <= c.y + c.height + 1;
  };
  for (let i = 0; i < 20 && !(await inView()); i++) await new Promise((x) => setTimeout(x, 100));
  assert.equal(await inView(), true, 'the new question is in view');

  await p.locator('[data-testid=nav-overview]').click();
  await p.locator('[data-testid=overview]').waitFor();
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-turn]', { hasText: 'And briefly?' }).waitFor();
  assert.equal(await p.locator('[data-testid=ask-row].selected .n').innerText(), 'Who did I text most?');
});

test('conversations are there after a restart', async () => {
  await run.close();
  run = await launch(env);
  // Page changes animate as view transitions, which stall in a window another covers (tests run four at once);
  // with Reduce Motion they happen at once, as in Explore's tests.
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  const p = run.page;
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-row]').nth(2).waitFor();
  assert.deepEqual(await p.locator('[data-testid=ask-row] .n').allInnerTexts(), ['Who did I text most?', 'How many calendar events do I have?', 'Who did I have dinner with?']);
  await p.locator('[data-testid=ask-row]').nth(2).click();
  await p.locator('[data-testid=ask-answer]', { hasText: 'Grace' }).waitFor();
  // Deleting asks first.
  await p.locator('[data-testid=ask-delete]').click();
  const confirm = p.locator('[data-testid=ask-delete-confirm]');
  assert.match(await confirm.innerText(), /Delete “Who did I have dinner with\?”\?[\s\S]*can't be brought back/);
  await look('ask-delete-confirm');
  await confirm.locator('button[data-action=confirm-cancel]').click();
  assert.equal(await p.locator('[data-testid=ask-row]').count(), 3, 'kept');
  await p.locator('[data-testid=ask-delete]').click();
  await confirm.locator('button[data-action=confirm]').click();
  await p.locator('[data-testid=ask-empty]').waitFor();
  assert.equal(await p.locator('[data-testid=ask-row]').count(), 2);
  assert.deepEqual(run.errors, []);
});
