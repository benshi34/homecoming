import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { CATALOG } from '../../src/shared/catalog.ts';
import { computeSources, gapYears, LAW_HINT, latestBackup, mirrorIsCurrent, nextUp, robustFirst, summarize, totals } from '../../src/shared/status.ts';
import type { Backup, JobView } from '../../src/shared/types.ts';
import { actionIds, H, hoursAgo, input, NOW, probe, state, stats, view, views } from './helpers.ts';

const backup = (over: Partial<Backup> = {}): Backup => ({
  dir: '/b/1', id: '00008120-TEST', device: 'Test iPhone', product: 'iPhone99,1', ios: '26.0',
  date: '2026-09-01T10:00:00+00:00', encrypted: true, finished: true, in_progress: false, ...over,
});
const job = (over: Partial<JobView>): JobView => ({ id: 'job-1', kind: 'connectors', label: 'Reading', sourceIds: [], connectors: [], state: 'running', startedAt: hoursAgo(0.1), ...over });

describe('every source', () => {
  test('each catalog source gets exactly one view, sorted by priority', () => {
    const vs = views();
    assert.equal(vs.length, CATALOG.length);
    assert.deepEqual(new Set(vs.map((v) => v.id)), new Set(CATALOG.map((s) => s.id)));
    for (let i = 1; i < vs.length; i++) assert.ok(vs[i - 1].priority <= vs[i].priority);
  });

  test('with no probe yet, nothing claims to be done and nothing crashes', () => {
    const vs = views({ probe: null, stats: null });
    for (const v of vs.filter((x) => x.group === 'setup')) assert.equal(v.section, 'working', v.id);
    assert.ok(vs.every((v) => typeof v.status === 'string'));
  });

  test('a fresh Mac starts with Full Disk Access and identity', () => {
    const vs = views({ probe: probe({ fda: false, identity: null, sources: { imessage: 'blocked', ai_coding: 'ok' } }) });
    assert.equal(nextUp(vs), 'fda');
    const needs = vs.filter((v) => v.section === 'needs' && !v.blockedBy).map((v) => v.id);
    assert.ok(needs.indexOf('fda') < needs.indexOf('identity'));
    assert.equal(vs.find((v) => v.id === 'ai_coding')!.blockedBy, undefined, 'collection never waits for identity');
    assert.ok(vs.find((v) => v.id === 'identity')!.priority > vs.find((v) => v.id === 'discord')!.priority, 'identity is a final check');
    assert.equal(vs.find((v) => v.id === 'imessage')!.blockedBy, 'fda');
  });
});

