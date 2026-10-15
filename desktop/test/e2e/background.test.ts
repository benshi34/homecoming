// Keep working when the window is closed: closing it leaves the app running in the menu bar, and opening it again
// (the Dock, the menu bar item, a second launch) brings the window back. Off, closing the window quits as before.

import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { launch, type Running, type Sandbox, sandbox, sandboxEnv } from './harness.ts';

let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox({ identity: true });
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_BACKGROUND: '1' }));
});
after(async () => {
  await run?.close().catch(() => {});
  sb?.cleanup();
});

const windows = () => run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length);

test('closing the window keeps the app in the menu bar; activating it brings the window back', async () => {
  await run.page.evaluate(() => (window as unknown as { api: { settings(p: object): Promise<unknown> } }).api.settings({ background: true }));
  await run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
  for (let i = 0; i < 40 && (await windows()) > 0; i++) await new Promise((r) => setTimeout(r, 100));
  assert.equal(await windows(), 0);
  await new Promise((r) => setTimeout(r, 800));
  assert.equal(await run.app.evaluate(({ app }) => app.isReady()), true, 'still running');
  const back = run.app.waitForEvent('window');
  await run.app.evaluate(({ app }) => void app.emit('activate'));
  const page = await back;
  await page.waitForSelector('[data-testid=app]', { timeout: 30_000 });
  assert.equal(await windows(), 1);
});
