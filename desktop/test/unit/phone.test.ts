import assert from 'node:assert/strict';
import { test } from 'node:test';
import { artifactWords, describePart, PHONE_GROUPS, PHONE_SOURCES, phoneGroups } from '../../src/shared/phone.ts';

test('artifact names lose the app name and file names', () => {
  assert.equal(artifactWords('Splitwise - Expense Balances'), 'Expense Balances');
  assert.equal(artifactWords('Uber - UR Message Locations (ur_message.db)'), 'UR Message Locations');
  assert.equal(artifactWords('Voice Memos'), 'Voice Memos');
  assert.equal(artifactWords('LSC - com.apple.routined.plist'), '');
});

test('a known source is described in words', () => {
  const d = describePart({ name: 'phone_splitwise', records: 9, artifacts: { 'Splitwise - Expenses': 5, 'Splitwise - Groups': 3 } });
  assert.deepEqual(d, { title: 'Splitwise expenses, balances and groups', group: 'Money and shopping' });
});

test('an unknown module is described by its artifacts, never by its module name', () => {
  const d = describePart({ name: 'phone_somenewapp', records: 2, artifacts: { 'Some App - Saved Recipes': 2 } });
  assert.deepEqual(d, { title: 'Saved Recipes', group: 'Other apps' });
  assert.equal(describePart({ name: 'phone_x', records: 1, artifacts: { 'X - y.plist': 1 } }).title, 'Other app data');
});

test('phone internals go last, whatever the source', () => {
  assert.equal(describePart({ name: 'phone_amazonshopping', records: 1, device: true }).group, 'Phone details');
  const g = phoneGroups([{ name: 'phone_filesapp', records: 900, device: true }, { name: 'phone_whatsapp', records: 5 }, { name: 'phone_wechat', records: 7 }, { name: 'health', records: 1 }]);
  assert.deepEqual(g.map((x) => [x.group, x.rows.map((r) => r.name)]), [
    ['People and messages', ['phone_wechat', 'phone_whatsapp']], ['Health', ['health']], ['Phone details', ['phone_filesapp']]]);
});

test('descriptions are words, not module names', () => {
  for (const [k, [title, group]] of Object.entries(PHONE_SOURCES)) {
    assert.ok(PHONE_GROUPS.includes(group), k);
    assert.match(title, /^([A-Z]|iCloud|iOS)/, k);
    assert.doesNotMatch(title, /_|sqlite|plist|db\b/i, k);
  }
});
