// AI Settings says whether Claude Code and Codex are signed in (as they say themselves), Codex's model can be picked
// like Claude Code's, and an export on its way opens your inbox searched for it. Stand-ins for both agents.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, until } from './harness.ts';

let sb: Sandbox;
let env: Record<string, string>;
let run: Running | null = null;

const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');

async function start(extra: Record<string, string> = {}) {
  await run?.close();
  run = await launch({ ...env, ...extra });
  await until(run.page, 'probe', (x) => !!x.probeTime);
  return run.page;
}

before(() => {
  sb = sandbox();
  fs.writeFileSync(path.join(sb.corpus, 'identity.json'), JSON.stringify({ names: ['Ada Lovelace'], emails: ['ada.lovelace@gmail.com', 'ada@work.example'], usernames: [], phones: [] }));
  const codexHome = path.join(sb.home, '.codex');
  fs.mkdirSync(codexHome, { recursive: true });
  fs.writeFileSync(path.join(codexHome, 'models_cache.json'), JSON.stringify({ models: [{ slug: 'gpt-test-big', visibility: 'list' }, { slug: 'gpt-test-small', visibility: 'list' }, { slug: 'hidden-one', visibility: 'hide' }] }));
  fs.writeFileSync(path.join(codexHome, 'config.toml'), 'model = "gpt-test-small"\n');
  env = sandboxEnv(sb, { UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), UMP_CODEX_CMD: path.join(DESKTOP, 'test/fakes/fake_codex.py') });
  const st = path.join(sb.userData, 'state.json');
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(st, JSON.stringify({ version: 1, onboarding: { done: true }, settings: { autoRefresh: false, watchDownloads: true, aiOn: true, aiAgreedAt: '2026-10-01T00:00:00Z' },
    sources: { discord: { requestedAt: new Date(Date.now() - 3600_000).toISOString() } } }));
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('AI Settings says Claude Code is signed in, and as whom', async () => {
  const p = await start();
  await p.click('[data-testid=nav-ai]');
  const row = p.locator('[data-testid=ai-provider-claude-code]');
  await row.locator('[data-testid=signed-in-claude-code]').waitFor({ timeout: 20_000 });
  assert.match(await row.innerText(), /Signed in as ada@example\.com · Max plan/);
  assert.match(await p.locator('[data-testid=ai-provider-codex]').innerText(), /Signed in with ChatGPT/);
});

test('Codex with your ChatGPT account: its model can be picked, its own default first', async () => {
  const p = run!.page;
  await p.locator('[data-testid=ai-provider-codex]').click();
  await p.locator('[data-testid=agent-not-yet] button[data-action=agent-not-yet-ok]').click(); // Do It for Me isn't here yet with Codex
  const model = p.locator('[data-testid=provider-detail] [data-testid=ask-model]');
  await model.waitFor();
  await p.waitForFunction(() => (document.querySelector('[data-testid=ask-model]') as HTMLInputElement | null)?.placeholder.includes('gpt-test-small'));
  const options = await p.locator('#ask-models option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
  assert.deepEqual(options, ['gpt-test-small', 'gpt-test-big'], 'listed ones only, the default first');
  await model.fill('gpt-test-big');
  await until(p, 'model saved', (x) => x.ask.settings.models.codex === 'gpt-test-big');
  await p.locator('[data-testid=ai-provider-claude-code]').click();
  await until(p, 'back to Claude Code', (x) => x.ask.settings.provider === 'claude-code');
});

test('signed out: Sign In opens the sign-in in your browser, the app sees it done, and Ask goes on; Codex too', async () => {
  const done = path.join(sb.root, 'signed-in');
  const codexDone = path.join(sb.root, 'codex-signed-in');
  fs.rmSync(done, { force: true });
  const p = await start({ FAKE_CLAUDE_AUTH: 'out', FAKE_CODEX_AUTH: 'out', FAKE_SIGN_IN_FILE: done, FAKE_SIGN_IN_SECONDS: '6' });
  await p.click('[data-testid=nav-ask]');
  const need = p.locator('[data-testid=agent-need]', { hasText: 'Sign In opens claude.ai\'s sign-in in your browser' });
  await need.waitFor({ timeout: 20_000 });
  assert.equal(await p.locator('[data-testid=agent-need] button[data-action=agent-open-terminal]').count(), 0, 'no Terminal');
  await need.locator('button[data-action=sign-in-claude-code]').click();
  // Under way: the app opens Claude Code's page, the one that comes back by itself, and can open it again.
  const page = 'https://claude.com/cai/oauth/authorize?code=true&redirect_uri=http%3A%2F%2Flocalhost%3A54545%2Fcallback';
  await until(p, 'the sign-in page', () => opened().includes(page), 10_000);
  const under = p.locator('[data-testid=agent-need]');
  assert.match(await under.innerText(), /It comes back here by itself/);
  await under.locator('button[data-action=reopen-sign-in-claude-code]', { hasText: 'Open the Page Again' }).click();
  await until(p, 'opened again', () => opened().split(page).length === 3, 10_000);
  assert.equal(await under.locator('[data-testid=paste-code-claude-code]').count(), 0, 'no code to paste');
  // Done in the browser: the app notices by itself, and Ask is ready.
  await until(p, 'signed in', (x) => x.ask.signIn?.['claude-code']?.state === 'in' && !x.ask.signingIn?.['claude-code'], 20_000);
  await under.waitFor({ state: 'detached', timeout: 10_000 });
  // Codex, from its row in AI Settings.
  fs.renameSync(done, codexDone);
  await p.click('[data-testid=nav-ai]');
  const row = p.locator('[data-testid=ai-provider-codex]');
  await row.locator('button[data-action=sign-in-codex]').click();
  await row.locator('text=It comes back here by itself').waitFor({ timeout: 10_000 });
  await until(p, 'Codex signed in', (x) => x.ask.signIn?.codex?.state === 'in', 20_000);
  await row.locator('text=Signed in with ChatGPT').waitFor({ timeout: 10_000 });
  assert.deepEqual(run!.errors, []);
});

test('Claude Code\'s page can\'t get back: Use a Code Instead opens the one that ends with a code, pasted in the app', async () => {
  const done = path.join(sb.root, 'pasted-in');
  fs.rmSync(done, { force: true });
  const p = await start({ FAKE_CLAUDE_AUTH: 'out', FAKE_CODEX_AUTH: 'out', FAKE_SIGN_IN_FILE: done, FAKE_SIGN_IN_PASTE: '1' });
  await p.click('[data-testid=nav-ai]');
  const row = p.locator('[data-testid=ai-provider-claude-code]');
  await row.locator('button[data-action=sign-in-claude-code]').click();
  await row.locator('button[data-action=sign-in-code-page-claude-code]', { hasText: 'Use a Code Instead' }).click();
  await until(p, 'the code page', () => opened().includes('redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback'), 10_000);
  const box = row.locator('[data-testid=paste-code-claude-code]');
  await box.waitFor({ timeout: 10_000 });
  assert.match(await row.innerText(), /paste the code it shows here/);
  await box.locator('[data-testid=sign-in-code-claude-code]').fill('not the code');
  await box.locator('button[data-action=send-sign-in-code-claude-code]').click();
  await box.locator('text=That doesn\'t look like the code from the page.').waitFor({ timeout: 5_000 });
  await box.locator('[data-testid=sign-in-code-claude-code]').fill('fake-code#state');
  await box.locator('button[data-action=send-sign-in-code-claude-code]').click();
  await until(p, 'signed in', (x) => x.ask.signIn?.['claude-code']?.state === 'in' && !x.ask.signingIn?.['claude-code'], 20_000);
  await row.locator('[data-testid=signed-in-claude-code]').waitFor({ timeout: 10_000 });
  assert.deepEqual(run!.errors, []);
});

test('an export on its way: Look in Your Email asks which inbox, and Gmail opens searched for mail from it since you asked', async () => {
  const p = run!.page;
  const s = await until(p, 'discord on its way', (x) => find(x, 'discord').actions.some((a) => a.id === 'open-inbox'));
  // The Gmail address, and Mail (this made-up Mac has it set up); the work address has no webmail it knows.
  assert.deepEqual(find(s, 'discord').inboxes?.map((x) => x.app), ['Gmail', 'Mail']);
  assert.equal(find(s, 'discord').actions.find((a) => a.id === 'open-inbox')?.label, 'Look in Your Email…');
  await p.click('[data-testid=nav-working]');
  await p.locator('[data-testid=row-discord]').click();
  await p.locator('[data-testid=detail][data-source=discord] button[data-action=open-inbox]').click();
  await p.locator('[data-testid=inbox-choice] [data-testid="inbox-ada.lovelace@gmail.com"]').click();
  const log = path.join(sb.userData, 'opened.txt');
  await until(p, 'opened', () => fs.existsSync(log) && fs.readFileSync(log, 'utf8').includes('mail.google.com'));
  const url = fs.readFileSync(log, 'utf8').trim().split('\n').filter((l) => l.includes('mail.google.com')).pop()!;
  assert.match(url, /authuser=ada\.lovelace%40gmail\.com/);
  assert.match(decodeURIComponent(url), /#search\/from:\(discord\.com OR discordapp\.com\) after:\d{4}\/\d+\/\d+$/);
  // Mail is an app: opened (in a test, written down instead).
  await p.locator('[data-testid=detail][data-source=discord] button[data-action=open-inbox]').click();
  await p.locator('[data-testid=inbox-choice] [data-testid=inbox-mail]').click();
  await until(p, 'Mail opened', () => fs.readFileSync(log, 'utf8').includes('app: Mail'));
  assert.deepEqual(run!.errors, []);
});
