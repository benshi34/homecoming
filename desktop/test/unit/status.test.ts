import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { CATALOG } from '../../src/shared/catalog.ts';
import { computeSources, fdaLost, gapYears, LAW_HINT, latestBackup, mirrorIsCurrent, nextUp, otherPhoneRead, phoneDevices, READ_ONLY_OK, robustFirst, summarize, totals } from '../../src/shared/status.ts';
import type { Backup, JobView } from '../../src/shared/types.ts';
import { actionIds, H, hoursAgo, input, NOW, probe, state, stats, view, views } from './helpers.ts';
// Where it lives (its stage), and whether it needs you there.
const place = (v: { section: string; needsYou?: boolean }) => [v.section, !!v.needsYou];

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
    const needs = vs.filter((v) => v.needsYou && !v.blockedBy).map((v) => v.id);
    assert.ok(needs.includes('fda'), 'Full Disk Access holds the rest up: it needs you');
    assert.deepEqual(place(vs.find((v) => v.id === 'identity')!), ['todo', false], 'who you are is to do: nothing waits on it');
    assert.equal(vs.find((v) => v.id === 'ai_coding')!.blockedBy, undefined, 'collection never waits for identity');
    assert.ok(vs.find((v) => v.id === 'identity')!.priority > vs.find((v) => v.id === 'discord')!.priority, 'identity is a final check');
    assert.equal(vs.find((v) => v.id === 'imessage')!.blockedBy, 'fda');
  });
});

