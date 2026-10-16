// Homecoming with its window closed (main/background.ts): what the menu bar lists as needing you, and opening at login.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loginItemWanted, trayNeeds } from '../../src/main/background.ts';
import { hoursAgo, state, views } from './helpers.ts';

test('the menu bar lists what needs you, most pressing first, Claude\'s questions as such', () => {
  const vs = views({ state: state((s) => {
    s.sources.linkedin = { agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0), note: 'Enter the code LinkedIn sent you.', session: 's' } };
    s.found.push({ path: '/d/package.zip', name: 'package.zip', kind: 'discord', valid: true, size: 6e6, foundAt: hoursAgo(0), sourceId: 'discord' });
  }) });
  const needs = trayNeeds(vs);
  const summary = vs.filter((v) => v.section === 'needs' && !v.blockedBy && !v.optional).length;
  assert.equal(needs.length, summary, 'as many as the Dock badge counts');
  assert.deepEqual(needs.slice(0, 2), [{ id: 'linkedin', label: 'Claude needs you for LinkedIn' }, { id: 'discord', label: 'Discord: Found the export in Downloads' }]);
  assert.ok(needs.every((n) => n.label.length <= 60));
});

test('opening at login is its own choice, and follows keeping working in the background until it is made', () => {
  const base = { autoRefresh: true, watchDownloads: true };
  assert.equal(loginItemWanted(base, true), true, 'the packaged app: on, like the background');
  assert.equal(loginItemWanted(base, false), false);
  assert.equal(loginItemWanted({ ...base, background: false }, true), false, 'background off, login not set: off');
  assert.equal(loginItemWanted({ ...base, background: false, openAtLogin: true }, true), true, 'set on its own');
  assert.equal(loginItemWanted({ ...base, background: true, openAtLogin: false }, true), false, 'off while the background stays on');
});
