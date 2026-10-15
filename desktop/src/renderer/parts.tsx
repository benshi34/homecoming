// Pieces shared by the main window and the Setup Assistant: a source's detail page, its forms and steps.

import { type CSSProperties, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { buildIdentity, KINDS, keyOf, type Kind, pickerRows, type PickRow } from '../shared/identity.ts';
import { ago, bytes, count } from '../shared/format.ts';
import type { Action, FoundService, Identity, MappingPreview, Snapshot, SourceView, UnknownSender } from '../shared/types.ts';
import { BY_ID } from '../shared/catalog.ts';
import { api } from './api.ts';
import { Glyph, SourceIcon } from './icons.tsx';
import { PHONE_SOURCES, phoneGroups } from '../shared/phone.ts';
import { AiMark, Banner, Button, Group, GroupRow, ProgressBar, Sheet, Spinner, StatusGlyph, Toggle } from './ui.tsx';
import { WaitClock } from './moments.tsx';

export const vt = (name: string): CSSProperties => ({ viewTransitionName: name } as CSSProperties);

// Manifest keys of sources with several parts (Google, Instagram...), in words. iPhone parts: shared/phone.ts.
const SOURCE_NAMES: Record<string, string> = {
  google_activity: 'Search, YouTube and Maps activity', chrome_synced: 'Chrome (synced)', google_chat: 'Google Chat and Hangouts', gmail: 'Gmail',
  google_maps_places: 'Maps places', instagram_activity: 'Instagram activity', facebook_activity: 'Facebook activity', notion_export: 'Notion pages',
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

export function AddServiceSheet({ onClose, onAdded }: { onClose: () => void; onAdded: (id: string) => void }) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [err, setErr] = useState('');
  return (
    <Sheet onClose={onClose} testId="add-service" width={440}>
      <form onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) return setErr('Enter the service\'s name.');
        void api.action('*', 'add-service', { name, url }).then((r) => (r.ok && r.id ? (onAdded(r.id), onClose()) : setErr(r.error ?? 'Couldn\'t add it.')));
      }}>
        <h2>Add Another Service</h2>
        <p>Any site or app that holds your data, however small. Whatever it gives you is kept, file by file, whatever the format; the steps show how to ask for it.</p>
        <div className="form-grid" style={{ padding: '12px 0 0' }}>
          <label htmlFor="svc-name">Name</label>
          <input id="svc-name" autoFocus value={name} placeholder="Wattpad" onChange={(e) => { setName(e.target.value); setErr(''); }} />
          <label htmlFor="svc-url">Website</label>
          <input id="svc-url" value={url} placeholder="wattpad.com (optional)" onChange={(e) => setUrl(e.target.value)} />
        </div>
        {err && <div className="form-error error">{err}</div>}
        <div className="sheet-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" testAction="add-service">Add</Button>
        </div>
      </form>
    </Sheet>
  );
}

// ---------------------------------------------------------------- reading an unknown format

// A service you added is first kept file by file. Claude can read the download's structure and write a mapping
// that turns it into posts, comments, purchases..., which the person checks before it's used.
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
          <GroupRow title="Read as generic records" subtitle={`${count(view.records)} kept so far`} />
        )}
        <div className="kv">
          <Button kind="plain" ai onClick={() => setOpen(true)} testAction="open-mapping">{m ? 'Remake the Mapping…' : `Ask ${snap.claude === 'codex' ? 'Codex' : 'Claude'} to Make Sense of It…`}</Button>
          {m ? <Button kind="plain" onClick={() => void api.action(view.id, 'remove-mapping')} testAction="remove-mapping">Stop Using It</Button> : <span />}
        </div>
      </Group>
      {open && <MappingSheet snap={snap} view={view} onClose={() => setOpen(false)} />}
    </>
  );
}

