// The demo (scripts/demo.mjs) on its made-up library, in a folder of its own: it reads nothing real (its home folder
// is made up), every page has something to show, it keeps the library as it is, Do It for Me is a stand-in, and
// links aren't opened. Ask uses the stand-in for Claude Code here. DEMO_PHOTOS=dir cuts the photos from real
// pictures (for looking at the screenshots); DEMO_REAL_ASK=1 asks your own Claude Code.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
// @ts-expect-error: a plain .mjs script, without types
import { demoEnv, prepare } from '../../scripts/demo.mjs';
import { act, clickAction, DESKTOP, find, launch, type Running, selectSource, shot, snap, until } from './harness.ts';

let root: string;
let d: Record<string, string>;
let run: Running;

before(async () => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'homecoming-demo-'));
  d = prepare(path.join(root, 'Homecoming (demo)'), { photos: process.env.DEMO_PHOTOS || null });
  fs.writeFileSync(path.join(root, 'claude-plan.json'), JSON.stringify({ answer: 'You texted **Maya Chen** the most this year.', steps: [{ tool: 'sql', input: { query: 'select 1' } }] }));
  run = await launch({ ...demoEnv(d), UMP_HIDDEN: '1', UMP_DEMO_DOWNLOAD_MS: '1500', UMP_EXTERNAL_LOG: path.join(root, 'opened.txt'),
    ...(process.env.DEMO_REAL_ASK ? {} : { UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: path.join(root, 'claude-plan.json') }) });
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  fs.rmSync(root, { recursive: true, force: true });
});

test('a whole library, read from nothing real', async () => {
  const p = run.page;
  const s = await snap(p);
  assert.equal(s.demo, true);
  assert.equal(s.label, 'Demo: made-up data');
  assert.equal(s.corpusPath, d.corpus);
  assert.match(find(s, 'iphone_backup').detail ?? '', /^Riley's iPhone/, 'the made-up home\'s iPhone backup, not this Mac\'s');
  for (const id of ['imessage', 'photos', 'calendar', 'calls', 'apple_notes', 'browser_history', 'contacts', 'git_commits', 'iphone_backup',
    'google_takeout', 'instagram', 'facebook', 'discord', 'linkedin', 'x', 'spotify', 'chatgpt']) {
    assert.equal(find(s, id).section, 'done', `${id}: ${find(s, id).status}`);
  }
  assert.match(find(s, 'notion').status, /^Requested/, 'one on its way');
  assert.equal(find(s, 'claude_ai').section, 'needs', 'one not asked for yet');
  const needs = s.sources.filter((v) => v.section === 'needs').map((v) => `${v.id}: ${v.status}`);
  console.log(`Needs you:\n  ${needs.join('\n  ')}`);
  assert.deepEqual(needs, ['claude_ai: Not requested yet'], 'only what the demo leaves for Do It for Me');
  await shot(p, 'demo-overview');
});