describe('setup', () => {
  test('identity', () => {
    const missing = view('identity', { probe: probe({ identity: null }) });
    assert.equal(missing.section, 'needs');
    assert.equal(missing.priority, 65);
    assert.equal(missing.actions[0].input, 'identity');
    const partial = view('identity', { probe: probe({ identity: { names: ['Ada'], emails: [], usernames: [], phones: [] } }) });
    assert.equal(partial.section, 'needs', 'a name without an email is not enough');
    const ok = view('identity');
    assert.equal(ok.section, 'done');
    assert.match(ok.status, /Ada Lovelace, 1 email$/);
  });

  test('Full Disk Access', () => {
    const no = view('fda', { probe: probe({ fda: false, sources: { imessage: 'blocked', photos: 'blocked', ai_coding: 'ok' } }) });
    assert.equal(no.section, 'needs');
    assert.equal(no.status, 'Needed for 2 sources on this Mac');
    assert.deepEqual(actionIds(no), ['open-fda-settings', 'recheck']);
    assert.equal(view('fda', { probe: probe({ fda: null }) }).section, 'unavailable');
    assert.equal(view('fda').section, 'done');
  });

  test('Python packages', () => {
    const v = view('python_env', { probe: probe({ python: { path: '/usr/local/bin/python3', version: '3.14', cryptography: false, pypdf: false } }) });
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'Missing cryptography and pypdf');
    assert.match(v.detail!, /\/usr\/local\/bin\/python3 -m pip install cryptography pypdf/);
    assert.equal(view('python_env').section, 'done');
  });

  test('corpus in iCloud asks before moving anything', () => {
    const p = probe();
    p.corpus.in_icloud = true;
    const v = view('corpus_location', { probe: p });
    assert.equal(v.section, 'needs');
    const a = v.actions.find((x) => x.id === 'exclude-icloud')!;
    assert.match(a.confirm!, /corpus\.nosync/);
    assert.equal(view('corpus_location').section, 'done');
  });

  test('disk space', () => {
    const p = probe();
    p.corpus.free_bytes = 5e9;
    assert.equal(view('disk_space', { probe: p }).section, 'needs');
    const ok = view('disk_space', { probe: p, state: state((s) => (s.sources.disk_space = { doneAt: hoursAgo(1) })) });
    assert.equal(ok.section, 'done');
    assert.equal(ok.warnings.length, 1);
    assert.equal(view('disk_space').status, '100 GB free');
  });

  test('Claude Code retention', () => {
    const retention = (claude: object) => ({ ...probe().retention, claude: claude as never });
    assert.equal(view('retention_claude', { probe: probe({ retention: retention({ present: false }) }) }).section, 'unavailable');
    const short = view('retention_claude', { probe: probe({ retention: retention({ present: true, days: 7 }) }) });
    assert.equal(short.section, 'needs');
    assert.equal(short.status, 'Transcripts are deleted after 7 days');
    assert.deepEqual(actionIds(short), ['fix-claude-retention']);
    assert.equal(view('retention_claude', { probe: probe({ retention: retention({ present: true, days: null }) }) }).status, 'Transcripts are deleted after 30 days');
    assert.equal(view('retention_claude').section, 'done');
  });

  test('Terminal history retention', () => {
    const shell = (s: object | undefined) => probe({ retention: { ...probe().retention, shell: s as never } });
    const def = view('retention_shell', { probe: shell({ shell: 'zsh', savehist: 1000, extended: false }) });
    assert.equal(def.section, 'needs');
    assert.equal(def.status, 'Keeps only your last 1,000 commands, without times');
    assert.deepEqual(actionIds(def), ['fix-shell-retention']);
    assert.equal(view('retention_shell', { probe: shell({ shell: 'zsh', savehist: 10000, extended: true }) }).status, 'Keeps only your last 10,000 commands');
    assert.equal(view('retention_shell', { probe: shell({ shell: 'zsh', savehist: 1000000, extended: true }) }).section, 'done');
    assert.equal(view('retention_shell', { probe: shell({ shell: 'fish' }) }).section, 'unavailable');
    assert.equal(view('retention_shell', { probe: shell(undefined) }).section, 'unavailable');
  });

  test('Messages retention', () => {
    const with_ = (messages: object) => probe({ retention: { ...probe().retention, messages: messages as never } });
    assert.equal(view('retention_messages', { probe: with_({ readable: true, value: 30 }) }).section, 'needs');
    assert.equal(view('retention_messages', { probe: with_({ readable: true, value: null }) }).section, 'done', 'unset means the default, Forever');
    const unknown = view('retention_messages', { probe: with_({ readable: false, value: null }) });
    assert.equal(unknown.section, 'needs');
    assert.ok(actionIds(unknown).includes('mark-done'));
    assert.equal(view('retention_messages', { probe: with_({ readable: false, value: null }), state: state((s) => (s.sources.retention_messages = { doneAt: hoursAgo(1) })) }).section, 'done');
  });

  test('iPhone Messages retention, read from the backup', () => {
    const with_ = (m?: object, over = {}) => probe({ retention: { ...probe().retention, iphone_messages: m as never }, ...over });
    assert.equal(view('retention_iphone_messages', { probe: with_({ readable: true, value: null }) }).status, 'Forever (from your iPhone backup)');
    const short = view('retention_iphone_messages', { probe: with_({ readable: true, value: 365 }) });
    assert.equal(short.section, 'needs');
    assert.equal(short.status, 'The iPhone deletes messages after 365 days');
    const unknown = view('retention_iphone_messages', { probe: with_(undefined) });
    assert.match(unknown.detail!, /once one has been read/);
    assert.equal(view('retention_iphone_messages', { probe: with_(undefined), state: state((s) => (s.sources.retention_iphone_messages = { doneAt: hoursAgo(1) })) }).section, 'done');
    assert.equal(view('retention_iphone_messages', { probe: with_(undefined), state: state((s) => (s.sources.iphone_backup = { skipped: 'No iPhone' })) }).section, 'unavailable');
  });

  test('Codex, Google and Maps Timeline retention', () => {
    const r = probe().retention;
    assert.equal(view('retention_codex', { probe: probe({ retention: { ...r, codex: { present: true } } }) }).status, 'Keeps every session until you delete it');
    assert.equal(view('retention_codex').section, 'unavailable');
    const g = view('retention_google');
    assert.equal(g.section, 'needs');
    assert.deepEqual(actionIds(g), ['open-external', 'mark-done']);
    assert.equal(view('retention_google', { state: state((s) => (s.sources.google_takeout = { skipped: 'I don\'t use it' })) }).section, 'unavailable');
    assert.equal(view('retention_maps').status, 'Timeline deletes visits older than 3 months by default');
    assert.equal(view('retention_maps', { state: state((s) => (s.sources.retention_maps = { doneAt: hoursAgo(1) })) }).section, 'done');
  });

  test('Safari retention', () => {
    const with_ = (safari: object, over = {}) => probe({ retention: { ...probe().retention, safari: safari as never }, ...over });
    const dflt = view('retention_safari', { probe: with_({ readable: true, value: null }) });
    assert.equal(dflt.section, 'needs');
    assert.equal(dflt.status, 'Safari removes history after a year');
    assert.equal(view('retention_safari', { probe: with_({ readable: false, value: null }, { fda: false }) }).blockedBy, 'fda');
    assert.equal(view('retention_safari').section, 'done');
    assert.equal(view('retention_safari', { probe: with_({ readable: true, value: null }), state: state((s) => (s.sources.retention_safari = { doneAt: hoursAgo(1) })) }).section, 'done');
  });
});

