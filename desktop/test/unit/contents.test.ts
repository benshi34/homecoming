import assert from 'node:assert/strict';
import { test } from 'node:test';
import { contents } from '../../src/shared/contents.ts';
import { stats, view } from './helpers.ts';

test('kinds of record and the split by service, in words', () => {
  const s = { ...stats({ imessage: { count: 12, kinds: { message: 9, reaction: 2, event: 1 } } }), facets: { imessage: { iMessage: 8, iMessageLite: 1, SMS: 2 } } };
  assert.deepEqual(contents('imessage', ['imessage'], s), [
    { title: 'What it holds', rows: [{ label: 'Messages', count: 9 }, { label: 'Reactions', count: 2 }, { label: 'Group chat changes: renames, people added or removed', count: 1 }] },
    { title: 'Sent over', rows: [{ label: 'iMessage', count: 8 }, { label: 'SMS', count: 2 }, { label: 'iMessage by satellite', count: 1 }] },
  ]);
});

test('merged sources say which copy their records came from', () => {
  const s = { ...stats({ calls: { count: 3, kinds: { call: 3 } } }), copies: { calls: { iphone: 2, mac: 1 } } };
  assert.deepEqual(contents('calls', ['calls'], s).at(-1), { title: 'Where it came from', rows: [{ label: 'The iPhone backup', count: 2 }, { label: 'Only in this Mac\'s copy', count: 1 }] });
});

test('devices with build numbers are named, and two Macs are told apart', () => {
  const s = { ...stats({ app_usage: { count: 9, kinds: { app_usage: 9 } } }), facets: { app_usage: { 'this Mac': 4, 'Mac (25F80)': 1, 'iPhone (23G83)': 3, 'iPad (22F76)': 1 } } };
  assert.deepEqual(contents('app_usage', ['app_usage'], s)[1].rows.map((r) => r.label), ['This Mac', 'iPhone', 'Another Mac', 'iPad']);
});

test('a split with one value says nothing and is left out; unknown kinds are still listed', () => {
  const s = { ...stats({ photos: { count: 3, kinds: { photo: 3, live_photo_pair: 0, panorama: 1 } } }), facets: { photos: { photo: 3 } } };
  assert.deepEqual(contents('photos', ['photos'], s), [{ title: 'What it holds', rows: [{ label: 'Photos and videos', count: 3 }, { label: 'Panorama', count: 1 }] }]);
});

test('Mac sources carry their contents once read', () => {
  const s = { ...stats({ git_commits: { count: 5, kinds: { commit: 5 } } }), facets: { git_commits: { repositories: 2 } } };
  assert.deepEqual(view('git_commits', { stats: s }).contents, [{ title: 'What it holds', rows: [{ label: 'Commits', count: 5 }, { label: 'Repositories', count: 2 }] }]);
  assert.equal(view('apple_notes').contents, undefined, 'nothing read, nothing to list');
});

test('a Mac source that is empty here points at its iPhone copy', () => {
  const s = stats({ voice_memos: { count: 0 }, phone_voicerecordings: { count: 2284 } });
  assert.equal(view('voice_memos', { stats: s }).status, 'None on this Mac: 2,284 came from the iPhone backup');
  assert.equal(view('voice_memos', { stats: stats({ voice_memos: { count: 0 } }) }).status, 'Nothing found on this Mac');
});

test('WhatsApp and Maps on this Mac say what the iPhone backup already had (it counts those)', () => {
  const some = stats({ whatsapp: { count: 40, kinds: { message: 38, event: 2 }, notes: { in_the_iphone_backup: 1200 } }, phone_whatsapp: { count: 1300 } });
  assert.deepEqual(contents('whatsapp', ['whatsapp'], some), [
    { title: 'What it holds', rows: [{ label: 'Messages', count: 38 }, { label: 'Group chat changes', count: 2 }] },
    { title: 'Where it came from', rows: [{ label: 'Only in this Mac\'s copy', count: 40 }, { label: 'Also in the iPhone backup, counted there', count: 1200 }] },
  ]);
  const all = stats({ apple_maps: { count: 0, notes: { in_the_iphone_backup: 25 } }, phone_mapssync: { count: 25 } });
  assert.equal(view('apple_maps', { stats: all }).status, 'All 25 on this Mac are in the iPhone backup too, and counted there');
  assert.deepEqual(view('books', { stats: stats({ books: { count: 3, kinds: { book: 2, highlight: 1 } } }) }).contents?.[0].rows.map((r) => r.label),
    ['Books in your library', 'Highlights and notes']);
});
