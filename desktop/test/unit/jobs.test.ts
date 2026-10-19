import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { BridgeEvent, StreamResult } from '../../src/main/bridge.ts';
import { errorsBySource, type Finished, type Job, JobQueue, labelFor, type Runner } from '../../src/main/jobs.ts';

// A runner the test drives by hand: each started job waits until finish() is called.
function harness() {
  const started: { job: Job; emit: (e: BridgeEvent) => void; finish: (r?: Partial<StreamResult>) => void; killed: boolean; stdinSeen?: string }[] = [];
  const runner: Runner = (job, onEvent) => {
    let resolve!: (r: StreamResult) => void;
    const done = new Promise<StreamResult>((r) => (resolve = r));
    const h = {
      job, emit: onEvent, killed: false, stdinSeen: job.stdin,
      finish: (r: Partial<StreamResult> = {}) => resolve({ code: 0, signal: null, failed: [], errors: {}, ...r }),
    };
    started.push(h);
    return { done, kill: () => { h.killed = true; h.finish({ code: null, signal: 'SIGTERM' }); } };
  };
  const q = new JobQueue(runner, () => new Date('2026-10-08T12:00:00Z'));
  const finished: Finished[] = [];
  q.onFinish((f) => finished.push(f));
  return { q, started, finished };
}

const tick = () => new Promise((r) => setImmediate(r));

test('runs one job at a time, in order', async () => {
  const { q, started, finished } = harness();
  q.add({ kind: 'connectors', label: 'a', sourceIds: ['imessage'], connectors: ['imessage'] });
  q.add({ kind: 'iphone', label: 'b', sourceIds: ['iphone_backup'], connectors: ['iphone'] });
  assert.equal(started.length, 1);
  assert.deepEqual(q.list().map((j) => j.state), ['running', 'queued']);
  started[0].finish();
  await tick();
  assert.equal(started.length, 2);
  assert.equal(started[1].job.kind, 'iphone');
  started[1].finish();
  await tick();
  assert.equal(q.busy(), false);
  assert.deepEqual(finished.map((f) => f.job.label), ['a', 'b']);
});

test("held: what's queued waits, the running job carries on, and they start once it's let go", async () => {
  const { q, started } = harness();
  q.add({ kind: 'connectors', label: 'a', sourceIds: ['imessage'], connectors: ['imessage'] });
  const release = q.hold();
  assert.equal(q.runningNow(), true);
  q.add({ kind: 'import', label: 'b', sourceIds: ['x'], connectors: ['imports'] });
  started[0].finish();
  await tick();
  assert.equal(q.runningNow(), false);
  assert.equal(started.length, 1, 'nothing new starts while held');
  assert.deepEqual(q.list().map((j) => j.state), ['queued']);
  const second = q.hold();
  release();
  release(); // twice is once
  await tick();
  assert.equal(started.length, 1, 'still held by the other');
  second();
  await tick();
  assert.equal(started.length, 2);
  assert.equal(started[1].job.label, 'b');
});

test('queued connector jobs merge; a duplicate of the running job is dropped', async () => {
  const { q, started } = harness();
  const first = q.add({ kind: 'connectors', label: 'x', sourceIds: ['imessage'], connectors: ['imessage'] });
  assert.equal(q.add({ kind: 'connectors', label: 'x', sourceIds: ['imessage'], connectors: ['imessage'] }), first);
  const queued = q.add({ kind: 'connectors', label: 'y', sourceIds: ['photos'], connectors: ['photos'] });
  const merged = q.add({ kind: 'connectors', label: 'z', sourceIds: ['apple_notes', 'photos'], connectors: ['apple_notes', 'photos'] });
  assert.equal(merged, queued);
  assert.deepEqual(merged.connectors, ['photos', 'apple_notes']);
  assert.equal(merged.label, 'Reading 2 sources on this Mac');
  assert.equal(q.list().length, 2);
  started[0].finish();
  await tick();
  assert.deepEqual(started[1].job.sourceIds, ['photos', 'apple_notes']);
});

