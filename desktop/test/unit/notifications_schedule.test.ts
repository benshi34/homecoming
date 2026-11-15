import assert from 'node:assert/strict';
import { test } from 'node:test';
import { notificationReadDue } from '../../src/main/notifications_schedule.ts';

test('notification polling runs once for a new database mtime and skips an unchanged or unavailable database', () => {
  assert.equal(notificationReadDue(true, 12, null), true, 'first readable database');
  assert.equal(notificationReadDue(true, 12, 12), false, 'unchanged mtime');
  assert.equal(notificationReadDue(true, 13, 12), true, 'database changed');
  assert.equal(notificationReadDue(false, 13, 12), false, 'source turned off');
  assert.equal(notificationReadDue(true, null, 12), false, 'database disappeared');
});
