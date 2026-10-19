import assert from 'node:assert/strict';
import { test, type TestContext } from 'node:test';
import { Pusher } from '../../src/main/push.ts';

function harness(t: TestContext) {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1_000_000 });
  const sent: number[] = [];
  const away: number[] = [];
  let visible = true;
  const p = new Pusher(() => sent.push(Date.now()), () => away.push(Date.now()), () => visible);
  return { p, sent, away, tick: (ms: number) => t.mock.timers.tick(ms), hide: (v: boolean) => (visible = !v) };
}

test('changes within a moment go as one snapshot, soon', (t) => {
  const { p, sent, tick } = harness(t);
  p.push();
  p.push();
  tick(119);
  assert.equal(sent.length, 0);
  tick(1);
  assert.equal(sent.length, 1);
  p.push();
  tick(120);
  assert.equal(sent.length, 2, 'a change after it goes too');
});

test('a running job\'s lines go at most once a second, and a real change still goes at once', (t) => {
  const { p, sent, tick } = harness(t);
  for (let i = 0; i < 50; i++) {
    p.push(true);
    tick(20);
  }
  assert.ok(sent.length <= 2, `${sent.length} snapshots in a second of lines`);
  const before = sent.length;
  for (let i = 0; i < 100; i++) {
    p.push(true);
    tick(20);
  }
  assert.ok(sent.length - before <= 3 && sent.length - before >= 1, `${sent.length - before} in two seconds`);
  for (let i = 1; i < sent.length; i++) assert.ok(sent[i] - sent[i - 1] >= 1000, 'a second apart');
  p.push(true);
  p.push(); // a job finished, say
  const n = sent.length;
  tick(120);
  assert.equal(sent.length, n + 1, 'not held back by the lines');
});

test('nothing goes to a window that can\'t be seen; the badge now and then; all of it once it can', (t) => {
  const { p, sent, away, tick, hide } = harness(t);
  hide(true);
  for (let i = 0; i < 100; i++) {
    p.push(i % 2 === 0);
    tick(100);
  }
  assert.equal(sent.length, 0);
  assert.ok(away.length >= 1 && away.length <= 3, `${away.length} badge updates in ten seconds`);
  hide(false);
  p.shown();
  tick(120);
  assert.equal(sent.length, 1, 'one snapshot when it\'s shown');
  p.shown();
  tick(1000);
  assert.equal(sent.length, 1, 'and no more when there was nothing new');
});

test('shown while one is waiting: it goes at once rather than after the wait', (t) => {
  const { p, sent, tick, hide } = harness(t);
  p.push();
  tick(120);
  hide(true);
  p.push();
  tick(500);
  hide(false);
  p.shown();
  tick(120);
  assert.equal(sent.length, 2);
});
