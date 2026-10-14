import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ago, bytes, count, day, hours, list, range, waitRange } from '../../src/shared/format.ts';

const NOW = new Date('2026-10-08T12:00:00Z');

test('count and bytes', () => {
  assert.equal(count(1234567), '1,234,567');
  assert.equal(count(3.6), '4');
  assert.equal(bytes(0), '0 B');
  assert.equal(bytes(999), '999 B');
  assert.equal(bytes(6_000_000), '6.0 MB');
  assert.equal(bytes(12_345_678_901), '12 GB');
  assert.equal(bytes(NaN), '0 B');
});

test('waits', () => {
  assert.equal(hours(0.5), 'under an hour');
  assert.equal(hours(1), 'about an hour');
  assert.equal(hours(20), 'about 20 hours');
  assert.equal(hours(30), 'about 30 hours');
  assert.equal(hours(48), 'about 2 days');
  assert.equal(hours(24 * 1.2), 'about 29 hours');
  assert.equal(waitRange([1, 48]), 'an hour to 2 days');
  assert.equal(waitRange([4, 720]), '4 hours to 30 days');
  assert.equal(waitRange([24, 24]), '24 hours');
});

test('ago', () => {
  assert.equal(ago(new Date(NOW.getTime() - 30_000).toISOString(), NOW), 'just now');
  assert.equal(ago(new Date(NOW.getTime() - 20 * 60_000).toISOString(), NOW), '20 min ago');
  assert.equal(ago(new Date(NOW.getTime() - 5 * 3600_000).toISOString(), NOW), '5 h ago');
  assert.equal(ago(new Date(NOW.getTime() - 40 * 3600_000).toISOString(), NOW), 'yesterday');
  assert.equal(ago(new Date(NOW.getTime() - 7 * 86400_000).toISOString(), NOW), '7 days ago');
  assert.equal(ago('nonsense', NOW), '');
  assert.equal(ago(undefined, NOW), '');
  assert.equal(ago(new Date(NOW.getTime() + 60_000).toISOString(), NOW), 'just now', 'clock skew is not negative time');
});

test('dates and ranges', () => {
  assert.equal(day('2026-09-01T10:00:00+00:00'), 'Sep 1, 2026');
  assert.equal(range('2015-03-01T00:00:00Z', '2026-10-06T00:00:00Z', NOW), '2015 to now');
  assert.equal(range('2015-03-01T00:00:00Z', '2026-01-05T12:00:00Z', NOW), '2015 to Jan 5, 2026');
  assert.equal(range(null, null, NOW), '');
  assert.equal(range('2015-03-01T00:00:00Z', null, NOW), '2015');
});

test('list', () => {
  assert.equal(list([]), '');
  assert.equal(list(['a']), 'a');
  assert.equal(list(['a', 'b']), 'a and b');
  assert.equal(list(['a', 'b', 'c']), 'a, b and c');
});
