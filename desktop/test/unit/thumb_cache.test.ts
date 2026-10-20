// renderer/thumb_cache.ts: Explore's thumbnails kept in the window, the latest few and whatever a grid shows.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ThumbCache } from '../../src/renderer/thumb_cache.ts';

test('the ones used longest ago go first, once there are more than it keeps', () => {
  const c = new ThumbCache(3);
  for (const k of ['a', 'b', 'c']) c.set(k, `img ${k}`);
  assert.equal(c.get('a'), 'img a'); // used again: now the newest
  c.set('d', 'img d');
  assert.equal(c.size, 3);
  assert.ok(!c.has('b'), 'b was the oldest');
  assert.ok(c.has('a') && c.has('c') && c.has('d'));
  c.set('e', '');
  assert.ok(c.has('e') && c.get('e') === '', 'no picture is kept too, as an empty one');
});

test('what a grid on screen shows stays, however many; when it goes, so can they', () => {
  const c = new ThumbCache(2);
  const grid = {};
  const keys = ['1', '2', '3', '4', '5'];
  c.showing(grid, keys);
  for (const k of keys) c.set(k, k);
  assert.equal(c.size, 5, 'a grid of five, all kept: none asked for again and again');
  c.set('other', 'x');
  assert.ok(!c.has('other'), 'one not shown goes instead');
  assert.ok(keys.every((k) => c.has(k)));
  c.showing(grid, ['5']);
  c.set('6', '6');
  assert.ok(c.has('5') && c.size <= 2);
  c.showing(grid, null);
  c.set('7', '7');
  assert.equal(c.size, 2);
  assert.ok(c.has('7'));
});

test('a changed library forgets visible pictures and missing pictures, and invalidates pending requests', () => {
  const c = new ThumbCache(2);
  c.showing({}, ['240:1', '240:2']);
  c.set('240:1', 'old image');
  c.set('240:2', '');
  const pendingGeneration = c.generation;
  c.clear();
  assert.ok(!c.has('240:1') && !c.has('240:2'));
  assert.notEqual(c.generation, pendingGeneration, 'a reply from before the change must not repopulate the cache');
});
