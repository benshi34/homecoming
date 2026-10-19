// Pieces shared by the main window and the Setup Assistant: a source's detail page, its forms and steps.

import { type CSSProperties, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { buildIdentity, KINDS, keyOf, type Kind, pickerRows, type PickRow } from '../shared/identity.ts';
import { ago, bytes, count } from '../shared/format.ts';
import type { Action, FoundService, Identity, MappingPreview, Snapshot, SourceView, UnknownSender } from '../shared/types.ts';
import { BY_ID } from '../shared/catalog.ts';
import { READ_ONLY_NOTE, READ_ONLY_OK } from '../shared/status.ts';
import { agentNeed, PROVIDER, RETENTION, retentionOk } from '../shared/ask.ts';
import { AiAgreement, decideAi } from './ai.tsx';
import { api } from './api.ts';
import { AgentNeedNote, RetentionSheet } from './ask.tsx';
import { Glyph, SourceIcon } from './icons.tsx';
import { PHONE_SOURCES, phoneGroups } from '../shared/phone.ts';
import { agentGate, AgentGateSheet, type Gate } from './agent_gate.tsx';
import { AiMark, Banner, Button, Group, GroupRow, ProgressBar, Sheet, Spinner, StatusGlyph, Toggle, useReadOnly } from './ui.tsx';
import { WaitClock } from './moments.tsx';
import { SourceGlance } from './glance.tsx';
import type { ExplorePage } from './explore.tsx';

export const vt = (name: string): CSSProperties => ({ viewTransitionName: name } as CSSProperties);

// Manifest keys of sources with several parts (Google, Instagram...), in words. iPhone parts: shared/phone.ts.
const SOURCE_NAMES: Record<string, string> = {
  google_activity: 'Search, YouTube and Maps activity', chrome_synced: 'Chrome (synced)', google_chat: 'Google Chat and Hangouts', gmail: 'Gmail',
  google_maps_places: 'Maps places', instagram_activity: 'Instagram activity', facebook_activity: 'Facebook activity', notion_export: 'Notion pages',
  youtube: 'YouTube comments, uploads and playlists', google_tasks: 'Tasks', google_saved: 'Saved lists',
};

export function prettySource(name: string): string {
  return SOURCE_NAMES[name] ?? PHONE_SOURCES[name]?.[0] ?? name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------- your other accounts

// Why a found service is on the list, in a few words: the apps, the mail, the visits.
export function evidenceLine(f: FoundService | UnknownSender): string {
  const bits: string[] = [];
  if (f.apps.length) bits.push(f.apps.length === 1 ? f.apps[0] : `${f.apps[0]} and ${f.apps.length - 1} more app${f.apps.length === 2 ? '' : 's'}`);
  if (f.emails) bits.push(`${count(f.emails)} email${f.emails === 1 ? '' : 's'}${f.first ? ` since ${f.first.slice(0, 4)}` : ''}`);
  if (f.visits) bits.push(`${count(f.visits)} page visit${f.visits === 1 ? '' : 's'}`);
  return bits.join(' · ');
}

// The hub's suggestions: services you clearly use whose export steps are known.
export const strongFind = (f: FoundService) => !!f.export?.url && (f.apps.length > 0 || f.visits >= 50);

export function AddServiceSheet({ onClose, onAdded, initialName = '' }: { onClose: () => void; onAdded: (id: string) => void; initialName?: string }) {
  const [name, setName] = useState(initialName);
  const [url, setUrl] = useState('');
  const [err, setErr] = useState('');
  const locked = useReadOnly(); // read-only mode: nothing is added
  return (
    <Sheet onClose={onClose} testId="add-service" width={440}>
      <form onSubmit={(e) => {
        e.preventDefault();
        if (locked) return;
        if (!name.trim()) return setErr('Enter the service\'s name.');
        void api.action('*', 'add-service', { name, url }).then((r) => (r.ok && r.id ? (onAdded(r.id), onClose()) : setErr(r.error ?? 'Couldn\'t add it.')));
      }}>
        <h2>Add a Source</h2>
        <p>Any site or app that holds your data, however small. Whatever it gives you is kept, file by file, whatever the format; the steps show how to ask for it.</p>
        <div className="form-grid" style={{ padding: '12px 0 0' }}>
          <label htmlFor="svc-name">Name</label>
          <input id="svc-name" autoFocus value={name} placeholder="Wattpad" onChange={(e) => { setName(e.target.value); setErr(''); }} />
          <label htmlFor="svc-url">Website</label>
          <input id="svc-url" value={url} placeholder="wattpad.com (optional)" onChange={(e) => { setUrl(e.target.value); setErr(''); }} />
        </div>
        {err && <div className="form-error error">{err}</div>}
        {locked && <p>{locked}</p>}
        <div className="sheet-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" testAction="add-service" disabled={!!locked} title={locked ?? undefined}>Add</Button>
        </div>
      </form>
    </Sheet>
  );
}

// ---------------------------------------------------------------- reading an unknown format

// The agent that makes sense of a download: the one Ask uses, by its first name.
const mapper = (snap: Snapshot) => (PROVIDER[snap.ask.settings.provider]?.harness === 'codex' ? 'Codex' : 'Claude');

// A service you added is first kept file by file. The agent picked in AI Settings can read the download's structure
// and write a mapping that turns it into posts, comments, purchases..., which the person checks before it's used.
export function MakeSenseOfIt({ snap, view }: { snap: Snapshot; view: SourceView }) {
  const src = BY_ID[view.id];
  const [open, setOpen] = useState(false);
  if (!src?.custom || !(view.records > 0)) return null;
  const m = snap.mappings[src.importDir ?? ''];
  return (
    <>
      <Group title="Make sense of it" testId="mapping"
        footer={m ? 'Each item is read from the download with this mapping. The download itself stays as it came.'
          : 'Each file is kept as it came: every row and item, with its time when one is found. A mapping says which are posts, comments or purchases, and who wrote them.'}>
        {m ? m.items.map((r, i) => <GroupRow key={i} title={r.describe} trailing={<span className="tag">{r.kind}</span>} />) : (
          <GroupRow title="Kept as it came, file by file" subtitle={`${count(view.records)} ${view.records === 1 ? 'item' : 'items'} so far, not yet sorted into posts, comments and the like`} />
        )}
        <div className="kv">
          <Button kind="plain" ai onClick={() => setOpen(true)} testAction="open-mapping">{m ? 'Remake the Mapping…' : `Ask ${mapper(snap)} to Make Sense of It…`}</Button>
          {m ? <Button kind="plain" onClick={() => void api.action(view.id, 'remove-mapping')} testAction="remove-mapping">Stop Using It</Button> : <span />}
        </div>
      </Group>
      {open && <MappingSheet snap={snap} view={view} onClose={() => setOpen(false)} />}
    </>
  );
}

// One primary button: ask the agent (after the one-time AI agreement, if AI is off). What's sent, and pasting a reply
// from a chat of your own, are there to open.
function MappingSheet({ snap, view, onClose }: { snap: Snapshot; view: SourceView; onClose: () => void }) {
  const a = snap.ask.settings;
  const who = mapper(snap);
  const local = !PROVIDER[a.provider]?.cloud;
  const aiOn = snap.settings.aiOn === true;
  const need = agentNeed(snap.ask);
  const [examples, setExamples] = useState(false);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  const [preview, setPreview] = useState<MappingPreview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<{ text: string; detail?: string } | null>(null);
  const [showSent, setShowSent] = useState(false);
  const [showPaste, setShowPaste] = useState(false);
  const [showDetail, setShowDetail] = useState(false);
  const [agreeing, setAgreeing] = useState(false); // AI is off: what turning it on means, before anything is sent
  const [retention, setRetention] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    setPrompt(null);
    void api.action(view.id, 'describe-export', { examples }).then((r) => (r.ok ? setPrompt((r.data as { prompt: string }).prompt) : setErr({ text: r.error ?? 'Couldn\'t read the download.' })));
  }, [examples]);
  const check = (text: string) => {
    setBusy('Checking it against the whole download…');
    setErr(null);
    void api.action(view.id, 'try-mapping', { text }).then((r) => (r.ok ? setPreview(r.data as MappingPreview) : setErr({ text: r.error ?? 'That mapping didn\'t work.' }))).finally(() => setBusy(null));
  };
  // confirmed: the data settings were just confirmed (this render's settings don't know yet).
  const ask = (confirmed = false) => {
    if (!prompt) return;
    if (!confirmed && !retentionOk(a, a.provider)) return setRetention(true);
    setBusy(`${who} is reading how the download is laid out…`);
    setErr(null);
    setShowDetail(false);
    void api.action(view.id, 'ask-claude', { prompt }).then((r) => {
      if (r.error === 'confirm-retention') return setRetention(true);
      if (!r.ok) return setErr({ text: `${who} couldn't make sense of it: ${r.error}`, detail: (r.data as { detail?: string } | undefined)?.detail });
      setReply(r.data as string);
      check(r.data as string);
    }).finally(() => setBusy((b) => (b?.startsWith(who) ? null : b)));
  };
  const turnOnAndAsk = () => void decideAi(snap, true).then(() => {
    setAgreeing(false);
    ask();
  });
  const use = () => void api.action(view.id, 'save-mapping', { mapping: preview!.mapping }).then((r) => (r.ok ? onClose() : setErr({ text: r.error ?? 'Couldn\'t save it.' })));
  const copy = () => {
    if (!prompt) return;
    void navigator.clipboard.writeText(prompt).then(() => setCopied(true));
  };
  return (
    <>
      <Sheet onClose={onClose} testId="mapping-sheet" width={600}>
        {agreeing ? (
          <>
            <h2>Turn on AI to ask {who}?</h2>
            {snap.settings.aiAgreedAt
              ? <p>This turns AI back on in Homecoming, for Ask{snap.settings.agentExports ? ' and Do It for Me' : ''} too. You can turn it off again in AI Settings.</p>
              : <div style={{ marginTop: 8 }}><AiAgreement snap={snap} actions={false} /></div>}
            {need && <div style={{ marginTop: 10 }}><AgentNeedNote snap={snap} need={need} /></div>}
            <div className="sheet-actions">
              <Button onClick={() => setAgreeing(false)}>Back</Button>
              <Button kind="primary" ai onClick={turnOnAndAsk} disabled={!prompt || !!need} testAction="mapping-ai-on">Turn On AI and Ask</Button>
            </div>
          </>
        ) : !preview ? (
          <>
            <h2>Make sense of your {view.name} download</h2>
            <p>{who} reads how the download is laid out: its files, the names of their fields and the kinds of values in them, not what's in them
              {examples ? ' (apart from one example value per field)' : ''}. It writes a mapping that says which items are posts, comments or purchases, and you see what
              it finds before anything is used. {local ? 'It runs on this Mac: nothing leaves it.' : `${PROVIDER[a.provider].name} (${PROVIDER[a.provider].short}) answers, as in Ask.`}</p>
            <label className="check"><input type="checkbox" checked={examples} onChange={(e) => setExamples(e.target.checked)} /> Include one example value per field (a better mapping; those values are sent too)</label>
            <Disclosure open={showSent} onToggle={() => setShowSent(!showSent)} label="What's sent" testId="mapping-sent">
              <pre className="prompt" data-testid="mapping-prompt">{prompt ?? 'Reading the download…'}</pre>
              <div className="disclosure-actions"><Button size="small" onClick={copy} disabled={!prompt} testAction="copy-request">{copied ? 'Copied' : 'Copy'}</Button></div>
            </Disclosure>
            <Disclosure open={showPaste} onToggle={() => setShowPaste(!showPaste)} label="Paste a reply" testId="mapping-paste">
              <p>Ask any AI chat of your own with what's sent, then paste its reply here.</p>
              <textarea className="reply" placeholder="The reply (the mapping)" value={reply} onChange={(e) => setReply(e.target.value)} data-testid="mapping-reply" />
              <div className="disclosure-actions"><Button size="small" onClick={() => check(reply)} disabled={!reply.trim() || !!busy} testAction="check-mapping">Check It</Button></div>
            </Disclosure>
            {aiOn && need && <div style={{ marginTop: 10 }}><AgentNeedNote snap={snap} need={need} /></div>}
            {busy && <div className="note"><Spinner size={12} /><span>{busy}</span></div>}
            {err && (
              <div className="mapping-error" data-testid="mapping-error">{err.text}
                {err.detail && <> <button className="link" onClick={() => setShowDetail(!showDetail)}>{showDetail ? 'Hide Details' : 'Details'}</button></>}
                {showDetail && <pre className="error-detail selectable">{err.detail}</pre>}
              </div>
            )}
            <div className="sheet-actions">
              <Button onClick={onClose}>Cancel</Button>
              {aiOn
                ? <Button kind="primary" ai onClick={() => ask()} disabled={!prompt || !!busy || !!need} testAction="ask-claude">Ask {who}</Button>
                : <Button kind="primary" ai onClick={() => setAgreeing(true)} disabled={!prompt} testAction="mapping-turn-on">Turn On AI and Ask…</Button>}
            </div>
          </>
        ) : (
          <>
            <h2>What the mapping finds</h2>
            <p>Run over the whole download, nothing saved yet. {preview.mapped} of {preview.structured} data file{preview.structured === 1 ? '' : 's'} read.</p>
            <div className="group-box" style={{ marginTop: 12 }} data-testid="mapping-preview">
              {preview.rules.map((r, i) => (
                <GroupRow key={i} title={<>{r.describe}<span className="tag">{r.kind}</span></>}
                  subtitle={r.items ? `${count(r.items)} found${r.items ? `, ${Math.round((r.timed / r.items) * 100)}% with a time` : ''}${r.repeats ? `, but ${count(r.repeats)} more share an id with one of them and would be left out` : ''}${r.sample[0] ? ` · “${(r.sample[0].title ?? r.sample[0].text ?? '').slice(0, 80)}”` : ''}` : 'Nothing found: the mapping may name the wrong file or field'}
                  trailing={count(r.items)} />
              ))}
            </div>
            <p style={{ marginTop: 10 }}>The mapping is kept on this Mac, for your {view.name} downloads only.</p>
            {preview.unmapped.length > 0 && <p style={{ marginTop: 10 }}>Still kept file by file: {preview.unmapped.slice(0, 6).join(', ')}{preview.unmapped.length > 6 ? ` and ${preview.unmapped.length - 6} more` : ''}.</p>}
            {err && <div className="mapping-error">{err.text}</div>}
            <div className="sheet-actions">
              <Button onClick={() => setPreview(null)}>Back</Button>
              <Button kind="primary" onClick={use} disabled={!preview.rules.some((r) => r.items)} testAction="use-mapping">Use It</Button>
            </div>
          </>
        )}
      </Sheet>
      {retention && RETENTION[a.provider] && (
        <RetentionSheet provider={a.provider} confirmed={false} onClose={() => setRetention(false)}
          onConfirm={() => void api.ask({ op: 'confirm-retention', provider: a.provider }).then(() => {
            setRetention(false);
            ask(true);
          })} />
      )}
    </>
  );
}

