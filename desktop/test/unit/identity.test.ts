import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildIdentity, describeNew, identityKeys, keyOf, newCandidates, normalize, pickerRows } from '../../src/shared/identity.ts';
import type { Candidate } from '../../src/shared/types.ts';
import { probe, state, view } from './helpers.ts';

const c = (kind: Candidate['kind'], value: string, strong = true, label = 'Apple ID'): Candidate => ({ kind, value, strong, sources: [{ label }] });
const ADA = { names: ['Ada Lovelace'], emails: ['ada@example.com'], usernames: [], phones: [] };

test('normalize matches bridge.py', () => {
  assert.equal(normalize('email', ' Ada@Example.COM '), 'ada@example.com');
  assert.equal(normalize('phone', '(415) 555-0100'), '+14155550100');
  assert.equal(normalize('phone', '+44 20 7946 0958'), '+442079460958');
  assert.equal(normalize('username', '@Ada_L'), 'ada_l');
  assert.equal(normalize('name', 'Ada   Lovelace'), 'ada lovelace');
  assert.equal(keyOf('phone', '4155550100'), keyOf('phone', '+1 415 555 0100'));
  assert.deepEqual([...identityKeys(ADA)].sort(), ['email:ada@example.com', 'name:ada lovelace']);
});

test('a first identity: strong evidence is ticked, weak evidence is offered', () => {
  const rows = pickerRows([c('email', 'ada@example.com'), c('username', 'ada', false, 'Mac user account')], null, []);
  assert.deepEqual(rows.map((r) => [r.value, r.checked, r.isNew]), [['ada@example.com', true, false], ['ada', false, false]]);
});

test('later: confirmed stays ticked, new evidence is flagged, a "not me" stays unticked', () => {
  const cands = [c('email', 'ADA@example.com'), c('email', 'ada.work@example.com', true, 'LinkedIn export'), c('phone', '+14155550100'), c('email', 'someone@example.com')];
  const rows = pickerRows(cands, { ...ADA, usernames: ['ada_l'] }, ['email:someone@example.com']);
  const by = Object.fromEntries(rows.map((r) => [r.value, r]));
  assert.equal(by['ADA@example.com'].checked, true);
  assert.equal(by['ADA@example.com'].isNew, false);
  assert.equal(by['ada.work@example.com'].isNew, true);
  assert.equal(by['ada.work@example.com'].checked, true);
  assert.equal(by['someone@example.com'].checked, false);
  assert.equal(by['someone@example.com'].isNew, false);
  assert.deepEqual(by['ada_l'].sources, [{ label: 'Added by you' }], 'confirmed values with no evidence still show');
  assert.equal(rows.filter((r) => r.value.toLowerCase() === 'ada@example.com').length, 1, 'no duplicates across case');
});

test('buildIdentity and newCandidates', () => {
  const rows = pickerRows([c('email', 'ada@example.com'), c('name', 'Ada Lovelace'), c('phone', '+14155550100')], null, []);
  const id = buildIdentity(rows, new Set(rows.filter((r) => r.kind !== 'phone').map((r) => r.key)));
  assert.deepEqual(id, { names: ['Ada Lovelace'], emails: ['ada@example.com'], usernames: [], phones: [] });
  const fresh = newCandidates([c('email', 'ada@example.com'), c('email', 'x@example.com'), c('email', 'weak@example.com', false), c('phone', '415 555 0100')], ADA, ['phone:+14155550100']);
  assert.deepEqual(fresh.map((x) => x.value), ['x@example.com']);
});

test('describeNew', () => {
  assert.equal(describeNew([c('email', 'a@x.y')]), '1 new email address');
  assert.equal(describeNew([c('email', 'a@x.y'), c('email', 'b@x.y'), c('phone', '+1')]), '2 new email addresses and 1 new phone number');
});

test('the identity row asks about new finds, and only new ones', () => {
  const cands = [c('email', 'ada@example.com'), c('email', 'ada.work@example.com', true, 'LinkedIn export')];
  const asked = view('identity', { probe: probe({ identity: ADA }), candidates: cands });
  assert.equal(asked.section, 'needs');
  assert.equal(asked.status, '1 new email address found');
  assert.match(asked.detail!, /ada\.work@example\.com \(LinkedIn export\)/);
  assert.equal(asked.actions[0].label, 'Review');
  const answered = view('identity', { probe: probe({ identity: ADA }), candidates: cands, state: state((s) => (s.identityDismissed = ['email:ada.work@example.com'])) });
  assert.equal(answered.section, 'done');
  const first = view('identity', { probe: probe({ identity: null }), candidates: cands });
  assert.equal(first.status, 'Found 2 things that look like you: check them');
  assert.equal(first.priority, 65);
});