test('a collected source shows itself over the years, by hour and weekday, day by day, and in words; Explore is a click away', async () => {
  const p = run.page;
  await selectSource(p, 'imessage');
  const g = p.locator('[data-testid=glance]');
  await g.waitFor({ timeout: 60_000 });
  for (const part of ['glance-months', 'glance-hours', 'glance-weekdays', 'glance-calendar', 'glance-facts']) await g.locator(`[data-testid=${part}]`).waitFor();
  assert.ok(await g.locator('[data-testid=glance-months] rect').count() > 12, 'a bar a month');
  const facts = await g.locator('[data-testid=glance-facts]').innerText();
  for (const f of ['Your first message', 'Busiest day', 'Longest run', 'Written by you', 'Conversations']) assert.match(facts, new RegExp(f));
  await selectSource(p, 'calls');
  await p.locator('[data-testid=glance-facts]', { hasText: 'Time on calls' }).waitFor({ timeout: 60_000 });
  await shot(p, 'demo-source-glance');
  // Samples: records as they are, from across the years, the latest or at random; every one, searched; a message opens
  // in its conversation.
  await selectSource(p, 'imessage');
  const samples = p.locator('[data-testid=samples]');
  await samples.locator('[data-testid=sample-row]').first().waitFor({ timeout: 30_000 });
  const years = await samples.locator('[data-testid=sample-row] .sample-when').allInnerTexts();
  assert.ok(new Set(years.map((t) => t.match(/\d{4}/)?.[0])).size >= 5, `from across the years: ${years.join(' | ')}`);
  await p.click('[data-testid=samples-recent]');
  await samples.locator('[data-testid=sample-row]').first().waitFor();
  await samples.locator('[data-testid=sample-row]').first().click();
  await p.locator('[data-testid=conversation]').waitFor({ timeout: 20_000 });
  await p.keyboard.press('Escape');
  await p.click('[data-testid=samples] button[data-action=browse-records]');
  const browse = p.locator('[data-testid=browse-records]');
  await browse.locator('[data-testid=sample-row]').first().waitFor();
  await p.fill('[data-testid=browse-search]', 'dinner');
  await browse.locator('[data-testid=browse-count]', { hasText: /\d+ match/ }).waitFor();
  assert.match(await browse.locator('[data-testid=sample-row]').first().innerText(), /dinner/i);
  await p.keyboard.press('Escape');
  await selectSource(p, 'photos');
  await p.locator('[data-testid=samples] .thumbs .thumb').first().waitFor({ timeout: 30_000 });
  await selectSource(p, 'calls');
  await p.locator('[data-testid=glance-facts]', { hasText: 'Time on calls' }).waitFor({ timeout: 60_000 });
  await p.click('[data-testid=glance] button[data-action=glance-explore]');
  await p.locator('[data-testid=explore-people]').waitFor({ timeout: 60_000 });
  await p.click('[data-testid=explore-back]');
  await p.locator('[data-testid=explore-home]').waitFor();
});

test('Explore has a life to show', async () => {
  const p = run.page;
  await p.click('[data-testid=nav-explore]');
  await p.locator('[data-testid=explore-home]').waitFor({ timeout: 60_000 });
  for (const id of ['year', 'on-this-day', 'people', 'places', 'they-know', 'listening', 'movement', 'curiosity', 'journeys', 'watching', 'rhythms', 'groups', 'firsts', 'made', 'stream']) {
    await p.locator(`[data-testid=explore-card-${id}][data-ready=yes]`).waitFor({ timeout: 90_000 });
    assert.equal(await p.locator(`[data-testid=explore-card-${id}]`).getAttribute('data-locked'), null, `${id} has enough in the demo`);
  }
  await p.waitForTimeout(1500); // the photos on the tiles
  await shot(p, 'demo-explore');
  for (const [i, y] of [[2, 560], [3, 1500]] as const) {
    await p.locator('.explore-scroll').evaluate((el, top) => el.scrollTo(0, top), y);
    await p.waitForTimeout(600);
    await shot(p, `demo-explore-${i}`);
  }
  await p.locator('.explore-scroll').evaluate((el) => el.scrollTo(0, 0));
  const card = (id: string) => p.locator(`[data-testid=explore-card-${id}]`);
  assert.match(await card('people').innerText(), /Maya Chen|Jordan Reyes|Priya Patel/);
  assert.match(await card('groups').innerText(), /group chats/);
  assert.match(await card('they-know').innerText(), /1,0\d\d\s+companies have you/);
  for (const id of ['people', 'places', 'listening', 'movement', 'curiosity', 'watching', 'groups', 'journeys', 'year', 'stream']) {
    await card(id).click();
    await p.locator(`[data-testid=explore-${id === 'year' ? 'year-story' : id}], [data-testid=explore-${id}]`).first().waitFor({ timeout: 60_000 }).catch(() => {});
    await p.waitForTimeout(1800);
    await shot(p, `demo-explore-${id}`);
    if (id === 'people') {
      await p.locator('[data-testid=person-row]').first().click();
      await p.waitForTimeout(1500);
      await shot(p, 'demo-explore-person');
      await p.click('[data-testid=explore-back]');
    }
    await p.click('[data-testid=explore-back]').catch(() => p.click('[data-testid=nav-explore]'));
    await p.locator('[data-testid=explore-home]').waitFor({ timeout: 20_000 }).catch(() => p.click('[data-testid=nav-explore]'));
  }
});

