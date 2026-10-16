import assert from 'node:assert/strict';
import { test } from 'node:test';
import { countFor, listFor, listSummary, setupNeeds } from '../../src/shared/lists.ts';
import { summarize } from '../../src/shared/status.ts';
import type { SourceView } from '../../src/shared/types.ts';
import { input, stats, views } from './helpers.ts';

const v = (id: string, section: SourceView['section'], over: Partial<SourceView> = {}) =>
  ({ id, name: id, group: 'setup', section, records: 0, optional: false, ...over }) as SourceView;

test('Setup Checks: what needs you first (the badge counts it), then optional, checking, all set', () => {
  const all = [
    v('retention_google', 'needs'), v('identity', 'done'), v('iphone_notifications', 'needs', { optional: true }),
    v('fda', 'done'), v('retention_shell', 'needs'), v('disk_space', 'working'), v('imessage', 'needs', { group: 'mac' }),
  ];
  const g = listFor('setup', all);
  assert.deepEqual(g.map((x) => [x.title ?? 'main', x.rows.map((r) => r.id)]), [
    ['main', ['retention_shell', 'retention_google']], ['Optional', ['iphone_notifications']], ['Checking', ['disk_space']],
    ['All set', ['identity', 'fda']], ['Not available', []],
  ]);
  assert.equal(g[0].needsYou, true);
  assert.ok(g.slice(1).every((x) => !x.needsYou), 'only what needs you gets a dot');
  assert.equal(countFor('setup', all), 0, 'no badge: the ones that need you are counted in Needs You');
  assert.equal(setupNeeds(all), 2, 'optional checks are not counted');
  assert.equal(listSummary('setup', g), '2 need you · 1 optional · 2 all set');
});

test('the line under the title says what the badge counts, and never "all set" while checking', () => {
  const checking = [v('identity', 'working'), v('fda', 'working')];
  assert.equal(listSummary('setup', listFor('setup', checking)), 'Checking this Mac');
  assert.equal(listSummary('setup', listFor('setup', [v('identity', 'done'), v('fda', 'done')])), 'Nothing needs you · 2 all set');
  assert.equal(listSummary('setup', listFor('setup', [v('fda', 'needs')])), '1 needs you');
  const web = (id: string, over: Partial<SourceView> = {}) => v(id, 'needs', { group: 'web', ...over });
  const needs = listFor('needs', [web('reddit'), web('slack', { optional: true }), web('imessage', { blockedBy: 'fda' }), web('x')]);
  assert.deepEqual(needs.map((x) => [x.title ?? 'main', x.rows.map((r) => r.id)]), [['main', ['reddit', 'x']], ['Waiting on Full Disk Access', ['imessage']], ['Optional', ['slack']]],
    'blocked sources are listed, without a dot, under what they wait on');
  assert.ok(!needs[1].needsYou);
  assert.equal(countFor('needs', [web('reddit'), web('imessage', { blockedBy: 'fda' })]), 1, 'and not counted');
  assert.equal(listSummary('needs', needs), '2 need you · 1 waiting on Full Disk Access · 1 optional');
  assert.equal(listSummary('done', listFor('done', [v('photos', 'done', { group: 'mac', records: 5 })])), '1 source');
});

test('the Dock badge and the Needs You badge count the same things', () => {
  for (const vs of [views(), views({ probe: undefined }), views({ stats: stats({ imessage: { count: 10 } }) })]) {
    assert.equal(summarize(vs, input().stats).needsYou, countFor('needs', vs));
  }
});

test('Not Collecting: what you skipped, then what isn\'t on this Mac, each under its own heading', () => {
  const skipped = v('reddit', 'unavailable', { group: 'web', status: 'Skipped: I don\'t use it', actions: [{ id: 'unskip', label: 'Include Again' }] });
  const absent = v('voice_memos', 'unavailable', { group: 'mac', status: 'Not on this Mac', actions: [{ id: 'recheck', label: 'Check Again' }] });
  const g = listFor('unavailable', [absent, skipped]);
  assert.deepEqual(g.map((x) => [x.title, x.rows.map((r) => r.id)]), [['Skipped by You', ['reddit']], ['Not on This Mac', ['voice_memos']]]);
  assert.equal(countFor('unavailable', [absent, skipped]), 2);
});
