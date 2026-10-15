// The search index behind what was read (a read cut short before its last step) is rebuilt on launch; one that won't
// build is tried once, not again after every job.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, test } from 'node:test';
import { launch, type Running, type Sandbox, sandbox, sandboxEnv, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running | null = null;
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('an index that won\'t build is tried once', async () => {
  sb = sandbox();
  // Data read, no index; and a line in it the index can't take.
  fs.mkdirSync(path.join(sb.corpus, 'normalized'), { recursive: true });
  fs.writeFileSync(path.join(sb.corpus, 'normalized', 'broken.jsonl'), 'not json\n');
  fs.writeFileSync(path.join(sb.corpus, 'manifest.json'), '{}');
  run = await launch(sandboxEnv(sb));
  const started = (s: { log: { line: string }[] }) => s.log.filter((l) => l.line === 'Started: Rebuilding the search index').length;
  await until(run.page, 'tried', (x) => started(x) === 1 && !x.jobs.length, 60_000);
  // Jobs after it (the Mac being read, if it is) don't set it off again for the same data.
  await new Promise((r) => setTimeout(r, 4000));
  const s = await snap(run.page);
  const reads = s.log.filter((l) => /^Started: /.test(l.line) && !/search index/.test(l.line)).length;
  assert.ok(started(s) <= 1 + reads, `${started(s)} rebuilds for ${reads} reads`);
  assert.ok(!fs.existsSync(path.join(sb.corpus, 'corpus.db')));
  assert.ok(!s.log.some((l) => l.line.trim() === 'Read'), 'no empty "Read" toast'); // toasts are logged too
});
