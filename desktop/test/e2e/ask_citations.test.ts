// What an Ask answer cites, opened, as a person would open it. A message opens in its conversation, drawn as Messages
// draws one: the days around it, scrolled to it and marked, earlier and later a click away, its details and the page
// Explore has for the conversation one more. A calendar event opens as Calendar shows one; anything else, by itself.
// Claude Code is the stand-in (test/fakes), its answer scripted per question, over a made-up corpus
// (make_fixtures.cited_corpus). Nothing here reaches the network or a real AI.

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
  if (SHOTS) await run.page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};
let rowid: (where: string) => number;

before(async () => {
  sb = sandbox({ identity: true });
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'cited-corpus', sb.corpus]);
  const db = path.join(sb.corpus, 'corpus.db');
  rowid = (where) => Number(execFileSync(PY, ['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(db)}).execute(${JSON.stringify(`select rowid from records where ${where}`)}).fetchone()[0])`]).toString());
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, ask: claudeChecked(), onboarding: { done: true },
    settings: { aiOn: true, aiAgreedAt: new Date().toISOString() } }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_PLAN: path.join(sb.root, 'claude-plan.json'),
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
  for (let i = 0; i < 3 && await p.locator('.sheet-backdrop').count(); i++) await p.keyboard.press('Escape'); // one a failed test left open
  fs.writeFileSync(path.join(sb.root, 'claude-plan.json'), JSON.stringify({ steps: [{ tool: 'search', input: { query: 'Tasca' } }], answer }));
  await p.locator('[data-testid=ask-new]').click();
  await p.locator('[data-testid=ask-input]').fill(question);
  await p.locator('[data-testid=ask-input]').press('Enter');
  await p.locator('[data-testid=ask-answer]').last().waitFor({ timeout: 30_000 });
  await p.locator('[data-testid=ask-send]').waitFor({ timeout: 30_000 });
}

// The message `text` is in the conversation's box, where you can see it.
const inView = (text: string) => run.page.evaluate((t) => {
  const box = document.querySelector('[data-testid=convo]')!.getBoundingClientRect();
  const el = [...document.querySelectorAll('[data-testid=convo] [data-rowid]')].find((e) => e.textContent?.includes(t));
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.top >= box.top && r.bottom <= box.bottom;
}, text);

test('a cited message opens in its conversation: the days around it, both sides, scrolled to it and marked', async () => {
  const p = run.page;
  const tasca = rowid("text like 'Are we still%'");
  await ask('When is dinner with Grace?', `Friday at 7:30, at Tasca: [Grace asked](record:${tasca}) and you'd booked a table.`);
  await p.locator('[data-testid=ask-cite]').click();
  const sheet = p.locator('[data-testid=conversation]');
  const convo = sheet.locator('[data-testid=convo]');
  await convo.locator('.msg-row').first().waitFor();
  assert.match(await sheet.locator('.convo-head').innerText(), /Grace Hopper\s*Messages · one on one/);
  assert.equal(await convo.locator('.msg-row.anchor').innerText(), 'Are we still on for dinner at Tasca on Friday?', 'the cited one, marked');
  assert.ok(await inView('Are we still on for dinner'), 'and scrolled to');
  const text = await convo.innerText();
  // The days before and after it, oldest first; a message whose time was lost says so, not 1970.
  for (const [a, b] of [['an old message whose time was lost', 'Can you send me the slides?'], ['Did you see the eclipse?', 'Are we still on'], ['Are we still on', 'That was so much fun']]) {
    assert.ok(text.indexOf(a) >= 0 && text.indexOf(a) < text.indexOf(b), `${a} before ${b}`);
  }
  assert.deepEqual((await convo.locator('.convo-day').allInnerTexts()).slice(0, 1), ['No date']);
  assert.equal(await convo.locator('.convo-day').count(), 5, 'a day each, and No date');
  assert.doesNotMatch(text, /1970/);
  // Yours on the right in blue, theirs on the left.
  assert.equal(await convo.locator('.msg-row.me', { hasText: 'Yes! 7:30, I booked a table.' }).count(), 1);
  assert.equal(await convo.locator('.msg-row.them', { hasText: 'Did you see the eclipse?' }).count(), 1);
  assert.equal(await convo.locator('.msg-author').count(), 0, 'no names in a one-on-one');
  // A tapback, a picture, emoji alone, a file, and an edit (with what it said before).
  assert.equal(await convo.locator('.convo-reaction').innerText(), 'Grace Hopper loved “Yes! 7:30, I booked a table.”');
  await convo.locator('.msg-image img').waitFor();
  assert.equal(await convo.locator('.bubble-emoji').innerText(), '🍷🍷');
  assert.equal(await convo.locator('.msg-row.me [data-testid=msg-attachment]').innerText(), 'Tasca menu.pdf');
  const edited = convo.locator('.msg-row', { hasText: 'Should I bring the wine?' });
  await edited.locator('[data-testid=msg-edited]', { hasText: 'Edited' }).click();
  assert.equal(await edited.locator('[data-testid=msg-earlier]').innerText(), 'Should I bring wine');
  await convo.locator('.msg-row.anchor').scrollIntoViewIfNeeded();
  await look('ask-cited-conversation');
  // Its details, over the conversation; Done goes back to it.
  await sheet.locator('button[data-action=convo-details]').click();
  const rec = p.locator('[data-testid=ask-record]');
  await rec.locator('h2').waitFor();
  assert.match(await rec.innerText(), /Message with Grace Hopper[\s\S]*From\s+Messages/);
  await rec.locator('button', { hasText: 'Done' }).click();
  await rec.waitFor({ state: 'detached' });
  await sheet.locator('button', { hasText: 'Done' }).click();
  await sheet.waitFor({ state: 'detached' });
});

test('earlier and later are a click away, and what you were reading stays put', async () => {
  const p = run.page;
  const fun = rowid("text = 'That was so much fun'");
  await ask('What did Grace say after dinner?', `She said it [was so much fun](record:${fun}).`);
  await p.locator('[data-testid=ask-cite]').last().click();
  const convo = p.locator('[data-testid=conversation] [data-testid=convo]');
  await convo.locator('.msg-row.anchor', { hasText: 'That was so much fun' }).waitFor();
  assert.doesNotMatch(await convo.innerText(), /Can you send me the slides\?/, 'not yet');
  assert.equal(await convo.locator('button[data-action=convo-later]').count(), 0, 'nothing later');
  // Scrolled up to the first message there is, Show Earlier puts the ones before it on top, and that one stays where it was.
  await convo.locator('button[data-action=convo-earlier]').click();
  await convo.locator('.msg-row', { hasText: 'Can you send me the slides?' }).waitFor();
  assert.equal(await convo.locator('button[data-action=convo-earlier]').count(), 0, 'nothing earlier now');
  assert.equal((await convo.locator('.convo-day').allInnerTexts())[0], 'No date');
  assert.ok(await inView('Good luck tomorrow'), 'still where you were');
  await p.keyboard.press('Escape');
  await p.locator('[data-testid=conversation]').waitFor({ state: 'detached' });
});

test('a group chat: who said what, the reactions on a message, and its page in Explore', async () => {
  const p = run.page;
  const ch7 = rowid("text like 'Chapter 7%'");
  await ask('What does book club think of chapter 7?', `[Katherine](record:${ch7}) says it's the best one.`);
  await p.locator('[data-testid=ask-cite]').last().click();
  const sheet = p.locator('[data-testid=conversation]');
  const convo = sheet.locator('[data-testid=convo]');
  await convo.locator('.msg-row.anchor').waitFor();
  assert.match(await sheet.locator('.convo-head').innerText(), /Book club\s*Instagram · group conversation/);
  const anchor = convo.locator('.msg-row.anchor');
  assert.match(await anchor.innerText(), /^Katherine Johnson\s*Chapter 7 is the best one/, 'their name over what they said');
  assert.equal(await anchor.locator('[data-testid=msg-reactions]').innerText(), '❤😂');
  assert.equal(await anchor.locator('[data-testid=msg-reactions]').getAttribute('title'), 'Dorothy Vaughan: ❤\nYou: 😂');
  assert.ok(await convo.locator('.msg-author', { hasText: 'Dorothy Vaughan' }).count() > 0);
  await look('ask-cited-group');
  await sheet.locator('button[data-action=convo-explore]').click();
  await p.locator('[data-testid=explore-group]', { hasText: 'Book club' }).waitFor({ timeout: 60_000 });
  assert.equal(await p.locator('[data-testid=conversation]').count(), 0, 'the sheet closed with Ask');
  // Back: Group Chats, then Explore's home.
  await p.locator('[data-testid=explore-back]').click();
  await p.locator('[data-testid=explore-groups]').waitFor();
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-chat]').waitFor();
});

