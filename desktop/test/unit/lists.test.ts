import assert from 'node:assert/strict';
import { test } from 'node:test';
import { countFor, listFor, listSummary, navOf, needsYou, setupNeeds, todoBadge } from '../../src/shared/lists.ts';
import { summarize } from '../../src/shared/status.ts';
import type { SourceView } from '../../src/shared/types.ts';
import { hoursAgo, input, state, stats, views } from './helpers.ts';

const v = (id: string, section: SourceView['section'], over: Partial<SourceView> = {}) =>
  ({ id, name: id, group: 'setup', section, records: 0, optional: false, ...over }) as SourceView;
const ids = (g: { title?: string; rows: SourceView[] }[]) => g.map((x) => [x.title ?? 'main', x.rows.map((r) => r.id)]);

test('Setup Checks: what\'s to do first (those that need you have a dot, counted in To Do), then optional, checking, all set', () => {
  const all = [
    v('retention_google', 'todo', { needsYou: true }), v('identity', 'done'), v('iphone_notifications', 'todo', { optional: true }),
    v('fda', 'done'), v('retention_shell', 'todo', { needsYou: true }), v('disk_space', 'working'), v('imessage', 'todo', { group: 'mac' }),
  ];
  const g = listFor('setup', all);
  assert.deepEqual(ids(g), [
    ['main', ['retention_shell', 'retention_google']], ['Optional', ['iphone_notifications']], ['Checking', ['disk_space']],
    ['All set', ['fda']], ['Not available', []],
  ], 'who you are is in Your Setup, not here');
  assert.equal(countFor('setup', all), 0, 'no badge: the ones that need you are counted in To Do');
  assert.equal(setupNeeds(all), 2, 'optional checks are not counted');
  assert.equal(listSummary('setup', g), '2 need you · 1 optional · 1 all set');
});

test('the line under the title says what the badge counts, and never "all set" while checking', () => {
  const checking = [v('identity', 'working'), v('fda', 'working')];
  assert.equal(listSummary('setup', listFor('setup', checking)), 'Checking this Mac');
  assert.equal(listSummary('setup', listFor('setup', [v('python_env', 'done'), v('fda', 'done')])), 'Nothing to do · 2 all set');
  // What's worth doing but holds nothing up: to do, counted by Setup Checks' own badge (what needs you is in To Do's).
  const keep = [v('fda', 'todo', { needsYou: true }), v('retention_safari', 'todo'), v('disk_space', 'todo')];
  assert.equal(listSummary('setup', listFor('setup', keep)), '1 needs you · 2 to do');
  assert.equal(countFor('setup', keep), 2);
  assert.deepEqual(todoBadge(keep), { n: 1, alert: true });
  assert.equal(listSummary('setup', listFor('setup', [v('fda', 'todo', { needsYou: true })])), '1 needs you');
  const web = (id: string, section: SourceView['section'], over: Partial<SourceView> = {}) => v(id, section, { group: 'web', ...over });
  // To Do: what needs you now, from any stage (each row says where), then what hasn't started, what waits on a setup
  // check (under it), and the optional ones.
  const mixed = [web('instagram', 'working', { needsYou: true }), web('spotify', 'working'), web('discord', 'done', { needsYou: true }), web('reddit', 'todo'),
    web('slack', 'todo', { optional: true }), web('imessage', 'todo', { group: 'mac', blockedBy: 'fda' }), web('x', 'todo'), v('fda', 'todo', { needsYou: true }),
    web('notes', 'todo', { needsYou: true, blockedBy: 'fda' })];
  assert.deepEqual(ids(listFor('todo', mixed)), [['Needs you now', ['instagram', 'discord', 'fda']], ['Not started', ['reddit', 'x']],
    ['Waiting on Full Disk Access', ['imessage', 'notes']], ['Optional', ['slack']]], 'what waits on a setup check doesn\'t need you: the check does');
  assert.deepEqual(todoBadge(mixed), { n: 3, alert: true }, 'the badge: what needs you now, in orange');
  assert.equal(listSummary('todo', listFor('todo', mixed)), '3 need you now · 2 not started · 2 waiting on Full Disk Access · 1 optional');
  // With nothing needing you: how many haven't started, plainly.
  const calm = [web('reddit', 'todo'), web('x', 'todo'), web('slack', 'todo', { optional: true })];
  assert.deepEqual(todoBadge(calm), { n: 2, alert: false });
  assert.equal(listSummary('todo', listFor('todo', calm)), '2 not started · 1 optional');
  assert.equal(listSummary('todo', listFor('todo', [])), 'Nothing to do');
  // The other lists say how many, and how many of those need you.
  assert.equal(listSummary('working', listFor('working', mixed)), '2 sources · 1 needs you');
  assert.equal(listSummary('done', listFor('done', [v('photos', 'done', { group: 'mac', records: 5 })])), '1 source');
});