test('What They Know: every advertiser, what they decided, who told on you; searched, filtered, opened', async () => {
  const p = run.page;
  await p.click('[data-testid=nav-explore]');
  const card = p.locator('[data-testid=explore-card-they-know]');
  await card.click();
  const page = p.locator('[data-testid=explore-they-know]');
  await page.waitFor({ timeout: 60_000 });
  await p.waitForTimeout(1200);
  await shot(p, 'demo-they-know');
  const hero = await page.locator('.explore-hero').innerText();
  assert.match(hero, /1,0\d\d\s+companies have you/);
  for (const svc of ['Facebook', 'Instagram', 'X', 'LinkedIn']) assert.match(hero, new RegExp(`From your .*\\b${svc}\\b.* exports`), svc); // most first: Facebook and Instagram are about even
  const guesses = await page.locator('[data-testid=tk-guesses]').innerText();
  assert.match(guesses, /Frequent travelers/);
  assert.match(await page.locator('[data-testid=tk-guesses] [data-testid=tk-fact]', { hasText: '25-34' }).innerText(), /age/, 'a single answer is a card, large');
  assert.equal(await page.locator('[data-testid=tk-card]').count(), 3, 'one card each: Facebook and Instagram (one profile), X, LinkedIn');
  // The crowd: a dot each, by how they got you; find one, hover one.
  assert.match(await page.locator('[data-testid=tk-legend]').first().innerText(), /Had you on a list\s+\d+[\s\S]*Saw what you did\s+\d+/);
  await page.locator('[data-testid=tk-find]').fill('strava');
  assert.match(await page.locator('[data-testid=tk-found]').innerText(), /1 has you:\s*Strava/);
  await page.locator('[data-testid=tk-find]').fill('air');
  const air = await page.locator('[data-testid=tk-found]').innerText();
  assert.match(air, /Airbnb/);
  assert.doesNotMatch(air, /Prairie/, 'a name is found by how a word in it starts');
  await page.locator('[data-testid=tk-find]').fill('nobody by this name');
  assert.match(await page.locator('[data-testid=tk-found]').innerText(), /Not one/);
  await page.locator('[data-testid=tk-find]').fill('');
  assert.match(await page.locator('.tk-found').innerText(), /heard from\s+10\s+of them/);
  const crowd = page.locator('[data-testid=tk-crowd] canvas');
  const box = (await crowd.boundingBox())!;
  await p.mouse.move(box.x + 6, box.y + 6);
  await page.locator('.tk-tip').waitFor();
  assert.match(await page.locator('.tk-tip').innerText(), /uploaded a list you were on/, 'the first dots are the ones that had you on a list');
  await p.mouse.move(box.x - 40, box.y - 40);
  await page.locator('.tk-tip').waitFor({ state: 'detached' });
  assert.match(await page.locator('[data-testid=tk-told]').innerText(), /Airbnb|United Airlines|REI Co-op/);
  // An interest you turned off says so.
  const x = page.locator('[data-testid=tk-card]', { hasText: /^X/ });
  await x.locator('[data-testid=tk-see-all]').click();
  const sheet = p.locator('[data-testid=tk-sheet]');
  await sheet.waitFor();
  assert.equal(await sheet.locator('.chip.off', { hasText: 'Cryptocurrency' }).count(), 1, 'every interest, one you turned off marked');
  await shot(p, 'demo-they-know-sheet');
  await sheet.locator('button', { hasText: 'Done' }).click();
  await sheet.waitFor({ state: 'detached' });
  assert.ok(await page.locator('[data-testid=tk-lane]').count() >= 5, 'a timeline for each company that told on you');
  // Every advertiser, searchable: 120 at first, more on request; filters and search, back and forth.
  const list = page.locator('[data-testid=tk-advertisers]');
  const rows = list.locator('[data-testid=tk-advertiser]');
  assert.equal(await rows.count(), 120);
  await list.locator('button[data-action=tk-more]').click();
  assert.equal(await rows.count(), 620);
  await list.locator('[data-testid=tk-filter-emailed]').click();
  assert.equal(await rows.count(), 10, 'the brands Riley gets email from');
  assert.match(await rows.first().innerText(), /emailed you/);
  await list.locator('[data-testid=tk-filter-list]').click();
  const lists = await rows.count();
  assert.ok(lists >= 100 && lists <= 120);
  await list.locator('[data-testid=tk-search]').fill('strava');
  assert.equal(await rows.count(), 1);
  await list.locator('button[role=tab]', { hasText: 'All' }).click();
  assert.equal(await rows.count(), 1, 'the search stays');
  await list.locator('[data-testid=tk-search]').fill('nobody by this name');
  await list.locator('.tk-none').waitFor();
  await list.locator('[data-testid=tk-search]').fill('');
  assert.equal(await rows.count(), 120);
  await shot(p, 'demo-they-know-list');
  // Anything opens the record it came from.
  await page.locator('[data-testid=tk-guesses] .chip').first().click();
  await p.locator('[data-testid=ask-record]').waitFor();
  await p.keyboard.press('Escape');
  await p.locator('[data-testid=ask-record]').waitFor({ state: 'detached' });
  // Back home and in again: the same page, from its cache.
  await p.click('[data-testid=explore-back]');
  await p.locator('[data-testid=explore-home]').waitFor();
  await card.click();
  await page.waitFor();
  assert.equal(await page.locator('[data-testid=tk-advertisers] [data-testid=tk-advertiser]').count(), 120);
  await p.click('[data-testid=explore-back]');
  assert.deepEqual(run.errors, []);
});