test('a one-on-one opens its person\'s page in Explore', async () => {
  const p = run.page;
  const tasca = rowid("text like 'Are we still%'");
  await ask('Who asked about Tasca?', `[Grace](record:${tasca}).`);
  await p.locator('[data-testid=ask-cite]').last().click();
  await p.locator('[data-testid=conversation] .msg-row.anchor').waitFor();
  assert.equal(await p.locator('[data-testid=conversation] button[data-action=convo-explore]').getAttribute('title'), 'Grace Hopper\'s page in Explore');
  await p.locator('[data-testid=conversation] button[data-action=convo-explore]').click();
  await p.locator('[data-testid=explore-person]', { hasText: 'Grace Hopper' }).waitFor({ timeout: 60_000 });
  await p.locator('[data-testid=explore-back]').click();
  await p.locator('[data-testid=explore-people]').waitFor();
  await p.locator('[data-testid=nav-ask]').click();
  await p.locator('[data-testid=ask-chat]').waitFor();
});

test('a conversation shown in an answer, and cited in a sentence, opens the same way', async () => {
  const p = run.page;
  const tasca = rowid("text like 'Are we still%'");
  await ask('Show me the dinner plans', `Here they are:\n[[chat:${tasca}]]\nOr open [[chat:${tasca}]] again.`);
  const turn = p.locator('[data-testid=ask-turn]').last();
  const card = turn.locator('[data-testid=ask-chat-card]');
  await card.locator('.bubble').first().waitFor();
  assert.equal(await card.locator('[data-testid=msg-edited]').count(), 1, 'an edit says so in the card too');
  await turn.locator('[data-testid=ask-cite]', { hasText: 'the conversation' }).click();
  const convo = p.locator('[data-testid=conversation] [data-testid=convo]');
  assert.equal(await convo.locator('.msg-row.anchor').innerText(), 'Are we still on for dinner at Tasca on Friday?');
  await p.keyboard.press('Escape');
  await card.locator('[data-testid=ask-chat-open]').click();
  await convo.locator('.msg-row.anchor', { hasText: 'Are we still on' }).waitFor();
  await p.locator('[data-testid=conversation] button[data-action=convo-explore]').waitFor();
  await p.keyboard.press('Escape');
  await p.locator('[data-testid=conversation]').waitFor({ state: 'detached' });
});

