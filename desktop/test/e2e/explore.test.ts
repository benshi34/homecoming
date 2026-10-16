// Explore, end to end: the real app over a made-up corpus (make_fixtures.explore_corpus) in UTC. Every artifact
// opens from its card, shows what the corpus holds, and opens the records it rests on.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot } from './harness.ts';

let sb: Sandbox;
let run: Running;
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';

before(async () => {
  sb = sandbox();
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'explore-corpus', sb.corpus]);
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_TZ: 'UTC' }));
  // Numbers count up and pages animate in; with Reduce Motion they land at once, so text can be read straight away.
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

const card = (id: string) => run.page.locator(`[data-testid=explore-card-${id}]`);
async function openCard(id: string) {
  await card(id).click();
  await run.page.locator(`[data-testid=explore-${id}]`).waitFor({ timeout: 60_000 });
}
async function back() {
  await run.page.click('[data-testid=explore-back]');
}

test('the tiles say what each artifact holds', async () => {
  await run.page.click('[data-testid=nav-explore]');
  await run.page.locator('[data-testid=explore-home]').waitFor({ timeout: 60_000 });
  // The cards show at once and fill in one by one as each artifact is built.
  for (const id of ['year', 'on-this-day', 'people', 'places', 'they-know', 'listening', 'movement', 'curiosity', 'journeys', 'watching', 'rhythms', 'groups', 'firsts', 'made', 'stream']) {
    await run.page.locator(`[data-testid=explore-card-${id}][data-ready=yes]`).waitFor({ timeout: 60_000 });
  }
  assert.match(await card('year').innerText(), /2025/, 'the latest year with data');
  assert.match(await card('groups').innerText(), /2\s+group chats/);
  assert.match(await card('journeys').innerText(), /21,7\d\d\s+km traveled[\s\S]*2\s+flights/);
  assert.match(await card('people').innerText(), /Grace Hopper/);
  assert.match(await card('places').innerText(), /2\s+countries[\s\S]*1\s+trip\b/);
  assert.match(await card('made').innerText(), /3\s+days in a row, your longest/);
  assert.match(await card('stream').innerText(), /March 2026, as it happened[\s\S]*3\s+events from/, 'the latest month');
  assert.match(await card('firsts').innerText(), /\d+\s+firsts/);
  assert.doesNotMatch(await run.page.locator('[data-testid=explore-home]').innerText(), /corpus/i, 'plain words');
});

test('a tile without enough to show is locked, and says what would unlock it', async () => {
  // This corpus has two days of steps, a few searches and one video, and no music.
  for (const id of ['listening', 'movement', 'curiosity', 'watching', 'they-know']) {
    await run.page.locator(`[data-testid=explore-card-${id}][data-ready=yes]`).waitFor({ timeout: 60_000 });
    assert.equal(await card(id).getAttribute('data-locked'), 'yes', `${id} is locked`);
  }
  for (const id of ['people', 'places', 'groups', 'journeys', 'made', 'rhythms', 'firsts']) assert.equal(await card(id).getAttribute('data-locked'), null, `${id} has enough`);
  assert.match(await card('listening').innerText(), /Needs your listening history[\s\S]*Spotify/);
  assert.match(await card('movement').innerText(), /Needs more of your Health data[\s\S]*2 of 14 days of steps so far[\s\S]*iPhone backup/, 'how much there is, and what unlocks it');
  assert.match(await card('curiosity').innerText(), /21 of 50 searches so far/);
  await shot(run.page, 'explore-locked-tiles');
  await card('listening').click();
  const page = run.page.locator('[data-testid=explore-locked]');
  await page.waitFor();
  assert.match(await page.innerText(), /Listening needs your listening history[\s\S]*top artists and songs each year/);
  assert.match(await page.locator('[data-testid=unlock-spotify]').innerText(), /Spotify[\s\S]*Not requested yet/);
  await shot(run.page, 'explore-locked');
  // "Add It…" shows the source in the main window, where it's requested; Explore, opened again, is where you left it.
  await page.locator('button[data-action=unlock-spotify]').click();
  await run.page.locator('[data-testid=detail][data-source=spotify]').waitFor({ timeout: 10_000 });
  await run.page.click('[data-testid=nav-explore]');
  await run.page.locator('[data-testid=explore-locked]').waitFor();
  await run.page.keyboard.press('Escape'); // Back, with no sheet open
  await run.page.locator('[data-testid=explore-home]').waitFor();
});