function MappingSheet({ snap, view, onClose }: { snap: Snapshot; view: SourceView; onClose: () => void }) {
  const [examples, setExamples] = useState(false);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  const [preview, setPreview] = useState<MappingPreview | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    setPrompt(null);
    void api.action(view.id, 'describe-export', { examples }).then((r) => (r.ok ? setPrompt((r.data as { prompt: string }).prompt) : setErr(r.error ?? 'Couldn\'t read the download.')));
  }, [examples]);
  const check = (text: string) => {
    setBusy('Checking it against the whole download…');
    setErr('');
    void api.action(view.id, 'try-mapping', { text }).then((r) => (r.ok ? setPreview(r.data as MappingPreview) : setErr(r.error ?? 'That mapping didn\'t work.'))).finally(() => setBusy(null));
  };
  const ask = () => {
    setBusy('Claude is reading the structure…');
    setErr('');
    void api.action(view.id, 'ask-claude', { prompt }).then((r) => {
      if (!r.ok) return setErr(`Couldn't ask Claude: ${r.error}. Copy the request instead.`);
      setReply(r.data as string);
      check(r.data as string);
    }).finally(() => setBusy((b) => (b?.startsWith('Claude') ? null : b)));
  };
  const use = () => void api.action(view.id, 'save-mapping', { mapping: preview!.mapping }).then((r) => (r.ok ? onClose() : setErr(r.error ?? 'Couldn\'t save it.')));
  return (
    <Sheet onClose={onClose} testId="mapping-sheet" width={640}>
      {!preview ? (
        <>
          <h2>Make sense of your {view.name} download</h2>
          <p>Claude sees the download's structure: its files, field names and the kinds of values they hold. Your content stays on this Mac
            {examples ? ', apart from one example value per field' : ''}. This is everything that would be sent:</p>
          <pre className="prompt" data-testid="mapping-prompt">{prompt ?? 'Reading the download…'}</pre>
          <label className="check"><input type="checkbox" checked={examples} onChange={(e) => setExamples(e.target.checked)} /> Include one example value per field (a better mapping; those values leave this Mac)</label>
          {!snap.claude ? <p style={{ marginTop: 10 }}>There's no Claude on this Mac to ask directly. Copy the request into any Claude chat, then paste its reply here.</p>
            : snap.settings.aiOn !== true && (
              <div className="note" style={{ marginTop: 10 }} data-testid="mapping-ai-off"><AiMark size={13} /><span>AI is off in Homecoming, so nothing is sent from here. Turn it on to ask {snap.claude === 'codex' ? 'Codex' : 'Claude'}, or copy the request into any chat.</span>
                <Button size="small" ai onClick={() => void api.settings({ aiOn: true, aiAgreedAt: snap.settings.aiAgreedAt ?? new Date().toISOString() })} testAction="mapping-ai-on">Turn On AI</Button></div>
            )}
          <textarea className="reply" placeholder="Claude's reply (the mapping)" value={reply} onChange={(e) => setReply(e.target.value)} data-testid="mapping-reply" />
          {busy && <div className="note"><Spinner size={12} /><span>{busy}</span></div>}
          {err && <div className="form-error error" data-testid="mapping-error">{err}</div>}
          <div className="sheet-actions">
            <Button onClick={onClose}>Cancel</Button>
            <Button onClick={() => prompt && void navigator.clipboard.writeText(prompt)} disabled={!prompt} testAction="copy-request">Copy Request</Button>
            {reply.trim() ? <Button kind="primary" onClick={() => check(reply)} disabled={!!busy} testAction="check-mapping">Check It</Button>
              : snap.claude && snap.settings.aiOn === true && <Button kind="primary" ai onClick={ask} disabled={!prompt || !!busy} testAction="ask-claude">{snap.claude === 'codex' ? 'Ask Codex' : 'Ask Claude'}</Button>}
          </div>
        </>
      ) : (
        <>
          <h2>What the mapping finds</h2>
          <p>Run over the whole download, nothing saved yet. {preview.mapped} of {preview.structured} data file{preview.structured === 1 ? '' : 's'} read.</p>
          <div className="group-box" style={{ marginTop: 12 }} data-testid="mapping-preview">
            {preview.rules.map((r, i) => (
              <GroupRow key={i} title={<>{r.describe}<span className="tag">{r.kind}</span></>}
                subtitle={r.items ? `${count(r.items)} found${r.items ? `, ${Math.round((r.timed / r.items) * 100)}% with a time` : ''}${r.sample[0] ? ` · “${(r.sample[0].title ?? r.sample[0].text ?? '').slice(0, 80)}”` : ''}` : 'Nothing found: the mapping may name the wrong file or field'}
                trailing={count(r.items)} />
            ))}
          </div>
          <p style={{ marginTop: 10 }}>The mapping is kept on this Mac, for your {view.name} downloads only.</p>
          {preview.unmapped.length > 0 && <p style={{ marginTop: 10 }}>Still kept file by file: {preview.unmapped.slice(0, 6).join(', ')}{preview.unmapped.length > 6 ? ` and ${preview.unmapped.length - 6} more` : ''}.</p>}
          {err && <div className="form-error error">{err}</div>}
          <div className="sheet-actions">
            <Button onClick={() => setPreview(null)}>Back</Button>
            <Button kind="primary" onClick={use} disabled={!preview.rules.some((r) => r.items)} testAction="use-mapping">Use It</Button>
          </div>
        </>
      )}
    </Sheet>
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

export function Steps({ view }: { view: SourceView }) {
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
          <input type="checkbox" checked={done[i] ?? s.done} onChange={() => toggle(i)} aria-label={`Step ${i + 1}`} />
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
export function IdentityPicker({ snap, onSubmit, busy, submitLabel = 'Save', hideSubmit, formId }: {
  snap: Snapshot; onSubmit: (id: Identity, dismissed: string[]) => void; busy: boolean; submitLabel?: string; hideSubmit?: boolean; formId?: string;
}) {
  const found = pickerRows(snap.identityCandidates ?? [], snap.identity, snap.identityDismissed ?? []);
  const [extra, setExtra] = useState<PickRow[]>([]);
  const rows = [...found, ...extra.filter((e) => !found.some((r) => r.key === e.key))];
  const touched = useRef(new Set<string>());
  const [checked, setChecked] = useState<Set<string>>(() => new Set(found.filter((r) => r.checked).map((r) => r.key)));
  // Candidates arrive a moment after the page opens: tick the strong ones unless the person already chose.
  const sig = found.map((r) => `${r.key}${r.checked}`).join();
  useEffect(() => {
    setChecked((prev) => {
      const n = new Set(prev);
      for (const r of found) if (!touched.current.has(r.key) && r.checked) n.add(r.key);
      return n;
    });
  }, [sig]);
  const [drafts, setDrafts] = useState<Record<Kind, string>>({ name: '', email: '', username: '', phone: '' });
  const [err, setErr] = useState('');
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
      const id = buildIdentity(rows, checked);
      if (!id.names.length || !id.emails.length) return setErr('Keep at least one name and one email address.');
      const dismissed = rows.filter((r) => !checked.has(r.key) && r.sources.some((x) => x.label !== 'Added by you')).map((r) => r.key);
      onSubmit(id, dismissed);
    }}>
      {KINDS.map((k) => {
        const mine = rows.filter((r) => r.kind === k.kind);
        return (
          <Group key={k.kind} title={k.label}>
            <div className="group-box">
              {mine.map((r) => (
                <label key={r.key} className="cand-row" data-testid={`cand-${r.key}`}>
                  <input type="checkbox" checked={checked.has(r.key)} onChange={() => flip(r.key)} aria-label={r.value} />
                  <div className="main">
                    <div className="v">{r.value}{r.isNew && <span className="tag new">New</span>}{!r.strong && <span className="tag">Maybe</span>}</div>
                    <div className="src">{r.sources.slice(0, 3).map((x) => (x.count ? `${x.label} · ${count(x.count)}` : x.label)).join('  ·  ')}{r.sources.length > 3 ? `  +${r.sources.length - 3} more` : ''}</div>
                  </div>
                </label>
              ))}
              <div className="cand-add">
                <input id={`add-${k.kind}`} type="text" placeholder={`${k.add}…`} value={drafts[k.kind]}
                  onChange={(e) => setDrafts({ ...drafts, [k.kind]: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(k.kind); } }} />
                <Button onClick={() => add(k.kind)} testAction={`add-${k.kind}`}>Add</Button>
              </div>
            </div>
          </Group>
        );
      })}
      {err && <div className="form-error error" style={{ padding: '8px 2px 0' }}>{err}</div>}
      {!hideSubmit && <div style={{ marginTop: 14 }}><Button kind="primary" type="submit" disabled={busy}>{submitLabel}</Button></div>}
    </form>
  );
}