describe('Mac sources', () => {
  test('reading does not wait for identity', () => {
    const v = view('apple_notes', { probe: probe({ identity: null }) });
    assert.equal(v.blockedBy, undefined);
    assert.equal(v.status, 'Ready to read');
  });

  test('present but never read', () => {
    const v = view('apple_notes');
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'Ready to read');
    assert.equal(v.actions[0].id, 'run');
  });

  test('blocked, absent, skipped', () => {
    const p = probe({ fda: false, sources: { ...probe().sources, imessage: 'blocked', voice_memos: 'absent' } });
    assert.equal(view('imessage', { probe: p }).blockedBy, 'fda');
    assert.equal(view('voice_memos', { probe: p }).section, 'unavailable');
    const skipped = view('photos', { state: state((s) => (s.sources.photos = { skipped: 'Not using it' })) });
    assert.equal(skipped.section, 'unavailable');
    assert.deepEqual(actionIds(skipped), ['unskip']);
  });

  test('blockedBy clears once Full Disk Access is granted', () => {
    const p = probe({ sources: { ...probe().sources, imessage: 'blocked' } }); // fda true, stale source state
    assert.equal(view('imessage', { probe: p }).blockedBy, undefined);
  });

  test('read: records, range, staleness', () => {
    const s = stats({ apple_notes: { count: 321, first: '2018-02-01T00:00:00Z', last: hoursAgo(2), ran_at: hoursAgo(2) } });
    const v = view('apple_notes', { stats: s });
    assert.equal(v.section, 'done');
    assert.equal(v.status, '321 records, 2018 to now');
    assert.deepEqual(v.warnings, []);
    const stale = view('apple_notes', { stats: stats({ apple_notes: { count: 5, ran_at: hoursAgo(24 * 7) } }) });
    assert.deepEqual(stale.warnings, ['Last read 7 days ago.']);
  });

  test('read but empty', () => {
    assert.equal(view('voice_memos', { stats: stats({ voice_memos: { count: 0 } }) }).section, 'unavailable');
  });

  test('errors show until a later successful run', () => {
    const err = state((s) => (s.sources.calls = { lastError: 'database is locked', lastErrorAt: hoursAgo(0.5) }));
    const failed = view('calls', { state: err, stats: stats({ calls: { count: 3, ran_at: hoursAgo(5) } }) });
    assert.equal(failed.section, 'needs');
    assert.equal(failed.detail, 'database is locked');
    const recovered = view('calls', { state: err, stats: stats({ calls: { count: 3, ran_at: hoursAgo(0.1) } }) });
    assert.equal(recovered.section, 'done');
  });

  test('running and queued jobs', () => {
    const running = view('imessage', { jobs: [job({ sourceIds: ['imessage', 'contacts'], connectors: ['contacts', 'imessage'], current: 'imessage', lastLine: '[imessage] 400k records' })] });
    assert.equal(running.section, 'working');
    assert.match(running.status, /^Reading: imessage…/);
    assert.equal(running.detail, '[imessage] 400k records');
    const queued = view('photos', { jobs: [job({ state: 'queued', sourceIds: ['photos'], connectors: ['photos'] })] });
    assert.equal(queued.status, 'Waiting to start');
  });

  test('Mac + iPhone tag once a phone mirror exists', () => {
    assert.equal(view('imessage').tag, 'Mac');
    assert.equal(view('imessage', { probe: probe({ mirror: { backup: 'x' } }) }).tag, 'Mac + iPhone');
  });

  test('gap warnings only for message sources', () => {
    const years = { '2019': 5000, '2020': 30000, '2021': 900, '2022': 31000, '2023': 29000, '2024': 30000, '2025': 1000, '2026': 20000 };
    const s = stats({ imessage: { count: 1, ran_at: hoursAgo(1) }, photos: { count: 1, ran_at: hoursAgo(1) } }, { imessage: years, photos: years });
    const msg = view('imessage', { stats: s });
    assert.deepEqual(msg.warnings, ['2021 and 2025 look thin: 900 and 1,000 records against about 30,000 in a typical year.']);
    assert.deepEqual(view('photos', { stats: s }).warnings, []);
  });
});

