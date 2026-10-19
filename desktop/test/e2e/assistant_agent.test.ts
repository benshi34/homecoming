// The Setup Assistant's exports with Do It for Me there to use (the stand-in for Claude Code in Chrome): the list
// offers Ask Claude for All first, and each page's main button is Do It for Me (asking the first time), which starts
// Claude and goes on to the next; asking for them all goes on past the exports.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { confirmClaudeSheet, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const file = (n: string) => path.join(sb.home, n);
const step = () => run.page.locator('[data-testid=assistant]').getAttribute('data-step');

before(async () => {
  sb = sandbox({ identity: true });
  fs.writeFileSync(file('plan.json'), JSON.stringify({ request: [{ steps: ['Requesting the export'], result: 'requested', sleep: 0.3 }], download: [] }));
  const keep = ['instagram', 'spotify'];
  const sources = Object.fromEntries(Object.values(BY_ID).filter((s) => s.group === 'web' && !keep.includes(s.id)).map((s) => [s.id, { skipped: 'I don\'t use it' }]));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({
    version: 1, onboarding: { done: false, step: 'exports', chosen: keep }, sources,
    settings: { autoRefresh: false, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString() },
  }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'), FAKE_BROWSER_LOG: file('agent.log'),
  }), { assistant: true });
  await until(run.page, 'probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('a page\'s main button is Do It for Me: asked once, Claude starts, and on to the next', async () => {
  const p = run.page;
  assert.equal(await step(), 'exports');
  assert.match(await p.locator('[data-testid=ask-all-box]').innerText(), /Claude can ask for 2 of these for you/);
  await shot(p, 'assistant-ask-all');
  const go = p.locator('button[data-action=assistant-continue]');
  assert.equal(await go.innerText(), 'One by One: Spotify', 'one by one is the other way in');
  await go.click();
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'export:spotify');
  assert.equal(await go.innerText(), 'Do It for Me');
  await go.click();
  await p.locator('[data-testid=agent-opt-in] button[data-action=agent-on]').click();
  // Then Anthropic's data settings, as Ask has them, before Claude first works in the browser.
  await confirmClaudeSheet(p);
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'export:instagram');
  await until(p, 'Spotify asked for', (x) => !!find(x, 'spotify').requestedAt, 20_000);
});

test('Ask Claude for All on the list: Claude asks for the rest, and the Setup Assistant goes on past the exports', async () => {
  const p = run.page;
  await p.locator('button[data-action=all-exports]').click();
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'exports');
  const box = p.locator('[data-testid=ask-all-box]');
  assert.match(await box.innerText(), /Claude can ask for it for you/);
  await box.locator('button[data-action=ask-all]').click();
  await p.locator('[data-testid=request-all] button[data-action=ra-ask]', { hasText: 'Ask Claude for Instagram' }).click();
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'identity');
  await until(p, 'Instagram asked for', (x) => !!find(x, 'instagram').requestedAt, 20_000);
  assert.deepEqual(run.errors, []);
  assert.equal((await snap(p)).onboarding.step, 'identity');
});
