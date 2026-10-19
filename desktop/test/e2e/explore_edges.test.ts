// Explore at the edges: the real app over libraries made to trip it up (make_fixtures.edge_corpus): an index with
// nothing in it, everything on one day, and 37 years of messy records (no times, times that can't be right, offsets
// and a clock change, odd text, one name for two people, you in your own chats). Every tile opens, and on every page
// every tab and year (and a spread of months and days) is picked and picked back; nothing throws, nothing reads NaN
// or Invalid Date, and no year that can't be right shows. Off screen, in Los Angeles time (it has clock changes).

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { test } from 'node:test';
import type { Page } from 'playwright-core';
import { DESKTOP, launch, type Running, sandbox, sandboxEnv } from './harness.ts';

const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const HOME = ['year', 'on-this-day', 'people', 'places', 'they-know', 'listening', 'movement', 'curiosity', 'journeys', 'watching', 'rhythms', 'groups', 'firsts', 'made', 'stream'];
const WRONG = /NaN|Invalid Date|undefined|Infinity|\[object Object\]|Couldn't build/;
const NOT_A_YEAR = /\b(1970|1985|2099|9999)\b/; // the messy library's times that can't be right

async function withLibrary(kind: string, fn: (r: Running) => Promise<void>) {
  const sb = sandbox();
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'edge-corpus', sb.corpus, kind]);
  const run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_TZ: 'America/Los_Angeles' }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  try {
    await fn(run);
  } finally {
    await run.close();
    sb.cleanup();
  }
}

// What a page says once it has settled (nothing still building), checked.
async function settled(r: Running, scope: string, what: string) {
  const p = r.page;
  await p.locator(scope).waitFor({ timeout: 60_000 });
  await p.waitForFunction(() => !document.querySelector('[data-testid=explore-building]'), null, { timeout: 60_000 });
  const text = await p.locator(scope).innerText();
  assert.doesNotMatch(text, WRONG, `${what} reads right`);
  assert.doesNotMatch(text, NOT_A_YEAR, `${what} shows no year that can't be right`);
  assert.deepEqual(r.errors, [], `${what}: nothing threw`);
  return text;
}

// Every tab, one way and back; every year, month or day in each picker, one way and back (a spread of them where
// each one is built when picked: Your Year's and Your Stream's); a year picker's arrows to its ends and back.
async function exercise(r: Running, scope: string, what: string) {
  const p = r.page;
  const page = p.locator(scope);
  const tabs = page.locator('button[role=tab]');
  const n = await tabs.count();
  const order = [...Array(n).keys()];
  for (const i of [...order, ...order.reverse().slice(1)]) {
    if (i >= await tabs.count() || !(await tabs.nth(i).isVisible())) continue;
    await tabs.nth(i).click();
    await settled(r, scope, `${what}, tab ${i}`);
  }
  const selects = page.locator('select');
  for (let s = 0; s < await selects.count(); s++) {
    const sel = selects.nth(s);
    const id = await sel.getAttribute('data-testid');
    const values = await sel.locator('option').evaluateAll((os) => os.map((o) => (o as HTMLOptionElement).value));
    assert.doesNotMatch(values.join(' '), NOT_A_YEAR, `${what}: ${id} offers no year that can't be right`);
    const built = id === 'year-picker' || id === 'stream-month';
    const pick = built && values.length > 6 ? [values[1], values[values.length - 1], values[Math.floor(values.length / 2)], values[0]] : [...values.slice(1), ...values.slice(0, -1).reverse()];
    for (const v of pick) {
      if (!(await sel.isVisible())) break;
      await sel.selectOption(v);
      await settled(r, scope, `${what}, ${id} ${v}`);
    }
  }
  for (const [back, on] of [['prev', 'next'], ['next', 'prev']]) {
    const arrows = page.locator(`button[data-testid$=-year-${back}]:not([disabled])`);
    for (let i = 0; i < 60 && await arrows.count(); i++) await arrows.first().click();
    for (let i = 0; i < 60 && await page.locator(`button[data-testid$=-year-${on}]:not([disabled])`).count(); i++) {
      await page.locator(`button[data-testid$=-year-${on}]:not([disabled])`).first().click();
    }
    await settled(r, scope, `${what}, every year by its arrows`);
  }
  for (const [label, times] of [['The day before', 3], ['The day after', 6], ['The day before', 3]] as const) {
    for (let i = 0; i < times && await page.getByRole('button', { name: label }).count(); i++) {
      await page.getByRole('button', { name: label }).click();
      await settled(r, scope, `${what}, ${label.toLowerCase()}`);
    }
  }
}

