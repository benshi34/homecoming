// Do It for Me's instructions to Claude and how its answer is read (main/export_agent.ts).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { agentPrompt, outcomeOf } from '../../src/main/export_agent.ts';

test('the request prompt: the export page, the service\'s own steps, everything picked, and when to stop', () => {
  const p = agentPrompt(BY_ID.instagram, 'request');
  assert.match(p, /Open https:\/\/accountscenter\.instagram\.com\/info_and_permissions\/dyi\/ in a new tab/);
  assert.match(p, /Format: JSON/, 'its steps, as written for a person');
  assert.match(p, /all time, JSON/);
  assert.match(p, /Never type a password or a code and never answer a CAPTCHA/);
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
