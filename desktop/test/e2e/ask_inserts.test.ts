// What an Ask answer shows in place, beyond conversations and photos: a map, a day, a chart over time, a person, an
// email, songs, a trip, a calendar and what a company decided about you, each drawn from the library on this Mac and
// each opening what it shows (a record, a conversation, its page in Explore). Claude Code is the stand-in
// (test/fakes), its answer scripted, over a made-up library (make_fixtures.inserts_corpus) in UTC. Nothing here
// reaches the network or a real AI.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { claudeChecked, DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot } from './harness.ts';

let sb: Sandbox;
let run: Running;
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const SHOTS = process.env.UMP_SHOTS; // also save the screens looked at here, to this folder
const look = async (name: string) => {
  await shot(run.page, name);
  if (SHOTS) await run.page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });
};
let rowid: (where: string) => number;

before(async () => {
  sb = sandbox({ identity: true });
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'inserts-corpus', sb.corpus], { env: { ...process.env, UMP_TZ: 'UTC' } });
  const db = path.join(sb.corpus, 'corpus.db');
  rowid = (where) => Number(execFileSync(PY, ['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(db)}).execute(${JSON.stringify(`select rowid from records where ${where} order by ts`)}).fetchone()[0])`]).toString());
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, ask: claudeChecked(), onboarding: { done: true },
    settings: { aiOn: true, aiAgreedAt: new Date().toISOString() } }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_TZ: 'UTC', TZ: 'UTC', UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: path.join(sb.root, 'claude-plan.json'),
  }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await run.page.locator('[data-testid=nav-ask]').click();
  await run.page.locator('[data-testid=ask-empty]').waitFor();
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

// Asks a question the stand-in answers with `answer`, in a new conversation, and waits for the answer.
async function ask(question: string, answer: string) {
  const p = run.page;
  for (let i = 0; i < 3 && await p.locator('.sheet-backdrop').count(); i++) await p.keyboard.press('Escape');
  fs.writeFileSync(path.join(sb.root, 'claude-plan.json'), JSON.stringify({ steps: [{ tool: 'search', input: { query: 'Grace' } }], answer }));
  await p.locator('[data-testid=ask-new]').click();
  await p.locator('[data-testid=ask-input]').fill(question);
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-answer]').last().waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-send]').waitFor({ timeout: 30_000 });
}
const card = (id: string) => run.page.locator('[data-testid=ask-answer]').last().locator(`[data-testid=${id}]`);
// Back to Ask from Explore, to the same answer.
async function backToAsk() {
  await run.page.locator('[data-testid=nav-ask]').click();
  await card('ask-trip').waitFor();
}