test('your people: the year-by-year circle, everyone, and one person over time', async () => {
  await openCard('people');
  assert.match(await run.page.locator('[data-testid=circle]').innerText(), /2025[\s\S]*Grace Hopper/);
  assert.equal(await run.page.locator('[data-testid=person-row]').count(), 2, 'Grace and lin; not you, not the group chat');
  await run.page.fill('[data-testid=people-search]', 'lin');
  assert.equal(await run.page.locator('[data-testid=person-row]').count(), 1);
  await run.page.fill('[data-testid=people-search]', 'grace');
  await run.page.locator('[data-testid=person-row]').first().click();
  await run.page.locator('[data-testid=explore-person]').waitFor();
  const text = await run.page.locator('[data-testid=explore-person]').innerText();
  assert.match(text, /Messages\s+14/);
  assert.match(text, /Photos together\s+3/);
  assert.equal(await run.page.locator('.explore-title').innerText(), 'Grace Hopper');
  // A message opens its conversation: both sides, the one you came from marked.
  await run.page.getByRole('button', { name: 'First Conversation' }).click();
  const convo = run.page.locator('[data-testid=convo]');
  await convo.waitFor();
  assert.match(await convo.innerText(), /saw your post![\s\S]*thanks!/);
  assert.equal(await convo.locator('.msg-row.me').count() > 0 && await convo.locator('.msg-row.them').count() > 0, true);
  assert.match(await convo.locator('.msg-row.anchor').innerText(), /saw your post!/);
  await run.page.keyboard.press('Escape');
  await back();
  await back();
});

test('places and trips: the map, the trip to Tokyo, and its photos', async () => {
  await openCard('places');
  await run.page.locator('.map svg .map-land').waitFor();
  assert.equal(await run.page.locator('.map-dot').count(), 2, 'home and Tokyo');
  await run.page.locator('[data-testid=trip]', { hasText: 'Shinjuku' }).click();
  await run.page.locator('[data-testid=explore-trip]').waitFor();
  assert.match(await run.page.locator('[data-testid=explore-trip]').innerText(), /3 days[\s\S]*Japan/);
  await run.page.locator('[data-testid=explore-thumb] img').first().waitFor({ timeout: 30_000 });
  await run.page.locator('[data-testid=explore-thumb]').first().click();
  await run.page.locator('[data-testid=ask-record]', { hasText: 'Shinjuku' }).waitFor();
  await run.page.keyboard.press('Escape');
  await back();
  await back();
});

test('rhythms: a day-by-hour heatmap with its table, for each kind of record', async () => {
  await openCard('rhythms');
  await run.page.locator('[data-testid=heat-grid] rect.heat').first().waitFor();
  assert.equal(await run.page.locator('[data-testid=heat-grid] rect.heat').count(), 7 * 24);
  assert.match(await run.page.locator('[data-testid=explore-rhythms]').innerText(), /Busiest hour\s+5 pm/);
  await run.page.getByRole('button', { name: 'Show as Table' }).click();
  assert.equal(await run.page.locator('.viz-table tbody tr').count(), 7);
  await run.page.click('[data-testid=rhythm-coding]');
  assert.match(await run.page.locator('[data-testid=explore-rhythms]').innerText(), /Busiest hour\s+8 pm/);
  await back();
});