test('Ask answers from the made-up library', async () => {
  const p = run.page;
  await p.click('[data-testid=nav-ask]');
  await p.locator('button[data-action=ai-on]').click(); // AI isn't decided yet: the demo shows the one-time choice
  await p.locator('[data-testid=ask-input]').fill('Who have I texted the most this year?');
  await p.locator('[data-testid=ask-send]').click();
  await p.locator('[data-testid=ask-stop], [data-testid=ask-retention]').first().waitFor();
  const sheet = p.locator('[data-testid=ask-retention]');
  if (await sheet.isVisible()) {
    await sheet.locator('input[type=checkbox]').check();
    await sheet.locator('button[data-action=confirm-retention]').click();
  }
  await p.locator('[data-testid=ask-stop]').waitFor({ timeout: 10_000 }).catch(() => {}); // a stand-in can be done already
  await p.locator('[data-testid=ask-send]').waitFor({ timeout: 240_000 });
  await p.waitForTimeout(800);
  await shot(p, 'demo-ask');
  assert.match(await p.locator('[data-testid=ask-turn]').last().innerText(), /Maya|Jordan|Priya|Mom/);
});

test('Do It for Me is a stand-in, links stay closed, and the library stays as it is', async () => {
  const p = run.page;
  const manifest = fs.statSync(path.join(d.corpus, 'manifest.json')).mtimeMs;
  await selectSource(p, 'claude_ai');
  await clickAction(p, 'agent-request');
  assert.match(await p.locator('[data-testid=agent-opt-in] [data-testid=agent-demo-note]').innerText(), /In the demo, a stand-in plays Claude: nothing opens/);
  await p.locator('[data-testid=agent-opt-in] button[data-action=agent-on]').click();
  await p.locator('[data-testid=status]', { hasText: 'Signed in as rileyp' }).waitFor({ timeout: 20_000 });
  await shot(p, 'demo-do-it-for-me');
  let s = await until(p, 'requested by the stand-in', (x) => !!find(x, 'claude_ai').requestedAt, 30_000);
  assert.match(find(s, 'claude_ai').status, /^Requested/);
  // Its downloads are made up too: it says so, rather than sit at "Downloading in Chrome" for 45 minutes.
  await act(p, 'notion', 'agent-download');
  await until(p, 'downloading', (x) => find(x, 'notion').status === 'Downloading in Chrome', 30_000);
  s = await until(p, 'said so', (x) => find(x, 'notion').status !== 'Downloading in Chrome', 15_000);
  assert.ok(s.log.some((l) => /In the demo, nothing really downloads/.test(l.line)));
  await act(p, 'claude_ai', 'open');
  await act(p, '*', 'run-all-mac');
  const log = (await snap(p)).log.map((l) => l.line).join('\n');
  assert.match(log, /The demo doesn't open links \(this one goes to claude\.ai\)/);
  assert.match(log, /The demo keeps its made-up library as it is/);
  assert.equal(fs.statSync(path.join(d.corpus, 'manifest.json')).mtimeMs, manifest, 'nothing was read into it');
  assert.deepEqual(run.errors, []);
});