describe('iPhone backup', () => {
  test('no backup yet: steps to make one', () => {
    const v = view('iphone_backup');
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'No backup on this Mac yet');
    assert.equal(v.steps!.length, 5);
  });

  test('backup in progress', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup({ finished: false, in_progress: true })] }) });
    assert.equal(v.section, 'working');
  });

  test('encrypted backup ready: asks for the password', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup()] }) });
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'Backup from Sep 1, 2026 is ready to read');
    assert.equal(v.actions[0].id, 'iphone-run');
    assert.equal(v.actions[0].input, 'password');
    const macRead = stats(Object.fromEntries(CATALOG.filter((x) => x.group === 'mac').map((x) => [x.produces![0], { count: 1 }])));
    assert.equal(nextUp(views({ probe: probe({ backups: [backup()] }), stats: macRead })), 'iphone_backup', 'entering a password beats starting web exports');
  });

  test('a Keychain password means no prompt', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup()], keychain_password: true }) });
    assert.equal(v.actions[0].input, undefined);
  });

  test('unencrypted backups warn about what is missing', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup({ encrypted: false })] }) });
    assert.match(v.warnings[0], /isn't encrypted/);
    assert.equal(v.actions[0].input, undefined);
  });

  test('read and current', () => {
    const s = stats({ phone_whatsapp: { count: 50 }, health: { count: 70 }, imessage: { count: 9000 } });
    const v = view('iphone_backup', { probe: probe({ backups: [backup()], mirror: { backup: '00008120-TEST', backed_up: '2026-09-01 10:00:00' } }), stats: s });
    assert.equal(v.section, 'done');
    assert.equal(v.records, 120, 'Messages from the phone count in the Messages row, not here');
    assert.equal(v.status, '120 records from 2 phone sources');
    assert.equal(v.merged, undefined);
  });

  test('what the phone added to Messages and calls counts too, and phone internals are marked', () => {
    const s = { ...stats({ phone_whatsapp: { count: 50 }, phone_filesapp: { count: 900 }, health: { count: 70 }, imessage: { count: 9005 }, calls: { count: 3 } }),
      copies: { imessage: { iphone: 9000, mac: 5 }, calls: { mac: 3 } }, device: ['phone_filesapp'] };
    const v = view('iphone_backup', { probe: probe({ backups: [backup()], mirror: { backup: '00008120-TEST', backed_up: '2026-09-01 10:00:00' } }), stats: s });
    assert.equal(v.records, 1020, 'Messages from the phone count in the Messages row, not here');
    assert.equal(v.status, '1,020 records from 3 phone sources');
    assert.deepEqual(v.merged, [{ id: 'imessage', name: 'Messages', fromPhone: 9000, onlyMac: 5 }], 'calls only on the Mac are not from the phone');
    assert.deepEqual(v.parts!.map((p) => [p.name, !!p.device]), [['phone_filesapp', true], ['health', false], ['phone_whatsapp', false]]);
  });

  test('a newer backup than the mirror', () => {
    const s = stats({ phone_whatsapp: { count: 50 } });
    const v = view('iphone_backup', { probe: probe({ backups: [backup({ date: '2026-10-09T10:00:00+00:00' })], mirror: { backup: '00008120-TEST', backed_up: '2026-09-01 10:00:00' } }), stats: s });
    assert.equal(v.section, 'needs');
    assert.match(v.status, /^A newer backup is ready/);
  });

  test('wrong password', () => {
    const st = state((s) => (s.sources.iphone_backup = { lastError: 'Wrong password: the backup\'s keys didn\'t unwrap. Nothing was written.', lastErrorAt: hoursAgo(0.01) }));
    const v = view('iphone_backup', { probe: probe({ backups: [backup()] }), state: st });
    assert.equal(v.status, 'That password didn\'t work');
    assert.equal(v.actions[0].input, 'password');
  });

  test('needs cryptography', () => {
    const p = probe({ backups: [backup()], python: { path: 'p', version: '3', cryptography: false, pypdf: true } });
    assert.equal(view('iphone_backup', { probe: p }).blockedBy, 'python_env');
  });

  test('running', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup()] }), jobs: [job({ kind: 'iphone', sourceIds: ['iphone_backup'], connectors: ['iphone'] })] });
    assert.equal(v.section, 'working');
    assert.match(v.status, /^Decrypting and reading…/);
  });

  test('latestBackup and mirrorIsCurrent', () => {
    const p = probe({ backups: [backup({ id: 'a', date: '2026-01-01T00:00:00+00:00' }), backup({ id: 'b', date: '2026-02-01T00:00:00+00:00' }), backup({ id: 'c', date: '2026-03-01T00:00:00+00:00', finished: false })] });
    assert.equal(latestBackup(p)!.id, 'b');
    const b = backup();
    assert.ok(mirrorIsCurrent(probe({ mirror: { backup: b.id, backed_up: '2026-09-01 10:00:00' } }), b));
    assert.ok(mirrorIsCurrent(probe({ mirror: { backup: b.id, backed_up: '2026-09-01T10:00:00Z' } }), b));
    assert.ok(!mirrorIsCurrent(probe({ mirror: { backup: 'other', backed_up: '2026-09-01 10:00:00' } }), b));
    assert.ok(!mirrorIsCurrent(probe({ mirror: { backup: b.id, backed_up: '2026-08-01 00:00:00' } }), b));
    assert.ok(!mirrorIsCurrent(probe(), b));
  });
});

