// Quitting in the middle of things. The app is killed (as a crash or a forced quit would) while it reads the Mac;
// the next launch has to pick up where it was: nothing stuck as "working", every source read, the corpus whole.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, until } from './harness.ts';

let sb: Sandbox;
let run: Running | null = null;

before(() => {
  sb = sandbox({ identity: true }); // knowing who you are, it starts reading the Mac on its own
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('killed mid-read, the next launch finishes the job', async () => {
  const env = sandboxEnv(sb);
  run = await launch(env);
  await until(run.page, 'a read under way', (x) => x.jobs.some((j) => j.state === 'running'));
  run.app.process().kill('SIGKILL');
  run = null;
  await new Promise((r) => setTimeout(r, 500));

  run = await launch(env);
  // Read again, not just idle: right after launch there's a moment before the read is queued, when what the killed
  // run read already shows as done. The index, built last, says the job was finished.
  const ids = ['ai_coding', 'documents', 'git_commits']; // what this fake Mac has
  const db = path.join(sb.corpus, 'corpus.db');
  const s = await until(run.page, 'everything read', (x) => !x.jobs.length && ids.every((id) => find(x, id).section === 'done') && fs.existsSync(db), 120_000);
  for (const id of ids) {
    assert.equal(find(s, id).section, 'done', `${id} read after the restart`);
    assert.ok((find(s, id).records ?? 0) > 0, `${id} has its records`);
  }
  const manifest = readJson(path.join(sb.corpus, 'manifest.json')); // whole, not half-written
  assert.ok(manifest.documents?.count > 0);
  assert.ok(fs.existsSync(db));
});
