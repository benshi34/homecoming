// A mapping the app ships (data/mappings/<slug>.json) reaches a service added before it shipped: at the next launch
// its download is read again with it, once. TikTok's own export is one nested JSON file.

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
  fs.copyFileSync(path.join(DESKTOP, 'data/mappings/tiktok.json'), path.join(lib, 'tiktok.json'));
  fs.mkdirSync(path.join(sb.corpus, 'imports/tiktok'), { recursive: true });
  fs.writeFileSync(path.join(sb.corpus, 'imports/tiktok/user_data_tiktok.json'), JSON.stringify({
    'Your Activity': { 'Watch History': { VideoList: [{ Date: '2026-06-13 07:51:55', Link: 'https://www.tiktokv.com/share/video/1/', Title: '' }] },
      Searches: { SearchList: [{ Date: '2026-05-22 11:54:24', SearchTerm: 'sourdough' }] },
      'Login History': { LoginHistoryList: [{ Date: '2026-06-13 07:00:00', IP: '10.1.2.3' }] } },
    'Profile And Settings': { 'Profile Info': { ProfileMap: { userName: 'ada_l' } } },
  }));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, onboarding: { done: true },
    services: [{ id: 'svc_tiktok', slug: 'tiktok', name: 'TikTok', folder: 'tiktok', domains: ['tiktok.com'], addedAt: '2026-10-01T00:00:00Z', from: 'found' }],
    sources: { svc_tiktok: { requestedAt: '2026-10-01T00:00:00Z' } } }));
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
