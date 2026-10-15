import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { accountChoices, assistantSteps, commonAccounts, defaultChosen, nextExportStep, POPULARITY, progress, readyIn, RECOMMENDED, recommended, STEP_GROUPS, stepIndex } from '../../src/shared/progress.ts';
import { CATALOG, setServices } from '../../src/shared/catalog.ts';
import type { FoundService } from '../../src/shared/types.ts';
import { H, hoursAgo, NOW, probe, state, stats, views } from './helpers.ts';

const macRead = () => stats(Object.fromEntries(CATALOG.filter((x) => x.group === 'mac').map((x) => [x.produces![0], { count: 1 }])));

describe('progress', () => {
  test('a fresh Mac: nothing collected, setup is where to start', () => {
    const p = progress(views({ probe: probe({ identity: null, fda: false, sources: { imessage: 'blocked' } }) }), NOW);
    assert.equal(p.collected, 0);
    assert.equal(p.percent, 0);
    assert.deepEqual(p.phases.map((x) => x.id), ['setup', 'mac', 'iphone', 'request', 'arrive', 'extras']);
    assert.equal(p.phases[0].status, 'active');
    assert.ok(p.toDo > 0);
    assert.equal(p.phases.find((x) => x.id === 'arrive')!.status, 'skipped', 'nothing requested, nothing to arrive');
  });

  test('phases count what they should', () => {
    const vs = views({ stats: macRead() });
    const p = progress(vs, NOW);
    const mac = p.phases.find((x) => x.id === 'mac')!;
    assert.equal(mac.done, mac.total);
    assert.equal(mac.status, 'done');
    const req = p.phases.find((x) => x.id === 'request')!;
    assert.equal(req.done, 0);
    assert.equal(req.total, vs.filter((v) => v.group === 'web' && !v.optional && v.section !== 'unavailable').length);
    assert.equal(req.sourceIds.length, req.total);
    assert.ok(p.collected >= mac.total);
    assert.ok(p.percent > 0 && p.percent < 1);
  });

  test('requests and arrivals', () => {
    const st = state((s) => {
      s.sources.discord = { requestedAt: hoursAgo(1) };
      s.sources.spotify = { requestedAt: hoursAgo(100) };
    });
    const s = stats({ linkedin: { count: 5 } }); // imported without a request in this app: counts as asked and arrived
    const p = progress(views({ state: st, stats: s }), NOW);
    const req = p.phases.find((x) => x.id === 'request')!;
    const arr = p.phases.find((x) => x.id === 'arrive')!;
    assert.equal(req.done, 3);
    assert.equal(arr.total, 3);
    assert.equal(arr.done, 1);
    assert.equal(arr.status, 'active');
    assert.deepEqual(p.waiting.map((w) => w.id), ['spotify', 'discord'], 'soonest expected first');
    assert.equal(p.waiting[0].ready, true);
    assert.equal(p.waiting[1].ready, false);
  });

  test('skipped and optional sources are not part of the percentage', () => {
    const base = progress(views(), NOW);
    const st = state((s) => (s.sources.reddit = { skipped: 'I don\'t use it' }));
    const skipped = progress(views({ state: st }), NOW);
    assert.equal(skipped.applicable, base.applicable - 1);
    assert.ok(!base.phases.find((x) => x.id === 'request')!.sourceIds.includes('google_photos_drive'));
  });

  test('readyIn wording', () => {
    const w = (from: number, by: number) => ({ id: 'x', name: 'X', readyFrom: NOW.getTime() + from * H, readyBy: NOW.getTime() + by * H, ready: from <= 0 });
    assert.equal(readyIn(w(0.5, 5), NOW), 'ready within the hour');
    assert.equal(readyIn(w(6, 48), NOW), 'ready in about 6 h');
    assert.equal(readyIn(w(72, 720), NOW), 'ready in about 3 days');
    assert.equal(readyIn(w(-1, 10), NOW), 'should be ready now');
    assert.equal(readyIn(w(-50, -2), NOW), 'should have arrived by now');
  });
});