test('import jobs merge too, iPhone jobs never do', () => {
  const { q } = harness();
  q.add({ kind: 'iphone', label: 'p', sourceIds: ['iphone_backup'], connectors: ['iphone'] });
  q.add({ kind: 'iphone', label: 'p', sourceIds: ['iphone_backup'], connectors: ['iphone'] });
  const a = q.add({ kind: 'import', label: 'i', sourceIds: ['discord'], connectors: ['imports'] });
  const b = q.add({ kind: 'import', label: 'i', sourceIds: ['linkedin'], connectors: ['imports'] });
  assert.equal(a, b);
  assert.deepEqual(b.sourceIds, ['discord', 'linkedin']);
  assert.deepEqual(q.list().map((j) => j.kind), ['iphone', 'iphone', 'import']);
});

test('cancel: queued jobs vanish, the running one is killed', async () => {
  const { q, started, finished } = harness();
  q.add({ kind: 'connectors', label: 'run', sourceIds: ['photos'], connectors: ['photos'] });
  const later = q.add({ kind: 'iphone', label: 'later', sourceIds: ['iphone_backup'], connectors: ['iphone'] });
  assert.ok(q.cancel(later.id));
  assert.equal(q.list().length, 1);
  assert.ok(q.cancelForSource('photos'));
  await tick();
  assert.ok(started[0].killed);
  assert.equal(finished[0].cancelled, true);
  assert.equal(q.busy(), false);
  assert.equal(q.cancel('nope'), false);
});

test('cancelAll empties the queue and stops the running job', async () => {
  const { q, started, finished } = harness();
  q.add({ kind: 'connectors', label: 'a', sourceIds: ['photos'], connectors: ['photos'] });
  q.add({ kind: 'iphone', label: 'b', sourceIds: ['iphone_backup'], connectors: ['iphone'] });
  q.cancelAll();
  await tick();
  assert.ok(started[0].killed);
  assert.equal(started.length, 1, 'the queued job never starts');
  assert.equal(finished.length, 1);
  assert.equal(q.busy(), false);
});

test('the password reaches the runner and is then dropped', async () => {
  const { q, started } = harness();
  const j = q.add({ kind: 'iphone', label: 'p', sourceIds: ['iphone_backup'], connectors: ['iphone'], stdin: 'secret\n' });
  assert.equal(started[0].stdinSeen, 'secret\n');
  assert.equal(j.stdin, undefined);
  assert.ok(!JSON.stringify(q.list()).includes('secret'));
});

test('events update the running job and its log', () => {
  const { q, started } = harness();
  const lines: string[] = [];
  q.onLine((_j, l) => lines.push(l));
  let changes = 0;
  q.onChange(() => changes++);
  const j = q.add({ kind: 'connectors', label: 'r', sourceIds: ['imessage'], connectors: ['imessage'] });
  started[0].emit({ type: 'start', connector: 'imessage' });
  started[0].emit({ type: 'log', connector: 'imessage', line: '[imessage] 12 records' });
  started[0].emit({ type: 'error', connector: 'imessage', error: 'locked' });
  for (let i = 0; i < 500; i++) started[0].emit({ type: 'raw', line: `line ${i}` });
  assert.equal(j.current, 'imessage');
  assert.equal(j.lastLine, 'line 499');
  assert.equal(j.log.length, 400);
  assert.equal(lines[0], '[imessage] 12 records');
  assert.equal(lines[1], 'imessage: locked');
  assert.ok(changes > 500);
  assert.equal(q.list()[0].startedAt, '2026-10-08T12:00:00.000Z');
});

test('a line is only progress; a start, an error or the end is a change (the window hears those at once)', async () => {
  const { q, started } = harness();
  const seen: boolean[] = [];
  q.onChange((progress) => seen.push(progress));
  q.add({ kind: 'import', label: 'i', sourceIds: ['spotify'], connectors: ['imports'] });
  started[0].emit({ type: 'start', connector: 'imports' });
  started[0].emit({ type: 'log', connector: 'imports', line: '[spotify] 3 records' });
  started[0].emit({ type: 'raw', line: 'Traceback' });
  started[0].emit({ type: 'error', connector: 'imports', error: 'boom' });
  started[0].finish();
  await tick();
  assert.deepEqual(seen, [false, false, false, true, true, false, false]);
});