describe('web exports', () => {
  test('not requested: open the page in your browser, or say it is already requested', () => {
    const v = view('discord');
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'Not requested yet');
    assert.deepEqual(actionIds(v), ['open', 'mark-requested', 'add-file', 'skip']);
    assert.equal(v.detail, 'Takes 4 hours to 30 days after you request it.');
  });

  test('the longest waits come first', () => {
    const order = views().filter((v) => v.group === 'web' && !v.optional).map((v) => v.id);
    assert.ok(order.indexOf('spotify') < order.indexOf('google_takeout'));
    assert.ok(order.indexOf('discord') < order.indexOf('notion'));
    assert.ok(order.indexOf('x') < order.indexOf('instagram'));
  });

  test('every export page says which privacy law to pick on a request form, and to ask for a copy, not deletion', () => {
    for (const id of ['discord', 'spotify', 'google_takeout']) assert.ok(view(id).notes!.includes(LAW_HINT), id);
    assert.ok(!view('reddit').notes!.includes(LAW_HINT), 'Reddit\'s own steps already walk through its form');
    assert.match(LAW_HINT, /never deletion/);
  });

  test('a notification that looks like the service saying it is ready: "looks ready", with its words, never certain', () => {
    const asked = (signalAt: string) => state((s) => (s.sources.spotify = { requestedAt: hoursAgo(5), readySignal: { at: signalAt, via: 'Mail', text: 'Your Spotify data is ready to download' } }));
    const v = view('spotify', { state: asked(hoursAgo(1)) });
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'Looks ready: a notification from Mail 1 h ago');
    assert.match(v.detail!, /"Your Spotify data is ready to download"/);
    assert.match(v.detail!, /check your email or Spotify to be sure/);
    assert.equal(v.actions[0].id, 'open', 'its page, to download it');
    const stale = view('spotify', { state: asked(hoursAgo(9)) });
    assert.equal(stale.section, 'working', 'a notification from before the request means nothing');
    assert.ok(stale.notes!.some((n) => /watches this Mac's notifications.*can miss one or guess wrong/.test(n)), 'and it says it is only a guess');
  });

  test('iPhone notifications on this Mac: why to turn them on, and whether they are', () => {
    const off = view('iphone_notifications', { probe: probe({ notifications: { readable: true, iphone: false } }) });
    assert.equal(off.section, 'needs');
    assert.ok(off.optional);
    assert.deepEqual(actionIds(off), ['open-notification-settings', 'mark-done']);
    assert.match(off.detail!, /Many services tell you on your iPhone/);
    assert.equal(view('iphone_notifications', { probe: probe({ notifications: { readable: true, iphone: true } }) }).section, 'done');
    const told = view('iphone_notifications', { state: state((s) => (s.sources.iphone_notifications = { doneAt: hoursAgo(1) })) });
    assert.equal(told.status, 'Turned on by you');
    assert.equal(view('iphone_notifications', { state: state((s) => (s.sources.iphone_backup = { skipped: 'No iPhone' })) }).section, 'unavailable');
  });

  test('every export page opens in your own browser, X included', () => {
    for (const id of ['x', 'discord', 'google_takeout']) assert.equal(view(id).actions[0].id, 'open', id);
  });

  test('requested: waiting, then ready, then late, then expired', () => {
    const at = (h: number) => state((s) => (s.sources.google_takeout = { requestedAt: hoursAgo(h) }));
    const waiting = view('google_takeout', { state: at(1) });
    assert.equal(waiting.section, 'working');
    assert.equal(waiting.status, 'Requested 1 h ago. Usually ready in 8 hours to 2 days.');
    const ready = view('google_takeout', { state: at(10) });
    assert.equal(ready.section, 'needs');
    assert.equal(ready.status, 'Requested 10 h ago. It should be ready.');
    assert.equal(ready.actions[0].id, 'open-download');
    assert.ok(ready.notes!.includes('The download link stays valid for 7 days.'));
    const late = view('google_takeout', { state: at(60) });
    assert.match(late.status, /taking longer than usual/);
    const expired = view('google_takeout', { state: at(48 + 24 * 8) });
    assert.match(expired.status, /probably expired/);
    assert.ok(actionIds(expired).includes('unrequest'));
  });

  test('ready exports outrank exports not started yet', () => {
    const vs = views({ state: state((s) => (s.sources.instagram = { requestedAt: hoursAgo(2) })) });
    const ig = vs.find((v) => v.id === 'instagram')!;
    const spotify = vs.find((v) => v.id === 'spotify')!;
    assert.ok(ig.priority < spotify.priority);
  });

  test('a file found in Downloads', () => {
    const st = state((s) => s.found.push({ path: '/d/package.zip', name: 'package.zip', kind: 'discord', valid: true, size: 6e6, foundAt: hoursAgo(0), sourceId: 'discord' }));
    const v = view('discord', { state: st });
    assert.equal(v.section, 'needs');
    assert.equal(v.priority, 9);
    assert.equal(v.detail, 'package.zip (6.0 MB)');
    assert.deepEqual(actionIds(v), ['import-found', 'ignore-found']);
  });

  test('importing, imported, failed', () => {
    const importing = view('discord', { jobs: [job({ kind: 'import', sourceIds: ['discord'], connectors: ['imports'] })] });
    assert.equal(importing.section, 'working');
    assert.match(importing.status, /^Importing…/);
    const s = stats({ discord: { count: 1234, first: '2018-05-01T00:00:00Z', last: hoursAgo(3), ran_at: hoursAgo(1) } });
    const done = view('discord', { stats: s, state: state((x) => (x.sources.discord = { requestedAt: hoursAgo(30) })) });
    assert.equal(done.section, 'done');
    assert.equal(done.status, '1,234 records, 2018 to now');
    assert.ok(done.notes!.some((n) => n.includes('only your own messages')));
    const err = view('discord', { stats: s, state: state((x) => (x.sources.discord = { lastError: 'BadZipFile', lastErrorAt: hoursAgo(0.5) })) });
    assert.equal(err.section, 'needs');
    assert.equal(err.status, 'The import failed');
  });

  test('an import finishing in the same second as the request counts as done', () => {
    // manifest times are cut to the second with +00:00; app times have milliseconds and Z
    const s = stats({ discord: { count: 3, ran_at: '2026-10-08T11:59:59+00:00' } });
    const st = state((x) => (x.sources.discord = { requestedAt: '2026-10-08T11:59:59.500Z', importedAt: '2026-10-08T11:59:59.900Z' }));
    assert.equal(view('discord', { stats: s, state: st }).section, 'done');
    const cli = state((x) => (x.sources.discord = { requestedAt: '2026-10-08T11:59:59.500Z' }));
    assert.equal(view('discord', { stats: s, state: cli }).section, 'done', 'imported from the command line within the same second');
    // An error right after a run in the same second still shows: the app clears errors itself on success.
    const err = state((x) => (x.sources.discord = { lastError: 'not a Discord export', lastErrorAt: '2026-10-08T11:59:59.800Z' }));
    assert.equal(view('discord', { stats: s, state: err }).status, 'The import failed');
    assert.equal(view('discord', { stats: stats({ discord: { count: 3, ran_at: '2026-10-08T12:00:00+00:00' } }), state: err }).section, 'done',
      'a run in a later second clears it');
  });

  test('an export that imports to nothing says so', () => {
    const st = state((x) => (x.sources.spotify = { lastFileAt: hoursAgo(0.2), importedAt: hoursAgo(0.1) }));
    const v = view('spotify', { stats: stats({ spotify: { count: 0, ran_at: hoursAgo(0.1) } }), state: st });
    assert.equal(v.section, 'needs');
    assert.equal(v.status, 'The export had nothing the app could read');
    assert.match(v.detail!, /Extended streaming history/);
    assert.equal(view('spotify', { stats: stats({ spotify: { count: 0, ran_at: hoursAgo(0.1) } }) }).status, 'Not requested yet', 'no file added: nothing to report');
  });

  test('requesting again after an import goes back to waiting', () => {
    const s = stats({ linkedin: { count: 10, ran_at: hoursAgo(48) } });
    const v = view('linkedin', { stats: s, state: state((x) => (x.sources.linkedin = { requestedAt: hoursAgo(1) })) });
    assert.equal(v.section, 'working');
  });

  test('ChatGPT can be marked as unable to export', () => {
    assert.ok(actionIds(view('chatgpt')).includes('cant-export'));
    const v = view('chatgpt', { state: state((s) => (s.sources.chatgpt = { skipped: 'My account is on a school or work workspace (only admins can export)' })) });
    assert.equal(v.section, 'unavailable');
    assert.match(v.status, /^Skipped: My account is on a school/);
  });

  test('Google Photos and Drive is optional and not done by other documents', () => {
    const v = view('google_photos_drive', { stats: stats({ imported_documents: { count: 400 } }) });
    assert.equal(v.optional, true);
    assert.equal(v.section, 'needs');
    assert.ok(v.priority >= 70);
  });
});

