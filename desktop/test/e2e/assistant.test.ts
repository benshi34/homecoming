// The Setup Assistant from the first page to the Overview, on a fake Mac: no Full Disk Access at first,
// Claude Code deleting transcripts, an encrypted iPhone backup, and one account exported (its page opened in your
// browser, its download picked up from Downloads). Every page is screenshotted to test-results/assistant-*.png.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap, until } from './harness.ts';

const PASSWORD = 'correct horse battery';
const FAKE_IPHONE = `
import json, sys, time
from common import RAW, Writer

def main(argv=None):
    argv = argv or []
    pw = sys.stdin.readline().rstrip("\\n") if "--password-stdin" in argv else None
    print("[iphone_backup] Test iPhone, encrypted", flush=True)
    time.sleep(1)
    if pw != ${JSON.stringify(PASSWORD)}:
        sys.exit("Wrong password: the backup's keys didn't unwrap. Nothing was written.")
    (RAW / "iphone").mkdir(parents=True, exist_ok=True)
    (RAW / "iphone/backup.json").write_text(json.dumps({"backup": "00008120-TEST", "backed_up": "2026-09-01 10:00:00"}))
    with Writer("phone_whatsapp", "fixture", parser="fixture") as w:
        w.add(id="m1", kind="message", ts="2026-09-01T00:00:00Z", text="hi")
    time.sleep(1)
`;