test('an answer shows a map, a day, a chart, a person, an email, songs, a trip, a calendar and what Meta decided', async () => {
  const p = run.page;
  const email = rowid("source = 'gmail' and is_me = 0");
  const podcast = rowid("source = 'podcasts'");
  const warp = rowid("source = 'spotify' and title = 'Warp'");
  await ask('Tell me about March 2025', [
    'Tokyo, for three days:', '[[trip:2025-03-21]]',
    'Where you were that spring:', '[[map:2025-03-01..2025-04-30]]',
    'The Wednesday before you left:', '[[day:2025-03-12]]',
    'How often you text Grace:', '[[trend:messages:Grace Hopper]]', '[[person:Grace Hopper]]',
    'Katherine wrote the day before:', `[[email:${email}]]`,
    'What you played that morning:', `[[songs:${podcast},${warp}]]`,
    'Your calendar that day:', '[[agenda:2025-03-12]]',
    'And what Meta decided about you:', '[[they-know:Meta]]',
    'Someone who isn\'t in your data:', '[[person:Nobody Atall]]',
    `Read [[email:${email}]] again, or see [[day:2025-03-12]].`,
  ].join('\n'));

  // The trip: where and when, its map, its photos.
  const trip = card('ask-trip');
  await trip.locator('img').first().waitFor();
  assert.match(await trip.locator('.embed-chat-who').innerText(), /🇯🇵 Shinjuku, Japan\s*Mar 20 to 22, 2025 · 3 days · 3 photos/);
  assert.equal(await trip.locator('svg .dot').count(), 1, 'one spot on its map');
  assert.match(await trip.locator('.viz.map svg').innerHTML(), /class="map-label"[^>]*>Shinjuku</, 'named on the map');

  // The map of the spring: home and Tokyo, not the picture someone sent, nor a friend's shared album.
  const map = card('ask-map');
  await map.locator('svg .dot').first().waitFor();
  assert.equal(await map.locator('svg .dot').count(), 2);
  assert.match(await map.locator('.embed-photos-cap').innerText(), /Princeton and Shinjuku · March 1 to April 20, 2025 · 2 places/);

  // The day, in order; a conversation in it opens whole.
  const day = card('ask-day');
  assert.match(await day.locator('.embed-chat-who').innerText(), /Wednesday, March 12, 2025\s*\d+ things that happened · \d+ photos?/);
  const shown = await day.locator('[data-testid=ask-day-event]').count();
  assert.equal(shown, 8, 'the first eight');
  await day.locator('[data-testid=ask-day-more]').click();
  assert.ok(await day.locator('[data-testid=ask-day-event]').count() > shown, 'and the rest a click away');
  const rows = await day.locator('[data-testid=ask-day-event]').allInnerTexts();
  assert.ok(rows.some((r) => /Dinner with Grace/.test(r)) && rows.some((r) => /Grace/.test(r) && /Messages/.test(r)), rows.join(' | '));
  await day.locator('[data-testid=ask-day-event]', { hasText: 'Messages' }).first().click();
  await p.locator('[data-testid=convo]').waitFor();
  await p.locator('[data-testid=conversation] button', { hasText: 'Done' }).click();

  // The chart: every month from the first to the last, its busiest said in words.
  const trend = card('ask-trend');
  assert.match(await trend.locator('.embed-trend-head').innerText(), /Messages with Grace Hopper\s*14 messages · 2024 to 2026/);
  assert.equal(await trend.locator('svg .bar').count(), 5, 'a bar for each month with messages');
  assert.equal(await trend.locator('svg > g').count() - 3, 27, 'January 2024 to March 2026, quiet months as gaps');
  assert.equal(await trend.locator('[data-testid=ask-trend-peak]').innerText(), 'Most in March 2024: 4 messages');

  // The person: both apps, one person; their first message opens in its conversation.
  const person = card('ask-person');
  assert.match(await person.locator('.embed-chat-who').innerText(), /Grace Hopper\s*14 messages · since January 2024 · last Mar 13, 2026/);
  assert.match(await person.innerText(), /Messages\s*12/);
  assert.match(await person.innerText(), /Instagram\s*2/);
  await person.locator('[data-testid=ask-person-first]').click();
  await p.locator('[data-testid=convo]', { hasText: 'saw your post!' }).waitFor();
  await p.locator('[data-testid=conversation] button', { hasText: 'Done' }).click();

  // The email, without the reply it quotes; it opens as a record.
  const mail = card('ask-email');
  assert.match(await mail.locator('.embed-chat-who').innerText(), /Katherine Johnson\s*katherine@example.com · March 11, 2025/);
  assert.equal(await mail.locator('.embed-email-subject').innerText(), 'Orbit numbers for Friday');
  assert.equal(await mail.locator('.embed-email-to').first().innerText(), 'To You');
  const text = await mail.locator('.embed-email-text').innerText();
  assert.match(text, /The numbers check out: launch at 9:40\./);
  assert.doesNotMatch(text, /Can you check the orbit/, 'not the reply it quotes');
  assert.match(await mail.innerText(), /orbit\.xlsx/);
  assert.match(await mail.locator('.embed-chat-foot').innerText(), /Gmail · 2 in this thread/);
  await mail.locator('[data-testid=ask-email-open]').click();
  await p.locator('[data-testid=ask-record] h2').waitFor();
  assert.match(await p.locator('[data-testid=ask-record]').innerText(), /Orbit numbers for Friday/);
  await p.locator('[data-testid=ask-record] button', { hasText: 'Done' }).click();

  // Songs and a podcast, each with how often you've played it.
  const songs = await card('ask-songs').locator('[data-testid=ask-song]').allInnerTexts();
  assert.equal(songs.length, 2);
  assert.match(songs[0], /Episode 12: Gears\s*Engine Hour\s*Played\s*Podcasts · March 12, 2025/);
  assert.match(songs[1], /Warp\s*The Weavers · Loom\s*5 plays\s*Spotify · March 12, 2025/);

  // The calendar that day, in order, with times, places and calendars.
  const events = await card('ask-agenda').locator('[data-testid=ask-event]').allInnerTexts();
  assert.deepEqual(events.map((e) => e.replace(/\s+/g, ' ').trim()), ['Orbit review 3:00 PM to 3:15 PM · Room 4 · Work', 'Dinner with Grace 7:30 PM']);
  assert.match(await card('ask-agenda').locator('.embed-agenda-date').innerText(), /Wednesday, March 12, 2025/i);

  // What Meta decided: its one profile for Facebook and Instagram, and who has you.
  const tk = card('ask-they-know');
  assert.match(await tk.locator('[data-testid=tk-card]').innerText(), /Facebook and Instagram[\s\S]*Frequent travelers[\s\S]*Rock climbing/);
  assert.match(await tk.locator('.embed-photos-cap').innerText(), /1 advertiser has your information: Acme Outdoor/);

  // One that isn't in the data says so; mid-sentence, a citation or words.
  assert.equal(await card('ask-embed-missing').innerText(), 'That person isn’t in Your People.');
  assert.equal(await p.locator('[data-testid=ask-answer]').last().locator('[data-testid=ask-cite]', { hasText: 'the email' }).count(), 1);
  assert.match(await p.locator('[data-testid=ask-answer]').last().innerText(), /or see March 12, 2025\./);
  await p.locator('[data-testid=ask-answer]').last().evaluate((el) => el.closest('.scroll')?.scrollTo(0, 0));
  await look('ask-inserts');
  if (SHOTS) for (const id of ['ask-trip', 'ask-map', 'ask-day', 'ask-trend', 'ask-person', 'ask-email', 'ask-songs', 'ask-agenda', 'ask-they-know']) {
    await card(id).scrollIntoViewIfNeeded();
    await card(id).screenshot({ path: path.join(SHOTS, `${id}.png`) });
  }
  if (SHOTS) {
    await p.emulateMedia({ colorScheme: 'dark' });
    for (const id of ['ask-trip', 'ask-trend', 'ask-person', 'ask-songs']) await card(id).screenshot({ path: path.join(SHOTS, `${id}-dark.png`) });
    await p.emulateMedia({ colorScheme: 'light' });
  }
});

