// Claude at work, on the Overview and in the Setup Assistant (renderer/claude_work.tsx): its first look at each site and
// what it's waiting for you to do there, each service in turn, how far Ask for Everything has got, and Stop, for one or
// for all, even during that first look (before any service has started).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { act, claudeChecked, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const file = (n: string) => path.join(sb.home, n);
const runs = () => (fs.existsSync(file('agent.log')) ? fs.readFileSync(file('agent.log'), 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : []);

before(async () => {
  sb = sandbox({ identity: true });
  fs.writeFileSync(file('plan.json'), JSON.stringify({
    // The first look: Chrome asks to allow Claude on Instagram, and Claude waits (long enough to be stopped); then a quick one.
    visit: [
      { steps: ['Opening Instagram', 'WAITING: Allow Claude on instagram.com in Chrome.', 'OPENED: https://accountscenter.instagram.com/info_and_permissions/dyi/'], result: 'requested', sleep: 4 },
      { steps: ['OPENED: https://accountscenter.instagram.com/info_and_permissions/dyi/', 'OPENED: https://www.spotify.com/account/privacy/'], result: 'requested', sleep: 0.2 },
    ],
    request: [{ steps: ['Opening Instagram\'s download page', 'Choosing all of your data'], result: 'requested', sleep: 4 }],
  }));
  const keep = ['instagram', 'spotify'];
  const sources = Object.fromEntries(Object.values(BY_ID).filter((s) => s.group === 'web' && !keep.includes(s.id)).map((s) => [s.id, { skipped: 'I don\'t use it' }]));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, ask: claudeChecked(), onboarding: { done: true }, sources,
    settings: { autoRefresh: false, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true, agentDownloads: true, agentChecks: false } }));
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'),
    FAKE_BROWSER_LOG: file('agent.log'), UMP_NOTIFICATIONS_DB: path.join(sb.home, 'no-notifications/db') }));
  await until(run.page, 'probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('the first look at each site, waiting for you in Chrome, on the Overview; Stop All stops it, and nothing starts after', async () => {
  const p = run.page;
  await p.click('[data-testid=nav-overview]');
  await act(p, '*', 'request-all', { ids: ['instagram', 'spotify'] });
  const box = p.locator('[data-testid=overview] [data-testid=claude-work]');
  await box.waitFor({ timeout: 10_000 });
  assert.match(await box.innerText(), /Claude is opening each site first/);
  assert.match(await box.innerText(), /0 of 2 done/);
  await box.locator('[data-testid=claude-work-instagram]').waitFor();
  await box.locator('[data-testid=claude-work-spotify]').waitFor();
  // Chrome asks to allow Claude: said at the top, with the way there.
  await box.locator('[data-testid=claude-work-title]', { hasText: 'Claude needs you in Chrome' }).waitFor({ timeout: 15_000 });
  assert.match(await box.innerText(), /Allow Claude on instagram\.com in Chrome/);
  await box.locator('button[data-action=claude-work-open]').waitFor();
  await shot(p, 'claude-work-waiting');
  await box.locator('button[data-action=agent-stop-all]').click();
  await box.waitFor({ state: 'detached', timeout: 10_000 });
  const s = await until(p, 'both stopped', (x) => !x.claudeWork?.visit && ['instagram', 'spotify'].every((id) => !find(x, id).actions.some((a) => a.id === 'agent-stop')), 10_000);
  assert.equal(s.claudeWork?.batch, null, 'the batch is over');
  await new Promise((r) => setTimeout(r, 1500));
  assert.deepEqual(runs().map((r) => r.mode ?? (/Request a full export/.test(r.prompt) ? 'request' : 'visit')).filter((m) => m === 'request'), [], 'no export was asked for');
  assert.deepEqual(run.errors, []);
});

test('each in turn, how far it\'s got, Stop for one, Stop All for the rest; and the same in the Setup Assistant', async () => {
  const p = run.page;
  await act(p, '*', 'request-all', { ids: ['instagram', 'spotify'] });
  const box = p.locator('[data-testid=overview] [data-testid=claude-work]');
  await box.locator('[data-testid=claude-work-title]', { hasText: 'Claude is working on 2 services' }).waitFor({ timeout: 15_000 });
  assert.match(await box.innerText(), /0 of 2 done/);
  await box.locator('[data-testid=claude-work-instagram]', { hasText: 'Choosing all of your data' }).waitFor({ timeout: 10_000 });
  await shot(p, 'claude-work-running');
  // The Setup Assistant shows it too, a strip that opens to each.
  await p.locator('button[aria-label="Setup Assistant"]').first().click();
  const strip = p.locator('[data-testid=assistant] [data-testid=claude-work]');
  await strip.waitFor();
  assert.equal(await strip.locator('[data-testid=claude-work-spotify]').count(), 0, 'closed to start with');
  await strip.locator('button[data-action=claude-work-more]').click();
  await strip.locator('[data-testid=claude-work-spotify]').waitFor();
  // Stop for Spotify (waiting its turn): Instagram goes on.
  await strip.locator('button[data-action=claude-work-stop-spotify]').click();
  await strip.locator('[data-testid=claude-work-spotify]').waitFor({ state: 'detached', timeout: 10_000 });
  assert.ok(find(await until(p, 'instagram still', (x) => find(x, 'instagram').actions.some((a) => a.id === 'agent-stop')), 'instagram'));
  await p.locator('button[data-action=assistant-exit]').click();
  await p.click('[data-testid=nav-overview]');
  await box.locator('button[data-action=agent-stop-all]').click();
  await box.waitFor({ state: 'detached', timeout: 10_000 });
  await until(p, 'all stopped', (x) => !find(x, 'instagram').actions.some((a) => a.id === 'agent-stop'), 10_000);
  assert.deepEqual(run.errors, []);
});
