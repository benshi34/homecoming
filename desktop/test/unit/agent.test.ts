// Do It for Me's instructions to Claude and how its answer is read (main/export_agent.ts), and its runs, a few at once
// (main/agent_pool.ts).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { agentPrompt, CONTINUE, outcomeOf, runAgent, visitPrompt } from '../../src/main/export_agent.ts';
import { type AgentJob, AgentPool } from '../../src/main/agent_pool.ts';
import { agentsAtOnce } from '../../src/shared/at_once.ts';

const FAKE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../fakes/fake_claude_browser.py');

test('the request prompt: the export page, the service\'s own steps, everything picked, and when to stop', () => {
  const p = agentPrompt(BY_ID.instagram, 'request');
  assert.match(p, /Open https:\/\/accountscenter\.instagram\.com\/info_and_permissions\/dyi\/ in a new tab/);
  assert.match(p, /Format: JSON/, 'its steps, as written for a person');
  assert.match(p, /all time, JSON/);
  assert.match(p, /Never type a password or a code, never confirm with a passkey, and never answer a CAPTCHA/);
  assert.match(p, /Stay on Instagram's own sites \(.*accountscenter\.instagram\.com/);
  assert.match(p, /happy for you to click through to the end without checking with them/, 'no asking before the last click');
  assert.match(p, /RESULT: needs_you/);
});

test('the download prompt uses the link from the email', () => {
  const p = agentPrompt(BY_ID.google_takeout, 'download', 'https://takeout.google.com/settings/takeout/downloads?u=1');
  assert.match(p, /Open https:\/\/takeout\.google\.com\/settings\/takeout\/downloads\?u=1 in a new tab\. .*Download it: every part/);
  assert.doesNotMatch(p, /webmail/, 'with the link, no need to look in the inbox');
  assert.match(p, /Follow each download link or button once/, 'not twice: that makes copies');
});

test('looking for it with no link: the service\'s page if it shows a download there, else the one email in their webmail', () => {
  const discord = agentPrompt(BY_ID.discord, 'download', undefined, '2026-10-14T20:00:00Z');
  assert.match(discord, /requested their Discord data on October 14, 2026/);
  assert.match(discord, /search for mail from discord\.com or discordapp\.com since October 14, 2026/);
  assert.match(discord, /Don't open or read any other email/);
  assert.doesNotMatch(discord, /shows a download button/, 'Discord only emails the link');
  assert.match(discord, /RESULT: not_ready/);
  const takeout = agentPrompt(BY_ID.google_takeout, 'download', undefined, '2026-10-14T20:00:00Z');
  assert.match(takeout, /Open https:\/\/takeout\.google\.com\/manage in a new tab: once it's ready, Google shows a download button there/);
  assert.doesNotMatch(agentPrompt(BY_ID.instagram, 'request'), /not_ready/, 'requesting has nothing to be not ready');
  const two = agentPrompt(BY_ID.discord, 'download', undefined, undefined, { mine: ['ada@example.com', 'ada@alumni.example.edu'], to: 'ada@alumni.example.edu' });
  assert.match(two, /Discord said it would write to ada@alumni\.example\.edu, so look in that inbox/);
  assert.match(two, /Their addresses: ada@example\.com, ada@alumni\.example\.edu/);
  assert.match(two, /If the inbox it went to isn't signed in to Chrome, don't call it not ready: stop and ask them/);
  assert.match(agentPrompt(BY_ID.discord, 'request'), /EMAIL: <address>/, 'requesting, it notes where the link will go');
  const which = agentPrompt(BY_ID.discord, 'request', undefined, undefined, { names: ['ada_l'], mine: ['ada@example.com'] });
  assert.match(which, /check which account Discord is signed in as/);
  assert.match(which, /Theirs, as far as this Mac knows: ada_l, ada@example\.com/);
  assert.match(which, /looks made up by the service .* stop and ask them, naming the account, before requesting/);
});

test('reading the result: the last RESULT line', () => {
  assert.deepEqual(outcomeOf('Opening the page\nRESULT: requested'), { status: 'requested', note: '' });
  assert.deepEqual(outcomeOf('RESULT: failed first try\n...\nRESULT: needs_you Sign in to Instagram in Chrome.'), { status: 'needs_you', note: 'Sign in to Instagram in Chrome.' });
  assert.deepEqual(outcomeOf('result: Failed — the page never loaded'), { status: 'failed', note: 'the page never loaded' });
  assert.deepEqual(outcomeOf('No email from Discord yet.\nRESULT: not_ready (it isn\'t ready yet)'), { status: 'not_ready', note: '' });
  assert.deepEqual(outcomeOf('Submitted.\nEMAIL: ada@alumni.example.edu\nRESULT: requested'), { status: 'requested', note: '', email: 'ada@alumni.example.edu' });
  assert.equal(outcomeOf('All done, I think.'), null);
});

// A run with the stand-in for Claude Code in Chrome (test/fakes/fake_claude_browser.py), its plan and extension as given.
async function fakeRun(plan: object, chrome = 'connected') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-agent-'));
  const env = { FAKE_BROWSER_PLAN: path.join(dir, 'plan.json'), FAKE_BROWSER_LOG: path.join(dir, 'log'), FAKE_CHROME_STATUS: chrome };
  fs.writeFileSync(env.FAKE_BROWSER_PLAN, JSON.stringify(plan));
  const saved = { ...process.env };
  Object.assign(process.env, env);
  const logged: string[] = [];
  const steps: string[] = [];
  const waited: string[] = [];
  try {
    const started = Date.now();
    const out = await runAgent({ bin: FAKE, prompt: 'Request a full export of their Instagram data.', onStep: (l) => steps.push(l), log: (l) => logged.push(l),
      onWaiting: (w) => waited.push(w) }).done;
    return { out, steps, logged, waited, ms: Date.now() - started };
  } finally {
    process.env = saved;
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test('without the Claude in Chrome extension, a run stops as it starts and says what to turn on', async () => {
  const r = await fakeRun({ request: [{ steps: ['Opening Instagram', 'Trying without a browser'], result: 'requested', sleep: 2 }] }, 'failed');
  assert.equal(r.out.status, 'needs_you');
  assert.equal(r.out.reason, 'chrome');
  assert.equal(r.out.note, 'Turn on the Claude in Chrome extension.');
  assert.deepEqual(r.steps, [], 'it never went on without one');
  assert.ok(r.ms < 1500, `stopped at once (${r.ms} ms)`);
});

test('a run that ends without a RESULT line says so in plain words, the details in the log', async () => {
  const r = await fakeRun({ request: [{ steps: ['Opening Instagram'], result: '', sleep: 0.05 }] });
  assert.equal(r.out.status, 'failed');
  assert.equal(r.out.note, 'It stopped partway, without saying how far it got.');
  assert.doesNotMatch(r.out.note, /Claude Code|exit/);
});

test('one tab: Claude works in the tab it opens, reloads it to look again, and closes it (not when it stops for you)', () => {
  const mine = ['ada@gmail.com', 'ada@work.example'];
  const look = agentPrompt(BY_ID.chatgpt, 'download', undefined, '2026-10-10T00:00:00Z', { mine, inboxes: mine });
  assert.match(look, /- Use one tab: the one you open first\. Go from page to page in it, and to look in another account go to that account's address in it/);
  assert.match(look, /Before your last line, close that tab \(tabs_close_mcp\), unless you stop with needs_you: then leave it open/);
  assert.match(look, /In Gmail, look in the accounts of those addresses signed in to Chrome, one after another in the same tab/);
  assert.doesNotMatch(look, /any other webmail they're signed in to/, 'only the inboxes listed');
  assert.match(look, /look at that tab again every 15 seconds or so \(wait, then read it again\)/);
  assert.match(agentPrompt(BY_ID.instagram, 'request'), /- Use one tab/, 'asking for it too');
  assert.match(agentPrompt(BY_ID.chatgpt, 'download', undefined, undefined, {}), /every account signed in to Chrome, one after another in the same tab .*, and in any other webmail/, 'no addresses known: any');
  assert.match(CONTINUE, /in the same tab \(tabs_context_mcp lists your own\), or in one new tab if it's gone: never in another session's tab/);
  assert.match(visitPrompt([{ name: 'Instagram', url: 'https://instagram.com/' }]), /in one tab of your own \(go from one to the next in it\)/);
});

test('in the browser picked in Your Setup, looking only in the inboxes allowed there', () => {
  const mine = ['ada@gmail.com', 'ada@work.example'];
  const look = agentPrompt(BY_ID.discord, 'download', undefined, '2026-10-01T00:00:00Z', { mine, inboxes: ['ada@gmail.com'] }, 'Arc');
  assert.match(look, /^You're doing this for the person whose Arc this is\./);
  assert.match(look, /in their email in Arc:/);
  assert.match(look, /Their addresses: ada@gmail\.com \(/);
  assert.doesNotMatch(look, /ada@work\.example/);
  assert.match(look, /Look only in the inboxes of the addresses above/);
  assert.match(look, /if more than one browser is connected \(list_connected_browsers\), select Arc \(select_browser\) before anything else/, 'in the one picked');
  const none = agentPrompt(BY_ID.discord, 'download', undefined, undefined, { mine, inboxes: [] }, 'Arc');
  assert.match(none, /They've turned off looking in their email: don't open any webmail or email\. Discord sends the link only by email, so stop with needs_you/, 'every inbox off');
  assert.doesNotMatch(none, /webmail \(mail\.google\.com/);
  assert.doesNotMatch(look, /\bChrome\b(?! extension)/);
  // Requesting, every address still says which account is theirs.
  const ask = agentPrompt(BY_ID.instagram, 'request', undefined, undefined, { mine, inboxes: ['ada@gmail.com'] }, 'Arc');
  assert.match(ask, /Theirs, as far as this Mac knows: ada@gmail\.com, ada@work\.example/);
  assert.match(ask, /Arc may be signed in to an old or secondary one/);
  assert.match(ask, /"Allow Claude on <site> in Arc\." when Arc asks them to let Claude work on a site/, 'waiting, in its words too');
  // All allowed (nothing turned off): no limit is said.
  assert.doesNotMatch(agentPrompt(BY_ID.discord, 'download', undefined, undefined, { mine }), /Look only in/);
});

test('Claude waiting in Chrome for the person says so on a line of its own: the app hears it as waiting, not as a step', async () => {
  const r = await fakeRun({ request: [{ steps: ['Opening GitHub', 'WAITING: Confirm it\'s you with your passkey in Chrome.', 'Confirmed: starting the export'], result: 'requested', sleep: 0.1 }] });
  assert.equal(r.out.status, 'requested');
  assert.deepEqual(r.waited, ['Confirm it\'s you with your passkey in Chrome.']);
  assert.deepEqual(r.steps, ['Opening GitHub', 'Confirmed: starting the export', 'Done.']);
});

test('the instructions say to wait for the person a few minutes, not stop, and how to say what they need to do', () => {
  const p = agentPrompt(BY_ID.x, 'request');
  assert.match(p, /wait for them, don't stop: first write one line, WAITING: <what they need to do/);
  assert.match(p, /for up to 5 minutes, and carry on as soon as it's done\. Don't reload a page where they're signing in[^.]*\. Only if it still isn't done after that, stop with needs_you/);
  assert.match(p, /"Allow Claude on <site> in Chrome\." when Chrome asks them to let Claude work on a site/);
  assert.match(p, /never confirm with a passkey/);
});

test('reading the result however it\'s written: bold, in backticks, a list item, the prompt\'s <brackets>, "needs you"', () => {
  assert.deepEqual(outcomeOf('Done.\n**RESULT: requested**'), { status: 'requested', note: '' });
  assert.deepEqual(outcomeOf('`RESULT: downloading`'), { status: 'downloading', note: '' });
  assert.deepEqual(outcomeOf('- RESULT: needs you <Sign in to Instagram in Chrome.>'), { status: 'needs_you', note: 'Sign in to Instagram in Chrome.' });
  assert.deepEqual(outcomeOf('> RESULT: not ready'), { status: 'not_ready', note: '' });
  assert.deepEqual(outcomeOf('EMAIL: <ada@example.com>\nRESULT: requested'), { status: 'requested', note: '', email: 'ada@example.com' });
  assert.deepEqual(outcomeOf('EMAIL: a***a@example.com\nRESULT: requested'), { status: 'requested', note: '' }, 'an address shown masked isn\'t one to look in');
  assert.deepEqual(outcomeOf('OPENED: <https://x.com/settings>\nRESULT: requested')!.opened, ['https://x.com/settings']);
});

test('only its own WAITING: line is a wait, said once each; "Waiting for the page" is a step', async () => {
  const r = await fakeRun({ request: [{ steps: ['Waiting for the export page to load', 'WAITING: Sign in to Instagram in Chrome.', '**WAITING:** Sign in to Instagram in Chrome.',
    'waiting: lowercase is a step too'], result: 'requested', sleep: 0.05 }] });
  assert.deepEqual(r.waited, ['Sign in to Instagram in Chrome.'], 'one alert, not one a line');
  assert.ok(r.steps.includes('Waiting for the export page to load'));
  assert.equal(r.out.status, 'requested');
});

test('the extension gone partway, or Claude\'s usage limit: said as what it is, not "couldn\'t finish"', async () => {
  const lost = await fakeRun({ request: [{ steps: ['Opening Instagram'], tool: 'Error: Browser extension is not connected', result: 'failed couldn\'t click', sleep: 0.05 }] });
  assert.deepEqual([lost.out.status, lost.out.reason, lost.out.note], ['needs_you', 'chrome', 'Turn on the Claude in Chrome extension.']);
  const limit = await fakeRun({ request: [{ steps: ['Opening Instagram'], limit: 'You\'ve hit your usage limit · resets 7:40pm', result: '', sleep: 0.05 }] });
  assert.deepEqual([limit.out.status, limit.out.reason], ['failed', 'limit']);
  assert.equal(limit.out.note, 'Claude\'s usage limit was reached (resets 7:40pm). Try again then.');
});

test('a copy only, never deletion; a sign-in page read again, not reloaded; a download run doesn\'t ask again', () => {
  const ask = agentPrompt(BY_ID.chatgpt, 'request');
  assert.match(ask, /- Only ever ask for a copy of their data\. Never pick or click anything that deletes, deactivates, cancels, clears or opts out/);
  assert.doesNotMatch(ask, /repeat the export on a schedule/, 'no standing change to the account');
  assert.match(ask, /One that's finished and waiting to be downloaded: download it, and finish with RESULT: downloading/);
  assert.match(ask, /Don't reload a page where they're signing in or entering a password, passkey or code/);
  assert.doesNotMatch(ask, /reload it to look again/);
  const look = agentPrompt(BY_ID.chatgpt, 'download');
  assert.match(look, /Don't request a new export here: if the link has expired or there's no export to download, finish with RESULT: failed/);
  assert.doesNotMatch(look, /^RESULT: requested$/m, 'not one of its answers when downloading');
  assert.match(agentPrompt(BY_ID.chatgpt, 'download', 'https://chatgpt.com/x'), /Don't request a new export here: if the link has expired, finish with RESULT: failed The download link has expired/);
  assert.match(look, /If you can't tell which one is Chrome, don't guess: stop with needs_you, asking "Which browser is Chrome\?"/);
});

test('Spotify\'s request is confirmed in its email; Google\'s two exports each download only their own', () => {
  const spotify = agentPrompt(BY_ID.spotify, 'request', undefined, undefined, { mine: ['ada@gmail.com'], inboxes: ['ada@gmail.com'] });
  assert.match(spotify, /Spotify starts the export only once its email is confirmed\. After requesting, find that email in their email in Chrome \(mail from spotify\.com/);
  assert.match(spotify, /stop with needs_you: "Confirm the request in Spotify's email\."/);
  assert.match(spotify, /mail\.google\.com/, 'its webmail is a site it may use, for that one email');
  assert.match(agentPrompt(BY_ID.spotify, 'request', undefined, undefined, { mine: ['ada@gmail.com'], inboxes: [] }),
    /they've turned off looking in their email, so stop with needs_you: "Confirm the request in Spotify's email\."/);
  assert.match(agentPrompt(BY_ID.google_takeout, 'download'), /theirs is the one with Mail, Calendar, Chrome and the rest \(not one with only Google Photos and Drive\)\. Leave any other alone/);
  const photos = agentPrompt(BY_ID.google_photos_drive, 'download');
  assert.match(photos, /[Dd]ownload its first part only, even if there are more/);
  assert.doesNotMatch(photos, /every part/);
});

test('a visit before Ask for Everything: only opening each page, waiting for Allow, and saying which it got onto', () => {
  const p = visitPrompt([{ name: 'Spotify', url: 'https://www.spotify.com/account/privacy/' }], 'Brave');
  assert.match(p, /whose Brave this is/);
  assert.match(p, /only open it: don't click, type or sign in to anything on it/);
  assert.match(p, /WAITING: Allow Claude on <site> in Brave\./);
  const out = outcomeOf('OPENED: https://www.spotify.com/account/privacy/\nOPENED: https://x.com/settings\nRESULT: requested');
  assert.deepEqual(out?.opened, ['https://www.spotify.com/account/privacy/', 'https://x.com/settings']);
});

test('several at once: each run keeps to its own tab group, and never touches another session\'s tabs', () => {
  const own = /Other Claude sessions may be working in this browser at the same time, each in a tab group of its own\. Work only in the tab you open \(tabs_context_mcp lists your own\): never switch to, read, use or close any other tab, even one on the same site\./;
  assert.match(agentPrompt(BY_ID.instagram, 'request'), own);
  assert.match(agentPrompt(BY_ID.discord, 'download', undefined, '2026-10-14T20:00:00Z'), own);
  assert.match(visitPrompt([{ name: 'Spotify', url: 'https://www.spotify.com/account/privacy/' }]), own);
  for (const p of [agentPrompt(BY_ID.instagram, 'request'), agentPrompt(BY_ID.google_takeout, 'download', 'https://takeout.google.com/settings/takeout/downloads'), visitPrompt([{ name: 'X', url: 'https://x.com/' }])]) {
    assert.doesNotMatch(p, /current tab|active tab|the tab that's open|tab you're on/i, 'its own new tab, never whatever is in front');
    assert.match(p, /in a new tab|one tab of your own/);
  }
});

// The queue (main.ts pumpAgents), with stand-ins for Claude's runs: each says whether it was told to stop.
type Fake = { id: string; stopped: boolean; stop(): void };
function pool(cap: { n: number }, expires: Record<string, number> = {}) {
  const started: string[] = [];
  const runs = new Map<string, Fake>();
  const p = new AgentPool<Fake>(() => cap.n, (id) => expires[id] ?? Infinity);
  const start = (j: AgentJob) => {
    started.push(`${j.mode} ${j.sourceId}`);
    const r: Fake = { id: j.sourceId, stopped: false, stop() { this.stopped = true; } };
    runs.set(j.sourceId, r);
    return r;
  };
  const add = (sourceId: string, mode: AgentJob['mode'] = 'request') => {
    if (!p.busy(sourceId)) p.add({ sourceId, mode, resume: false });
    p.fill(start);
  };
  // A run ends (as runAgent's done does): room for the next.
  const end = (id: string) => {
    p.ended(id);
    p.fill(start);
  };
  return { p, started, runs, add, end, fill: () => p.fill(start), at: () => [...p.running.keys()], waiting: () => p.queue.map((q) => q.sourceId) };
}

test('a few at once, 3 unless set: no more than that, in the order asked, and never two on one service', () => {
  assert.equal(agentsAtOnce({}), 3, 'as usual');
  assert.equal(agentsAtOnce({ agentsAtOnce: 8 }), 5);
  const q = pool({ n: agentsAtOnce({}) });
  for (const id of ['instagram', 'spotify', 'discord', 'linkedin', 'x']) q.add(id);
  assert.deepEqual(q.at(), ['instagram', 'spotify', 'discord'], 'three at once');
  assert.deepEqual(q.waiting(), ['linkedin', 'x'], 'the rest wait their turn');
  q.add('spotify');
  q.add('linkedin');
  assert.equal(q.started.length, 3, 'one already at it or waiting isn\'t asked for twice');
  assert.deepEqual(q.p.ids(), ['linkedin', 'x', 'instagram', 'spotify', 'discord']);
  q.end('spotify');
  assert.deepEqual(q.at(), ['instagram', 'discord', 'linkedin'], 'one ends, the next in line starts');
  q.end('instagram');
  q.end('discord');
  q.end('linkedin');
  assert.deepEqual(q.at(), ['x']);
  assert.equal(q.p.room(), true, 'room, and nothing waiting: Claude\'s own looks may start');
  assert.deepEqual(q.started, ['request instagram', 'request spotify', 'request discord', 'request linkedin', 'request x']);
  // A service it's at already, asked for again behind it (its download, once its request is done): not alongside it.
  const one = pool({ n: 3 });
  one.add('instagram');
  one.p.add({ sourceId: 'instagram', mode: 'download', resume: false });
  one.add('spotify');
  assert.deepEqual(one.at(), ['instagram', 'spotify']);
  assert.deepEqual(one.waiting(), ['instagram'], 'waits for the one on its own service');
  one.end('instagram');
  assert.deepEqual(one.at(), ['spotify', 'instagram']);
  assert.deepEqual(one.started, ['request instagram', 'request spotify', 'download instagram']);
});

test('downloads go first, the link that runs out soonest first; set to one at a time, one after another', () => {
  const q = pool({ n: 1 }, { discord: 3, google_takeout: 1, chatgpt: 2 });
  q.add('instagram');
  q.add('spotify');
  q.add('discord', 'download');
  q.add('x');
  q.add('google_takeout', 'download');
  q.add('chatgpt', 'download');
  assert.deepEqual(q.at(), ['instagram'], 'one at a time');
  assert.deepEqual(q.waiting(), ['google_takeout', 'chatgpt', 'discord', 'spotify', 'x'], 'downloads first, soonest to expire first');
  for (const id of ['instagram', 'google_takeout', 'chatgpt', 'discord', 'spotify']) q.end(id);
  assert.deepEqual(q.started, ['request instagram', 'download google_takeout', 'download chatgpt', 'download discord', 'request spotify', 'request x']);
});

test('stopping the rest (the extension gone, or Claude\'s usage limit): the ones waiting are taken out, the ones running alongside told to stop', () => {
  const q = pool({ n: 3 });
  const batch = ['instagram', 'spotify', 'discord', 'linkedin', 'x'];
  for (const id of batch) q.add(id);
  // Instagram ends on the limit: the rest of Ask for Everything (not a look Claude is making by itself) is stopped.
  q.p.ended('instagram');
  q.p.add({ sourceId: 'chatgpt', mode: 'download', resume: false, auto: 'check' });
  const how = Object.fromEntries(q.p.ids().filter((id) => batch.includes(id)).map((id) => [id, q.p.stop(id)]));
  assert.deepEqual(how, { linkedin: 'waiting', x: 'waiting', spotify: 'running', discord: 'running' });
  assert.equal(q.runs.get('spotify')!.stopped, true, 'running alongside: told to stop');
  assert.equal(q.runs.get('discord')!.stopped, true);
  assert.equal(q.runs.get('instagram')!.stopped, false, 'the one that ended: nothing to stop');
  assert.deepEqual(q.waiting(), ['chatgpt'], 'what wasn\'t one of them stays');
  assert.deepEqual(q.at(), ['spotify', 'discord'], 'still running until each has stopped');
  assert.equal(q.p.busy('spotify'), true, 'and still busy until then: not asked for again meanwhile');
  q.end('spotify');
  q.end('discord');
  assert.deepEqual(q.started, ['request instagram', 'request spotify', 'request discord', 'download chatgpt'], 'none of the stopped ones started');
  assert.equal(q.p.stop('linkedin'), null, 'stopped already: nothing to stop');
  // Stop All: everything, at it or waiting.
  q.add('reddit');
  q.add('notion');
  for (const id of q.p.ids()) q.p.stop(id);
  assert.deepEqual(q.waiting(), []);
  assert.ok(['chatgpt', 'reddit', 'notion'].every((id) => q.runs.get(id)!.stopped));
});

test('the number changed mid-run: more starts the waiting ones now; fewer lets the ones running finish, and the next waits for room', () => {
  const cap = { n: 3 };
  const q = pool(cap);
  for (const id of ['instagram', 'spotify', 'discord', 'linkedin', 'x', 'chatgpt']) q.add(id);
  assert.deepEqual(q.at(), ['instagram', 'spotify', 'discord']);
  cap.n = 5; // AI Settings: 5 at once (main.ts pumps again when it changes)
  q.fill();
  assert.deepEqual(q.at(), ['instagram', 'spotify', 'discord', 'linkedin', 'x']);
  assert.deepEqual(q.waiting(), ['chatgpt']);
  cap.n = 2; // then 2 at once
  q.fill();
  assert.equal(q.at().length, 5, 'none of the running ones is stopped');
  assert.ok([...q.runs.values()].every((r) => !r.stopped));
  q.end('instagram');
  q.end('spotify');
  q.end('discord');
  assert.deepEqual(q.at(), ['linkedin', 'x'], 'still two running: the next waits');
  assert.deepEqual(q.waiting(), ['chatgpt']);
  q.end('linkedin');
  assert.deepEqual(q.at(), ['x', 'chatgpt'], 'room again: it starts');
  assert.equal(q.p.room(), false, 'two of two');
});