describe('guided sources', () => {
  test('other mail accounts come from mailbox folders and the account name', () => {
    const p = probe({ mailbox_sources: ['hotmail'] });
    const s = stats({ hotmail: { count: 4321, first: '2015-02-01T00:00:00Z', last: hoursAgo(1) }, work_mail: { count: 10 } });
    const v = view('other_mail', { probe: p, stats: s });
    assert.equal(v.section, 'done');
    assert.equal(v.records, 4321);
    const both = view('other_mail', { probe: p, stats: s, state: state((x) => (x.sources.other_mail = { accountName: 'Work Mail' })) });
    assert.equal(both.records, 4331);
    assert.equal(both.accountName, 'Work Mail');
    assert.ok(actionIds(view('other_mail')).includes('open-internet-accounts'));
  });

  test('a guided source waits for its file', () => {
    const v = view('maps_timeline');
    assert.equal(v.section, 'needs');
    assert.equal(v.actions[0].id, 'add-file');
    assert.equal(v.priority, 40);
    assert.equal(view('zoom').priority, 90);
  });

  test('settings-only steps are done when the user says so', () => {
    const v = view('messages_sync');
    assert.deepEqual(actionIds(v), ['mark-done', 'skip']);
    const done = view('messages_sync', { state: state((s) => (s.sources.messages_sync = { doneAt: hoursAgo(2) })) });
    assert.equal(done.section, 'done');
    assert.equal(done.status, 'Done 2 h ago');
  });

  test('ticked steps are remembered', () => {
    const v = view('maps_timeline', { state: state((s) => (s.sources.maps_timeline = { stepsDone: [0, 2] })) });
    assert.deepEqual(v.steps!.map((s) => s.done), [true, false, true]);
  });
});