describe('Setup Assistant steps', () => {
  test('one page per step, in the order of a first setup', () => {
    const steps = assistantSteps(views());
    assert.deepEqual(steps.slice(0, 6).map((s) => s.id), ['welcome', 'access', 'library', 'mac', 'iphone', 'accounts']);
    assert.deepEqual(steps.slice(-5).map((s) => s.id), ['mail', 'extras', 'identity', 'keep', 'done'], 'who you are once there is data; keeping history going last');
    for (const s of steps) assert.ok(STEP_GROUPS.includes(s.group), s.group);
    assert.equal(new Set(steps.map((s) => s.id)).size, steps.length);
  });

  test('one export page per chosen account, longest wait first', () => {
    const vs = views();
    const exports = assistantSteps(vs).filter((s) => s.kind === 'export').map((s) => s.sourceId);
    assert.deepEqual(exports, defaultChosen(vs));
    assert.ok(exports.indexOf('spotify') < exports.indexOf('google_takeout'));
    assert.ok(!exports.includes('google_photos_drive'), 'optional accounts start off');
    const picked = assistantSteps(vs, ['instagram', 'discord']).filter((s) => s.kind === 'export').map((s) => s.sourceId);
    assert.deepEqual(picked, ['discord', 'instagram']);
    assert.deepEqual(assistantSteps(vs, []).filter((s) => s.kind === 'export'), []);
  });

  test('the account list puts optional ones last', () => {
    const list = accountChoices(views()).map((v) => v.id);
    assert.equal(list[list.length - 1], 'google_photos_drive');
    assert.equal(list.length, CATALOG.filter((s) => s.group === 'web').length);
  });

  test('the accounts most people use are listed most used first, without the ones you added', () => {
    setServices([{ id: 'svc_wattpad', slug: 'wattpad', name: 'Wattpad', folder: 'wattpad', domains: ['wattpad.com'], addedAt: hoursAgo(1), from: 'you' }]);
    try {
      const list = commonAccounts(views({ state: state((s) => (s.services = [])) })).map((v) => v.id);
      assert.deepEqual(list, POPULARITY, 'every built-in web account, in that order');
      assert.deepEqual(list.slice(0, 4), ['google_takeout', 'google_photos_drive', 'facebook', 'instagram']);
      assert.ok(!list.includes('svc_wattpad'));
    } finally {
      setServices([]);
    }
  });

  test('recommendations: what you seem to use most first, and only the top few', () => {
    const f = (slug: string, emails: number, visits: number, apps: string[] = [], exportUrl?: string): FoundService =>
      ({ slug, name: slug, domains: [`${slug}.com`], emails, automated: 0, visits, apps, ...(exportUrl ? { export: { url: exportUrl } } : {}) });
    const found = [f('newsletter', 300, 0), f('duolingo', 2, 10, ['Duolingo on your iPhone']), f('strava', 40, 400),
      f('goodreads', 120, 120, [], 'https://goodreads.example/export'), f('etsy', 120, 120), ...Array.from({ length: 12 }, (_, i) => f(`shop${i}`, 1, 0))];
    const top = recommended(found).map((x) => x.slug);
    assert.equal(top.length, RECOMMENDED);
    assert.deepEqual(top.slice(0, 5), ['strava', 'duolingo', 'goodreads', 'etsy', 'newsletter'],
      'an app or a lot of visits beats a pile of mail; a tie goes to the one with export steps');
    assert.deepEqual(recommended([]), []);
  });

  test('the exports start with a list of them, so you can do them in any order', () => {
    const vs = views();
    const steps = assistantSteps(vs, ['instagram', 'discord', 'reddit']);
    const ids = steps.map((s) => s.id);
    assert.equal(ids[ids.indexOf('export:discord') - 1], 'exports', 'the list comes right before the pages');
    assert.deepEqual(ids.slice(ids.indexOf('accounts'), ids.indexOf('accounts') + 3), ['accounts', 'ai', 'exports'], 'AI is decided before the export pages, which offer Do It for Me');
    assert.ok(!assistantSteps(vs, []).some((s) => s.kind === 'exports'), 'no accounts, no list');
    const order = steps.filter((s) => s.kind === 'export').map((s) => s.sourceId);
    // From the list: the first not yet asked for. Jumping to the last and asking: back round to the first.
    assert.equal(nextExportStep(steps, vs), `export:${order[0]}`);
    assert.equal(nextExportStep(steps, vs, order[2]), `export:${order[0]}`);
    // Once the others are asked for or skipped, on to the step after the exports.
    const asked = views({ state: state((s) => {
      s.sources[order[0]!] = { requestedAt: hoursAgo(1) };
      s.sources[order[1]!] = { skipped: 'Not now' };
    }) });
    assert.equal(nextExportStep(steps, asked, order[0]), `export:${order[2]}`, 'skips what is handled');
    assert.equal(nextExportStep(steps, asked, order[2]), ids[ids.indexOf(`export:${order[2]}`) + 1]);
    const none = assistantSteps(vs, []);
    assert.equal(none[stepIndex(none, 'exports')].id, 'mail', 'all turned off: on past the exports, not back to the start');
  });

  test('the export pages keep their order as imports finish', () => {
    const before = assistantSteps(views(), ['discord', 'reddit']).map((s) => s.id);
    const after = assistantSteps(views({ stats: stats({ discord: { count: 3 } }) }), ['discord', 'reddit']).map((s) => s.id);
    assert.deepEqual(after, before, 'Discord collected: still the same pages in the same order');
    assert.deepEqual(assistantSteps([...views()].reverse(), ['discord', 'reddit']).map((s) => s.id), before);
  });

  test('a saved step survives the step list changing', () => {
    const steps = assistantSteps(views(), ['discord']);
    assert.equal(steps[stepIndex(steps, 'keep')].id, 'keep');
    assert.equal(steps[stepIndex(steps, 'history')].id, 'library', 'a step saved before the History page was split');
    assert.equal(steps[stepIndex(steps, 'export:spotify')].id, 'mail', 'an account dropped since: carry on after the exports');
    assert.equal(stepIndex(steps, undefined), 0);
    assert.equal(stepIndex(steps, 'nonsense'), 0);
  });
});