test('firsts and what you made', async () => {
  await openCard('firsts');
  const firsts = await run.page.locator('[data-testid=explore-firsts]').innerText();
  assert.match(firsts, /First commit to\s+engine/);
  assert.match(firsts, /First photo in\s+Japan/);
  await run.page.click('[data-testid=firsts-country]');
  assert.equal(await run.page.locator('[data-testid=first]').count(), 2);
  await back();
  await openCard('made');
  await run.page.selectOption('[data-testid=made-year]', '2025');
  await run.page.click('[data-testid=made-code]');
  assert.match(await run.page.locator('[data-testid=explore-made]').innerText(), /Days in 2025\s+3/);
  assert.ok(await run.page.locator('[data-testid=calendar] rect.heat-5, [data-testid=calendar] rect.heat-1').count() > 0, 'the three days are marked');
  await back();
});

test('your year: a story to step through, and the year in numbers', async () => {
  await openCard('year');
  const slide = run.page.locator('[data-testid=year-slide]');
  const said: Record<string, string> = {};
  for (let i = 0; i < 20; i++) {
    said[(await slide.getAttribute('data-slide'))!] = await slide.innerText();
    if (!(await run.page.locator('[data-testid=story-next]').count())) break;
    await run.page.click('[data-testid=story-next]');
  }
  assert.deepEqual(Object.keys(said), ['intro', 'people', 'messages', 'new-people', 'travel', 'trips', 'photos', 'made', 'rhythm', 'steps', 'firsts', 'busiest']);
  assert.match(said.intro, /2025/);
  assert.match(said.people, /2[\s\S]*Grace Hopper/);
  assert.match(said.travel, /21,7\d\d[\s\S]*2 flights · 2 countries/);
  assert.match(said.steps, /13,000[\s\S]*9,000/);
  assert.match(said.busiest, /March 12/);
  await run.page.keyboard.press('ArrowLeft');
  assert.equal(await slide.getAttribute('data-slide'), 'firsts', '← goes back one');
  assert.match(await run.page.locator('[data-testid=year-numbers]').innerText(), /13,000\s+steps/);
  // Another year, and back: one story and one set of numbers each time, not one more on top.
  for (const y of ['2024', '2025', '2024', '2025']) {
    await run.page.selectOption('[data-testid=year-picker]', y);
    await run.page.locator('[data-testid=explore-year] .section-title', { hasText: y }).waitFor({ timeout: 60_000 });
    assert.equal(await run.page.locator('[data-testid=year-story]').count(), 1, `one story after switching to ${y}`);
    assert.equal(await run.page.locator('.num-card').count() > 0 && await run.page.locator('[data-testid=year-numbers]').count(), 1);
    assert.equal(await slide.getAttribute('data-slide'), 'intro', 'a new year starts at its beginning');
  }
  await back();
});

test('journeys: arcs on a night map, and every journey', async () => {
  await openCard('journeys');
  await run.page.locator('.arc-map:not(.mini) svg .arc').first().waitFor();
  assert.equal(await run.page.locator('.arc-map:not(.mini) .arc').count(), 2, 'there and back; not Sydney');
  assert.equal(await run.page.locator('[data-testid=leg]').count(), 2);
  assert.match(await run.page.locator('[data-testid=leg]').first().innerText(), /Shinjuku → Princeton[\s\S]*flew/);
  await run.page.locator('[data-testid=leg]').first().click();
  await run.page.locator('[data-testid=ask-record]', { hasText: 'Princeton' }).waitFor();
  await run.page.keyboard.press('Escape');
  await back();
});

