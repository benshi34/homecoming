// Do It for Me's instructions to Claude and how its answer is read (main/export_agent.ts).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { agentPrompt, outcomeOf, runAgent, visitPrompt } from '../../src/main/export_agent.ts';

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
  assert.match(p, /Open https:\/\/takeout\.google\.com\/settings\/takeout\/downloads\?u=1 in a new tab\. Download it: every part/);
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

test('in the browser picked in Your Setup, looking only in the inboxes allowed there', () => {
  const mine = ['ada@gmail.com', 'ada@work.example'];
  const look = agentPrompt(BY_ID.discord, 'download', undefined, '2026-10-01T00:00:00Z', { mine, inboxes: ['ada@gmail.com'] }, 'Arc');
  assert.match(look, /^You're doing this for the person whose Arc this is\./);
  assert.match(look, /in their email in Arc:/);
  assert.match(look, /Their addresses: ada@gmail\.com \(/);
  assert.doesNotMatch(look, /ada@work\.example/);
  assert.match(look, /Look only in the inboxes of the addresses above/);
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
  assert.match(p, /for up to 5 minutes, and carry on as soon as it's done\. Only if it still isn't done after that, stop with needs_you/);
  assert.match(p, /"Allow Claude on <site> in Chrome\." when Chrome asks them to let Claude work on a site/);
  assert.match(p, /never confirm with a passkey/);
});

test('a visit before Ask for Everything: only opening each page, waiting for Allow, and saying which it got onto', () => {
  const p = visitPrompt([{ name: 'Spotify', url: 'https://www.spotify.com/account/privacy/' }], 'Brave');
  assert.match(p, /whose Brave this is/);
  assert.match(p, /only open it: don't click, type or sign in to anything on it/);
  assert.match(p, /WAITING: Allow Claude on <site> in Brave\./);
  const out = outcomeOf('OPENED: https://www.spotify.com/account/privacy/\nOPENED: https://x.com/settings\nRESULT: requested');
  assert.deepEqual(out?.opened, ['https://www.spotify.com/account/privacy/', 'https://x.com/settings']);
});