test('a source lives in its stage, whether or not it needs you: jumping to one goes there', () => {
  assert.equal(navOf(v('instagram', 'working', { group: 'web', needsYou: true })), 'working');
  assert.equal(navOf(v('reddit', 'todo', { group: 'web' })), 'todo');
  assert.equal(navOf(v('discord', 'done', { group: 'web', needsYou: true })), 'done');
  assert.equal(navOf(v('fda', 'todo', { needsYou: true })), 'setup', 'a setup check, in Setup Checks');
  assert.equal(navOf(v('identity', 'todo')), 'yoursetup', 'who you are, in Your Setup');
  assert.equal(navOf(v('reddit', 'unavailable', { group: 'web' })), 'hub', 'not collected: in All Sources, its page over it');
  // New finds to look at: counted on Your Setup, not Setup Checks.
  const fresh = [v('identity', 'todo'), v('retention_safari', 'todo')];
  assert.equal(countFor('yoursetup', fresh), 1);
  assert.equal(countFor('setup', fresh), 1);
  assert.equal(countFor('yoursetup', [v('identity', 'done')]), 0);
});

test('Claude stopped for a sign-in: the export stays In Progress, with a dot, and To Do lists it first too', () => {
  const at = (status: 'running' | 'needs_you') => views({ state: state((s) => {
    Object.assign(s.settings, { aiOn: true, agentExports: true });
    s.sources.instagram = { agent: { mode: 'request', status, at: hoursAgo(0), ...(status === 'needs_you' ? { note: 'Sign in to Instagram in Chrome.' } : {}) } };
  }) });
  const find = (vs: SourceView[], id: string) => vs.find((x) => x.id === id)!;
  const running = at('running');
  const stopped = at('needs_you');
  assert.equal(find(running, 'instagram').section, 'working');
  assert.equal(find(stopped, 'instagram').section, 'working', 'the same place it was');
  assert.equal(needsYou(find(stopped, 'instagram')), true);
  assert.ok(listFor('working', stopped)[0].rows.some((r) => r.id === 'instagram'));
  assert.ok(listFor('todo', stopped)[0].rows.some((r) => r.id === 'instagram'), 'Needs you now');
  assert.ok(!listFor('todo', running).some((g) => g.rows.some((r) => r.id === 'instagram')), 'at work, it isn\'t in To Do at all');
  assert.equal(listFor('todo', stopped)[0].rows.length, listFor('todo', running)[0].rows.length + 1);
});

test('exports not asked for yet are in To Do\'s Not started, not with what needs you now', () => {
  const vs = views();
  const discord = vs.find((x) => x.id === 'discord')!;
  assert.equal(discord.section, 'todo');
  assert.ok(!discord.needsYou);
  assert.ok(listFor('todo', vs)[1].rows.some((r) => r.id === 'discord'));
  assert.ok(!listFor('todo', vs)[0].rows.some((r) => r.group === 'web'), 'no export needs you before anything has happened');
});

test('the Dock badge counts what To Do lists as needing you now', () => {
  for (const vs of [views(), views({ probe: undefined }), views({ stats: stats({ imessage: { count: 10 } }) })]) {
    assert.equal(summarize(vs, input().stats).needsYou, listFor('todo', vs)[0].rows.length);
  }
});
