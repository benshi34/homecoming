// Your Stream with almost nothing in it: a latest month whose records are all left out, a month before it with one
// call, and then a corpus with no dated records at all. Nothing should break, and nothing should look broken.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, test } from 'node:test';
import { launch, REPO, type Running, type Sandbox, sandbox, sandboxEnv } from './harness.ts';

const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
let sb: Sandbox | undefined;
let run: Running | undefined;
after(async () => {
  await run?.close();
  sb?.cleanup();
});

// A fresh sandbox with just these records, indexed, and the app open on it (the last one closed first, whatever
// happened in the test before).
async function start(records: Record<string, unknown>[]) {
  await run?.close();
  run = undefined;
  sb?.cleanup();
  sb = sandbox();
  const norm = path.join(sb.corpus, 'normalized');
  fs.mkdirSync(norm, { recursive: true });
  fs.writeFileSync(path.join(sb.corpus, 'identity.json'), JSON.stringify({ names: ['Ada Lovelace'], emails: [], usernames: [], phones: [] }));
  const by = new Map<string, Record<string, unknown>[]>();
  for (const r of records) by.set(String(r.source), [...(by.get(String(r.source)) ?? []), r]);
  for (const [s, rows] of by) fs.writeFileSync(path.join(norm, `${s}.jsonl`), rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
  execFileSync(PY, [path.join(REPO, 'connectors/build_index.py')], { env: { ...process.env, CORPUS_DIR: sb.corpus, UMP_TZ: 'UTC' } });
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_TZ: 'UTC' }));
}

async function openStream() {
  const p = run!.page;
  await p.emulateMedia({ reducedMotion: 'reduce' });
  await p.click('[data-testid=nav-explore]');
  await p.locator('[data-testid=explore-card-stream][data-ready=yes]').waitFor({ timeout: 60_000 });
  await p.click('[data-testid=explore-card-stream]');
  await p.locator('[data-testid=explore-stream]').waitFor({ timeout: 60_000 });
  return p;
}

test('a month whose records are all left out is empty, and the one before has its single call', async () => {
  await start([
    { id: 'h1', source: 'health_samples', kind: 'health_sample', ts: '2026-09-10T12:00:00Z', meta: { steps: 10 } },
    { id: 'f1', source: 'phone_filesapp', kind: 'record', ts: '2026-09-11T12:00:00Z', meta: { tier: 'device' } },
    { id: 'c1', source: 'calls', kind: 'call', ts: '2026-08-20T18:00:00Z', thread_name: 'Grace Hopper', meta: { direction: 'outgoing', seconds: 300 } },
  ]);
  const p = await openStream();
  assert.match(await p.locator('.explore-hero').innerText(), /0\s+events in September 2026[\s\S]*2 records aren't events/);
  await p.locator('[data-testid=stream-none]').waitFor();
  assert.equal(await p.locator('[data-testid=stream-day-jump]').count(), 30);
  assert.equal(await p.locator('[data-testid=stream-day-jump]:not([disabled])').count(), 0);
  assert.equal((await p.locator('[data-testid=stream-kind-all]').innerText()).replace(/\s+/g, ' '), 'Everything 0');
  assert.match(await p.locator('[data-testid=stream-file]').innerText(), /isn't saved as a file yet/, 'no file for a month with no events');
  await p.click('[data-testid=stream-prev]');
  await p.locator('[data-testid=stream-event]').first().waitFor({ timeout: 60_000 });
  assert.equal(await p.locator('[data-testid=stream-event]').count(), 1);
  // textContent, not innerText: a day not drawn yet (content-visibility) has no innerText.
  assert.match(await p.locator('[data-testid=stream-event]').textContent() ?? '', /Called Grace Hopper \(5 min\)/);
  await p.locator('[data-testid=stream-event] .stream-row').click();
  await p.locator('[data-testid=stream-more] button[data-action=stream-record]').click();
  await p.locator('[data-testid=ask-record] h2').waitFor();
  await p.keyboard.press('Escape');
  assert.equal(await p.locator('[data-testid=stream-prev]').isDisabled(), true, 'nothing earlier');
  await p.click('[data-testid=stream-next]');
  await p.locator('[data-testid=stream-none]').waitFor({ timeout: 60_000 });
  assert.deepEqual(run!.errors, []);
});

test('a corpus with no dated records: this month, empty, and nothing to step to', async () => {
  await start([{ id: 'x1', source: 'contacts', kind: 'contact', title: 'Grace Hopper' }]);
  const p = await openStream();
  assert.match(await p.locator('.explore-hero').innerText(), /0\s+events in/);
  await p.locator('[data-testid=stream-none]').waitFor();
  assert.equal(await p.locator('[data-testid=stream-month] option').count(), 1, 'the month it shows');
  assert.equal(await p.locator('[data-testid=stream-prev]').isDisabled(), true);
  assert.equal(await p.locator('[data-testid=stream-next]').isDisabled(), true);
  assert.equal(await p.locator('[data-testid=stream-search]').count(), 1);
  await p.fill('[data-testid=stream-search]', 'anything');
  await p.locator('[data-testid=stream-none]', { hasText: 'Nothing this month matches' }).waitFor();
  assert.deepEqual(run!.errors, []);
});