export function SkipForm({ view, action, onSubmit, onCancel }: { view: SourceView; action: Action; onSubmit: (r: string) => void; onCancel: () => void }) {
  const reasons = action.id === 'cant-export'
    ? ['My account is on a school or work workspace (only admins can export)', 'The site has no export for my account']
    : [`I don't use ${view.name}`, 'Not now', 'I\'ll do it another way'];
  return (
    <Sheet onClose={onCancel} testId="skip-form">
      <h2>{action.id === 'cant-export' ? `Why can't ${view.name} export?` : `Skip ${view.name}?`}</h2>
      <p>It moves to Not Available. You can include it again any time.</p>
      <div className="sheet-actions" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
        {reasons.map((r) => <Button key={r} onClick={() => onSubmit(r)}>{r}</Button>)}
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
          <input id="acct" type="text" value={name} placeholder="hotmail" onChange={(e) => setName(e.target.value)} />
          <Button onClick={() => void api.action(view.id, 'set-account', { name })}>Save</Button>
        </div>
      </div>
      <div className="form-hint">Becomes the source name, e.g. hotmail or work_mail.</div>
    </div>
  );
}

// ---------------------------------------------------------------- detail

// Do It for Me, the first time: Claude Code works in the person's Chrome, where they're signed in, and stops only for
// what's theirs to do.
export function AgentOptIn({ snap, onClose, onOn }: { snap: Snapshot; onClose: () => void; onOn: () => void }) {
  const [downloads, setDownloads] = useState(snap.settings.agentDownloads !== false);
  const installed = snap.ask.installed['claude-code'];
  return (
    <Sheet onClose={onClose} testId="agent-opt-in" width={480}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 7 }}><AiMark size={16} />Let Claude request and download your exports?</h2>
      <p>Claude Code opens each service's export page in your Chrome, where you're signed in, picks the right options and requests your data. When the service says it's ready, Claude downloads it, and the app reads it from Downloads.</p>
      <p>It stops and tells you when it needs you to sign in, enter a code, or prove you're not a robot. It uses the Claude in Chrome extension and your Claude account.</p>
      {snap.settings.aiOn !== true && <p data-testid="agent-ai-note">This turns on AI in Homecoming, so Ask can use it too. You can turn it off on the AI page.</p>}
      {!installed && <div style={{ marginTop: 10 }}><Banner kind="warning">Claude Code isn't on this Mac yet. Install it, and turn on the Claude in Chrome extension.</Banner></div>}
      <label className="check" style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, marginTop: 12 }}>
        <input type="checkbox" checked={downloads} onChange={(e) => setDownloads(e.target.checked)} data-testid="agent-downloads" />
        <span>Download exports by themselves when they're ready</span>
      </label>
      <div className="sheet-actions">
        <Button onClick={onClose}>Not Now</Button>
        <Button kind="primary" ai testAction="agent-on" onClick={() => void api.settings({ aiOn: true, aiAgreedAt: snap.settings.aiAgreedAt ?? new Date().toISOString(), agentExports: true, agentDownloads: downloads }).then(onOn)}>Turn On</Button>
      </div>
    </Sheet>
  );
}