test('the trip, the person, the day and What They Know open their pages in Explore', async () => {
  const p = run.page;
  await card('ask-trip').locator('[data-testid=ask-trip-open]').click();
  await p.locator('[data-testid=explore-trip]').waitFor();
  assert.match(await p.locator('[data-testid=explore-trip] .hero-title').innerText(), /Shinjuku, Japan/);
  await p.locator('[data-testid=explore-back]').click();
  await p.locator('[data-testid=explore-places]').waitFor(); // Back goes to the trip's Places and Trips
  await backToAsk();

  await card('ask-person').locator('[data-testid=ask-person-open]').click();
  await p.locator('[data-testid=explore-person]').waitFor();
  await backToAsk();

  await card('ask-day').locator('[data-testid=ask-day-open]').click();
  await p.locator('#stream-day-2025-03-12').waitFor();
  await backToAsk();

  await card('ask-they-know').locator('button[data-action=ask-they-know-open]').click();
  await p.locator('[data-testid=explore-they-know]').waitFor();
  await backToAsk();
});

test('a chart of an average says it as one: hours a night', async () => {
  const p = run.page;
  await ask('When did I sleep best?', 'Best in March 2025:\n[[trend:sleep]]');
  const trend = card('ask-trend');
  assert.match(await trend.locator('.embed-trend-head').innerText(), /Sleep\s*7\.0 hours a night, on average · 2025/);
  assert.equal(await trend.locator('[data-testid=ask-trend-peak]').innerText(), 'Most in March 2025: 7.0 hours a night, on average');
  assert.equal(await p.locator('[data-testid=ask-answer]').last().innerText().then((t) => t.includes('[[')), false, 'no brackets left showing');
});
