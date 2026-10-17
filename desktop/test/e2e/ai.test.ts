// The AI page: turned on once, with which agent, and off again. The agent picked shows what it needs right under it
// (an API key's field). With it off, nothing offers AI: Ask says so and turns it on in place (through the agreement if
// it was never agreed to), and the export pages have no Do It for Me. Claude Code and Codex are stand-ins (test/fakes).

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, snap, until } from './harness.ts';

const SHOTS = process.env.UMP_SHOTS; // also save the screens looked at here, to this folder
const look = async (name: string) => {
  await shot(run.page, name);
  if (SHOTS) await run.page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};

let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox({ identity: true });
  fs.mkdirSync(path.join(sb.home, 'Applications/Google Chrome.app'), { recursive: true }); // a browser Claude in Chrome runs in
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

test('Not Now on Ask\'s first page: AI is off, and turning it on there goes through the agreement', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-ai-gate] [data-testid=ai-agreement]').waitFor();
  await p.locator('button[data-action=ai-not-now]').click();
  await until(p, 'not now', (x) => x.settings.aiOn === false && !x.settings.aiAgreedAt);
  const off = p.locator('[data-testid=ask-ai-off]');
  await off.locator('button[data-action=ask-ai-on]', { hasText: 'Turn On AI…' }).click();
  await p.locator('[data-testid=ask-ai-gate] [data-testid=ai-agreement]').waitFor();
  assert.equal((await snap(p)).settings.aiOn, false, 'not turned on by itself');
  await p.locator('button[data-action=ai-not-now]').click();
  await off.waitFor();
  assert.equal((await snap(p)).settings.aiOn, false);
});

test('AI is agreed to once, its agent picked, and turned off and on', async () => {
  const p = run.page;
  // AI Settings, so it isn't taken for a place to talk to an AI: in a Settings section of its own (after Your Setup), last.
  assert.match(await p.locator('[data-testid=sidebar]').innerText(), /Setup Checks[\s\S]*\bSettings\s+Your Setup\s+AI Settings\s+[\d,]+ of [\d,]+ sources collected/);
  await p.locator('[data-testid=nav-ai]').click();
  const page = p.locator('[data-testid=ai-page]');
  await page.waitFor();
  assert.equal(await page.locator('.toolbar h1').innerText(), 'AI Settings');
  assert.match(await page.locator('[data-testid=ai-agreement]').innerText(), /Nothing goes to an AI until you turn this on/);
  await shot(p, 'ai-page-agreement');
  await page.locator('button[data-action=ai-on]').click();
  let s = await until(p, 'on', (x) => x.settings.aiOn === true && !!x.settings.aiAgreedAt);
  await page.locator('[data-testid=toggle-ai][aria-checked=true]').waitFor();
  assert.equal(await page.locator('[data-testid=ai-agreement]').count(), 0, 'asked once');
  // It says what it is: one agent, and only Do It for Me with a switch of its own.
  assert.match(await page.locator('.ai-hero p').innerText(), /Ask and making sense of a download use it only when you ask; Do It for Me can be turned on or off/);
  assert.doesNotMatch(await page.innerText(), /turn each use of it on or off/);

  // An API key: its field is right under the choice, focused, saying where to get one. No other sheet to find.
  assert.equal(await page.locator('[data-testid=ai-model]').count(), 0, 'no "Model, key and server…" row');
  await page.locator('[data-testid=ai-provider-anthropic]').click();
  const key = page.locator('[data-testid=provider-detail] [data-testid=ask-key]');
  await key.waitFor();
  assert.equal(await key.evaluate((e) => e === document.activeElement), true, 'ready to paste into');
  assert.match(await page.locator('[data-testid=key-anthropic]').innerText(), /Paste it here\. It's kept encrypted with your Mac's Keychain\. Make one at console\.anthropic\.com\./);
  assert.match(await page.locator('[data-testid=ai-provider-anthropic] .warn-text').innerText(), /Needs a key/);
  await look('ai-page-anthropic-key');
  // Its model, with the default shown when the field is empty.
  assert.match(await page.locator('[data-testid=provider-detail] [data-testid=ask-model]').getAttribute('placeholder') ?? '', /claude-sonnet-5-5 \(Sonnet 5\.5, the default\)/);

  // Codex for the agent: Ask and the download helper use it; Do It for Me stays with Claude, and says why.
  await page.locator('[data-testid=ai-provider-codex]').click();
  s = await until(p, 'Codex picked', (x) => x.ask.settings.provider === 'codex' && x.claude === 'codex');
  // Its model can be picked too (empty: Codex's own default), and its row says whether it's signed in.
  await page.locator('[data-testid=provider-detail] [data-testid=ask-model]').waitFor();
  await page.locator('[data-testid=ai-provider-codex]', { hasText: /Signed in with ChatGPT|Uses the sign-in in Codex/ }).waitFor();
  await page.getByText(/It's Claude even with Codex picked above: Codex can use a browser only inside its own app/).waitFor();
  await look('ai-page-codex');
  await p.emulateMedia({ colorScheme: 'dark' });
  await look('ai-page-dark');
  await p.emulateMedia({ colorScheme: 'light' });

  // Off: Ask says so, and nothing offers to do an export for you.
  await page.locator('[data-testid=toggle-ai]').click();
  s = await until(p, 'off', (x) => x.settings.aiOn === false);
  assert.ok(!find(s, 'instagram').actions.some((a) => a.id.startsWith('agent-')));
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-ai-off]').waitFor();
  await look('ai-off-ask');
  await selectSource(p, 'instagram');
  assert.equal(await p.locator('button[data-action=agent-request]').count(), 0);

  // Back on from Ask's notice, in place (agreed to before), or from AI Settings.
  await p.locator('[data-testid=nav-ask]').click();
  assert.equal(await p.locator('button[data-action=open-ai]').count(), 1);
  await p.locator('[data-testid=ask-ai-off] button[data-action=ask-ai-on]', { hasText: /^Turn On AI$/ }).click();
  s = await until(p, 'on again', (x) => x.settings.aiOn === true);
  await p.locator('[data-testid=ask-input]').waitFor();
  assert.ok(find(s, 'instagram').actions.some((a) => a.id === 'agent-request' && a.ai));
  await p.locator('[data-testid=nav-ai]').click();
  await page.locator('[data-testid=toggle-ai][aria-checked=true]').waitFor();
  assert.deepEqual(run.errors, []);
});