describe('setup', () => {
  test('identity', () => {
    const missing = view('identity', { probe: probe({ identity: null }) });
    assert.deepEqual(place(missing), ['todo', false]);
    assert.equal(missing.priority, 65);
    assert.equal(missing.actions[0].input, 'identity');
    const partial = view('identity', { probe: probe({ identity: { names: ['Ada'], emails: [], usernames: [], phones: [] } }) });
    assert.deepEqual(place(partial), ['todo', false], 'a name without an email is not enough');
    const ok = view('identity');
    assert.equal(ok.section, 'done');
    assert.match(ok.status, /Ada Lovelace, 1 email$/);
  });

  test('Full Disk Access', () => {
    const no = view('fda', { probe: probe({ fda: false, sources: { imessage: 'blocked', photos: 'blocked', ai_coding: 'ok' } }) });
    assert.deepEqual(place(no), ['todo', true]);
    assert.equal(no.status, 'Needed for 3 sources on this Mac', 'and the iPhone backup it can\'t see yet');
    assert.equal(view('fda', { probe: probe({ fda: false, backups: [backup()], sources: { imessage: 'blocked', photos: 'blocked', ai_coding: 'ok' } }) }).status, 'Needed for 2 sources on this Mac');
    assert.deepEqual(actionIds(no), ['open-fda-settings', 'recheck']);
    assert.equal(view('fda', { probe: probe({ fda: null }) }).section, 'unavailable');
    assert.equal(view('fda').section, 'done');
  });

  test('Full Disk Access turned off by an update says so', () => {
    const off = probe({ fda: false, sources: { imessage: 'blocked', photos: 'blocked', ai_coding: 'ok' } });
    // Seen on before (the app remembers), or Messages read before and closed now: macOS dropped it when the app was rebuilt.
    for (const inp of [{ state: state((s) => (s.fdaOnAt = hoursAgo(30))) }, { stats: stats({ imessage: { count: 12 } }) }]) {
      const v = view('fda', { probe: off, ...inp });
      assert.deepEqual(place(v), ['todo', true]);
      assert.equal(v.status, 'Turned off after the update');
      assert.match(v.detail!, /turn it off and on again in System Settings/);
      assert.deepEqual(actionIds(v), ['open-fda-settings', 'recheck']);
      assert.ok(fdaLost(off, inp.stats ?? stats(), inp.state ?? state()));
    }
    // A first run without it, or something read without it (Claude Code's transcripts): only "needed".
    assert.equal(view('fda', { probe: off, stats: stats({ ai_coding: { count: 3 } }) }).status, 'Needed for 3 sources on this Mac');
    assert.ok(!fdaLost(probe(), stats(), state((s) => (s.fdaOnAt = hoursAgo(1)))), 'on now: nothing lost');
  });

  test('Python packages', () => {
    const v = view('python_env', { probe: probe({ python: { path: '/usr/local/bin/python3', version: '3.14', cryptography: false, pypdf: false } }) });
    assert.deepEqual(place(v), ['todo', true]);
    assert.equal(v.status, 'Missing cryptography and pypdf');
    assert.match(v.detail!, /\/usr\/local\/bin\/python3 -m pip install cryptography pypdf/);
    assert.equal(view('python_env').section, 'done');
  });

  test('corpus in iCloud asks before moving anything', () => {
    const p = probe();
    p.corpus.in_icloud = true;
    const v = view('corpus_location', { probe: p });
    assert.deepEqual(place(v), ['todo', true]);
    const a = v.actions.find((x) => x.id === 'exclude-icloud')!;
    assert.match(a.confirm!, /corpus\.nosync/);
    assert.equal(view('corpus_location').section, 'done');
  });

  test('disk space', () => {
    const p = probe();
    p.corpus.free_bytes = 5e9;
    assert.deepEqual(place(view('disk_space', { probe: p })), ['todo', false], 'worth doing; nothing waits on it');
    const ok = view('disk_space', { probe: p, state: state((s) => (s.sources.disk_space = { doneAt: hoursAgo(1) })) });
    assert.equal(ok.section, 'done');
    assert.equal(ok.warnings.length, 1);
    assert.equal(view('disk_space').status, '100 GB free');
  });

  test('Claude Code retention', () => {
    const retention = (claude: object) => ({ ...probe().retention, claude: claude as never });
    assert.equal(view('retention_claude', { probe: probe({ retention: retention({ present: false }) }) }).section, 'unavailable');
    const short = view('retention_claude', { probe: probe({ retention: retention({ present: true, days: 7 }) }) });
    assert.deepEqual(place(short), ['todo', false]);
    assert.equal(short.status, 'Transcripts are deleted after 7 days');
    assert.deepEqual(actionIds(short), ['fix-claude-retention']);
    assert.equal(view('retention_claude', { probe: probe({ retention: retention({ present: true, days: null }) }) }).status, 'Transcripts are deleted after 30 days');
    assert.equal(view('retention_claude').section, 'done');
  });

  test('Terminal history retention', () => {
    const shell = (s: object | undefined) => probe({ retention: { ...probe().retention, shell: s as never } });
    const def = view('retention_shell', { probe: shell({ shell: 'zsh', savehist: 1000, extended: false }) });
    assert.deepEqual(place(def), ['todo', false]);
    assert.equal(def.status, 'Keeps only your last 1,000 commands, without times');
    assert.deepEqual(actionIds(def), ['fix-shell-retention']);
    assert.equal(view('retention_shell', { probe: shell({ shell: 'zsh', savehist: 10000, extended: true }) }).status, 'Keeps only your last 10,000 commands');
    assert.equal(view('retention_shell', { probe: shell({ shell: 'zsh', savehist: 1000000, extended: true }) }).section, 'done');
    assert.equal(view('retention_shell', { probe: shell({ shell: 'fish' }) }).section, 'unavailable');
    assert.equal(view('retention_shell', { probe: shell(undefined) }).section, 'unavailable');
  });

  test('Messages retention', () => {
    const with_ = (messages: object) => probe({ retention: { ...probe().retention, messages: messages as never } });
    assert.deepEqual(place(view('retention_messages', { probe: with_({ readable: true, value: 30 }) })), ['todo', false]);
    assert.equal(view('retention_messages', { probe: with_({ readable: true, value: null }) }).section, 'done', 'unset means the default, Forever');
    const unknown = view('retention_messages', { probe: with_({ readable: false, value: null }) });
    assert.deepEqual(place(unknown), ['todo', false]);
    assert.ok(actionIds(unknown).includes('mark-done'));
    assert.equal(view('retention_messages', { probe: with_({ readable: false, value: null }), state: state((s) => (s.sources.retention_messages = { doneAt: hoursAgo(1) })) }).section, 'done');
  });

  test('iPhone Messages retention, read from the backup', () => {
    const with_ = (m?: object, over = {}) => probe({ retention: { ...probe().retention, iphone_messages: m as never }, ...over });
    assert.equal(view('retention_iphone_messages', { probe: with_({ readable: true, value: null }) }).status, 'Forever (from your iPhone backup)');
    const short = view('retention_iphone_messages', { probe: with_({ readable: true, value: 365 }) });
    assert.deepEqual(place(short), ['todo', false]);
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
    assert.deepEqual(place(g), ['todo', false]);
    assert.deepEqual(actionIds(g), ['open-external', 'mark-done', 'skip'], 'with "I Don\'t Use Google"');
    assert.equal(view('retention_google', { state: state((s) => (s.sources.google_takeout = { skipped: 'I don\'t use it' })) }).section, 'unavailable');
    assert.equal(view('retention_maps').status, 'Timeline deletes visits older than 3 months by default');
    assert.equal(view('retention_maps', { state: state((s) => (s.sources.retention_maps = { doneAt: hoursAgo(1) })) }).section, 'done');
  });

  test('Safari retention', () => {
    const with_ = (safari: object, over = {}) => probe({ retention: { ...probe().retention, safari: safari as never }, ...over });
    const dflt = view('retention_safari', { probe: with_({ readable: true, value: null }) });
    assert.deepEqual(place(dflt), ['todo', false]);
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
    assert.deepEqual(place(v), ['todo', false]);
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

  test('Mail with no accounts: nothing to read, said so; once read, what it read stays', () => {
    const none = view('apple_mail', { probe: probe({ mail_accounts: [] }) });
    assert.equal(none.section, 'unavailable');
    assert.equal(none.status, 'No accounts in Mail');
    assert.deepEqual(actionIds(none), ['open-internet-accounts', 'recheck']);
    assert.equal(view('apple_mail', { probe: probe({ mail_accounts: ['ada@example.com'] }) }).status, 'Ready to read');
    assert.equal(view('apple_mail').status, 'Ready to read', 'accounts not looked at: read as before');
    assert.equal(view('apple_mail', { probe: probe({ mail_accounts: [] }), stats: stats({ mail: { count: 40 } }) }).section, 'done');
    const blocked = view('apple_mail', { probe: probe({ fda: false, mail_accounts: [], sources: { ...probe().sources, mail_app: 'blocked' } }) });
    assert.equal(blocked.blockedBy, 'fda', 'without Full Disk Access, that\'s what it needs');
  });

  test('errors show until a later successful run', () => {
    const err = state((s) => (s.sources.calls = { lastError: 'database is locked', lastErrorAt: hoursAgo(0.5) }));
    const failed = view('calls', { state: err, stats: stats({ calls: { count: 3, ran_at: hoursAgo(5) } }) });
    assert.deepEqual(place(failed), ['done', true], 'read before: still collected, and the failed read needs you');
    assert.equal(failed.detail, 'database is locked');
    const recovered = view('calls', { state: err, stats: stats({ calls: { count: 3, ran_at: hoursAgo(0.1) } }) });
    assert.equal(recovered.section, 'done');
  });

  test('running and queued jobs', () => {
    // One run reads the Mac's sources in turn: each says where it is, not what the run is reading right now.
    const all = job({ sourceIds: ['contacts', 'imessage', 'photos'], connectors: ['contacts', 'imessage', 'photos'], current: 'imessage', finished: ['contacts'], lastLine: '[imessage] 400k records' });
    const running = view('imessage', { jobs: [all] });
    assert.equal(running.section, 'working');
    assert.match(running.status, /^Reading… \(started/);
    assert.equal(running.detail, undefined, 'its own log line ("[imessage] 400k records") is for the Progress log, not the page');
    assert.equal(view('photos', { jobs: [all] }).status, 'Waiting its turn');
    assert.equal(view('contacts', { jobs: [all] }).status, 'Read; the others are still being read');
    const indexing = { ...all, current: 'build_index', finished: ['contacts', 'imessage', 'photos'] };
    assert.equal(view('photos', { jobs: [indexing] }).status, 'Read; making it searchable');
    for (const id of ['contacts', 'imessage', 'photos']) assert.equal(view(id, { jobs: [all] }).section, 'working');
    assert.deepEqual(['contacts', 'imessage', 'photos'].map((id) => view(id, { jobs: [all] }).stage), ['read', 'reading', 'waiting']);
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
    assert.deepEqual(place(v), ['todo', false]);
    assert.equal(v.status, 'No backup on this Mac yet');
    assert.equal(v.steps!.length, 5);
  });

  test('backup in progress', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup({ finished: false, in_progress: true })] }) });
    assert.equal(v.section, 'working');
  });

  test('encrypted backup ready: asks for the password', () => {
    const v = view('iphone_backup', { probe: probe({ backups: [backup()] }) });
    assert.deepEqual(place(v), ['todo', false]);
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
    assert.deepEqual(place(v), ['done', false]);
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

  test('several devices backed up: yours, not whichever is newest', () => {
    const phone = (id: string, udid: string, product: string, date: string, device = id) =>
      backup({ id, udid, product, device, date: `2026-${date}T00:00:00+00:00` });
    const ada = phone('ada', 'U-ADA', 'iPhone17,1', '03-01', "Ada's iPhone");
    const adaOld = phone('ada-archived', 'U-ADA', 'iPhone17,1', '01-01');
    const ipad = phone('ipad', 'U-PAD', 'iPad16,3', '05-01');
    const sam = phone('sam', 'U-SAM', 'iPhone16,2', '04-01', "Sam's iPhone");
    const all = [adaOld, ada, ipad, sam];
    assert.equal(latestBackup(probe({ backups: [ada, ipad] }))!.id, 'ada', 'an iPhone before a newer iPad');
    assert.equal(latestBackup(probe({ backups: all }))!.id, 'sam', 'nothing read yet: the newest iPhone');
    assert.equal(latestBackup(probe({ backups: all, mirror: { backup: 'ada', udid: 'U-ADA' } }))!.id, 'ada', 'the one read before, not a newer one');
    assert.equal(latestBackup(probe({ backups: all, mirror: { backup: 'ada' } }))!.id, 'ada', 'an older read, without its udid: by its folder');
    assert.equal(latestBackup(probe({ backups: all, mirror: { backup: 'ada', udid: 'U-ADA' } }), 'U-SAM')!.id, 'sam', 'picked in Your Setup');
    assert.equal(latestBackup(probe({ backups: all }), 'U-GONE')!.id, 'sam', 'a pick no longer here: as if none');
    assert.deepEqual(phoneDevices(probe({ backups: all })).map((x) => x.id), ['ipad', 'sam', 'ada'], 'each device once, by its newest backup');
    assert.deepEqual(otherPhoneRead(probe({ backups: all, mirror: { backup: 'ada', udid: 'U-ADA', device: "Ada's iPhone" } }), 'U-SAM'),
      { device: "Ada's iPhone", udid: 'U-ADA' });
    assert.equal(otherPhoneRead(probe({ backups: all, mirror: { backup: 'ada', udid: 'U-ADA' } })), null, 'still the one read');
    const v = view('iphone_backup', { probe: probe({ backups: all, mirror: { backup: 'ada', udid: 'U-ADA' } }),
      state: state((st) => (st.settings.iphoneDevice = 'U-SAM')) });
    assert.match(v.detail!, /^Sam's iPhone/);
    assert.ok(v.actions.some((a) => a.id === 'show-setup'), 'a way to pick another');
    assert.ok(!v.actions.some((a) => a.id === 'forget-phone'), 'nothing read from Ada\'s yet: nothing to take out');
    // Ada's was read (its records are in the library) and Sam's is picked: said here, with Take It Out, and reading Sam's asks first.
    const mixed = view('iphone_backup', { probe: probe({ backups: all, mirror: { backup: 'ada', udid: 'U-ADA', device: "Ada's iPhone" } }),
      stats: stats({ phone_whatsapp: { count: 120 } }), state: state((st) => (st.settings.iphoneDevice = 'U-SAM')) });
    assert.ok(mixed.notes?.some((n) => /^What was read from Ada's iPhone is still in your library\. If it isn't yours, take it out before reading this one\./.test(n)), String(mixed.notes));
    assert.deepEqual(mixed.actions.map((a) => a.id), ['forget-phone', 'iphone-run', 'show-setup', 'skip']);
    assert.match(mixed.actions[0].confirm ?? '', /^Take out what was read from Ada's iPhone\?/);
    assert.match(mixed.actions[1].confirm ?? '', /stays in your library, mixed in with Sam's iPhone's: once it's read, it can't be taken out by itself/);
  });
});

describe('web exports', () => {
  test('not requested: Claude does it for you, or open the page in your browser, or say it is already requested', () => {
    const v = view('discord');
    assert.deepEqual(place(v), ['todo', false]);
    assert.equal(v.status, 'Not requested yet');
    assert.deepEqual(actionIds(v), ['agent-request', 'open', 'mark-requested', 'add-file', 'skip']);
    assert.deepEqual(v.actions.filter((a) => a.primary).map((a) => a.id), ['agent-request']);
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
    for (const id of ['other_mail', 'maps_timeline']) assert.ok(!view(id).notes!.includes(LAW_HINT), `${id}: set up by hand, no request form`);
    assert.match(LAW_HINT, /never deletion/);
  });

  test('the link\'s days count from its ready email: Instagram\'s 4 days are up on day 5, not day 6', () => {
    const at = (requested: number, ready: number) => view('instagram', { state: state((s) => (s.sources.instagram = { requestedAt: hoursAgo(requested),
      readySignal: { at: hoursAgo(ready), via: 'Mail', sender: 'Instagram', text: 'Your information is ready' } })) });
    assert.equal(at(4 * 24, 4 * 24 - 2).onTheWay, 'ready', 'ready 2 hours after asking, 4 days ago less 2 hours: still good');
    const gone = at(5 * 24, 5 * 24 - 2);
    assert.deepEqual([gone.onTheWay, gone.status.endsWith('The link has probably expired.')], ['expired', true], 'ready 5 days ago: gone, though asked only 5 days ago');
    // Without a ready email, it's counted from the longest usual wait (2 days), then its 4 days.
    const quiet = (h: number) => view('instagram', { state: state((s) => (s.sources.instagram = { requestedAt: hoursAgo(h) })) }).onTheWay;
    assert.equal(quiet(5 * 24), 'late');
    assert.equal(quiet(6 * 24 + 1), 'expired');
  });

  test('a notification that looks like the service saying it is ready: "looks ready", with its words, never certain', () => {
    const asked = (signalAt: string) => state((s) => (s.sources.spotify = { requestedAt: hoursAgo(5), readySignal: { at: signalAt, via: 'Mail', text: 'Your Spotify data is ready to download' } }));
    const v = view('spotify', { state: asked(hoursAgo(1)) });
    assert.deepEqual(place(v), ['working', true]);
    assert.equal(v.status, 'Looks ready: a notification from Mail 1 h ago');
    assert.match(v.detail!, /"Your Spotify data is ready to download"/);
    assert.match(v.detail!, /check your email or Spotify to be sure/);
    assert.deepEqual(actionIds(v).slice(0, 2), ['agent-download', 'open-ready'], 'Claude downloads it, or its page');
    const stale = view('spotify', { state: asked(hoursAgo(9)) });
    assert.equal(stale.section, 'working', 'a notification from before the request means nothing');
    assert.ok(stale.notes!.some((n) => /watches Apple Mail and this Mac's notifications.*can miss one/.test(n)), 'and it says it can miss one');
    // An email from the service itself is surer: "Ready", and its link.
    const mailed = view('spotify', { state: state((s) => (s.sources.spotify = { requestedAt: hoursAgo(5),
      readySignal: { at: hoursAgo(1), via: 'Mail', sender: 'Spotify', text: 'Your Spotify data is ready to download', link: 'https://www.spotify.com/account/privacy/download' } })) });
    assert.equal(mailed.status, 'Ready: Spotify emailed you 1 h ago');
    assert.equal(mailed.actions.find((a) => a.id === 'open-ready')?.label, 'Open the Download Link');
  });

  test('iPhone notifications on this Mac: why to turn them on, and whether they are', () => {
    const off = view('iphone_notifications', { probe: probe({ notifications: { readable: true, iphone: false } }) });
    assert.deepEqual(place(off), ['todo', false], 'optional: to do, without needing you');
    assert.ok(off.optional);
    assert.deepEqual(actionIds(off), ['open-notification-settings', 'mark-done', 'skip']);
    assert.match(off.detail!, /Many services tell you on your iPhone/);
    assert.equal(view('iphone_notifications', { probe: probe({ notifications: { readable: true, iphone: true } }) }).section, 'done');
    const told = view('iphone_notifications', { state: state((s) => (s.sources.iphone_notifications = { doneAt: hoursAgo(1) })) });
    assert.equal(told.status, 'Turned on by you');
    assert.equal(view('iphone_notifications', { state: state((s) => (s.sources.iphone_backup = { skipped: 'No iPhone' })) }).section, 'unavailable');
    assert.notEqual(view('iphone_notifications', { state: state((s) => (s.sources.iphone_backup = { skipped: 'Not now' })) }).section, 'unavailable',
      'a backup set aside for later still has an iPhone');
  });

  test('every export page opens in your own browser, X included, and Claude can do it for you', () => {
    for (const id of ['x', 'discord', 'google_takeout']) assert.deepEqual(actionIds(view(id)).slice(0, 2), ['agent-request', 'open'], id);
  });

  test('with AI turned off, nothing offers to do it for you', () => {
    const off = (more: object = {}) => view('instagram', { state: state((s) => { s.settings.aiOn = false; s.sources.instagram = more as never; }) });
    assert.ok(!actionIds(off()).some((a) => a.startsWith('agent-')), 'no Do It for Me');
    assert.equal(off().actions.find((a) => a.primary)?.id, 'open', 'opening the page yourself comes first');
    assert.ok(!actionIds(off({ requestedAt: hoursAgo(30) })).some((a) => a.startsWith('agent-')), 'and no Download It for Me');
    assert.ok(view('instagram').actions.find((a) => a.id === 'agent-request')?.ai, 'with it on (or not decided yet), it carries the AI mark');
  });

  test('Do It for Me: working in Chrome, then needs you, could not finish, or downloading', () => {
    const with_ = (agent: object, more: object = {}) => view('instagram', { state: state((s) => (s.sources.instagram = { agent, ...more } as never)) });
    const working = with_({ mode: 'request', status: 'running', at: hoursAgo(0), step: 'Opening Instagram\'s export page' });
    assert.deepEqual([working.section, working.status, actionIds(working)], ['working', 'Opening Instagram\'s export page', ['agent-stop']]);
    const needs = with_({ mode: 'request', status: 'needs_you', at: hoursAgo(0), note: 'Sign in to Instagram in Chrome.', session: 's1' });
    assert.deepEqual([needs.section, needs.status, actionIds(needs)], ['working', 'Needs you: Sign in to Instagram in Chrome.', ['agent-continue', 'open-chrome', 'agent-dismiss']]);
    assert.equal(needs.needsYou, true, 'still in progress, and it needs you');
    assert.equal(needs.actions[0].input, 'reply', 'its answer box goes with Continue');
    assert.ok(needs.steps?.length, 'the steps stay, to do it yourself');
    const failed = with_({ mode: 'request', status: 'failed', at: hoursAgo(0), note: 'The page never loaded.' });
    assert.equal(failed.status, 'Claude couldn\'t finish: The page never loaded.');
    assert.equal(failed.actions[0].id, 'agent-request');
    assert.ok(failed.steps?.length, 'and here too');
    assert.equal(with_({ mode: 'request', status: 'failed', at: hoursAgo(3) }, { requestedAt: hoursAgo(1) }).status.startsWith('Requested'), true, 'requested since: that wins');
    assert.equal(with_({ mode: 'request', status: 'needs_you', at: hoursAgo(60) }).status, 'Not requested yet', 'after two days it is old news');
    const down = with_({ mode: 'download', status: 'downloading', at: hoursAgo(0) }, { requestedAt: hoursAgo(20) });
    assert.deepEqual([down.section, down.status], ['working', 'Downloading in Chrome']);
  });

  test('Do It for Me needs Claude Code: without it, nothing offers to start Claude, and a run that failed for it says how to set it up', () => {
    const none = (more: object = {}) => view('instagram', { claudeCode: false, state: state((s) => (s.sources.instagram = more as never)) });
    assert.ok(!actionIds(none()).some((a) => ['agent-request', 'agent-download', 'agent-continue'].includes(a)), 'no Do It for Me');
    assert.equal(none().actions.find((a) => a.primary)?.id, 'open', 'opening the page yourself comes first');
    assert.ok(!actionIds(none({ requestedAt: hoursAgo(30) })).some((a) => a.startsWith('agent-')), 'no Look for It either');
    const failed = none({ agent: { mode: 'request', status: 'failed', at: hoursAgo(0), note: 'Claude Code isn\'t on this Mac.', reason: 'no-claude' } });
    assert.equal(failed.status, 'Do It for Me needs Claude Code');
    assert.ok(actionIds(failed).includes('get-claude-code'));
    assert.ok(!failed.actions.some((a) => a.label === 'Try Again'), 'not Try Again, which can only fail');
    assert.ok(failed.steps?.length);
    assert.ok(actionIds(view('instagram')).includes('agent-request'), 'with it there (or not known), Do It for Me is offered');
  });

  test('Claude Code there but it can\'t run (signed out, say): the page says what\'s missing, and AI Settings fixes it', () => {
    const why = 'Claude Code isn\'t signed in. Sign in with your claude.ai account (Pro, Max, Team or Enterprise).';
    const v = view('instagram', { claudeCode: false, agentWhy: { why, fix: 'sign-in' }, state: state((s) => (s.sources.instagram = {
      agent: { mode: 'request', status: 'failed', at: hoursAgo(0), note: 'Not signed in.', reason: 'no-claude' } } as never)) });
    assert.equal(v.status, 'Do It for Me can\'t run yet');
    assert.match(v.detail!, /isn't signed in[\s\S]*Or do it yourself/);
    assert.ok(actionIds(v).includes('show-ai'), 'Open AI Settings');
    assert.ok(!actionIds(v).includes('get-claude-code'), 'not "get Claude Code": it\'s there');
  });

  test('the AI picked can\'t do it yet (Codex): Do It for Me is still there, to say so, after opening the page yourself', () => {
    const agentWhy = { ok: false, fix: 'provider' as const, soon: true, why: 'Do It for Me doesn\'t work with Codex (your ChatGPT account) yet: it\'s coming soon.' };
    const v = view('instagram', { claudeCode: false, agentWhy });
    assert.equal(v.actions.find((a) => a.primary)?.id, 'open', 'the page yourself first');
    assert.ok(actionIds(v).includes('agent-request'), 'pressed, it says it\'s coming');
    assert.ok(!actionIds(view('instagram', { claudeCode: false })).includes('agent-request'), 'without Claude Code, as before: none');
  });

  test('Do It for Me said no to: still offered, but opening the page yourself comes first', () => {
    const v = view('instagram', { state: state((s) => Object.assign(s.settings, { aiOn: true, agentExports: false })) });
    assert.equal(v.actions.find((a) => a.primary)?.id, 'open');
    assert.ok(actionIds(v).includes('agent-request'), 'Do It for Me is still there, to turn on');
    assert.equal(view('instagram').actions.find((a) => a.primary)?.id, 'agent-request', 'not decided: Do It for Me first');
  });

  test('Do It for Me turned off sets aside what Claude was doing, as AI off does', () => {
    const v = view('instagram', { state: state((s) => {
      Object.assign(s.settings, { aiOn: true, agentExports: false });
      s.sources.instagram = { agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0), note: 'Sign in.', session: 's' } };
    }) });
    assert.equal(v.status, 'Not requested yet');
    assert.ok(actionIds(v).includes('agent-request'), 'asking again goes through its sheet');
  });

  test('waiting its turn: named after the one Claude is doing, with a clock rather than a busy bar', () => {
    const vs = views({ state: state((s) => {
      s.sources.facebook = { agent: { mode: 'request', status: 'running', at: hoursAgo(0), step: 'Choosing JSON' } };
      s.sources.discord = { agent: { mode: 'request', status: 'queued', at: hoursAgo(0) } };
    }) });
    const d = vs.find((v) => v.id === 'discord')!;
    assert.equal(d.status, 'Waiting: Claude is doing Facebook and Messenger first');
    assert.equal(d.waiting, true);
    assert.equal(vs.find((v) => v.id === 'facebook')!.waiting, undefined);
  });

  test('several at once (AI Settings): each running says what it\'s doing, and one waiting names them all', () => {
    const vs = views({ state: state((s) => {
      s.sources.instagram = { agent: { mode: 'request', status: 'running', at: hoursAgo(0), step: 'Choosing JSON' } };
      s.sources.spotify = { agent: { mode: 'request', status: 'running', at: hoursAgo(0), step: 'Opening Spotify\'s privacy page' } };
      s.sources.discord = { agent: { mode: 'download', status: 'running', at: hoursAgo(0) } };
      s.sources.reddit = { agent: { mode: 'request', status: 'queued', at: hoursAgo(0) } };
    }) });
    const at = (id: string) => vs.find((v) => v.id === id)!;
    assert.equal(at('instagram').status, 'Choosing JSON');
    assert.equal(at('spotify').status, 'Opening Spotify\'s privacy page');
    assert.equal(at('discord').status, 'Downloading it in Chrome…');
    assert.ok(['instagram', 'spotify', 'discord'].every((id) => at(id).section === 'working' && !at(id).waiting));
    assert.equal(at('reddit').status, 'Waiting: Claude is doing Instagram, Spotify and Discord first');
    assert.equal(at('reddit').waiting, true);
  });

  test('after Homecoming quit mid-run: carry on or start over, with nothing to answer', () => {
    const quit = (session?: string) => view('instagram', { state: state((s) => (s.sources.instagram = {
      agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0), note: 'Homecoming quit before it finished.', reason: 'quit', session } })) });
    const v = quit('s1');
    assert.equal(v.status, 'Interrupted when Homecoming quit');
    assert.deepEqual(v.actions.map((a) => [a.id, a.label]), [['agent-continue', 'Carry On'], ['agent-request', 'Start Over'], ['agent-dismiss', 'I\'ll Do It Myself']]);
    assert.ok(!v.actions.some((a) => a.input === 'reply'), 'no answer box');
    assert.deepEqual(actionIds(quit()), ['agent-request', 'agent-dismiss'], 'never started: start it');
  });

  test('the Claude in Chrome extension not connected: open Chrome or try again, with nothing to answer', () => {
    const v = view('instagram', { state: state((s) => (s.sources.instagram = {
      agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0), note: 'Turn on the Claude in Chrome extension.', reason: 'chrome', session: 's1' } })) });
    assert.equal(v.status, 'Needs you: turn on Claude in Chrome');
    assert.deepEqual(actionIds(v), ['open-chrome', 'agent-request', 'agent-dismiss']);
    assert.equal(v.actions[0].primary, true);
    assert.ok(!v.actions.some((a) => a.input === 'reply'));
  });

  test('stopped, or taken over, while requesting: not requested yet, and what to do if Claude had asked already', () => {
    const at = (status: string) => view('instagram', { state: state((s) => (s.sources.instagram = { agent: { mode: 'request', status, at: hoursAgo(0.1) } as never })) });
    assert.equal(at('stopped').status, 'Not requested yet');
    assert.match(at('stopped').detail!, /^You stopped Claude 6 min ago\. If it had already asked Instagram for your data, choose I've Requested It\./);
    assert.match(at('dismissed').detail!, /^Doing it yourself: follow the steps below, then choose I've Requested It\./);
  });

  test('Do It for Me in another browser (Your Setup): its states and buttons name that one', () => {
    const v = view('instagram', { browser: 'Arc', state: state((s) => (s.sources.instagram = {
      agent: { mode: 'request', status: 'needs_you', at: hoursAgo(0), note: 'Turn on the Claude in Chrome extension.', reason: 'chrome', session: 's1' } })) });
    assert.equal(v.status, 'Needs you: turn on Claude in Arc');
    assert.match(v.detail!, /^Claude works in your Arc through the Claude in Chrome extension/);
    assert.equal(v.actions[0].label, 'Open Arc');
    const down = view('instagram', { browser: 'Brave', state: state((s) => (s.sources.instagram = { requestedAt: hoursAgo(30), agent: { mode: 'download', status: 'downloading', at: hoursAgo(1) } })) });
    assert.equal(down.status, 'Nothing arrived from Brave');
  });

  test('a download that never arrived says so, instead of quietly going back to waiting', () => {
    const v = view('instagram', { state: state((s) => (s.sources.instagram = { requestedAt: hoursAgo(30), agent: { mode: 'download', status: 'downloading', at: hoursAgo(1) } })) });
    assert.deepEqual(place(v), ['working', true]);
    assert.equal(v.status, 'Nothing arrived from Chrome');
    assert.match(v.detail!, /Look in Chrome's downloads/);
    assert.equal(v.actions[0].id, 'agent-download');
  });

  test('Claude\'s checks: Stop Checking while they\'re on, a quiet note when one didn\'t finish, and asking again turns them back on', () => {
    const on = (src: object, id = 'discord') => state((s) => {
      Object.assign(s.settings, { aiOn: true, agentExports: true, agentDownloads: true });
      s.ask.retention['claude-code'] = hoursAgo(1); // Anthropic's data settings checked
      s.sources[id] = src as never;
    });
    const waiting = view('discord', { state: on({ requestedAt: hoursAgo(30) }) });
    assert.ok(actionIds(waiting).includes('agent-no-checks'));
    const failed = view('discord', { state: on({ requestedAt: hoursAgo(30), agent: { mode: 'download', status: 'failed', at: hoursAgo(0.1), note: 'Gmail wouldn\'t load.', auto: 'check' } }) });
    assert.match(failed.status, /^Requested 30 h ago/, 'a look it made by itself is no news');
    assert.ok(failed.notes!.some((n) => /^Claude looked for it 6 min ago, but couldn't finish: Gmail wouldn't load\. It looks again every few hours\./.test(n)), failed.notes!.join('\n'));
    const mine = view('discord', { state: on({ requestedAt: hoursAgo(30), agent: { mode: 'download', status: 'failed', at: hoursAgo(0.1), note: 'Gmail wouldn\'t load.' } }) });
    assert.equal(mine.status, 'Claude couldn\'t finish: Gmail wouldn\'t load.', 'one you asked for is');
    const stopped = view('discord', { state: on({ requestedAt: hoursAgo(30), noChecks: hoursAgo(1) }) });
    assert.ok(!actionIds(stopped).includes('agent-no-checks'));
    assert.ok(stopped.notes!.some((n) => /you chose Stop Checking\. Look for It turns that back on/.test(n)));
    const off = view('discord', { state: state((s) => {
      Object.assign(s.settings, { aiOn: true, agentExports: true, agentDownloads: true, agentChecks: false });
      s.sources.discord = { requestedAt: hoursAgo(30) };
    }) });
    assert.ok(!actionIds(off).includes('agent-no-checks'), 'checks turned off in Settings: nothing to stop');
    // Claude doesn't look, so nothing says it does, and an export that should be ready needs you: the data settings never
    // checked, a site Claude can't work on, or nowhere it may look (every inbox off, for one that only emails its link).
    const due = { requestedAt: hoursAgo(24 * 20) };
    const unchecked = view('discord', { state: state((s) => {
      Object.assign(s.settings, { aiOn: true, agentExports: true, agentDownloads: true });
      s.sources.discord = due;
    }) });
    const blocked = view('reddit', { state: on(due, 'reddit') });
    const inboxOn = view('discord', { mail: { emails: ['ada@example.com'], appleMail: false }, state: on(due) });
    const allOff = view('discord', { mail: { emails: ['ada@example.com'], appleMail: false }, state: state((s) => {
      Object.assign(s.settings, { aiOn: true, agentExports: true, agentDownloads: true, inboxesOff: ['ada@example.com'] });
      s.ask.retention['claude-code'] = hoursAgo(1);
      s.sources.discord = due;
    }) });
    for (const [name, x] of [['data settings never checked', unchecked], ['Reddit', blocked], ['every inbox off', allOff]] as const) {
      assert.ok(!actionIds(x).includes('agent-no-checks'), `${name}: no Stop Checking`);
      assert.equal(x.needsYou, true, `${name}: it needs you`);
    }
    assert.ok(actionIds(inboxOn).includes('agent-no-checks'), 'an inbox on: Claude looks');
    // Six looks for this request, and it stops looking by itself: said, and it needs you.
    const r = hoursAgo(24 * 20);
    const tired = view('discord', { state: on({ requestedAt: r, looks: { since: r, n: 6 } }) });
    assert.ok(!actionIds(tired).includes('agent-no-checks'));
    assert.equal(tired.needsYou, true);
    assert.ok(tired.notes!.some((n) => /^Claude looked for it 6 times and didn't find it, so it stopped looking by itself\. Look for It asks it again\./.test(n)));
    assert.ok(actionIds(view('discord', { state: on({ requestedAt: r, looks: { since: hoursAgo(24 * 40), n: 6 } }) })).includes('agent-no-checks'), 'counted for an older request: not this one');
  });

  test('with Watch Downloads off, no page promises to pick the file up from Downloads', () => {
    const st = state((s) => {
      s.settings.watchDownloads = false;
      s.sources.google_takeout = { requestedAt: hoursAgo(10) };
    });
    assert.match(view('google_takeout', { state: st }).detail!, /download it, then add it here \(Watch Downloads is off in Settings\)/);
    const tl = view('maps_timeline', { state: state((s) => (s.settings.watchDownloads = false)) });
    assert.ok(!tl.steps!.some((x) => /picks it up from Downloads/.test(x.text)), tl.steps!.map((x) => x.text).join('\n'));
    assert.ok(view('maps_timeline').steps!.some((x) => /picks it up from Downloads/.test(x.text)), 'on, it does');
  });

  test('once it\'s ready, the page stops saying what it watches for', () => {
    const v = view('spotify', { state: state((s) => (s.sources.spotify = { requestedAt: hoursAgo(5), readySignal: { at: hoursAgo(1), via: 'Mail', sender: 'Spotify', text: 'Your data is ready' } })) });
    assert.ok(!v.notes!.some((n) => /While you wait/.test(n)));
  });

  test('read-only mode allows looking and opening pages, nothing that changes what is kept', () => {
    for (const id of ['open', 'open-ready', 'open-download', 'recheck', 'open-chrome', 'get-claude-code']) assert.ok(READ_ONLY_OK.has(id), id);
    for (const id of ['mark-requested', 'unrequest', 'skip', 'toggle-step', 'agent-request', 'agent-dismiss', 'ignore-found', 'import-found', 'add-file', 'run']) assert.ok(!READ_ONLY_OK.has(id), id);
  });

  test('requested: waiting, then ready, then late, then expired', () => {
    const at = (h: number) => state((s) => (s.sources.google_takeout = { requestedAt: hoursAgo(h) }));
    const waiting = view('google_takeout', { state: at(1) });
    assert.equal(waiting.section, 'working');
    assert.equal(waiting.status, 'Requested 1 h ago. Usually ready in 8 hours to 2 days.');
    assert.equal(waiting.waiting, true, 'waiting on the service: its clock shows, not a progress bar');
    const ready = view('google_takeout', { state: at(10) });
    assert.deepEqual(place(ready), ['working', true], 'still in progress; looking for it is yours (Claude doesn\'t check)');
    assert.equal(ready.waiting, undefined);
    assert.equal(ready.status, 'Requested 10 h ago. It should be ready.');
    assert.equal(ready.actions[0].id, 'open-download');
    assert.ok(ready.notes!.includes('The download link stays valid for 7 days.'));
    const late = view('google_takeout', { state: at(60) });
    assert.match(late.status, /taking longer than usual/);
    const expired = view('google_takeout', { state: at(48 + 24 * 8) });
    assert.match(expired.status, /probably expired/);
    assert.deepEqual(actionIds(expired), ['open', 'mark-requested', 'add-file'], 'ask again, then say so: no button that only resets');
    assert.equal(expired.actions[1].label, 'I\'ve Requested a New One');
    assert.equal(expired.onTheWay, 'expired');
    assert.equal(late.onTheWay, 'late');
    assert.equal(ready.onTheWay, 'due');
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
    assert.deepEqual(place(v), ['working', true]);
    assert.equal(v.priority, 4.5, 'a file waiting in Downloads comes before settings to change');
    assert.match(v.detail!, /^package\.zip \(6\.0 MB\)\n/);
    assert.match(v.detail!, /You hadn't asked Discord for your data in the app, so it waits for a yes\. Importing moves it out of Downloads/, 'why it asks');
    assert.deepEqual(actionIds(v), ['import-found', 'ignore-found']);
  });

  test('macOS won\'t let it look in Downloads: export pages say so, and how to fix it', () => {
    const v = view('discord', { probe: probe({ downloads: 'blocked' }) });
    assert.ok(v.warnings.some((w) => /can't look in your Downloads folder/.test(w)));
    assert.deepEqual(view('discord').warnings, [], 'readable: nothing to say');
    assert.deepEqual(view('imessage', { probe: probe({ downloads: 'blocked' }) }).warnings, [], 'only where an export lands there');
  });

  test('a new download for a source already collected: it stays in Collected, and importing it adds what\'s new', () => {
    const st = state((s) => s.found.push({ path: '/d/package.zip', name: 'package.zip', kind: 'discord', valid: true, size: 6e6, foundAt: hoursAgo(0), sourceId: 'discord' }));
    const v = view('discord', { state: st, stats: stats({ discord: { count: 40 } }) });
    assert.deepEqual([v.section, v.needsYou, v.status], ['done', true, 'Found the export in Downloads']);
    assert.match(v.detail!, /Discord is in your library already\. Importing it adds what's new/);
    assert.deepEqual(actionIds(v), ['import-found', 'ignore-found']);
  });

  test('a download for a source you skipped is offered too, and importing it includes the source again', () => {
    const st = state((s) => {
      s.sources.discord = { skipped: 'Not now' };
      s.found.push({ path: '/d/package.zip', name: 'package.zip', kind: 'discord', valid: true, size: 6e6, foundAt: hoursAgo(0), sourceId: 'discord' });
    });
    const v = view('discord', { state: st });
    assert.deepEqual([v.section, v.status, actionIds(v)], ['working', 'Found the export in Downloads', ['import-found', 'ignore-found']]);
    assert.match(v.detail!, /You skipped Discord\. Importing it includes Discord again/);
    assert.equal(view('discord', { state: state((s) => (s.sources.discord = { skipped: 'I don\'t use it' })) }).section, 'unavailable', 'nothing found: still skipped');
    assert.equal(view('discord', { state: state((s) => (s.sources.discord = { skipped: 'Not now' })) }).status, 'Set aside for now', 'or set aside for now');
  });

  test('an ignored download is not offered again, but the page can show it', () => {
    const st = state((s) => s.found.push({ path: '/d/package.zip', name: 'package.zip', kind: 'discord', valid: true, size: 6e6, foundAt: hoursAgo(1),
      sourceId: 'discord', ignoredAt: hoursAgo(0) }));
    const v = view('discord', { state: st });
    assert.equal(v.status, 'Not requested yet');
    assert.deepEqual(v.ignored, ['package.zip']);
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
    assert.deepEqual(place(err), ['done', true], 'imported before: still collected, and the failed import needs you');
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
    assert.deepEqual(place(v), ['working', true]);
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
    assert.deepEqual(place(v), ['todo', false]);
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
    assert.deepEqual(place(v), ['todo', false]);
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
    assert.equal(sum.needsYou, vs.filter((v) => v.needsYou && !v.blockedBy && !v.optional).length);
  });

  test('optional items come last; nothing left means no next step', () => {
    const vs = views().map((v) => (v.optional ? v : { ...v, section: 'done' as const, needsYou: false }));
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
    assert.equal(computeSources(input({ state: st, now: later })).find((v) => v.id === 'notion')!.section, 'working', 'still in progress');
  });
});

describe('ways back and plain next steps (the UX audit)', () => {
  test('a check you made by hand can be undone, and one that isn\'t for you can be set aside and brought back', () => {
    const checked = view('retention_google', { state: state((s) => (s.sources.retention_google = { doneAt: hoursAgo(1) })) });
    assert.equal(checked.status, 'Checked by you');
    assert.deepEqual(actionIds(checked), ['unmark-done']);
    assert.equal(view('retention_google').actions.find((a) => a.id === 'skip')?.label, 'I Don\'t Use Google');
    const notMine = view('retention_google', { state: state((s) => (s.sources.retention_google = { skipped: 'Not using it' })) });
    assert.equal(notMine.section, 'unavailable');
    assert.equal(notMine.status, 'Not using Google');
    assert.deepEqual(actionIds(notMine), ['unskip']);
    assert.ok(view('retention_google').notes!.some((n) => /gone for good/.test(n)), 'says why it matters');
  });

  test('changing a settings file asks first, and says what it changes', () => {
    const retention = (claude: object) => ({ ...probe().retention, claude: claude as never });
    const fix = view('retention_claude', { probe: probe({ retention: retention({ present: true, days: 7 }) }) }).actions[0];
    assert.match(fix.confirm ?? '', /cleanupPeriodDays in ~\/\.claude\/settings\.json/);
    assert.equal(view('retention_claude', { probe: probe({ retention: retention({ present: true, days: 100000 }) }) }).status, 'Kept forever');
  });

  test('waiting on Full Disk Access: the way to turn it on is right there', () => {
    const p = probe({ fda: false, sources: { ...probe().sources, imessage: 'blocked' } });
    const msgs = view('imessage', { probe: p });
    assert.deepEqual(actionIds(msgs), ['open-fda-settings', 'recheck']);
    const safari = view('retention_safari', { probe: probe({ fda: false, retention: { ...probe().retention, safari: { readable: false, value: null } as never } }) });
    assert.deepEqual(actionIds(safari), ['open-fda-settings', 'mark-done'], 'or check it by hand, then Done');
    const phone = view('iphone_backup', { probe: probe({ fda: false, backups: [] }) });
    assert.deepEqual(actionIds(phone), ['open-fda-settings', 'recheck'], 'not Open Finder');
  });

  test('"Not now" sets it aside in To Do, not away with the skipped ones', () => {
    for (const id of ['discord', 'photos']) {
      const v = view(id, { state: state((s) => (s.sources[id] = { skipped: 'Not now' })) });
      assert.deepEqual(place(v), ['todo', false], id);
      assert.equal(v.optional, true);
      assert.equal(v.deferred, true);
      assert.equal(v.status, 'Set aside for now');
      assert.deepEqual(actionIds(v), ['unskip']);
    }
    assert.equal(view('discord', { state: state((s) => (s.sources.discord = { skipped: 'I don\'t use it' })) }).section, 'unavailable');
  });

  test('a download that couldn\'t be used asks for the download again, not to run the import again', () => {
    const bad = view('discord', { state: state((s) => (s.sources.discord = { lastError: 'package.zip looks incomplete or damaged, so it wasn\'t added. Download it again.', lastErrorAt: hoursAgo(0.1), lastErrorKind: 'file' })) });
    assert.equal(bad.status, 'That download couldn\'t be used');
    assert.equal(bad.actions[0].id, 'add-file');
    assert.ok(bad.actions[0].primary);
    assert.ok(!actionIds(bad).includes('reimport'));
    const failed = view('discord', { state: state((s) => (s.sources.discord = { lastError: 'The importer couldn\'t read this export', lastErrorAt: hoursAgo(0.1) })) });
    assert.equal(failed.status, 'The import failed');
    assert.equal(failed.actions[0].id, 'reimport');
  });

  test('the privacy-law note is for asking: not once it\'s asked for or in', () => {
    const asked = view('discord', { state: state((s) => (s.sources.discord = { requestedAt: hoursAgo(1) })) });
    assert.ok(!asked.notes!.includes(LAW_HINT));
  });

  test('what waits on you outranks settings to change', () => {
    const retention = (claude: object) => ({ ...probe().retention, claude: claude as never });
    const p = probe({ retention: retention({ present: true, days: 7 }) });
    const ready = view('instagram', { probe: p, state: state((s) => (s.sources.instagram = { requestedAt: hoursAgo(30), readySignal: { at: hoursAgo(1), via: 'Mail', text: 'Your information is ready', sender: 'Instagram' } })) });
    assert.ok(ready.priority < view('retention_claude', { probe: p }).priority);
  });
});
