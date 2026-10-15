// The AI page: turned on once, with which agent, and off again. With it off, nothing offers AI: Ask says so and
// points back here, and the export pages have no Do It for Me. Claude Code and Codex are stand-ins (test/fakes).

import assert from 'node:assert/strict';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox({ identity: true });
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1',
    UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), UMP_CODEX_CMD: path.join(DESKTOP, 'test/fakes/fake_codex.py'),
  }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('AI is agreed to once, its agent picked, and turned off and on', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-ai]').click();
  const page = p.locator('[data-testid=ai-page]');
  await page.waitFor();
  assert.match(await page.locator('[data-testid=ai-agreement]').innerText(), /Nothing goes to an AI until you turn this on/);
  await shot(p, 'ai-page-agreement');
  await page.locator('button[data-action=ai-on]').click();
  let s = await until(p, 'on', (x) => x.settings.aiOn === true && !!x.settings.aiAgreedAt);
  await page.locator('[data-testid=toggle-ai][aria-checked=true]').waitFor();
  assert.equal(await page.locator('[data-testid=ai-agreement]').count(), 0, 'asked once');

  // Codex for the agent: Ask and the download helper use it; Do It for Me stays with Claude, and says why.
  await page.locator('[data-testid=ai-provider-codex]').click();
  s = await until(p, 'Codex picked', (x) => x.ask.settings.provider === 'codex' && x.claude === 'codex');
  await page.getByText(/It's Claude even with Codex picked above: Codex can use a browser only inside its own app/).waitFor();
  await shot(p, 'ai-page-codex');
  await p.emulateMedia({ colorScheme: 'dark' });
  await shot(p, 'ai-page-dark');
  await p.emulateMedia({ colorScheme: 'light' });

  // Off: Ask says so, and nothing offers to do an export for you.
  await page.locator('[data-testid=toggle-ai]').click();
  s = await until(p, 'off', (x) => x.settings.aiOn === false);
  assert.ok(!find(s, 'instagram').actions.some((a) => a.id.startsWith('agent-')));
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-ai-off]').waitFor();
  await shot(p, 'ai-off-ask');
  await selectSource(p, 'instagram');
  assert.equal(await p.locator('button[data-action=agent-request]').count(), 0);

  // Back on from Ask's notice.
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('button[data-action=open-ai]').click();
  await page.locator('[data-testid=toggle-ai]').click();
  s = await until(p, 'on again', (x) => x.settings.aiOn === true);
  assert.ok(find(s, 'instagram').actions.some((a) => a.id === 'agent-request' && a.ai));
  assert.deepEqual(run.errors, []);
});
