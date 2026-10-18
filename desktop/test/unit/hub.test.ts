import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { setServices } from '../../src/shared/catalog.ts';
import { CATEGORIES, hubRows, searchRows, sortRows } from '../../src/shared/hub.ts';
import type { DirectoryEntry, FoundService, ServiceEntry } from '../../src/shared/types.ts';
import { hoursAgo, state, views } from './helpers.ts';

const dir: DirectoryEntry[] = [
  { slug: 'instagram', name: 'Instagram', domains: ['instagram.com'], category: 'social' },
  { slug: 'wattpad', name: 'Wattpad', domains: ['wattpad.com'], category: 'reading', export: { url: 'https://support.example/x' } },
  { slug: 'goodreads', name: 'Goodreads', domains: ['goodreads.com'], category: 'reading', popular: true },
  { slug: 'kindle-notes', name: 'Kindle Notes', domains: ['read.amazon.com'], category: 'reading' },
  { slug: 'mystery', name: 'Mystery', domains: ['mystery.example'], category: 'not-a-kind' },
];
const found = (slug: string, apps: string[] = []): FoundService => ({ slug, name: slug, domains: [], emails: 9, automated: 9, visits: 0, apps });
const svc: ServiceEntry = { id: 'svc_goodreads', slug: 'goodreads', name: 'Goodreads', folder: 'goodreads', domains: ['goodreads.com'], addedAt: hoursAgo(1), from: 'you' };

afterEach(() => setServices([]));

test('every service once: built-in accounts, the ones you added, then the directory', () => {
  const st = state((s) => (s.services = [svc]));
  const rows = hubRows(dir, views({ state: st }), st.services, { found: [found('wattpad')], unmatched: [], services: dir.length });
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));
  assert.equal(rows.filter((r) => r.name === 'Instagram').length, 1, 'the built-in Instagram, not a second one from the directory');
  assert.equal(by.instagram.state, 'built-in');
  assert.equal(by.instagram.status, 'Not requested yet');
  assert.equal(by.svc_goodreads.state, 'added');
  assert.equal(by.svc_goodreads.category, 'reading', 'an added service keeps its kind');
  assert.ok(!by['dir:goodreads'], 'and isn\'t listed twice');
  assert.equal(by['dir:wattpad'].found?.emails, 9);
  assert.equal(by['dir:wattpad'].exportKnown, true);
  assert.equal(by['dir:mystery'].category, 'other', 'an unknown kind is "everything else"');
  assert.ok(CATEGORIES.some((c) => c.id === 'other'));
});

test('within a kind: in the app first, then found in your data, then popular, then the rest', () => {
  const st = state((s) => (s.services = [svc]));
  const rows = hubRows(dir, views({ state: st }), st.services, { found: [found('kindle-notes')], unmatched: [], services: dir.length });
  assert.deepEqual(sortRows(rows.filter((r) => r.category === 'reading')).map((r) => r.name), ['Goodreads', 'Kindle Notes', 'Wattpad']);
});

test('search: whole names first, then words, then anywhere in the name or domain', () => {
  const rows = hubRows(dir, views(), [], null);
  assert.deepEqual(searchRows(rows, 'notes').map((r) => r.name), ['Notes', 'Kindle Notes'], 'this Mac\'s Notes too: every source is here');
  assert.deepEqual(searchRows(rows, 'read').map((r) => r.name), ['Goodreads', 'Kindle Notes'], 'goodreads.com, read.amazon.com');
  assert.deepEqual(searchRows(rows, 'wattpad').map((r) => r.name), ['Wattpad']);
  assert.deepEqual(searchRows(rows, 'zzz'), []);
});