let sb: Sandbox;
let run: Running;
let env: Record<string, string>;
const step = () => run.page.locator('[data-testid=assistant]').getAttribute('data-step');
// Clicks something that moves the assistant to another step, and waits for the slide to finish.
const go = async (selector: string) => {
  const before = await step();
  await run.page.locator(selector).first().click();
  await run.page.waitForFunction((b) => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') !== b, before, { timeout: 15_000 });
  await run.page.waitForTimeout(450); // let the slide finish before the next screenshot
};
const cont = () => go('button[data-action=assistant-continue]');

before(async () => {
  sb = sandbox();
  fs.chmodSync(path.join(sb.home, 'Library/Messages'), 0);
  execFileSync(process.env.UMP_PYTHON || '/usr/local/bin/python3', [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'backup', sb.home]);
  const mods = path.join(sb.root, 'mods');
  fs.mkdirSync(mods);
  fs.writeFileSync(path.join(mods, 'fake_iphone.py'), FAKE_IPHONE);
  // Apps on this "Mac" that the services directory knows: what the Accounts page recommends.
  for (const name of ['Duolingo', 'Strava', 'Goodreads', 'Letterboxd', 'Pinterest', 'Tumblr', 'Twitch', 'Etsy', 'Airbnb', 'Uber']) {
    const dir = path.join(sb.home, 'Applications', `${name}.app`, 'Contents');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleName</key>`
      + `<string>${name}</string><key>CFBundleIdentifier</key><string>test.${name.toLowerCase()}</string></dict></plist>`);
  }
  env = sandboxEnv(sb, {
    UMP_IPHONE_MODULE: 'fake_iphone', UMP_EXTRA_PYPATH: mods,
    UMP_URLS: JSON.stringify({ discord: 'https://discord.example/export' }),
  });
  run = await launch(env, { assistant: true });
  await until(run.page, 'probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('opens on the welcome page with the step timeline', async () => {
  assert.equal(await run.page.locator('[data-testid=app]').getAttribute('data-mode'), 'assistant');
  assert.equal(await step(), 'welcome');
  assert.match(await run.page.locator('.hero h1').innerText(), /Welcome to Homecoming/);
  assert.match(await run.page.locator('[data-testid=sb-Welcome]').getAttribute('class') ?? '', /current/);
  assert.equal(await run.page.locator('[data-testid=steps-bar] .sb-item').count(), 11);
  // The tour: three steps on made-up data, labeled as such. Picking one stops it moving on by itself.
  const stage = run.page.locator('[data-testid=tour-stage]');
  assert.equal(await run.page.locator('.tour-timer').count(), 1, 'it moves on by itself until you pick a step');
  assert.equal(await run.page.locator('.tour-step').count(), 3);
  assert.match(await stage.innerText(), /made-up data/);
  await run.page.click('[data-testid=tour-step-2]');
  await stage.locator('text=All filed').waitFor({ timeout: 10_000 });
  assert.match(await stage.innerText(), /Your library/);
  assert.equal(await run.page.locator('.tour-timer').count(), 0, 'a step you picked stays up');
  // Step 3: the real Explore page on example data. This Mac has no corpus, so every tile being filled, and every
  // photo a drawn one, shows none of it came from real records.
  await run.page.click('[data-testid=tour-step-3]');
  const browse = run.page.locator('[data-testid=demo-browse]');
  await browse.locator('[data-testid=explore-home]').waitFor({ timeout: 10_000 });
  const tiles = browse.locator('.explore-tile');
  assert.equal(await tiles.count(), 15);
  assert.equal(await browse.locator('.explore-tile[data-ready=yes]').count(), 15);
  assert.equal(await browse.locator('.tile-note').count(), 0, 'no tile is building or failed');
  assert.equal(await browse.locator('.explore-tile.locked').count(), 0, 'an example has enough of everything');
  assert.match(await browse.locator('.t-on-this-day img').first().getAttribute('src') ?? '', /^data:image\/svg\+xml/);
  // The pointer browses into Your People on its own; a click of yours hands the window over.
  await browse.locator('[data-testid=explore-people]').waitFor({ timeout: 12_000 });
  assert.equal(await browse.getAttribute('data-driving'), 'yes');
  await browse.locator('[data-testid=explore-back]').click();
  assert.equal(await browse.getAttribute('data-driving'), 'no');
  await browse.locator('[data-testid=explore-card-made]').click();
  await browse.locator('[data-testid=explore-made]').waitFor({ timeout: 10_000 });
  await run.page.waitForTimeout(1500); // past where the pointer would have gone next: it's yours now
  assert.equal(await browse.locator('[data-testid=explore-made]').count(), 1);
  assert.equal(await run.page.locator('.demo-pointer').count(), 0);
  // Then a question for Ask.
  await run.page.click('[data-testid=demo-ask-tab]');
  await stage.locator('[data-testid=ask-answer]').waitFor({ timeout: 10_000 });
  await stage.locator('text=Climbing crew').waitFor({ timeout: 10_000 });
  await run.page.click('[data-testid=tour-step-1]');
  await shot(run.page, 'assistant-01-welcome');
  await cont();
  assert.match(await run.page.locator('[data-testid=sb-Welcome]').getAttribute('class') ?? '', /done/);
  assert.equal(await step(), 'access');
});

test('Full Disk Access turns green when granted', async () => {
  assert.equal(await step(), 'access');
  assert.match(await run.page.locator('[data-testid=fda-status]').innerText(), /Not allowed yet/);
  assert.match(await run.page.locator('[data-testid=fda-status]').innerText(), /Waiting on it: Messages/);
  await shot(run.page, 'assistant-02-access');
  fs.chmodSync(path.join(sb.home, 'Library/Messages'), 0o755);
  await run.page.locator('[data-testid=fda-status] button[data-action=recheck]').click();
  await run.page.locator('[data-testid=fda-status]', { hasText: 'Full Disk Access is on' }).waitFor();
  await cont();
});

test('the library page checks where everything goes', async () => {
  assert.equal(await step(), 'library');
  assert.match(await run.page.locator('[data-testid=check-corpus_location]').innerText(), /out of iCloud Drive/);
  await shot(run.page, 'assistant-03-library');
  await cont();
});

test('the Mac page shows sources being read', async () => {
  assert.equal(await step(), 'mac');
  await until(run.page, 'mac read', (x) => ['ai_coding', 'git_commits', 'documents'].every((id) => find(x, id).section === 'done') && !x.jobs.some((j) => j.kind === 'connectors'), 120_000);
  await run.page.locator('[data-testid=mac-count]', { hasText: '3 of 3 read' }).waitFor();
  await shot(run.page, 'assistant-05-mac');
  await cont();
});

test('the iPhone page takes the password, then reads the backup', async () => {
  assert.equal(await step(), 'iphone');
  await run.page.locator('#pw').waitFor();
  assert.equal(await run.page.locator('.hero .badge').textContent(), 'Highly Recommended');
  await shot(run.page, 'assistant-06-iphone');
  await run.page.fill('#pw', 'wrong');
  await run.page.locator('[data-testid=password-form] button[type=submit]').click();
  await run.page.locator('[data-testid=iphone-status]', { hasText: 'That password didn\'t work' }).waitFor({ timeout: 30_000 });
  await run.page.fill('#pw', PASSWORD);
  await run.page.locator('[data-testid=password-form] button[type=submit]').click();
  await until(run.page, 'phone read', (x) => find(x, 'iphone_backup').section === 'done', 60_000);
  await run.page.locator('[data-testid=iphone-status]', { hasText: '1 record from 1 phone source' }).waitFor();
  await run.page.locator('[data-testid^=phone-part-]').first().waitFor();
  await cont();
});

test('choosing accounts skips the rest and builds one page per account', async () => {
  assert.equal(await step(), 'accounts');
  await shot(run.page, 'assistant-07-accounts');
  // Yours: the ones most people use, most used first. Recommended: what's not added yet, with the top few found in
  // your data. Adding or removing one moves it to the other list.
  const ids = (list: string) => run.page.locator(`[data-testid=${list}] [data-testid^=account-]`).evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')!.slice(8)));
  assert.deepEqual((await ids('accounts')).slice(0, 4), ['google_takeout', 'facebook', 'instagram', 'other_mail'], 'Outlook and other email is an account like the rest');
  assert.ok((await ids('accounts')).includes('maps_timeline'));
  assert.ok((await ids('recommended')).includes('slack'), 'optional ones start off, as Google Photos does');
  const photos = await run.page.locator('[data-testid=recommended] [data-testid=account-google_photos_drive]').innerText();
  assert.doesNotMatch(photos, /Optional/, 'every account is a choice; none is singled out');
  assert.match(photos, /Can be hundreds of GB, so it isn't on your list unless you add it/);
  await until(run.page, 'apps found', (x) => (x.discovery?.found.length ?? 0) >= 10, 30_000);
  const rec = run.page.locator('[data-testid=recommended]');
  await rec.locator('[data-testid^="account-found:"]').first().waitFor();
  assert.equal(await rec.locator('[data-testid^="account-found:"]').count(), 8, 'only the top ones');
  assert.equal(await run.page.locator('[data-testid=accounts] [data-testid^="account-found:"]').count(), 0, 'not added until you add them');
  assert.match(await run.page.locator('button[data-action=see-all-found]').innerText(), /See All 10 Found/);
  // Found apps have their brands' logos.
  assert.equal(await rec.locator('[data-testid="account-found:duolingo"] [data-logo=duolingo]').count(), 1);
  await rec.scrollIntoViewIfNeeded();
  await shot(run.page, 'assistant-07-accounts-recommended');
  await rec.locator('[data-testid="account-found:duolingo"] button[data-action=add-account]').click();
  await run.page.locator('[data-testid=accounts] [data-testid="account-found:duolingo"]').waitFor();
  assert.equal(await rec.locator('[data-testid^="account-found:"]').count(), 8, 'the next one takes its place');
  await run.page.waitForTimeout(400);
  await run.page.locator('[data-testid=accounts] [data-testid="account-found:duolingo"] button[data-action=remove-account]').click();
  await rec.locator('[data-testid="account-found:duolingo"]').waitFor();
  await run.page.waitForTimeout(400);
  // Down to just Discord and Reddit, one move at a time (clicks during a move's animation don't land).
  const removes = run.page.locator('[data-testid=accounts] button[data-action=remove-account]');
  for (let n = await removes.count(); n > 0; n--) {
    await removes.first().click();
    await run.page.waitForFunction((k) => document.querySelectorAll('[data-testid=accounts] [data-action=remove-account]').length < k, n);
    await run.page.waitForTimeout(400);
  }
  assert.match(await run.page.locator('[data-testid=accounts]').innerText(), /None yet/);
  for (const id of ['discord', 'reddit', 'other_mail']) {
    await rec.locator(`[data-testid=account-${id}] button[data-action=add-account]`).click();
    await run.page.locator(`[data-testid=accounts] [data-testid=account-${id}]`).waitFor();
    await run.page.waitForTimeout(400);
  }
  assert.deepEqual(await ids('accounts'), ['other_mail', 'reddit', 'discord'], 'the common ones keep their most-used-first order');
  assert.match(await run.page.locator('button[data-action=assistant-continue]').innerText(), /Continue with 3/);
  await cont();
  // AI, asked once: what it's for, and which agent. Not Now moves on with it off.
  assert.equal(await step(), 'ai');
  assert.match(await run.page.locator('[data-testid=ai-agreement]').innerText(), /Do It for Me/);
  assert.match(await run.page.locator('button[data-action=assistant-continue]').innerText(), /Turn On AI/);
  await run.page.locator('[data-testid=ai-settings] [data-testid^=ai-provider-]').first().waitFor();
  await shot(run.page, 'assistant-07b-ai');
  await go('button[data-action=ai-not-now]');
  assert.equal((await snap(run.page)).settings.aiOn, false);
  // A list of the chosen ones first: start anywhere, and come back to it from any of them.
  assert.equal(await step(), 'exports');
  // Back to AI: Not Now agreed to nothing, so the choice is there again.
  await go('button[data-action=assistant-back]');
  assert.equal(await step(), 'ai');
  await run.page.locator('[data-testid=ai-agreement]').waitFor();
  assert.match(await run.page.locator('button[data-action=assistant-continue]').innerText(), /Turn On AI/);
  await go('button[data-action=ai-not-now]');
  assert.equal(await step(), 'exports');
  const rows = await run.page.locator('[data-testid=exports-list] [data-testid^=exports-]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')));
  assert.deepEqual(rows, ['exports-discord', 'exports-reddit', 'exports-other_mail'], 'longest wait first; Outlook, set up by hand, last');
  assert.match(await run.page.locator('button[data-action=assistant-continue]').innerText(), /Start with Discord/);
  await shot(run.page, 'assistant-08-exports-list');
  await go('[data-testid=exports-reddit]');
  assert.equal(await step(), 'export:reddit');
  assert.match(await run.page.locator('[data-testid=sb-Exports]').innerText(), /Exports 2\/3/);
  await go('button[data-action=all-exports]');
  assert.equal(await step(), 'exports');
  await go('[data-testid=exports-discord]');
  assert.equal(await step(), 'export:discord');
  const s = await snap(run.page);
  assert.equal(find(s, 'spotify').status, 'Skipped: I don\'t use it');
  assert.equal(find(s, 'discord').section, 'needs');
  assert.match(await run.page.locator('[data-testid=sb-Exports]').innerText(), /Exports 1\/3/);
});

test('an export page opens the site in your browser, and the download is picked up when it lands', async () => {
  await shot(run.page, 'assistant-08-export');
  const open = run.page.locator('[data-testid=export-status] button[data-action=open]');
  assert.match(await open.innerText(), /^Open Discord in /, 'named after the default browser');
  await open.click();
  const log = path.join(env.UMP_USER_DATA, 'opened.txt');
  await until(run.page, 'opened in the browser', () => fs.existsSync(log) && fs.readFileSync(log, 'utf8').includes('https://discord.example/export'));
  fs.copyFileSync(sb.exports.discord, path.join(sb.downloads, 'package.zip'));
  await until(run.page, 'discord imported', (x) => find(x, 'discord').section === 'done' && !x.jobs.length, 90_000);
  await shot(run.page, 'assistant-09-export-done');
  assert.match(await run.page.locator('button[data-action=assistant-continue]').innerText(), /^Continue$/);
  await cont();
  // On to the one not asked for yet, Reddit; skipping it, on past the exports.
  assert.equal(await step(), 'export:reddit');
  await go('button[data-action=skip-export]');
  assert.equal(find(await snap(run.page), 'reddit').status, 'Set aside for now', 'for now: kept under Needs You, not put away');
});

test('Outlook and other email: an account with its own page, set up through Mail; no Extras section after', async () => {
  assert.equal(await step(), 'export:other_mail');
  const status = run.page.locator('[data-testid=export-status]');
  assert.match(await run.page.locator('.hero h1').innerText(), /Outlook and other email/);
  assert.doesNotMatch(await run.page.locator('[data-testid=assistant] .page').innerText(), /privacy law/, 'no request form to fill in: nothing about which law');
  assert.equal(await status.locator('button[data-action=open-internet-accounts]').count(), 1, 'its own way in: Mail');
  assert.equal(await status.locator('button[data-action=add-file]').count(), 1);
  assert.equal(await status.locator('button[data-action=open]').count(), 0, 'nothing to open in a browser');
  await run.page.locator('[data-testid=account-form]').waitFor();
  assert.match(await run.page.locator('.drop').innerText(), /\.mbox/);
  await shot(run.page, 'assistant-10-other-mail');
  assert.equal(await run.page.locator('[data-testid=sb-Extras]').count(), 0, 'no Extras section');
  await go('.footer-bar button[data-action=skip-export]');
  assert.equal(find(await snap(run.page), 'other_mail').status, 'Skipped: No other mail accounts');
  assert.equal(await step(), 'identity');
});

test('which of these are you: found in the data, confirmed at the end', async () => {
  assert.equal(await step(), 'identity');
  await until(run.page, 'candidates', (x) => x.identityCandidatesReady && x.identityCandidates.length > 0);
  assert.match(await run.page.locator('.hero h1').innerText(), /Which of these are you\?/);
  const ada = run.page.locator('[data-testid="cand-email:ada@example.com"]');
  await ada.waitFor();
  assert.ok(await ada.locator('input').isChecked());
  await shot(run.page, 'assistant-11-identity');
  await cont();
  assert.equal(await step(), 'keep', 'keeping history going comes last');
  const id = readJson(path.join(sb.corpus, 'identity.json'));
  assert.deepEqual(id.names, ['Ada Lovelace']);
  assert.ok(id.emails.includes('ada@example.com') && id.emails.includes('ada.lovelace@icloud.example'));
  assert.deepEqual(id.phones, ['+14155550100']);
});

test('the keep-history page explains what each setting protects, and fixes it', async () => {
  assert.equal(await step(), 'keep');
  assert.match(await run.page.locator('.hero p').innerText(), /From now on/);
  const row = run.page.locator('[data-testid=check-retention_claude]');
  assert.match(await row.innerText(), /deletes conversation transcripts after 30 days/);
  assert.match(await run.page.locator('[data-testid=check-retention_messages]').innerText(), /Already keeps everything/);
  // grouped by where the setting lives; the iPhone's own Messages setting is there
  assert.match(await run.page.locator('[data-testid=check-retention_iphone_messages]').innerText(), /its own Keep Messages setting/);
  assert.equal(await run.page.locator('[data-testid=check-retention_google]').count(), 0, 'Google was turned off on the accounts page');
  assert.equal(await run.page.locator('[data-testid=check-retention_maps]').count(), 0, 'and so was Maps Timeline: an account like the rest');
  await run.page.locator('[data-testid=keep-backup]').waitFor();
  await shot(run.page, 'assistant-12-keep');
  await row.locator('button[data-action=fix-claude-retention]').click();
  // It changes a file of Claude Code's: it says exactly what, and asks first.
  const confirm = run.page.locator('[data-testid=confirm]');
  assert.match(await confirm.innerText(), /cleanupPeriodDays in ~\/\.claude\/settings\.json/);
  await confirm.locator('button', { hasText: 'Continue' }).click();
  await until(run.page, 'claude retention', (x) => find(x, 'retention_claude').section === 'done');
  await row.locator('.checkmark').waitFor();
  assert.equal(readJson(path.join(sb.home, '.claude/settings.json')).cleanupPeriodDays, 100000);
  // the daily read is a switch on the same page
  await run.page.locator('[data-testid=toggle-daily]').click();
  await until(run.page, 'daily off', (x) => x.settings.autoRefresh === false);
  await run.page.locator('[data-testid=toggle-daily][aria-checked=false]').waitFor();
  await run.page.locator('[data-testid=toggle-daily]').click();
  await until(run.page, 'daily on', (x) => x.settings.autoRefresh === true);
  await cont();
});

test('the summary', async () => {
  assert.equal(await step(), 'done');
  await run.page.locator('[data-testid=timeline]').waitFor();
  assert.equal(await run.page.locator('[data-testid=phase-mac]').getAttribute('data-status'), 'done');
  assert.equal(await run.page.locator('[data-testid=phase-iphone]').getAttribute('data-status'), 'done');
  await shot(run.page, 'assistant-12-done');
});

test('Back slides back and keeps what was entered', async () => {
  await run.page.locator('button[data-action=assistant-continue]').click(); // Open Overview
  await run.page.locator('[data-testid=app][data-mode=main]').waitFor();
  await run.page.locator('[data-testid=overview]').waitFor();
  assert.equal((await snap(run.page)).onboarding.done, true);
  await shot(run.page, 'assistant-13-overview');
  await run.page.locator('button[aria-label="Setup Assistant"]').click();
  await run.page.locator('[data-testid=app][data-mode=assistant]').waitFor();
  assert.equal(await step(), 'done', 'reopens where it was left');
  await run.page.locator('button[data-action=assistant-back]').click();
  await run.page.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'keep');
  assert.deepEqual(run.errors, []);
});

test('after a restart the main window comes first', async () => {
  await run.close();
  run = await launch(env, { assistant: true });
  await run.page.locator('[data-testid=app][data-mode=main]').waitFor();
  const s = await until(run.page, 'probe', (x) => !!x.probeTime);
  assert.equal(s.onboarding.done, true);
  assert.equal(find(s, 'discord').section, 'done');
});
