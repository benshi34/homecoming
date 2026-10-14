// This Mac's real data. Two runs, neither touching the real corpus:
//  1. read-only over the real corpus: the app must describe it correctly and change nothing;
//  2. the real Mac connectors reading the real Library into a throwaway corpus.
// Opt-in, since it takes about a minute and needs this Mac's corpus: npm run test:real (UMP_REAL=1).

import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, test } from 'node:test';
import { CATALOG } from '../../src/shared/catalog.ts';
import { PHONE_SOURCES } from '../../src/shared/phone.ts';
import { act, find, launch, REPO, type Running, selectSource, shot, snap, until } from './harness.ts';

const CORPUS = path.join(REPO, 'corpus');
const HAVE = fs.existsSync(path.join(CORPUS, 'manifest.json'));
const SKIP = process.env.UMP_REAL !== '1' ? 'set UMP_REAL=1 (npm run test:real) to check this Mac\'s real data' : !HAVE && 'no corpus here';

function fingerprint(): string {
  const h = crypto.createHash('sha256');
  for (const f of ['manifest.json', 'identity.json']) h.update(fs.readFileSync(path.join(CORPUS, f)));
  const db = fs.statSync(path.join(CORPUS, 'corpus.db'));
  h.update(`${db.size}:${db.mtimeMs}`);
  for (const d of ['imports', 'normalized']) {
    for (const f of fs.readdirSync(path.join(CORPUS, d), { recursive: true }) as string[]) {
      const st = fs.statSync(path.join(CORPUS, d, f));
      h.update(`${d}/${f}:${st.size}:${st.mtimeMs}`);
    }
  }
  return h.digest('hex');
}

describe('read-only on the real corpus', { skip: SKIP }, () => {
  let run: Running;
  let before = '';
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-real-ud-'));
  after(async () => {
    await run?.close();
    fs.rmSync(userData, { recursive: true, force: true });
  });

  test('describes the real corpus', async () => {
    before = fingerprint();
    run = await launch({ UMP_READONLY: '1', UMP_USER_DATA: userData });
    const s = await until(run.page, 'probe', (x) => !!x.probeTime && x.summary.records > 0, 60_000);
    const manifest = JSON.parse(fs.readFileSync(path.join(CORPUS, 'manifest.json'), 'utf8'));
    const total = Object.values(manifest as Record<string, { count?: number }>).reduce((n, e) => n + (e.count || 0), 0); // _metadata entries have no count
    assert.equal(s.summary.records, total);
    assert.equal(find(s, 'fda').section, 'done');
    assert.equal(find(s, 'identity').section, 'done');
    // Every source whose data is in the manifest shows as in the corpus, with the manifest's count.
    const has = (k: string) => (manifest[k]?.count ?? 0) > 0;
    for (const src of CATALOG.filter((x) => x.group !== 'setup' && x.group !== 'iphone' && (x.produces ?? []).some(has))) {
      const v = find(s, src.id);
      assert.ok(v.section === 'done' || v.section === 'needs', `${src.id}: ${v.section}`);
      assert.equal(v.records, (src.produces ?? []).reduce((n, k) => n + (manifest[k]?.count ?? 0), 0), src.id);
    }
    if (Object.keys(manifest).some((k) => k.startsWith('phone_'))) assert.ok(find(s, 'iphone_backup').records > 0);
    const phone = find(s, 'iphone_backup').parts ?? [];
    assert.deepEqual(phone.map((p) => p.name).filter((n) => !PHONE_SOURCES[n]), [], 'every phone source has a description in shared/phone.ts');
    assert.equal(s.jobs.length, 0, 'read-only never runs anything');
    assert.equal(s.readOnly, true);
    await shot(run.page, 'real-overview');
  });

  test('every detail page renders', async () => {
    const s = await snap(run.page);
    for (const v of s.sources.filter((x) => x.section !== 'unavailable' && x.group !== 'setup')) {
      await selectSource(run.page, v.id);
      const text = await run.page.locator('[data-testid=detail]').innerText();
      assert.ok(text.includes(v.name), v.id);
      if (v.id === 'iphone_backup' && v.section === 'done') {
        assert.equal(await run.page.locator('[data-testid^=phone-part-]').count(), v.parts!.length, 'every phone source is listed');
      }
      if (['iphone_backup', 'google_takeout', 'imessage', 'facebook'].includes(v.id)) await shot(run.page, `real-${v.id}`);
    }
    assert.deepEqual(run.errors, []);
  });

  test('actions that would change things are refused', async () => {
    const r = await act(run.page, 'apple_notes', 'run');
    assert.deepEqual(r, { ok: false, error: 'read-only' });
    assert.equal((await snap(run.page)).jobs.length, 0);
    await run.close();
    assert.equal(fingerprint(), before, 'the real corpus is byte-for-byte untouched');
  });
});

describe('real Mac connectors into a throwaway corpus', { skip: SKIP }, () => {
  let run: Running;
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-real-'));
  const corpus = path.join(root, 'corpus');
  fs.mkdirSync(corpus);
  after(async () => {
    await run?.close();
    fs.rmSync(root, { recursive: true, force: true });
  });
  // Not documents or git_commits: they walk iCloud Drive, and reading evicted files downloads them.
  const SOURCES = ['contacts', 'imessage', 'apple_notes', 'calendar', 'reminders', 'calls', 'browser_history', 'app_usage', 'ai_coding', 'notion_local', 'photos'];

  test('reads this Mac', { timeout: 15 * 60_000 }, async () => {
    fs.copyFileSync(path.join(CORPUS, 'identity.json'), path.join(corpus, 'identity.json'));
    const dl = path.join(root, 'Downloads');
    fs.mkdirSync(dl);
    run = await launch({ CORPUS_DIR: corpus, UMP_USER_DATA: path.join(root, 'ud'), UMP_DOWNLOADS: dl, UMP_NO_AUTORUN: '1' });
    await until(run.page, 'probe', (x) => !!x.probeTime);
    for (const id of SOURCES) await act(run.page, id, 'run');
    let s = await snap(run.page);
    assert.ok(s.jobs.length <= 2, 'the first run starts, the rest merge into one queued run');
    assert.deepEqual(new Set(s.jobs.flatMap((j) => j.sourceIds)), new Set(SOURCES));
    await selectSource(run.page, 'imessage');
    await shot(run.page, 'real-mac-reading');
    s = await until(run.page, 'all read', (x) => !x.jobs.length, 14 * 60_000);
    const real = JSON.parse(fs.readFileSync(path.join(CORPUS, 'manifest.json'), 'utf8'));
    const fresh = JSON.parse(fs.readFileSync(path.join(corpus, 'manifest.json'), 'utf8'));
    for (const id of SOURCES) {
      const v = find(s, id);
      assert.ok(v.section === 'done' || v.section === 'unavailable', `${id}: ${v.section} ${v.status} ${v.detail ?? ''}`);
    }
    // The Mac alone should give at least what earlier Mac-only runs recorded, minus what macOS has pruned.
    for (const k of ['imessage', 'apple_notes', 'photos']) {
      if (real[k]?.count) assert.ok(fresh[k]?.count > 0, k);
    }
    if (real.apple_notes?.count) assert.ok(fresh.apple_notes.count >= real.apple_notes.count * 0.9, 'notes');
    assert.ok(fs.statSync(path.join(corpus, 'corpus.db')).size > 1e6);
    await shot(run.page, 'real-mac-read');
    assert.deepEqual(run.errors, []);
  });
});
