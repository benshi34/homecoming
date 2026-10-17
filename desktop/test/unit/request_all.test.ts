// Ask for Everything (shared/request_all.ts) and the sign-in check it rests on (status.ts signInFor): who does each
// export still to ask for, what one notification says at the end, and which download goes first.

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentPrompt } from '../../src/main/export_agent.ts';
import { BY_ID } from '../../src/shared/catalog.ts';
import { batchSummary, linkExpires, requestPlan } from '../../src/shared/request_all.ts';
import { signInFor, signInNote } from '../../src/shared/status.ts';
import type { ServiceEntry, SignInCheck } from '../../src/shared/types.ts';
import { actionIds, hoursAgo, NOW, state, views } from './helpers.ts';

const DAY = 24 * 3600_000;
const check = (sources: SignInCheck['sources'], profiles: SignInCheck['chrome']['profiles'] = [{ dir: 'Default', name: 'Ada', claude: true }]): SignInCheck =>
  ({ at: NOW.toISOString(), chrome: { installed: true, profiles }, safari: { readable: true }, sources });
const none = { chrome: [], safari: false };

test('Chrome is signed in, or not, in the profile Claude in Chrome works in; and where else it is', () => {
  const ig = BY_ID.instagram;
  assert.deepEqual(signInFor(ig, check({ instagram: { chrome: [{ profile: 'Default', since: '2026-10-08T11:00:00Z' }], safari: false } })),
    { state: 'in', since: '2026-10-08T11:00:00Z' });
  assert.deepEqual(signInFor(ig, check({ instagram: { chrome: [], safari: true } })), { state: 'out', elsewhere: 'Safari' });
  const two = [{ dir: 'Default', name: 'Ada', claude: true }, { dir: 'Profile 1', name: 'Work', claude: false }];
  assert.deepEqual(signInFor(ig, check({ instagram: { chrome: [{ profile: 'Profile 1' }], safari: true } }, two)),
    { state: 'out', elsewhere: 'your Work profile in Chrome' }, 'another Chrome profile says more than Safari');
  assert.deepEqual(signInFor(ig, check({ instagram: { chrome: [{ profile: 'Default' }], safari: false } }, two)), { state: 'in', since: undefined, profile: 'Ada' },
    'with several profiles, which one');
  assert.equal(signInFor(ig, check({ instagram: { chrome: [{ profile: 'Profile 1' }], safari: false } }, two.map((p) => ({ ...p, claude: false })))).state, 'in',
    'no profile has Claude in Chrome: any one counts');
  assert.equal(signInFor(BY_ID.discord, check({})).state, 'unknown', 'Discord keeps its sign-in out of cookies');
  assert.equal(signInFor(ig, check({ instagram: { chrome: [], safari: true, unreadable: ['Default'] } })).state, 'unknown', 'its cookie file couldn\'t be read: can\'t tell');
  assert.equal(signInFor(ig, null).state, 'unknown');
  assert.equal(signInFor(ig, { ...check({ instagram: none }), chrome: { installed: false, profiles: [] } }).state, 'unknown', 'no Chrome');
  assert.match(signInNote('Instagram', { state: 'in' })!, /^Chrome is signed in to Instagram, so Claude can ask for it without you/);
  assert.match(signInNote('Spotify', { state: 'out', elsewhere: 'Safari' })!, /^Chrome isn't signed in to Spotify \(Safari is\)\. Sign in there once.*password or passkey.*never sees it/);
  assert.equal(signInNote('Discord', { state: 'unknown' }), null);
});

const strava: ServiceEntry = { id: 'svc_strava', slug: 'strava', name: 'Strava', folder: 'strava', domains: ['strava.com'], email: 'privacy@strava.example',
  addedAt: hoursAgo(1), from: 'you' };
const KEEP = ['instagram', 'spotify', 'reddit', 'svc_strava'];
const story = (fn?: (s: ReturnType<typeof state>) => void) => state((s) => {
  s.services = [strava];
  for (const src of Object.values(BY_ID)) if (src.group === 'web' && !KEEP.includes(src.id)) (s.sources[src.id] ??= {}).skipped = 'I don\'t use it';
  fn?.(s);
});
const signIns = check({ instagram: { chrome: [{ profile: 'Default' }], safari: false }, spotify: { chrome: [], safari: true }, reddit: { chrome: [], safari: true } });

test('the plan: Claude asks for what Chrome is signed in to, you sign in to the rest first; Reddit is yours; a service you added gets an email', () => {
  const vs = views({ state: story(), signIns });
  const plan = requestPlan(vs);
  const ids = (x: { id: string }[]) => x.map((v) => v.id);
  assert.deepEqual([ids(plan.claude), ids(plan.signIn), ids(plan.yourself), ids(plan.email)], [['instagram'], ['spotify'], ['reddit'], ['svc_strava']]);
  const find = (id: string) => vs.find((v) => v.id === id)!;
  assert.equal(find('svc_strava').requestEmail, 'privacy@strava.example');
  assert.ok(find('instagram').notes?.some((n) => /^Chrome is signed in to Instagram/.test(n)));
  assert.ok(find('spotify').notes?.some((n) => /^Chrome isn't signed in to Spotify \(Safari is\)/.test(n)));
  // Reddit: no Do It for Me, its page first, and why.
  const reddit = find('reddit');
  assert.ok(!actionIds(reddit).some((a) => a.startsWith('agent-')), actionIds(reddit).join());
  assert.equal(reddit.actions.find((a) => a.primary)?.id, 'open');
  assert.match(reddit.notes?.[0] ?? '', /isn't allowed on reddit\.com/);
  assert.equal(reddit.signIn, undefined, 'its sign-in doesn\'t matter: Claude can\'t go there');
  // Asked for already, or optional: not in it.
  const asked = requestPlan(views({ state: story((s) => (s.sources.instagram = { requestedAt: hoursAgo(2) })), signIns }));
  assert.deepEqual(ids(asked.claude), []);
  assert.ok(!Object.values(requestPlan(views({ state: state(), signIns }))).flat().some((v) => v.id === 'google_photos_drive'), 'Photos and Drive are optional');
  // AI off: nothing for Claude, and no word about Chrome.
  const off = views({ state: story((s) => (s.settings.aiOn = false)), signIns });
  const p2 = requestPlan(off);
  assert.deepEqual([ids(p2.claude), ids(p2.signIn), ids(p2.yourself).sort()], [[], [], ['instagram', 'reddit', 'spotify']]);
  assert.ok(!off.find((v) => v.id === 'spotify')!.notes?.some((n) => /Chrome/.test(n)));
});

test('Claude stopped for a sign-in: the page says your password manager fills it, and that Claude carries on by itself', () => {
  const vs = views({ state: story((s) => (s.sources.spotify = { agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0.1), note: 'Sign in to Spotify in Chrome.', session: 's1' } })) });
  const v = vs.find((x) => x.id === 'spotify')!;
  assert.equal(v.status, 'Needs you: Sign in to Spotify in Chrome.');
  assert.match(v.detail ?? '', /saved password or passkey fills it in\. Once you're signed in, Claude carries on by itself/);
  const code = views({ state: story((s) => (s.sources.spotify = { agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0.1), note: 'Enter the code Spotify emailed you.' } })) });
  assert.match(code.find((x) => x.id === 'spotify')!.detail ?? '', /^Do it in Chrome, or answer below/);
});

test('one notification for the whole run: how many it asked for, and what needs you, by name', () => {
  assert.deepEqual(batchSummary([{ name: 'Instagram', status: 'requested' }, { name: 'Spotify', status: 'needs_you', note: 'Sign in to Spotify in Chrome.' },
    { name: 'X', status: 'failed', note: 'The page didn\'t load' }]),
  { title: 'Claude asked for 1 of your exports', body: '2 need you: Spotify (sign in to Spotify in Chrome); X (the page didn\'t load).' });
  assert.deepEqual(batchSummary([{ name: 'Instagram', status: 'requested' }, { name: 'Notion', status: 'requested' }]),
    { title: 'Claude asked for 2 of your exports', body: 'Each one is imported when it comes.' });
  assert.equal(batchSummary([{ name: 'Instagram', status: 'stopped' }]), null, 'all stopped: nothing to say');
});

test('the download whose link expires first goes first', () => {
  const at = '2026-10-08T00:00:00Z';
  assert.equal(linkExpires(BY_ID.chatgpt, { requestedAt: at, readySignal: { at, via: 'Mail', text: 'ready' } }), Date.parse(at) + DAY);
  assert.equal(linkExpires(BY_ID.instagram, { requestedAt: at }), Date.parse(at) + 1 * 3600_000 + 4 * DAY, 'not ready yet: from when it should be');
  assert.equal(linkExpires(BY_ID.discord, { requestedAt: at }), Infinity, 'Discord doesn\'t say');
  assert.equal(linkExpires(BY_ID.instagram, undefined), Infinity);
});

test('a service you added with its export page: Claude requests it like the built-in ones; Patreon is yours', () => {
  const entry = (slug: string, name: string, domains: string[], url?: string): ServiceEntry => ({ id: `svc_${slug}`, slug, name, folder: slug, domains, url,
    notes: url ? `Settings → Export → Start export.` : undefined, addedAt: hoursAgo(1), from: 'you' });
  const added = [entry('github', 'GitHub', ['github.com', 'docs.github.com'], 'https://github.com/settings/admin'),
    entry('patreon', 'Patreon', ['patreon.com'], 'https://privacy.patreon.com/'), entry('wikipedia', 'Wikipedia', ['aa.wikipedia.org', 'ab.wikipedia.org', 'en.wikipedia.org'], 'https://en.wikipedia.org/wiki/Special:Preferences')];
  const st = story((s) => (s.services = [strava, ...added]));
  const signedIn = check({ ...signIns.sources, svc_github: { chrome: [{ profile: 'Default' }], safari: false } });
  const vs = views({ state: st, signIns: signedIn });
  const find = (id: string) => vs.find((v) => v.id === id)!;
  const gh = find('svc_github');
  assert.equal(gh.actions.find((a) => a.primary)?.id, 'agent-request', 'Do It for Me, first');
  assert.ok(actionIds(gh).includes('draft-request'), 'a drafted request is still there');
  assert.equal(gh.signIn?.state, 'in', 'GitHub\'s sign-in cookie is known');
  assert.ok(gh.notes?.some((n) => /^Chrome is signed in to GitHub/.test(n)));
  assert.equal(find('svc_wikipedia').signIn?.state, 'unknown', 'no cookie to go by: Claude checks');
  const patreon = find('svc_patreon');
  assert.ok(!actionIds(patreon).includes('agent-request'));
  assert.match(patreon.notes?.[0] ?? '', /isn't allowed on patreon\.com/);
  const plan = requestPlan(vs);
  const ids = (x: { id: string }[]) => x.map((v) => v.id).sort();
  assert.deepEqual(ids(plan.claude), ['instagram', 'svc_github', 'svc_wikipedia']);
  assert.deepEqual(ids(plan.yourself), ['reddit', 'svc_patreon']);
  assert.deepEqual(ids(plan.email), ['svc_strava'], 'no page Claude can use, but an address');
  // Its prompt names its own sites once each, not one per language.
  const p = agentPrompt(BY_ID.svc_wikipedia, 'request');
  assert.match(p, /Stay on Wikipedia's own sites \(en\.wikipedia\.org, wikipedia\.org\)/);
  assert.doesNotMatch(p, /drop it on this page/, "the app's own step isn't Claude's");
  // Looking for it: its export page first (some download straight away, with no email), then the email.
  assert.match(agentPrompt(BY_ID.svc_github, 'download', undefined, hoursAgo(30)),
    /Open https:\/\/github\.com\/settings\/admin in a new tab: once it's ready, GitHub may show a download there \(some download straight away\)\. If it doesn't[^]*look for the email instead/);
});

test('Claude in Chrome asked to be allowed on a site and nobody answered: the page says what that is, and to Continue with Chrome in view', () => {
  for (const note of ['Click Allow in the Claude permission window in Chrome so I can open wattpad.com.', 'Allow Claude on wattpad.com in Chrome.']) {
    const vs = views({ state: story((s) => (s.sources.spotify = { agent: { mode: 'download', status: 'needs_you', at: hoursAgo(0.1), note, session: 's1' } })) });
    const v = vs.find((x) => x.id === 'spotify')!;
    assert.match(v.detail ?? '', /^Claude in Chrome asks before it works on a site for the first time\. Click Continue with Chrome in view/, note);
    assert.equal(v.actions.find((a) => a.primary)?.id, 'agent-continue');
  }
  const signIn = views({ state: story((s) => (s.sources.spotify = { agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0.1), note: 'Sign in to Spotify in Chrome.' } })) });
  assert.match(signIn.find((x) => x.id === 'spotify')!.detail ?? '', /^Sign in to Spotify in Chrome/, 'a sign-in is still a sign-in');
});