// A disclosure triangle and what it shows, like a Finder info window's sections.
function Disclosure({ open, onToggle, label, testId, children }: { open: boolean; onToggle: () => void; label: string; testId?: string; children: ReactNode }) {
  return (
    <div className={`disclosure ${open ? 'open' : ''}`} data-testid={testId}>
      <button className="disclose-btn" onClick={onToggle} aria-expanded={open}>
        <Glyph name="chevronRight" size={9} strokeWidth={2.4} className={`disclose ${open ? 'open' : ''}`} />{label}
      </button>
      {open && <div className="disclosure-body">{children}</div>}
    </div>
  );
}

// What a source holds, every part of it, one group per split (shared/contents.ts).
export function Contents({ view }: { view: SourceView }) {
  return (
    <>
      {(view.contents ?? []).map((g) => (
        <Group key={g.title} title={g.title} testId="contents">
          {g.rows.map((r) => <GroupRow key={r.label} title={r.label} trailing={count(r.count)} />)}
        </Group>
      ))}
    </>
  );
}

// The same, as short lines under a source's name. A single row that is the whole source says nothing new.
export function ContentsLines({ view }: { view: SourceView }) {
  const groups = (view.contents ?? []).filter((g) => g.rows.length > 1);
  if (!groups.length) return null;
  return (
    <div className="contents-lines" data-testid="contents-lines">
      {groups.map((g) => <div key={g.title}><span>{g.title}:</span> {g.rows.map((r) => `${r.label} ${count(r.count)}`).join(' · ')}</div>)}
    </div>
  );
}