test('an import asked to read everything again keeps asking when another merges into it', () => {
  const { q, started } = harness();
  q.add({ kind: 'connectors', label: 'busy', sourceIds: ['imessage'], connectors: ['imessage'] });
  q.add({ kind: 'import', label: 'again', sourceIds: ['spotify'], connectors: ['imports'], args: ['--reread'] });
  const j = q.add({ kind: 'import', label: 'new', sourceIds: ['x'], connectors: ['imports'] });
  assert.deepEqual(j.args, ['--reread']);
  assert.deepEqual(j.sourceIds, ['spotify', 'x']);
  assert.equal(started.length, 1);
});

test('errors land on the right sources', () => {
  const map = { imessage: 'imessage', photos: 'photos', iphone: 'iphone_backup' };
  const job = { id: 'j', kind: 'connectors', label: '', sourceIds: ['imessage', 'photos'], connectors: ['imessage', 'photos'], state: 'running', log: ['a', 'b', 'c', 'd'] } as Job;
  assert.deepEqual(errorsBySource(job, { code: 1, signal: null, failed: ['photos'], errors: { photos: 'boom' } }, map), { photos: 'boom' });
  assert.deepEqual(errorsBySource(job, { code: 1, signal: null, failed: ['build_index'], errors: { build_index: 'disk full' } }, map),
    { imessage: 'disk full', photos: 'disk full' });
  assert.deepEqual(errorsBySource(job, { code: 2, signal: null, failed: [], errors: {} }, map),
    { imessage: 'It stopped before it finished. The last thing it said: b c d', photos: 'It stopped before it finished. The last thing it said: b c d' });
  assert.deepEqual(errorsBySource(job, { code: 0, signal: null, failed: [], errors: {} }, map), {});
  const imp = { ...job, kind: 'import', sourceIds: ['discord', 'linkedin'] } as Job;
  assert.deepEqual(errorsBySource(imp, { code: 1, signal: null, failed: ['imports'], errors: { imports: 'BadZipFile' } }, map),
    { discord: 'BadZipFile', linkedin: 'BadZipFile' });
});

test('import parser errors find the export that caused them', () => {
  const parsers = { x_archive: ['x'], meta: ['instagram', 'facebook'], csv_exports: ['linkedin', 'reddit'] };
  const job = { id: 'j', kind: 'import', label: '', sourceIds: ['discord'], connectors: ['imports'], state: 'running', log: [] } as unknown as Job;
  const res = (errors: Record<string, string>) => ({ code: 1, signal: null, failed: Object.keys(errors), errors });
  // an old X export breaks while importing Discord: the error is X's, Discord is fine
  const why = (_m: string) => 'Couldn\'t read this export: the site may have changed its format. What went wrong is in the Progress log below.';
  assert.deepEqual(errorsBySource(job, res({ 'imports:x_archive': 'KeyError' }), {}, parsers), { x: why('KeyError') });
  // Meta's parser fails: blame the Meta export that has a file waiting
  assert.deepEqual(errorsBySource(job, res({ 'imports:meta': 'boom' }), {}, parsers, (id) => id === 'facebook'), { facebook: why('boom') });
  // ...or the one this job was importing
  const both = { ...job, sourceIds: ['linkedin', 'discord'] } as Job;
  assert.deepEqual(errorsBySource(both, res({ 'imports:csv_exports': 'bad csv' }), {}, parsers), { linkedin: why('bad csv') });
  // an unknown parser falls back to the job's sources
  assert.deepEqual(errorsBySource(job, res({ 'imports:new_thing': 'x' }), {}, parsers), { discord: 'x' });
});

test('labels', () => {
  assert.equal(labelFor({ kind: 'connectors', connectors: ['photos'] }), 'Reading Photos', 'by the source\'s name');
  assert.equal(labelFor({ kind: 'connectors', connectors: ['calendar_events'] }), 'Reading Calendar');
  assert.equal(labelFor({ kind: 'connectors', connectors: [] }), 'Reading this Mac', 'never "Reading undefined"');
  assert.equal(labelFor({ kind: 'connectors', connectors: ['a', 'b', 'c'] }), 'Reading 3 sources on this Mac');
  assert.equal(labelFor({ kind: 'iphone', connectors: [] }), 'Reading the iPhone backup');
  assert.equal(labelFor({ kind: 'import', connectors: [] }), 'Importing downloaded exports');
});
