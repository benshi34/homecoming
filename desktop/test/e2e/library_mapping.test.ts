// A mapping the app ships (data/mappings/<slug>.json) reaches a service added before it shipped: at the next launch
// its download is read again with it, once. TikTok's own export is one nested JSON file; Goodreads' is one CSV, its
// rows split by shelf and its dates its own (2024/03/14); MyAnimeList's is gzipped XML.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, until } from './harness.ts';

let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox({ identity: true });
  const lib = path.join(sb.home, 'mapping-library');
  fs.mkdirSync(lib, { recursive: true });
  for (const m of ['tiktok', 'goodreads', 'myanimelist']) fs.copyFileSync(path.join(DESKTOP, 'data/mappings', `${m}.json`), path.join(lib, `${m}.json`));
  fs.mkdirSync(path.join(sb.corpus, 'imports/goodreads'), { recursive: true });
  fs.copyFileSync(path.join(DESKTOP, '../connectors/tests/fixtures/goodreads/goodreads_library_export.csv'),
    path.join(sb.corpus, 'imports/goodreads/goodreads_library_export.csv'));
  fs.mkdirSync(path.join(sb.corpus, 'imports/myanimelist'), { recursive: true });
  fs.copyFileSync(path.join(DESKTOP, '../connectors/tests/fixtures/myanimelist/animelist_1729500000_-_1000001.xml.gz'),
    path.join(sb.corpus, 'imports/myanimelist/animelist_1729500000_-_1000001.xml.gz'));
  fs.mkdirSync(path.join(sb.corpus, 'imports/tiktok'), { recursive: true });
  fs.writeFileSync(path.join(sb.corpus, 'imports/tiktok/user_data_tiktok.json'), JSON.stringify({
    'Your Activity': { 'Watch History': { VideoList: [{ Date: '2026-06-13 07:51:55', Link: 'https://www.tiktokv.com/share/video/1/', Title: '' }] },
      Searches: { SearchList: [{ Date: '2026-05-22 11:54:24', SearchTerm: 'sourdough' }] },
      'Login History': { LoginHistoryList: [{ Date: '2026-06-13 07:00:00', IP: '10.1.2.3' }] } },
    'Profile And Settings': { 'Profile Info': { ProfileMap: { userName: 'ada_l' } } },
  }));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, onboarding: { done: true },
    services: [{ id: 'svc_tiktok', slug: 'tiktok', name: 'TikTok', folder: 'tiktok', domains: ['tiktok.com'], addedAt: '2026-10-01T00:00:00Z', from: 'found' },
      { id: 'svc_goodreads', slug: 'goodreads', name: 'Goodreads', folder: 'goodreads', domains: ['goodreads.com'], addedAt: '2026-10-01T00:00:00Z', from: 'you' },
      { id: 'svc_mal', slug: 'myanimelist', name: 'MyAnimeList', folder: 'myanimelist', domains: ['myanimelist.net'], addedAt: '2026-10-01T00:00:00Z', from: 'you' }],
    sources: { svc_tiktok: { requestedAt: '2026-10-01T00:00:00Z' }, svc_goodreads: { requestedAt: '2026-10-01T00:00:00Z' },
      svc_mal: { requestedAt: '2026-10-01T00:00:00Z' } } }));
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1' }));
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('a service added before its mapping shipped is read with it at the next launch, and keeps the rest of its file', async () => {
  const s = await until(run.page, 'read with the shipped mapping', (x) => !x.jobs.length && find(x, 'svc_tiktok').records === 3, 120_000);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'mappings/tiktok.json')), 'the shipped mapping is now this library\'s');
  const rows = (f: string) => fs.readFileSync(path.join(sb.corpus, 'normalized', f), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(rows('tiktok.jsonl').map((r) => [r.kind, r.ts]).sort(), [['search', '2026-05-22T11:54:24Z'], ['watch', '2026-06-13T07:51:55Z']],
    'typed, with TikTok\'s UTC times kept as UTC');
  const rest = rows('tiktok_other.jsonl');
  assert.equal(rest.length, 1, 'the profile, which the mapping doesn\'t name, is still kept');
  assert.match(rest[0].text, /ada_l/);
  assert.doesNotMatch(JSON.stringify(rest), /10\.1\.2\.3/, 'never the login history');
  const state = JSON.parse(fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8'));
  assert.ok(state.sources.svc_tiktok.libraryMapping, 'used once: taking it out later sticks');
  assert.equal(find(s, 'svc_tiktok').section, 'done');
});

test('Goodreads\' library is read with its shipped mapping: every book once, by shelf, on the day it was read', async () => {
  const s = await until(run.page, 'Goodreads read', (x) => !x.jobs.length && find(x, 'svc_goodreads').records === 5, 120_000);
  const rows = fs.readFileSync(path.join(sb.corpus, 'normalized/goodreads.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(rows.map((r) => [r.title, r.kind, r.ts]).sort(), [
    ['A Field Guide to Fog', 'saved', '2024-06-11T00:00:00'],
    ['Notes on Tides', 'read', '2024-05-02T00:00:00'],
    ['Old Rivers', 'read', '2022-08-19T00:00:00'],
    ['The Lighthouse Keeper\'s Year', 'read', '2024-03-14T00:00:00'],
    ['The Unfinished Map', 'saved', '2023-11-05T00:00:00'],
  ]);
  assert.ok(!fs.existsSync(path.join(sb.corpus, 'normalized/goodreads_other.jsonl')), 'nothing left over for the catch-all');
  assert.equal(find(s, 'svc_goodreads').section, 'done');
});

test('MyAnimeList\'s list is read from its .xml.gz: an anime a record, your plans saved, its totals one record', async () => {
  const s = await until(run.page, 'MyAnimeList read', (x) => !x.jobs.length && find(x, 'svc_mal').records === 4, 120_000);
  const rows = fs.readFileSync(path.join(sb.corpus, 'normalized/myanimelist.jsonl'), 'utf8').trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(rows.map((r) => [r.title ?? null, r.kind, r.ts ?? null]).sort(), [
    [null, 'record', null],
    ['Harbor Lights: Second Season', 'watch', '2024-03-20T00:00:00'],
    ['Paper Moons & Stars', 'watch', null],
    ['Salt Flats', 'saved', null],
  ]);
  assert.equal(find(s, 'svc_mal').section, 'done');
});