// What an iPhone backup added, all of it: Messages and calls combined with the Mac's copy, then every other
// phone source by what it is (shared/phone.ts), phone internals (ileapp.py's "device" tier) last.
export function PhoneParts({ view }: { view: SourceView }) {
  const merged = view.merged ?? [];
  return (
    <>
      {merged.length > 0 && (
        <Group title="Combined with this Mac's copy" testId="phone-merged" footer="Each message and call appears once, under the same name in your library.">
          {merged.map((m) => <GroupRow key={m.id} title={m.name} trailing={count(m.fromPhone)} />)}
        </Group>
      )}
      {phoneGroups(view.parts ?? []).map((g) => (
        <Group key={g.group} title={g.group} testId="phone-group"
          footer={g.group === 'Phone details' ? 'Kept, and marked as phone details rather than things you did.' : undefined}>
          {g.rows.map((r) => <GroupRow key={r.name} testId={`phone-part-${r.name}`} title={r.title} trailing={count(r.records)} />)}
        </Group>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- steps

// locked: read-only mode, where ticking a step would change what the app keeps.
export function Steps({ view, locked }: { view: SourceView; locked?: boolean }) {
  // Flip at once; the main process confirms a moment later.
  const fromView = view.steps!.map((s) => s.done);
  const [done, setDone] = useState(fromView);
  useEffect(() => setDone(fromView), [view.id, fromView.join()]);
  const toggle = (i: number) => {
    setDone((d) => d.map((x, j) => (j === i ? !x : x)));
    void api.action(view.id, 'toggle-step', { index: i });
  };
  return (
    <div className="group-box" data-testid="steps">
      {view.steps!.map((s, i) => (
        <label key={i} className="steps-row">
          <input type="checkbox" checked={done[i] ?? s.done} onChange={() => toggle(i)} aria-label={`Step ${i + 1}`} disabled={locked} title={locked ? READ_ONLY_NOTE : undefined} />
          <div>
            <div className={`t ${done[i] ? 'done' : ''}`}>{s.text}</div>
            {s.detail && <div className="s">{s.detail}</div>}
          </div>
        </label>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- forms

export function PasswordForm({ onSubmit, busy, label = 'Read Backup' }: { onSubmit: (pw: string) => void; busy: boolean; label?: string }) {
  const [pw, setPw] = useState('');
  const [err, setErr] = useState('');
  return (
    <form className="group-box" data-testid="password-form" onSubmit={(e) => {
      e.preventDefault();
      if (!pw) return setErr('Enter the backup password first.');
      onSubmit(pw);
      setPw('');
    }}>
      <div className="form-grid">
        <label htmlFor="pw">Backup password</label>
        <input id="pw" type="password" value={pw} autoFocus onChange={(e) => { setPw(e.target.value); setErr(''); }} />
      </div>
      {err && <div className="form-error error">{err}</div>}
      <div className="form-hint">Sent only to the decryption step on this Mac. Never saved.</div>
      <div className="actions" style={{ paddingLeft: 156 }}><Button kind="primary" type="submit" disabled={busy}>{label}</Button></div>
    </form>
  );
}

// Who you are, from evidence: every name, address, username and number found on this Mac and in your exports,
// ticked when the evidence is strong. Untick what isn't you; add what's missing.
// What's ticked and typed in a picker that's kept (keep): Your Setup's, while you look at another page and come back.
interface PickerDraft { extra: PickRow[]; checked: Set<string>; drafts: Record<Kind, string>; touched: Set<string> }
const keptPickers = new Map<string, PickerDraft>();
export const forgetPicker = (keep: string) => keptPickers.delete(keep);

// keep: a name to keep what's ticked and typed under until forgetPicker (saved, or closed with Done). Read-only mode:
// shown as it is, every box and field disabled, with the note.
export function IdentityPicker({ snap, onSubmit, busy, submitLabel = 'Save', hideSubmit, formId, keep }: {
  snap: Snapshot; onSubmit: (id: Identity, dismissed: string[]) => void; busy: boolean; submitLabel?: string; hideSubmit?: boolean; formId?: string; keep?: string;
}) {
  const locked = useReadOnly();
  const was = keep ? keptPickers.get(keep) : undefined;
  const found = pickerRows(snap.identityCandidates ?? [], snap.identity, snap.identityDismissed ?? []);
  const [extra, setExtra] = useState<PickRow[]>(was?.extra ?? []);
  const rows = [...found, ...extra.filter((e) => !found.some((r) => r.key === e.key))];
  const touched = useRef(was?.touched ?? new Set<string>());
  const [checked, setChecked] = useState<Set<string>>(() => was?.checked ?? new Set(found.filter((r) => r.checked).map((r) => r.key)));
  // Candidates arrive a moment after the page opens: tick the strong ones unless the person already chose.
  const sig = found.map((r) => `${r.key}${r.checked}`).join();
  useEffect(() => {
    setChecked((prev) => {
      const n = new Set(prev);
      for (const r of found) if (!touched.current.has(r.key) && r.checked) n.add(r.key);
      return n;
    });
  }, [sig]);
  const [drafts, setDrafts] = useState<Record<Kind, string>>(was?.drafts ?? { name: '', email: '', username: '', phone: '' });
  const [err, setErr] = useState('');
  useEffect(() => {
    if (keep) keptPickers.set(keep, { extra, checked, drafts, touched: touched.current });
  }, [keep, extra, checked, drafts]);
  const flip = (key: string) => {
    touched.current.add(key);
    setChecked((c) => {
      const n = new Set(c);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
    setErr('');
  };
  const add = (kind: Kind) => {
    const v = drafts[kind].trim();
    if (!v) return;
    if (kind === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return setErr('That doesn\'t look like an email address.');
    const key = keyOf(kind, v);
    setExtra((e) => [...e, { key, kind, value: v, sources: [{ label: 'Added by you' }], checked: true, isNew: false, strong: true }]);
    touched.current.add(key);
    setChecked((c) => new Set(c).add(key));
    setDrafts((d) => ({ ...d, [kind]: '' }));
    setErr('');
  };
  return (
    <form id={formId} data-testid="identity-form" onSubmit={(e) => {
      e.preventDefault();
      if (locked) return;
      // What's typed in an Add field and not added yet counts too: nobody should have to press Add before Save.
      const typed: PickRow[] = [];
      for (const k of KINDS) {
        const v = drafts[k.kind].trim();
        if (!v) continue;
        if (k.kind === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return setErr('That doesn\'t look like an email address.');
        if (!rows.some((r) => r.key === keyOf(k.kind, v))) typed.push({ key: keyOf(k.kind, v), kind: k.kind, value: v, sources: [{ label: 'Added by you' }], checked: true, isNew: false, strong: true });
      }
      const all = [...rows, ...typed];
      const ticked = new Set([...checked, ...typed.map((r) => r.key)]);
      if (typed.length) {
        setExtra((x) => [...x, ...typed]);
        setChecked(ticked);
        setDrafts({ name: '', email: '', username: '', phone: '' });
      }
      const id = buildIdentity(all, ticked);
      if (!id.names.length || !id.emails.length) return setErr(`Add ${!id.names.length && !id.emails.length ? 'your name and an email address' : !id.names.length ? 'your name' : 'an email address'}: they're how your messages are told apart from everyone else's.`);
      const dismissed = all.filter((r) => !ticked.has(r.key) && r.sources.some((x) => x.label !== 'Added by you')).map((r) => r.key);
      onSubmit(id, dismissed);
    }}>
      {KINDS.map((k) => {
        const mine = rows.filter((r) => r.kind === k.kind);
        return (
          <Group key={k.kind} title={k.label}>
            <div className="group-box">
              {mine.map((r) => (
                <label key={r.key} className="cand-row" data-testid={`cand-${r.key}`}>
                  <input type="checkbox" checked={checked.has(r.key)} onChange={() => flip(r.key)} aria-label={r.value} disabled={!!locked} title={locked ?? undefined} />
                  <div className="main">
                    <div className="v">{r.value}{r.isNew && <span className="tag new">New</span>}{!r.strong && <span className="tag">Maybe</span>}</div>
                    <div className="src">{r.sources.slice(0, 3).map((x) => (x.count ? `${x.label} · ${count(x.count)}` : x.label)).join('  ·  ')}{r.sources.length > 3 ? `  +${r.sources.length - 3} more` : ''}</div>
                  </div>
                </label>
              ))}
              <div className="cand-add">
                <input id={`add-${k.kind}`} type="text" placeholder={`${k.add}…`} value={drafts[k.kind]} disabled={!!locked} title={locked ?? undefined}
                  onChange={(e) => setDrafts({ ...drafts, [k.kind]: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(k.kind); } }} />
                <Button onClick={() => add(k.kind)} testAction={`add-${k.kind}`} disabled={!!locked} title={locked ?? undefined}>Add</Button>
              </div>
            </div>
          </Group>
        );
      })}
      {err && <div className="form-error error" style={{ padding: '8px 2px 0' }}>{err}</div>}
      {locked && <div className="note" data-testid="identity-locked"><Glyph name="info" size={13} /><span>{locked}</span></div>}
      {!hideSubmit && <div style={{ marginTop: 14 }}><Button kind="primary" type="submit" disabled={busy || !!locked} title={locked ?? undefined}>{submitLabel}</Button></div>}
    </form>
  );
}

export function SkipForm({ view, action, onSubmit, onCancel }: { view: SourceView; action: Action; onSubmit: (r: string) => void; onCancel: () => void }) {
  const reasons = action.id === 'cant-export'
    ? ['My account is on a school or work workspace (only admins can export)', 'The site has no export for my account']
    : view.id === 'iphone_backup' ? ['I don\'t have an iPhone', 'Not now', 'I\'ll do it another way'] : [`I don't use ${view.name}`, 'Not now', 'I\'ll do it another way'];
  // "I don't have an iPhone" is the one answer for the backup and the checks about the iPhone (main.ts).
  const reasonOf = (r: string) => (r === 'I don\'t have an iPhone' ? 'No iPhone' : r);
  return (
    <Sheet onClose={onCancel} testId="skip-form">
      <h2>{action.id === 'cant-export' ? `Why can't ${view.name} export?` : `Skip ${view.name}?`}</h2>
      <p>Not now keeps it in To Do, under Optional. Any other reason puts it away: it stays in All Sources, where you can include it again any time.</p>
      <div className="sheet-actions" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
        {reasons.map((r) => <Button key={r} onClick={() => onSubmit(reasonOf(r))}>{r}</Button>)}
        <Button kind="plain" onClick={onCancel}>Cancel</Button>
      </div>
    </Sheet>
  );
}

export function AccountForm({ view }: { view: SourceView }) {
  const [name, setName] = useState(view.accountName ?? '');
  return (
    <div className="group-box" data-testid="account-form">
      <div className="form-grid">
        <label htmlFor="acct">Account name</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input id="acct" type="text" value={name} placeholder="Hotmail" onChange={(e) => setName(e.target.value)} />
          <Button onClick={() => void api.action(view.id, 'set-account', { name })}>Save</Button>
        </div>
      </div>
      <div className="form-hint">A short name for this account, like Hotmail or Work. It's how its mail is labeled in your library.</div>
    </div>
  );
}

// ---------------------------------------------------------------- detail

// Do It for Me, the first time: Claude Code works in the person's Chrome, where they're signed in, and stops only for
// what's theirs to do. It can't be turned on without Claude Code, and the Claude in Chrome extension is checked as the
// sheet opens, so a missing one is said up front rather than when a run fails.
// onOn: it's on, and Anthropic's data settings are checked (asked here first, before anything is saved, as AI Settings'
// switch asks: Cancel there leaves it off).
export function AgentOptIn({ snap, onClose, onOn }: { snap: Snapshot; onClose: () => void; onOn: () => void }) {
  const [downloads, setDownloads] = useState(snap.settings.agentDownloads !== false);
  const [check, setCheck] = useState(false);
  const [checks, setChecks] = useState(snap.settings.agentChecks !== false);
  const [chrome, setChrome] = useState<string | null>(null);
  const installed = snap.agentInstalled ?? snap.ask.installed['claude-code'];
  // Installed, but it can't run yet: signed out, no browser it works in, or a plan it doesn't work on (AI Settings fixes it).
  const cant = installed && !snap.demo && snap.setup?.agent && !snap.setup.agent.ok ? snap.setup.agent : null;
  const B = snap.setup?.agentBrowser?.name ?? 'Chrome';
  const locked = snap.readOnly && !snap.demo;
  useEffect(() => {
    if (!installed || snap.demo) return;
    let live = true;
    void api.aiChrome().then((x) => live && setChrome(x));
    return () => {
      live = false;
    };
  }, [installed]);
  const save = () => void api.settings({ aiOn: true, aiAgreedAt: snap.settings.aiAgreedAt ?? new Date().toISOString(), agentExports: true, agentDownloads: downloads, agentChecks: checks })
    .then(onOn);
  const turnOn = () => (snap.demo || retentionOk(snap.ask.settings, 'claude-code') ? save() : setCheck(true));
  if (check) {
    return <RetentionSheet provider="claude-code" confirmed={false} onClose={() => setCheck(false)}
      onConfirm={() => void api.ask({ op: 'confirm-retention', provider: 'claude-code' }).then(save)} />;
  }
  return (
    <Sheet onClose={onClose} testId="agent-opt-in" width={480}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 7 }}><AiMark size={16} />Let Claude request and download your exports?</h2>
      <p>Claude Code opens each service's export page in your {B}, where you're signed in, picks the right options and requests your data. When the service says it's ready, Claude downloads it, and the app reads it from Downloads.</p>
      <p>When it needs you to sign in, confirm it's you, or prove you're not a robot, it waits a few minutes and tells you in a notification: macOS may ask you to allow Homecoming's. It uses the Claude in Chrome extension and your Claude account.</p>
      {snap.settings.aiOn !== true && <p data-testid="agent-ai-note">This turns on AI in Homecoming, so Ask can use it too. You can turn it off in AI Settings.</p>}
      {snap.demo && <div style={{ marginTop: 10 }} data-testid="agent-demo-note"><Banner kind="info">In the demo, a stand-in plays Claude: nothing opens.</Banner></div>}
      {!installed ? (
        <div style={{ marginTop: 10 }} data-testid="agent-no-claude"><Banner kind="warning">
          Do It for Me needs Claude Code, which isn't on this Mac. Install it from claude.com/claude-code and sign in, then add the Claude in Chrome extension to {B}.
          <div style={{ marginTop: 6 }}><Button size="small" onClick={() => void api.action('*', 'get-claude-code')} testAction="get-claude-code">Get Claude Code…</Button></div>
        </Banner></div>
      ) : cant ? (
        <div style={{ marginTop: 10 }} data-testid="agent-cant"><Banner kind="warning">
          {cant.why}
          <div style={{ marginTop: 6 }}><Button size="small" onClick={() => { onClose(); void api.action('*', 'show-ai'); }} testAction="show-ai">Open AI Settings</Button></div>
        </Banner></div>
      ) : chrome === 'not connected' ? (
        <div style={{ marginTop: 10 }} data-testid="agent-chrome"><Banner kind="warning">
          The Claude in Chrome extension isn't connected. Open {B}, turn the extension on and sign in to it with your Claude account, then Turn On.
          <div style={{ marginTop: 6 }}><Button size="small" onClick={() => void api.action('*', 'open-chrome')} testAction="open-chrome">Open {B}</Button></div>
        </Banner></div>
      ) : !snap.demo && (
        <div className="note" data-testid="agent-chrome">
          {chrome === 'connected' ? <><Glyph name="checkCircle" size={13} /><span>The Claude in Chrome extension is connected.</span></> : <><Spinner size={12} /><span>Checking the Claude in Chrome extension…</span></>}
        </div>
      )}
      <label className="check" style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, marginTop: 12 }}>
        <input type="checkbox" checked={downloads} onChange={(e) => setDownloads(e.target.checked)} data-testid="agent-downloads" />
        <span>Download exports by themselves when they're ready</span>
      </label>
      <label className="check" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, marginTop: 6, paddingLeft: 22, opacity: downloads ? 1 : 0.5 }}>
        <input type="checkbox" checked={checks && downloads} disabled={!downloads} onChange={(e) => setChecks(e.target.checked)} data-testid="agent-checks" style={{ marginTop: 2 }} />
        <span>And look for them every few hours: while one is on its way, Claude opens {B} to check the service's page, or your webmail for the email saying it's ready</span>
      </label>
      {locked && <p style={{ marginTop: 10 }}>{READ_ONLY_NOTE}</p>}
      <div className="sheet-actions">
        {/* Not now is remembered: export pages lead with doing it yourself, until it's turned on (here, or in AI Settings). */}
        <Button onClick={() => { if (!locked) void api.settings({ agentExports: false }); onClose(); }} testAction="agent-not-now">Not Now</Button>
        <Button kind="primary" ai testAction="agent-on" disabled={!installed || !!cant || locked} title={locked ? READ_ONLY_NOTE : !installed ? 'Needs Claude Code' : cant ? cant.why : undefined} onClick={turnOn}>Turn On</Button>
      </div>
    </Sheet>
  );
}

// Look in your email for a service's "it's ready" message: the one inbox there is opens at once (Gmail searched for
// the service); with several, a short list asks which.
export function InboxButton({ view, action }: { view: SourceView; action: Action }) {
  const [choosing, setChoosing] = useState(false);
  const list = view.inboxes ?? [];
  const open = (inbox: string) => {
    setChoosing(false);
    void api.action(view.id, 'open-inbox', { inbox });
  };
  return (
    <>
      <Button kind={action.primary ? 'primary' : 'default'} onClick={() => (list.length === 1 ? open(list[0].id) : setChoosing(true))} testAction="open-inbox">{action.label}</Button>
      {choosing && (
        <Sheet onClose={() => setChoosing(false)} testId="inbox-choice" width={400}>
          <h2>Where does {view.name} email you?</h2>
          <p>Gmail opens searched for mail from {view.name}; the others open your inbox.</p>
          <div className="group-box" style={{ marginTop: 10 }}>
            {list.map((x) => <GroupRow key={x.id} testId={`inbox-${x.id}`} title={x.app === 'Mail' ? 'Mail on this Mac' : x.app} subtitle={x.email} onClick={() => open(x.id)} />)}
          </div>
          <div className="sheet-actions"><Button onClick={() => setChoosing(false)}>Cancel</Button></div>
        </Sheet>
      )}
    </>
  );
}

// What starts Claude in your browser.
const AGENT_ACTIONS = new Set(['agent-request', 'agent-download', 'agent-continue']);

// A Do It for Me button anywhere (the Setup Assistant's export pages): asks the first time, like the detail page does.
export function AgentButton({ snap, id, action }: { snap: Snapshot; id: string; action: Action }) {
  const [optIn, setOptIn] = useState(false);
  const [gate, setGate] = useState<Gate>(null);
  const go = () => void api.action(id, action.id);
  const needsOptIn = (action.id === 'agent-request' || action.id === 'agent-download') && !snap.settings.agentExports;
  const locked = snap.readOnly && !snap.demo && !READ_ONLY_OK.has(action.id);
  // Not yet with the AI picked: said at once. Otherwise what it does (the first time), then the data settings.
  const proceed = () => (agentGate(snap) === 'retention' ? setGate('retention') : go());
  const press = () => (agentGate(snap) === 'not-yet' ? setGate('not-yet') : needsOptIn ? setOptIn(true) : proceed());
  return (
    <>
      <Button kind={action.primary ? 'primary' : 'default'} ai={action.ai} onClick={press} testAction={action.id}
        disabled={locked} title={locked ? READ_ONLY_NOTE : undefined}>{action.label}</Button>
      {gate && <AgentGateSheet snap={snap} gate={gate} onClose={() => setGate(null)} onOk={() => { setGate(null); go(); }} />}
      {optIn && <AgentOptIn snap={snap} onClose={() => setOptIn(false)} onOn={() => { setOptIn(false); go(); }} />}
    </>
  );
}

export function Detail({ snap, view, onActed, onExplore }: { snap: Snapshot; view: SourceView; onActed?: (id: string) => void; onExplore?: (page: ExplorePage) => void }) {
  const [form, setForm] = useState<Action | null>(null);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const asked = useRef<unknown>(undefined); // what came with it (a backup's password): sent on, once confirmed
  const [optIn, setOptIn] = useState<Action | null>(null);
  const [gate, setGate] = useState<{ g: Exclude<Gate, null>; a: Action; payload?: unknown } | null>(null);
  const [reply, setReply] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [over, setOver] = useState(false);

  useEffect(() => {
    if (view.section !== 'working') return;
    let live = true;
    const tick = () => void api.jobLog(view.id).then((l) => live && setLog(l));
    tick();
    const t = setInterval(tick, 1000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [view.id, view.section]);

  // A source that needs a single input (password, identity) shows the form right away.
  useEffect(() => {
    const p = view.actions.find((a) => a.primary);
    // Not while it's running: once it's stopped for you (a password that didn't work), or before it starts.
    if (p && (p.input === 'password' || p.input === 'identity') && view.section !== 'unavailable' && (view.section !== 'working' || view.needsYou)) setForm(p);
    else setForm(null);
  }, [view.id, view.section, view.status, view.needsYou]);

  const run = async (a: Action, payload?: unknown, optedIn = false, gated = false) => {
    if (a.confirm && !(payload as { confirmed?: boolean })?.confirmed) {
      asked.current = payload;
      return setConfirm(a);
    }
    // Do It for Me with the AI picked (not yet with every one): said at once.
    const g = AGENT_ACTIONS.has(a.id) && !gated ? agentGate(snap) : null;
    if (g === 'not-yet') return setGate({ g, a, payload });
    // Do It for Me asks once: what it does, and whether downloads should start by themselves.
    if ((a.id === 'agent-request' || a.id === 'agent-download') && !snap.settings.agentExports && !optedIn) return setOptIn(a);
    // Then Anthropic's data settings, checked as Ask checks them (the first-time sheet asks them itself).
    if (g === 'retention' && !optedIn) return setGate({ g, a, payload });
    if ((a.input === 'password' || a.input === 'identity' || a.input === 'skip-reason') && payload === undefined) return setForm(a);
    setBusy(true);
    setError(null);
    onActed?.(view.id);
    const r = await api.action(view.id, a.id, payload);
    setBusy(false);
    if (!r.ok && r.error && r.error !== 'read-only') setError(r.error);
    else if (a.input !== 'identity') setForm(null);
  };

  // Where a download can be dropped: a source that takes one, and is in use.
  const isDropTarget = ['web', 'guided'].includes(view.group) && !BY_ID[view.id]?.manualDone && view.section !== 'unavailable' && !view.deferred;
  // A form that's open already is its own button: the same action above it would only open it again.
  const actions = view.actions.filter((a) => !(form && a.id === form.id && (a.input === 'password' || a.input === 'identity')));
  // Read-only mode: only what looks or opens a page works; the rest is disabled, and says why.
  const locked = snap.readOnly && !snap.demo;
  const off = (id: string) => locked && !READ_ONLY_OK.has(id);
  const answer = view.actions.find((a) => a.input === 'reply');
  return (
    <div className="detail" data-testid="detail" data-source={view.id}>
      <div className="dhead">
        <SourceIcon id={view.id} group={view.group} size={52} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2>{view.name}{view.tag && <span className="tag">{view.tag}</span>}</h2>
          <p className="blurb">{view.blurb}</p>
        </div>
      </div>

      <div className="group-box" data-testid="state">
        <div className="status-box">
          <div style={{ marginTop: 1 }}>{view.waiting ? <WaitClock size={18} started={view.requestedAt} /> : <StatusGlyph section={view.section} needsYou={view.needsYou} size={18} />}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="big appear-soft" key={view.status} data-testid="status">{view.status}</div>
            {view.detail && <div className="pre" data-testid="state-detail">{view.detail}</div>}
            {view.section === 'working' && !view.waiting && !view.needsYou && <ProgressBar value={view.progress} small />}
          </div>
        </div>
        {/* Claude asked something: what you write here goes back to it with Continue. Only then: carrying on after a quit,
            or turning on the Chrome extension, has nothing to answer. */}
        {answer && (
          <div className="agent-reply">
            <input type="text" value={reply} onChange={(e) => setReply(e.target.value)} placeholder={`Answer Claude here, or leave it empty once you've done it in ${snap.setup?.agentBrowser?.name ?? 'Chrome'}`}
              onKeyDown={(e) => e.key === 'Enter' && void run(answer, { reply }).then(() => setReply(''))} data-testid="agent-reply" disabled={off(answer.id)} />
          </div>
        )}
        {actions.length > 0 && (
          <div className="actions" data-testid="actions">
            {actions.map((a) => (a.id === 'open-inbox' ? <InboxButton key={a.id} view={view} action={a} />
              : <Button key={a.id} kind={a.primary ? 'primary' : 'default'} ai={a.ai} disabled={busy || off(a.id)} title={off(a.id) ? READ_ONLY_NOTE : undefined}
                onClick={() => void (a.input === 'reply' ? run(a, { reply }).then(() => setReply('')) : run(a))} testAction={a.id}>{a.label}</Button>))}
          </div>
        )}
        {error && <div style={{ padding: '0 14px 12px 42px' }}><Banner kind="error"><span data-testid="error">{error}</span></Banner></div>}
      </div>
      {/* Files in Downloads you said to ignore for this source: Show offers them again. */}
      {view.ignored && view.ignored.length > 0 && (
        <div className="note" data-testid="ignored"><Glyph name="info" size={13} />
          <span>{view.ignored.length === 1 ? `1 ignored file in Downloads (${view.ignored[0]})` : `${view.ignored.length} ignored files in Downloads`} · <Button kind="plain" size="small"
            onClick={() => void run({ id: 'unignore-found', label: 'Show' })} disabled={off('unignore-found')} testAction="unignore-found">Show</Button></span></div>
      )}

      {form?.input === 'password' && <Group title="Unlock the backup"><PasswordForm onSubmit={(pw) => run(form, { password: pw })} busy={busy} /></Group>}
      {form?.input === 'identity' && <IdentityPicker snap={snap} onSubmit={(identity, dismissed) => run(form, { identity, dismissed })} busy={busy} />}
      {form?.input === 'skip-reason' && <SkipForm view={view} action={form} onSubmit={(reason) => run(form, { reason })} onCancel={() => setForm(null)} />}
      {view.id === 'other_mail' && view.section !== 'unavailable' && <Group title="Account"><AccountForm view={view} /></Group>}

      {view.warnings.map((w, i) => <div key={i} style={{ marginTop: 12 }}><Banner kind="warning"><span data-testid="warning">{w}</span></Banner></div>)}

      {view.section === 'done' && view.records > 0 && (
        <Group title="Details">
          <div className="kv"><span>Records</span><span>{count(view.records)}</span></div>
          <div className="kv"><span>Since</span><span>{view.first ? view.first.slice(0, 4) : '—'}</span></div>
          <div className="kv"><span>Last read</span><span>{view.ranAt ? ago(view.ranAt, new Date()) : '—'}</span></div>
        </Group>
      )}

      {/* Collected: what it holds over time, when, and what's worth knowing, not only how many. */}
      {view.section === 'done' && view.records > 0 && <SourceGlance view={view} onExplore={onExplore} />}
      {view.group !== 'setup' && <Contents view={view} />}
      <MakeSenseOfIt snap={snap} view={view} />

      {view.steps && view.steps.length > 0 && <Group title="Steps"><Steps view={view} locked={locked} /></Group>}

      {view.id === 'iphone_backup' && view.section === 'done' && <PhoneParts view={view} />}
      {view.id !== 'iphone_backup' && view.parts && view.parts.length > 1 && (
        <Group title="Parts">
          {view.parts.map((p) => <div className="kv" key={p.name}><span>{prettySource(p.name)}</span><span>{count(p.records)}</span></div>)}
        </Group>
      )}

      {view.section === 'working' && log.length > 0 && (
        <Group title="Progress"><div className="log" data-testid="log">{log.slice(-60).join('\n')}</div></Group>
      )}

      {view.notes && view.notes.length > 0 && (
        <div style={{ marginTop: 14 }}>
          {view.notes.map((n, i) => <div key={i} className="note"><Glyph name="info" size={13} /><span>{n}</span></div>)}
        </div>
      )}

      {isDropTarget && view.section !== 'working' && (
        <div className={`drop ${over ? 'over' : ''}`} onDragOver={() => setOver(true)} onDragLeave={() => setOver(false)} onDrop={() => setOver(false)}>
          Drop the {view.name} download here, or <Button kind="plain" onClick={() => void run({ id: 'add-file', label: '' })} disabled={off('add-file')} title={off('add-file') ? READ_ONLY_NOTE : undefined}>choose it…</Button>
        </div>
      )}

      {optIn && <AgentOptIn snap={snap} onClose={() => setOptIn(null)} onOn={() => { const a = optIn; setOptIn(null); void run(a, undefined, true); }} />}
      {gate && <AgentGateSheet snap={snap} gate={gate.g} onClose={() => setGate(null)} onOk={() => { const x = gate; setGate(null); void run(x.a, x.payload, true, true); }} />}

      {confirm && (
        <Sheet onClose={() => setConfirm(null)} testId="confirm">
          <h2>{confirm.label}?</h2>
          <p>{confirm.confirm}</p>
          <div className="sheet-actions">
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            <Button kind="primary" onClick={() => { const a = confirm; setConfirm(null); void run(a, { ...(asked.current as object | undefined), confirmed: true }); }}>Continue</Button>
          </div>
        </Sheet>
      )}
    </div>
  );
}