// A Do It for Me button anywhere (the Setup Assistant's export pages): asks the first time, like the detail page does.
export function AgentButton({ snap, id, action }: { snap: Snapshot; id: string; action: Action }) {
  const [optIn, setOptIn] = useState(false);
  const go = () => void api.action(id, action.id);
  const needsOptIn = (action.id === 'agent-request' || action.id === 'agent-download') && !snap.settings.agentExports;
  return (
    <>
      <Button kind={action.primary ? 'primary' : 'default'} ai={action.ai} onClick={() => (needsOptIn ? setOptIn(true) : go())} testAction={action.id}>{action.label}</Button>
      {optIn && <AgentOptIn snap={snap} onClose={() => setOptIn(false)} onOn={() => { setOptIn(false); go(); }} />}
    </>
  );
}

export function Detail({ snap, view, onActed }: { snap: Snapshot; view: SourceView; onActed?: (id: string) => void }) {
  const [form, setForm] = useState<Action | null>(null);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [optIn, setOptIn] = useState<Action | null>(null);
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
    if (p && (p.input === 'password' || p.input === 'identity') && view.section === 'needs') setForm(p);
    else setForm(null);
  }, [view.id, view.section, view.status]);

  const run = async (a: Action, payload?: unknown, optedIn = false) => {
    if (a.confirm && !(payload as { confirmed?: boolean })?.confirmed) return setConfirm(a);
    // Do It for Me asks once: what it does, and whether downloads should start by themselves.
    if ((a.id === 'agent-request' || a.id === 'agent-download') && !snap.settings.agentExports && !optedIn) return setOptIn(a);
    if ((a.input === 'password' || a.input === 'identity' || a.input === 'skip-reason') && payload === undefined) return setForm(a);
    setBusy(true);
    setError(null);
    onActed?.(view.id);
    const r = await api.action(view.id, a.id, payload);
    setBusy(false);
    if (!r.ok && r.error && r.error !== 'read-only') setError(r.error);
    else if (a.input !== 'identity') setForm(null);
  };

  const isDropTarget = ['web', 'guided'].includes(view.group);
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
          <div style={{ marginTop: 1 }}>{view.waiting ? <WaitClock size={18} started={view.requestedAt} /> : <StatusGlyph section={view.section} size={18} />}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="big appear-soft" key={view.status} data-testid="status">{view.status}</div>
            {view.detail && <div className="pre" data-testid="state-detail">{view.detail}</div>}
            {view.section === 'working' && !view.waiting && <ProgressBar value={view.progress} small />}
          </div>
        </div>
        {/* Claude asked something: what you write here goes back to it with Continue. */}
        {view.actions.some((a) => a.id === 'agent-continue') && (
          <div className="agent-reply">
            <input type="text" value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Answer Claude here, or leave it empty once you've done it in Chrome"
              onKeyDown={(e) => e.key === 'Enter' && void run(view.actions.find((a) => a.id === 'agent-continue')!, { reply }).then(() => setReply(''))} data-testid="agent-reply" />
          </div>
        )}
        {view.actions.length > 0 && (
          <div className="actions" data-testid="actions">
            {view.actions.map((a) => <Button key={a.id} kind={a.primary ? 'primary' : 'default'} ai={a.ai} disabled={busy}
              onClick={() => void (a.id === 'agent-continue' ? run(a, { reply }).then(() => setReply('')) : run(a))} testAction={a.id}>{a.label}</Button>)}
          </div>
        )}
        {error && <div style={{ padding: '0 14px 12px 42px' }}><Banner kind="error"><span data-testid="error">{error}</span></Banner></div>}
      </div>

      {form?.input === 'password' && <Group title="Unlock the backup"><PasswordForm onSubmit={(pw) => run(form, { password: pw })} busy={busy} /></Group>}
      {form?.input === 'identity' && <IdentityPicker snap={snap} onSubmit={(identity, dismissed) => run(form, { identity, dismissed })} busy={busy} />}
      {form?.input === 'skip-reason' && <SkipForm view={view} action={form} onSubmit={(reason) => run(form, { reason })} onCancel={() => setForm(null)} />}
      {view.id === 'other_mail' && <Group title="Account"><AccountForm view={view} /></Group>}

      {view.warnings.map((w, i) => <div key={i} style={{ marginTop: 12 }}><Banner kind="warning"><span data-testid="warning">{w}</span></Banner></div>)}

      {view.section === 'done' && view.records > 0 && (
        <Group title="Details">
          <div className="kv"><span>Records</span><span>{count(view.records)}</span></div>
          <div className="kv"><span>Since</span><span>{view.first ? view.first.slice(0, 4) : '—'}</span></div>
          <div className="kv"><span>Last read</span><span>{view.ranAt ? ago(view.ranAt, new Date()) : '—'}</span></div>
        </Group>
      )}

      {(view.group === 'mac' || BY_ID[view.id]?.custom) && <Contents view={view} />}
      <MakeSenseOfIt snap={snap} view={view} />

      {view.steps && view.steps.length > 0 && <Group title="Steps"><Steps view={view} /></Group>}

      {view.id === 'iphone_backup' && view.section === 'done' && <PhoneParts view={view} />}
      {view.id !== 'iphone_backup' && view.parts && view.parts.length > 1 && (
        <Group title="Parts">
          {view.parts.slice(0, 14).map((p) => <div className="kv" key={p.name}><span>{prettySource(p.name)}</span><span>{count(p.records)}</span></div>)}
          {view.parts.length > 14 && <div className="kv"><span>{view.parts.length - 14} more</span><span>{count(view.parts.slice(14).reduce((n, p) => n + p.records, 0))}</span></div>}
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
          Drop the {view.name} download here, or <Button kind="plain" onClick={() => void run({ id: 'add-file', label: '' })}>choose it…</Button>
        </div>
      )}

      {optIn && <AgentOptIn snap={snap} onClose={() => setOptIn(null)} onOn={() => { const a = optIn; setOptIn(null); void run(a, undefined, true); }} />}

      {confirm && (
        <Sheet onClose={() => setConfirm(null)} testId="confirm">
          <h2>{confirm.label}?</h2>
          <p>{confirm.confirm}</p>
          <div className="sheet-actions">
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            <Button kind="primary" onClick={() => { const a = confirm; setConfirm(null); void run(a, { confirmed: true }); }}>Continue</Button>
          </div>
        </Sheet>
      )}
    </div>
  );
}