test('group chats: from any app, and what one chat says most', async () => {
  await openCard('groups');
  assert.equal(await run.page.locator('[data-testid=group-card]').count(), 2, 'not the channel only your side of was kept');
  assert.match(await run.page.locator('[data-testid=group-card]', { hasText: 'Katherine, Dorothy' }).innerText(), /Signal/);
  await run.page.locator('[data-testid=group-card]', { hasText: 'Dinner club' }).click();
  await run.page.locator('[data-testid=explore-group]').waitFor();
  const text = await run.page.locator('[data-testid=explore-group]').innerText();
  assert.match(text, /croissant/);
  assert.doesNotMatch(text, /attachment/, 'lines the app wrote itself are nobody\'s words');
  await run.page.getByRole('button', { name: 'How It Started' }).click();
  await run.page.locator('[data-testid=convo]').waitFor();
  assert.match(await run.page.locator('[data-testid=convo]').innerText(), /who's in\?/);
  await run.page.keyboard.press('Escape');
  await back();
  await back();
});

test('Back returns to a page as you left it: its search, sort, year and scroll; and so does coming back to Explore', async () => {
  const p = run.page;
  await openCard('people');
  await p.fill('[data-testid=people-search]', 'grace');
  await p.locator('button[role=tab]', { hasText: 'Most Recent' }).click();
  await p.locator('[data-testid=person-row]').first().click();
  await p.locator('[data-testid=explore-person]').waitFor();
  await p.keyboard.press('Meta+BracketLeft'); // ⌘[ is Back
  await p.locator('[data-testid=explore-people]').waitFor();
  assert.equal(await p.inputValue('[data-testid=people-search]'), 'grace', 'the search is kept');
  assert.equal(await p.locator('.explore-bar button[aria-selected=true]').innerText(), 'Most Recent', 'and the sort');
  assert.equal(await p.locator('[data-testid=person-row]').count(), 1);
  // Esc in the search field is the field's; Esc elsewhere is Back.
  await p.focus('[data-testid=people-search]');
  await p.keyboard.press('Escape');
  assert.equal(await p.locator('[data-testid=explore-people]').count(), 1);
  await p.locator('.explore-scroll').click({ position: { x: 5, y: 5 } });
  await p.keyboard.press('Escape');
  await p.locator('[data-testid=explore-home]').waitFor();

  // What You Made: a year and a kind, a day of it opened in Your Stream, and back to that year and kind.
  await openCard('made');
  await p.selectOption('[data-testid=made-year]', '2025');
  await p.click('[data-testid=made-code]');
  const day = p.locator('[data-testid=calendar] rect.day-link').first();
  await p.locator('[data-testid=calendar]').scrollIntoViewIfNeeded();
  await p.locator('.explore-scroll').evaluate((el) => el.scrollBy(0, 40));
  const top = await p.locator('.explore-scroll').evaluate((el) => el.scrollTop);
  const date = await day.getAttribute('data-day');
  assert.equal(date, '2025-03-10', 'the first day of the streak');
  await day.click();
  await p.locator('[data-testid=explore-stream]').waitFor();
  await p.waitForFunction(() => (document.querySelector('[data-testid=stream-month]') as HTMLSelectElement)?.value === '2025-03', null, { timeout: 60_000 });
  await back();
  await p.locator('[data-testid=explore-made]').waitFor();
  assert.equal(await p.inputValue('[data-testid=made-year]'), '2025');
  assert.match(await p.locator('[data-testid=explore-made]').innerText(), /Days in 2025\s+3[\s\S]*with commits/);
  assert.equal(await p.locator('.explore-scroll').evaluate((el) => el.scrollTop), top, 'scrolled where it was');

  // Leaving Explore for the rest of the window and coming back: the same page, the same year.
  await p.click('[data-testid=nav-overview]');
  await p.locator('[data-testid=explore]').waitFor({ state: 'detached' });
  await p.click('[data-testid=nav-explore]');
  await p.locator('[data-testid=explore-made]').waitFor();
  assert.equal(await p.inputValue('[data-testid=made-year]'), '2025');
  // And the sidebar's Explore, clicked while on Explore, takes it home.
  await p.click('[data-testid=nav-explore]');
  await p.locator('[data-testid=explore-home]').waitFor();
  assert.deepEqual(run.errors, []);
});

test('a year picked is the year of every panel under it, one picker on every page', async () => {
  const p = run.page;
  await openCard('journeys');
  const countries = p.locator('[data-testid=journeys-countries]');
  assert.match(await countries.innerText(), /The first time you were in each\n/);
  await p.selectOption('[data-testid=journeys-year]', '2025');
  assert.match(await countries.innerText(), /in each in 2025[\s\S]*United States[\s\S]*Japan/);
  assert.match(await p.locator('[data-testid=explore-journeys]').innerText(), /Every journey in 2025/);
  // the year before and after, and back to all of them
  assert.equal(await p.locator('[data-testid=journeys-year-next]').isDisabled(), true, 'the latest year has no year after it');
  await p.selectOption('[data-testid=journeys-year]', 'all');
  await p.click('[data-testid=journeys-year-prev]');
  assert.equal(await p.inputValue('[data-testid=journeys-year]'), '2025', 'from All Years, the year before is the latest');
  await back();
  await openCard('year');
  assert.deepEqual(await p.locator('[data-testid=year-picker] option').allInnerTexts(), ['2025', '2024'], 'every year, no cap');
  await back();
});

test('on this day: any date, through the app', async () => {
  const r = await run.page.evaluate(() => (window as unknown as { api: { explore(op: string, a: unknown[]): Promise<{ years: { year: number }[] }> } })
    .api.explore('on-this-day', ['03-12']));
  assert.deepEqual(r.years.map((y) => y.year), [2026, 2025, 2024]);
  await openCard('on-this-day');
  await run.page.locator('[data-testid=otd-year], .empty').first().waitFor();
  // A day with nothing on it offers the nearest one that has something (this corpus has nothing near most days).
  if (await run.page.locator('[data-testid=otd-none]').count()) {
    const near = run.page.locator('[data-testid=otd-none] button[data-action^=otd-nearest]').first();
    await near.click();
    await run.page.locator('[data-testid=otd-year]').first().waitFor({ timeout: 60_000 });
  }
  assert.doesNotMatch(await run.page.locator('[data-testid=explore-on-this-day]').innerText(), /\b1 (calls|messages|searches|photos|years)\b/);
  assert.deepEqual(run.errors, []);
});

test('with motion on, tiles zoom into their pages and back, and numbers count up to what they say', async () => {
  await run.page.emulateMedia({ reducedMotion: 'no-preference' });
  await back();
  await run.page.locator('[data-testid=explore-home]').waitFor();
  await card('people').click();
  await run.page.locator('[data-testid=explore-people]').waitFor();
  await run.page.waitForTimeout(1200);
  assert.equal(await run.page.locator('.hero-num b').first().innerText(), '2');
  await run.page.locator('[data-testid=person-row]').first().click();
  await run.page.locator('[data-testid=explore-person]').waitFor();
  await run.page.waitForTimeout(1000);
  await back();
  await run.page.waitForTimeout(800);
  await back();
  await run.page.locator('[data-testid=explore-home]').waitFor();
  await run.page.waitForTimeout(1000);
  assert.match(await card('made').innerText(), /3\s+days in a row/);
  assert.deepEqual(run.errors, [], 'no view transition was refused (two elements with one name) and nothing threw');
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
});

test('your stream: a month in order, by kind, searched, a day at a time, and every record behind an event', async () => {
  const p = run.page;
  const events = () => p.locator('[data-testid=stream-event]');
  const kinds = async () => [...new Set(await events().evaluateAll((els) => els.map((e) => e.getAttribute('data-kind'))))].sort();
  const pick = async (m: string, n: number) => {
    await p.selectOption('[data-testid=stream-month]', m);
    await p.waitForFunction(([want, k]) => document.querySelector('.explore-hero')?.textContent?.includes(want) && document.querySelectorAll('[data-testid=stream-event]').length === k,
      [`${n} events in ${new Date(`${m}-15T12:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}`, n] as const, { timeout: 60_000 });
  };
  await openCard('stream');
  assert.match(await p.locator('.explore-hero').innerText(), /3\s+events in March 2026/);
  assert.equal(await events().count(), 3);
  assert.equal(await p.inputValue('[data-testid=stream-month]'), '2026-03');
  assert.equal(await p.locator('[data-testid=stream-next]').isDisabled(), true, 'the latest month');
  assert.equal(await p.locator('[data-testid=stream-day-jump]').count(), 31, 'every day of March');
  assert.equal(await p.locator('[data-testid=stream-day-jump]:not([disabled])').count(), 2);
  assert.match(await p.locator('[data-testid=stream-day]').first().textContent() ?? '', /Thursday, March 12[\s\S]*2 events[\s\S]*Took 1 photo in Princeton[\s\S]*Texted with Grace H \(2 messages\)/);
  assert.match(await p.locator('[data-testid=stream-file]').innerText(), /Saved on this Mac as a file Ask can read/);
  assert.doesNotMatch(await p.locator('[data-testid=explore-stream]').innerText(), /corpus|jsonl|\b0 records/, 'plain words, and no "0 records aren\'t events"');

  // Kinds, back and forth: a second click on a kind shows everything again.
  await p.click('[data-testid=stream-kind-photos]');
  assert.deepEqual([await events().count(), await kinds()], [1, ['photos']]);
  await p.click('[data-testid=stream-kind-talk]');
  assert.deepEqual([await events().count(), await kinds()], [2, ['conversation']]);
  await p.click('[data-testid=stream-kind-talk]');
  assert.equal(await events().count(), 3);
  // Search: within the month, then nothing, then everything again.
  await p.fill('[data-testid=stream-search]', 'princeton');
  assert.equal(await events().count(), 1);
  assert.match(await p.locator('[data-testid=stream-kind-all]').innerText(), /Everything\s+1/, 'the kinds count what the search finds');
  assert.equal(await p.locator('[data-testid=stream-kind-talk]').count(), 0);
  await p.fill('[data-testid=stream-search]', 'nothing like this');
  await p.locator('[data-testid=stream-none]').waitFor();
  await p.fill('[data-testid=stream-search]', '');
  assert.equal(await events().count(), 3);

  // A conversation opens where it happened.
  await events().filter({ hasText: 'Texted with Grace H' }).first().locator('.stream-row').click();
  assert.match(await p.locator('[data-testid=stream-more]').textContent() ?? '', /You: |Grace: /);
  await p.locator('[data-testid=stream-more] button[data-action=stream-conversation]').click();
  await p.locator('[data-testid=convo]').waitFor();
  await p.keyboard.press('Escape');

  // Older months, picked from the menu and stepped through, and back.
  await p.click('[data-testid=stream-prev]');
  await p.waitForFunction(() => (document.querySelector('[data-testid=stream-month]') as HTMLSelectElement)?.value === '2025-08', null, { timeout: 60_000 });
  await pick('2025-05', 16);
  const club = events().filter({ hasText: 'Messages in “Dinner club” (3 messages)' }).first();
  await club.locator('.stream-row').click();
  await p.locator('[data-testid=stream-more] button[data-action=stream-records]').click();
  await p.locator('[data-testid=stream-rec]').nth(2).waitFor();
  assert.equal(await p.locator('[data-testid=stream-rec]').count(), 3, 'every record in it');
  await p.locator('[data-testid=stream-records] button', { hasText: 'Done' }).click();
  await p.click('[data-testid=stream-next]');
  await p.waitForFunction(() => document.querySelector('.explore-hero')?.textContent?.includes('June 2025'), null, { timeout: 60_000 });
  await pick('2026-03', 3);
  assert.equal(await p.locator('[data-testid=stream-day-jump]').count(), 31);

  // A month that isn't saved as a file yet can be, from here.
  fs.rmSync(path.join(sb.corpus, 'stream'), { recursive: true, force: true });
  await pick('2024-06', 20);
  assert.match(await p.locator('[data-testid=stream-file]').innerText(), /isn't saved as a file yet/);
  await p.click('[data-testid=stream-file] button[data-action=stream-save]');
  await p.locator('[data-testid=stream-file]', { hasText: 'Saved on this Mac' }).waitFor({ timeout: 60_000 });
  assert.equal(fs.readFileSync(path.join(sb.corpus, 'stream', '2024-06.jsonl'), 'utf8').trim().split('\n').length, 20);
  assert.deepEqual(run.errors, []);
});