async function back(p: Page) {
  await p.click('[data-testid=explore-back]');
}

// Every tile; the pages a tile leads to (a person, a group chat, a trip); and back home each time.
async function walk(r: Running) {
  const p = r.page;
  await p.click('[data-testid=nav-explore]');
  await p.locator('[data-testid=explore-home]').waitFor({ timeout: 60_000 });
  for (const id of HOME) await p.locator(`[data-testid=explore-card-${id}][data-ready=yes]`).waitFor({ timeout: 120_000 });
  await settled(r, '[data-testid=explore-home]', 'the home');
  const opened: Record<string, string> = {};
  for (const id of HOME) {
    await p.locator(`[data-testid=explore-card-${id}]`).click();
    const scope = (await p.locator('[data-testid=explore-locked]').count()) ? '[data-testid=explore-locked]' : `[data-testid=explore-${id}]`;
    await p.locator(`[data-testid=explore-locked], [data-testid=explore-${id}]`).first().waitFor({ timeout: 60_000 });
    const s = (await p.locator('[data-testid=explore-locked]').count()) ? '[data-testid=explore-locked]' : scope;
    opened[id] = await settled(r, s, id);
    await exercise(r, s, id);
    for (const [row, sub] of [['person-row', 'person'], ['group-card', 'group'], ['trip', 'trip']]) {
      const first = p.locator(`${s} [data-testid=${row}]`).first();
      if (!(await first.count())) continue;
      await first.click();
      await settled(r, `[data-testid=explore-${sub}]`, `${id}: a ${sub}`);
      await exercise(r, `[data-testid=explore-${sub}]`, `${id}: a ${sub}`);
      await back(p);
      await settled(r, s, `${id}, back from a ${sub}`);
    }
    await back(p);
    await p.locator('[data-testid=explore-home]').waitFor({ timeout: 10_000 });
  }
  return opened;
}

test('an index with nothing in it: every tile opens, locked or empty, and says so plainly', async () => {
  await withLibrary('empty', async (r) => {
    const opened = await walk(r);
    assert.match(opened.people, /needs your conversations/i);
    assert.match(opened['on-this-day'], /Nothing on/);
    assert.match(opened.stream, /Nothing in your library yet/);
    assert.doesNotMatch(opened.stream, /\b0 records|of this kind/, 'not "0 records", nor "nothing of this kind" when there\'s nothing at all');
    assert.match(await r.page.locator('[data-testid=explore-card-stream]').innerText(), /Nothing in your library yet/);
  });
});

test('everything on one day: one year, one day, every tab and year', async () => {
  await withLibrary('one-day', async (r) => {
    const opened = await walk(r);
    assert.match(opened.year, /2025/);
    assert.match(opened.made, /1\b/);
  });
});

test('37 messy years: every year offered is a real one, and every page reads right through them all', async () => {
  await withLibrary('messy', async (r) => {
    const p = r.page;
    const opened = await walk(r);
    await p.locator('[data-testid=explore-card-year]').click();
    await settled(r, '[data-testid=explore-year]', 'year');
    const years = await p.locator('[data-testid=year-picker] option').allInnerTexts();
    assert.equal(years.length, 37, 'every year from 1990, and none that can\'t be right');
    assert.equal(years.at(-1), '1990');
    await back(p);
    assert.match(opened.people, /Grace Hopper/);
    // Her first conversation, and the messages kept before it, some at times that can't be right: "No date", not 1970.
    await p.locator('[data-testid=explore-card-people]').click();
    await p.locator('[data-testid=person-row]', { hasText: 'Grace Hopper' }).first().click();
    await p.getByRole('button', { name: 'First Conversation' }).click();
    const convo = await settled(r, '[data-testid=convo]', 'her first conversation');
    assert.match(convo, /No date[\s\S]*January 15, 1990[\s\S]*hey 1990/);
    await p.keyboard.press('Escape');
    assert.doesNotMatch(opened.people, /^me$/m, '"me" is you, not one of your people');
  });
});