describe('summary and next step', () => {
  test('summary counts', () => {
    const s = stats({ imessage: { count: 100 }, discord: { count: 50 }, phone_x: { count: 7 } });
    const vs = views({ stats: s });
    const sum = summarize(vs, s);
    assert.equal(sum.records, 157);
    assert.equal(sum.sourcesDone, vs.filter((v) => v.group !== 'setup' && v.section === 'done').length);
    assert.equal(sum.needsYou, vs.filter((v) => v.section === 'needs' && !v.blockedBy && !v.optional).length);
  });

  test('optional items come last; nothing left means no next step', () => {
    const vs = views().map((v) => ({ ...v, section: v.optional ? v.section : ('done' as const) }));
    const next = nextUp(vs);
    assert.ok(next && vs.find((v) => v.id === next)!.optional);
    assert.equal(nextUp(vs.map((v) => ({ ...v, section: 'done' as const }))), null);
  });
});

describe('helpers', () => {
  test('gapYears ignores partial first and last years and tiny sources', () => {
    assert.deepEqual(gapYears({ '2020': 10, '2021': 1000, '2022': 5, '2023': 1000, '2024': 900, '2025': 3 }, 2026), [{ year: '2022', n: 5, typical: 1000 }]);
    assert.deepEqual(gapYears({ '2020': 100, '2023': 100 }, 2026), [], 'two points are not a trend');
    assert.deepEqual(gapYears({ '2019': 1, '2020': 3, '2021': 0, '2022': 2, '2023': 1 }, 2026), [], 'too small to judge');
    assert.deepEqual(gapYears({ '2019': 500, '2020': 1000, '2022': 1000, '2023': 1000, '2024': 400 }, 2026).map((g) => g.year), ['2021'], 'a missing year is a gap');
    assert.deepEqual(gapYears({ '1970': 5, '2018': 1000, '2019': 20, '2020': 1000, '2021': 1000, '2030': 3 }, 2026).map((g) => g.year), ['2019'],
      'stray 1970 and future records are ignored');
    // A chat app after end-to-end encryption: thin 2025 next to an even thinner (current) 2026 is still a gap
    const messenger = { '2020': 400, '2021': 3000, '2022': 9000, '2023': 6000, '2024': 2400, '2025': 150, '2026': 50 };
    assert.deepEqual(gapYears(messenger, 2026).map((g) => g.year), ['2025']);
  });

  test('robustFirst skips stray early records', () => {
    const s = stats({}, { gmail: { '1970': 1, '2014': 5000, '2015': 6000 } });
    assert.equal(robustFirst(['gmail'], s, '1970-01-01T00:00:00Z'), '2014-01-01T00:00:00Z');
    assert.equal(robustFirst(['gmail'], s, '2014-05-01T00:00:00Z'), '2014-05-01T00:00:00Z');
    assert.equal(robustFirst(['gmail'], stats(), '1970-01-01T00:00:00Z'), '1970-01-01T00:00:00Z');
  });

  test('totals sums keys and a prefix', () => {
    const s = stats({ health: { count: 1, first: '2017-01-01T00:00:00Z', last: '2026-01-01T00:00:00Z' }, phone_a: { count: 2, first: '2015-01-01T00:00:00Z', last: '2026-05-01T00:00:00Z' }, other: { count: 99 } });
    const t = totals(['health'], 'phone_', s);
    assert.equal(t.records, 3);
    assert.equal(t.first, '2015-01-01T00:00:00Z');
    assert.equal(t.last, '2026-05-01T00:00:00Z');
    assert.deepEqual(t.parts.map((p) => p.name), ['phone_a', 'health']);
  });

  test('time moves sources along without any events', () => {
    const st = state((s) => (s.sources.notion = { requestedAt: NOW.toISOString() }));
    assert.equal(computeSources(input({ state: st })).find((v) => v.id === 'notion')!.section, 'working');
    const later = new Date(NOW.getTime() + 2 * H);
    assert.equal(computeSources(input({ state: st, now: later })).find((v) => v.id === 'notion')!.section, 'needs');
  });
});