test('a calendar event opens as Calendar shows one; a note, by itself', async () => {
  const p = run.page;
  const dinner = rowid("source = 'calendar' and title = 'Dinner with Grace'");
  const birthday = rowid("source = 'calendar' and title like 'Grace%birthday'");
  const note = rowid("source = 'apple_notes'");
  await ask('What\'s on Friday?', `[Dinner with Grace](record:${dinner}), and it's [her birthday](record:${birthday}) soon. You noted [ideas](record:${note}).`);
  const cites = p.locator('[data-testid=ask-turn]').last().locator('[data-testid=ask-cite]');
  await cites.nth(0).click();
  const rec = p.locator('[data-testid=ask-record]');
  const ev = rec.locator('[data-testid=record-event]');
  await ev.waitFor();
  assert.equal(await rec.locator('h2').innerText(), 'Dinner with Grace');
  const shown = await ev.innerText();
  assert.match(shown, /^Tasca, Lisbon/);
  assert.match(await ev.locator('[data-testid=event-when]').innerText(), /2026\s*\d{1,2}:30\s*[AP]M to \d{1,2}:30\s*[AP]M/);
  assert.match(shown, /Calendar\s+iCloud \/ Personal\s*From\s+Calendar\s*Organized by\s+Grace Hopper\s*Your reply\s+Accepted/);
  assert.deepEqual(await ev.locator('[data-testid=event-people] .event-person > .selectable').allInnerTexts(), ['Grace Hopper', 'Alan Turing']);
  assert.match(shown, /2 invitees/);
  assert.match(shown, /Notes\s*Bring the good wine\.$/, 'its notes, not the lines laid out above again');
  await look('ask-cited-event');
  await rec.locator('button', { hasText: 'Done' }).click();
  await rec.waitFor({ state: 'detached' });
  await cites.nth(1).click();
  assert.match(await ev.locator('[data-testid=event-when]').innerText(), /^Sunday, March 22, 2026\s*All day$/);
  await p.keyboard.press('Escape');
  await rec.waitFor({ state: 'detached' });
  await cites.nth(2).click();
  await rec.locator('h2').waitFor();
  assert.equal(await rec.locator('[data-testid=record-event]').count(), 0);
  assert.match(await rec.innerText(), /What\s+Note\s+From\s+Notes/);
  await p.keyboard.press('Escape');
  await rec.waitFor({ state: 'detached' });
  assert.deepEqual(run.errors, []);
});
