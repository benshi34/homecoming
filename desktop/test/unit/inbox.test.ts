import assert from 'node:assert/strict';
import { test } from 'node:test';
import { inboxesFor, inboxLabel, inboxUrl } from '../../src/shared/inbox.ts';
import { claudeSignIn, codexSignIn } from '../../src/main/ask.ts';
import { agentNeed, DEFAULT_ASK, needText } from '../../src/shared/ask.ts';
import { actionIds, hoursAgo, state, view } from './helpers.ts';

test('your inboxes: webmail by address (the one the service writes to first), Mail last; work addresses through Mail', () => {
  const list = inboxesFor(['ada@work.example', 'Ada@Gmail.com', 'ada@icloud.com', 'ada@hotmail.co.uk'], true, 'ada.l@gmail.com');
  assert.deepEqual(list.map((x) => [x.app, x.email ?? '']), [['Gmail', 'ada.l@gmail.com'], ['Gmail', 'ada@gmail.com'], ['iCloud Mail', 'ada@icloud.com'],
    ['Outlook', 'ada@hotmail.co.uk'], ['Mail', '']]);
  assert.equal(inboxLabel(list), 'Look in Your Email…');
  assert.equal(inboxLabel([list[0]]), 'Look in Gmail');
  assert.equal(inboxLabel([list[4]]), 'Open Mail');
  assert.deepEqual(inboxesFor(['ada@work.example'], false), [], 'nowhere it knows to look');
});

test('Gmail opens searched for mail from the service since you asked; the others open their inbox; Mail is an app', () => {
  const url = inboxUrl({ id: 'ada@gmail.com', app: 'Gmail', email: 'ada@gmail.com' }, { name: 'Booking', domains: ['booking.com'], since: '2026-10-12T15:00:00Z' })!;
  assert.match(url, /^https:\/\/mail\.google\.com\/mail\/\?authuser=ada%40gmail\.com#search\//);
  assert.equal(decodeURIComponent(url.split('#search/')[1]), 'from:(booking.com) after:2026/10/11');
  assert.match(decodeURIComponent(inboxUrl({ id: 'x', app: 'Gmail', email: 'x@gmail.com' }, { name: 'Zorblet', domains: [] })!), /"Zorblet"$/);
  assert.equal(inboxUrl({ id: 'x', app: 'iCloud Mail', email: 'x@icloud.com' }, { name: 'X', domains: [] }), 'https://www.icloud.com/mail/');
  assert.equal(inboxUrl({ id: 'mail', app: 'Mail' }, { name: 'X', domains: [] }), null);
});

test('an export on its way offers to look in your email, when the app knows where that is', () => {
  const st = state((s) => (s.sources.discord = { requestedAt: hoursAgo(1) }));
  const mail = { emails: ['ada@gmail.com'], appleMail: false };
  const v = view('discord', { state: st, mail });
  assert.ok(actionIds(v).includes('open-inbox'));
  assert.equal(v.actions.find((a) => a.id === 'open-inbox')?.label, 'Look in Gmail');
  assert.deepEqual(v.inboxes?.map((x) => x.app), ['Gmail']);
  assert.ok(!actionIds(view('discord', { state: st, mail: { emails: ['ada@work.example'], appleMail: false } })).includes('open-inbox'), 'nowhere to look: no button');
  assert.ok(!actionIds(view('discord', { mail })).includes('open-inbox'), 'not asked for yet: no email to look for');
});

test('signed in or not, as Claude Code and Codex say; signed out stops Ask with the way to sign in', () => {
  assert.deepEqual(claudeSignIn('{"loggedIn":true,"authMethod":"claude.ai","email":"ada@example.com","subscriptionType":"max"}'),
    { state: 'in', who: 'ada@example.com', how: 'claude.ai', plan: 'Max plan' });
  assert.deepEqual(claudeSignIn('{"loggedIn":false}'), { state: 'out' });
  assert.deepEqual(claudeSignIn('error: unknown command'), { state: 'unknown' }, 'an older Claude Code: not known, not "out"');
  assert.deepEqual(codexSignIn('Logged in using ChatGPT'), { state: 'in', how: 'ChatGPT' });
  assert.deepEqual(codexSignIn('Not logged in'), { state: 'out' });
  const base = { settings: DEFAULT_ASK, installed: { 'claude-code': true, codex: true }, keys: { anthropic: false, openai: false } };
  const out = { state: 'out' as const, at: '' };
  assert.deepEqual(agentNeed({ ...base, signIn: { 'claude-code': out } }), { kind: 'sign-in', harness: 'claude-code' });
  assert.match(needText({ kind: 'sign-in', harness: 'codex' }), /Sign In opens ChatGPT's sign-in in your browser/);
  assert.equal(agentNeed({ ...base, signIn: { 'claude-code': { state: 'unknown', at: '' } } }), null, 'not known: not in the way');
  assert.deepEqual(agentNeed({ ...base, signIn: { 'claude-code': out } }, 'anthropic'), { kind: 'key', key: 'anthropic' }, 'a key choice needs its key, not the sign-in');
});
