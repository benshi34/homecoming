// The Setup Assistant: one thing per page, like setting up a new Mac. Every page shows live status from the
// same snapshot as the main window, so a step that finishes in the background turns green in place.

import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { BY_ID } from '../shared/catalog.ts';
import { READ_ONLY_NOTE, READ_ONLY_OK } from '../shared/status.ts';
import { count, waitRange } from '../shared/format.ts';
import { accountChoices, assistantSteps, commonAccounts, defaultChosen, exportHandled, KEEP_GROUPS, LIBRARY_SOURCES, nextExportStep, progress, readyIn, recommended, STEP_GROUPS, type Step, stepIndex } from '../shared/progress.ts';
import type { Action, FoundService, Snapshot, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { Glyph, GlyphTile, SourceIcon } from './icons.tsx';
import { AiAgreement, AiSettings } from './ai.tsx';
import { Hub, type HubFilter } from './hub.tsx';
import { Timeline } from './main_window.tsx';
import { agentGate, AgentGateSheet, type Gate } from './agent_gate.tsx';
import { AccountForm, AddServiceSheet, AgentButton, AgentOptIn, InboxButton, ContentsLines, evidenceLine, IdentityPicker, PasswordForm, PhoneParts, SkipForm, Steps, vt } from './parts.tsx';
import { AiMark, animate, Banner, Button, Checkmark, Group, GroupRow, ProgressBar, reducedMotion, Sheet, Spinner, StatusGlyph, Toggle } from './ui.tsx';
import { Tick, WaitClock } from './moments.tsx';
import { NotificationsBox } from './notifications.tsx';
import { RequestAllSheet } from './request_all.tsx';
import { requestPlan } from '../shared/request_all.ts';
import { Welcome } from './welcome.tsx';
import { ClaudeWork } from './claude_work.tsx';

interface PageSpec {
  body: ReactNode;
  // quiet: drawn as a plain button, when the page has its own thing to do first (one blue button per page).
  primary?: { label: string; onClick: () => void; disabled?: boolean; done?: boolean; ai?: boolean; quiet?: boolean };
  secondary?: ReactNode;
  wide?: boolean;
}

// "a, b, and c"; "a and b".
const and = (xs: string[]) => (xs.length < 3 ? xs.join(' and ') : `${xs.slice(0, -1).join(', ')}, and ${xs[xs.length - 1]}`);
// Read-only mode (not the demo): nothing chosen on a page is kept, so its controls are disabled, with the note.
const lockedHere = (ctx: { snap: Snapshot }) => ctx.snap.readOnly && !ctx.snap.demo;
const lockTitle = (locked: boolean) => (locked ? READ_ONLY_NOTE : undefined);

export function Assistant({ snap, onFinish, onExit }: { snap: Snapshot; onFinish: (showId?: string) => void; onExit: () => void }) {
  const views = snap.sources;
  const steps = useMemo(() => assistantSteps(views, snap.onboarding.chosen), [views, snap.onboarding.chosen]);
  // The page, by id: when the step list changes (accounts chosen, one dropped), the same page stays up.
  // Opened again once it's all done: from the start, as General's "Go through setting up again" says (part-way, where it was).
  const [at, setAt] = useState(() => steps[stepIndex(steps, snap.onboarding.done && snap.onboarding.step === 'done' ? 'welcome' : snap.onboarding.step)].id);
  // What you last chose, plus services added since (from the hub, or the main window) that you haven't turned down.
  const [draft, setDraft] = useState<Set<string>>(() => new Set([...(snap.onboarding.chosen ?? defaultChosen(views)),
    ...views.filter((x) => BY_ID[x.id]?.custom && x.section !== 'unavailable').map((x) => x.id)]));
  const i = stepIndex(steps, at);
  const step = steps[i];
  const v = (id: string) => views.find((x) => x.id === id)!;
  // The export pages shown so far: Continue doesn't send you back to one you've been past.
  const seen = useRef(new Set<string>());
  if (step.kind === 'export') seen.current.add(step.sourceId!);
  // Do It for Me from the footer, the first time: its one-time choice, then it carries on.
  const [optIn, setOptIn] = useState<(() => void) | null>(null);
  const [gate, setGate] = useState<{ g: Exclude<Gate, null>; go: () => void } | null>(null);
  const doIt = (id: string, then: () => void) => {
    const go = () => void api.action(id, 'agent-request').then((r) => r.ok && then());
    // Not yet with the AI picked: said at once. Otherwise what it does (the first time, which asks Anthropic's data
    // settings itself), or the data settings when they're due (agent_gate.tsx).
    const g = agentGate(snap);
    if (g === 'not-yet') setGate({ g, go });
    else if (!snap.settings.agentExports || snap.settings.aiOn !== true) setOptIn(() => go);
    else if (g === 'retention') setGate({ g, go });
    else go();
  };

  const goTo = (n: number, dir: 'forward' | 'back') => {
    if (n < 0 || n >= steps.length) return;
    animate(() => setAt(steps[n].id), dir);
    void api.onboarding({ step: steps[n].id });
  };
  const next = () => goTo(i + 1, 'forward');
  const back = () => goTo(i - 1, 'back');
  const jump = (id: string) => {
    const n = steps.findIndex((s) => s.id === id);
    if (n >= 0) goTo(n, n > i ? 'forward' : 'back');
  };

  // Saying you've requested an export is a commitment: the button turns into a checkmark for a beat, then moves on.
  const [justAsked, setJustAsked] = useState<string | null>(null);
  const confirmed = (id: string, then: () => void) => {
    setJustAsked(id);
    setTimeout(() => {
      setJustAsked(null);
      then();
    }, reducedMotion() ? 150 : 750);
  };
  const page = renderStep(step, { snap, v, next, jump, onFinish, steps, index: i, draft, setDraft, justAsked, confirmed, seen: seen.current, doIt });
  return (
    <div className="assistant" data-testid="assistant" data-step={step.id}>
      <StepsBar steps={steps} index={i} />
      <div className="page-wrap">
        <div style={vt('page')} key={step.id}>
          <div className={`page ${page.wide ? 'wide' : ''}`}>{page.body}</div>
        </div>
      </div>
      {/* Claude at work (asked for on an earlier page): how it's going, what it needs from you, and Stop. */}
      <div className="assistant-work"><ClaudeWork snap={snap} compact /></div>
      <div className="footer-bar">
        {i > 0 && <Button onClick={back} testAction="assistant-back">Back</Button>}
        {step.kind !== 'done' && <Button kind="plain" onClick={onExit} testAction="assistant-exit">Skip Setup Assistant</Button>}
        <div className="spacer" />
        <StepCount steps={steps} index={i} />
        {page.secondary}
        {page.primary && <Button kind={page.primary.quiet ? 'default' : 'primary'} size="large" onClick={page.primary.onClick} disabled={page.primary.disabled || page.primary.done} testAction="assistant-continue" ai={page.primary.ai}
          className={page.primary.done ? 'is-done' : ''}>{page.primary.done && <Tick size={13} />}{page.primary.label}</Button>}
      </div>
      {optIn && <AgentOptIn snap={snap} onClose={() => setOptIn(null)} onOn={() => { optIn(); setOptIn(null); }} />}
      {gate && <AgentGateSheet snap={snap} gate={gate.g} onClose={() => setGate(null)} onOk={() => { const x = gate; setGate(null); x.go(); }} />}
    </div>
  );
}

// Where you are, by the timeline's steps: a count that doesn't jump when accounts are chosen (each export is
// one step of Exports, counted in the timeline instead).
function StepCount({ steps, index }: { steps: Step[]; index: number }) {
  const groups = STEP_GROUPS.filter((g) => steps.some((s) => s.group === g));
  return <span className="where" data-testid="step-count">{groups.indexOf(steps[index].group) + 1} of {groups.length}</span>;
}

function StepsBar({ steps, index }: { steps: Step[]; index: number }) {
  const groups = STEP_GROUPS.filter((g) => steps.some((s) => s.group === g));
  const current = steps[index].group;
  const ci = groups.indexOf(current);
  const exports = steps.filter((s) => s.kind === 'export');
  const ei = exports.findIndex((s) => s.id === steps[index].id);
  return (
    <div className="steps-bar drag" data-testid="steps-bar">
      {groups.map((g, k) => (
        <div key={g} className={`sb-item ${k < ci ? 'done' : ''} ${k === ci ? 'current' : ''}`} data-testid={`sb-${g}`}>
          <div className="sb-dot" />
          <div className="sb-label">{g === 'Exports' && exports.length ? (ei >= 0 ? `Exports ${ei + 1}/${exports.length}` : `Exports (${exports.length})`) : g}</div>
        </div>
      ))}
    </div>
  );
}

function Hero({ icon, title, badge, children }: { icon: ReactNode; title: string; badge?: string; children?: ReactNode }) {
  return (
    <div className="hero">
      {icon}
      <h1>{title}</h1>
      {badge && <span className="badge">{badge}</span>}
      {children && <p>{children}</p>}
    </div>
  );
}

interface Ctx {
  snap: Snapshot;
  v: (id: string) => SourceView;
  next: () => void;
  jump: (stepId: string) => void;
  onFinish: (showId?: string) => void;
  steps: Step[];
  index: number;
  draft: Set<string>;
  setDraft: (s: Set<string>) => void;
  justAsked: string | null; // the export just marked requested: its button shows a checkmark for a beat
  confirmed: (id: string, then: () => void) => void;
  seen: ReadonlySet<string>; // the export pages shown so far
  doIt: (id: string, then: () => void) => void; // Do It for Me for this one (asking the first time), then on
}

function renderStep(step: Step, ctx: Ctx): PageSpec {
  switch (step.kind) {
    case 'welcome': return welcome(ctx);
    case 'identity': return identity(ctx);
    case 'access': return access(ctx);
    case 'library': return { body: <LibraryPage ctx={ctx} />, primary: { label: 'Continue', onClick: ctx.next } };
    case 'keep': return { body: <KeepPage ctx={ctx} />, primary: { label: 'Continue', onClick: ctx.next } };
    case 'mac': return mac(ctx);
    // While the page has something to do (read it, unlock it, allow access), that's its blue button.
    case 'iphone': return { body: <IphonePage ctx={ctx} />, primary: { label: 'Continue', onClick: ctx.next, quiet: iphoneToDo(ctx.v('iphone_backup')) } };
    case 'accounts': {
      // Found services you ticked become sources first, so their export pages join the steps. What you chose is then
      // those sources, so going Back shows them under Your accounts (not as found ones to add again).
      const apply = () => {
        if (lockedHere(ctx)) return ctx.next(); // read-only: the accounts stay as they are
        const picked = [...ctx.draft];
        void api.action('*', 'choose-services', { slugs: picked.filter((x) => x.startsWith('found:')).map((x) => x.slice(6)),
          domains: picked.filter((x) => x.startsWith('sender:')).map((x) => x.slice(7)) })
          .then((r) => {
            const chosen = [...picked.filter((x) => !/^(found|sender):/.test(x)), ...(r.ids ?? [])];
            ctx.setDraft(new Set(chosen));
            return api.action('*', 'choose-accounts', { chosen });
          })
          .then(() => ctx.next());
      };
      const n = listedChoices(ctx).length;
      return { body: <AccountsPage ctx={ctx} />, primary: { label: n ? `Continue with ${n}` : 'Continue', onClick: apply } };
    }
    case 'notifications': return notifications(ctx);
    case 'ai': return ai(ctx);
    case 'exports': return exportsList(ctx);
    case 'export': return exportPage(ctx, step.sourceId!);
    case 'done': return done(ctx);
  }
}

// ---------------------------------------------------------------- pages

function welcome(ctx: Ctx): PageSpec {
  return { primary: { label: 'Get Started', onClick: ctx.next }, wide: true, body: <Welcome /> };
}

function identity(ctx: Ctx): PageSpec {
  // Read-only mode keeps who you are as it is (the form says so): Continue just goes on.
  const locked = lockedHere(ctx);
  return {
    primary: { label: 'Continue', onClick: locked ? ctx.next : () => (document.getElementById('identity-step') as HTMLFormElement | null)?.requestSubmit() },
    // Not now is fine: it's asked again at the top of To Do, and collecting doesn't wait for it.
    secondary: ctx.v('identity').section !== 'done' && !locked ? <Button onClick={ctx.next} testAction="identity-later">Skip for Now</Button> : undefined,
    body: <IdentityPage ctx={ctx} />,
  };
}

function IdentityPage({ ctx }: { ctx: Ctx }) {
  const view = ctx.v('identity');
  const [err, setErr] = useState('');
  const save = (id: unknown, dismissed: string[]) => void api.action('identity', 'save-identity', { identity: id, dismissed })
    .then((r) => (r.ok ? ctx.next() : setErr(r.error === 'read-only' ? READ_ONLY_NOTE : `Couldn't save it: ${r.error ?? 'something went wrong'}. Try again, or skip it for now.`)));
  const found = ctx.snap.identityCandidates ?? [];
  const looking = !found.length && !ctx.snap.identityCandidatesReady;
  return (
    <>
      <Hero icon={<SourceIcon id="identity" size={64} />} title={found.length || looking ? 'Which of these are you?' : 'Who are you?'}>
        {found.length
          ? 'These turned up in your data: on this Mac, in your exports and in your chats. Tick the ones that are you. It decides which messages, emails and commits are marked as yours.'
          : looking ? 'Your names, email addresses and usernames decide which messages, emails and commits are marked as yours.'
            : 'Nothing that looks like you turned up yet. Type your name and an email address below: they decide which messages, emails and commits are marked as yours.'}
      </Hero>
      {looking && <div className="note" style={{ justifyContent: 'center', marginTop: 14 }}><Spinner size={12} /><span>Looking around this Mac…</span></div>}
      <IdentityPicker snap={ctx.snap} formId="identity-step" busy={false} hideSubmit onSubmit={save} />
      {err && <div className="form-error error" data-testid="identity-error">{err}</div>}
      <div className="note"><Glyph name="info" size={13} /><span>Nothing was held back while you went through the steps: everything is collected either way. Exports still on their way will turn up more, and the app asks about them then and re-labels what's already in.</span></div>
      {view.section === 'done' && <div className="note" style={{ justifyContent: 'center' }}><Checkmark size={13} /><span>Saved: {view.status}</span></div>}
    </>
  );
}

function access(ctx: Ctx): PageSpec {
  const view = ctx.v('fda');
  const granted = view.section === 'done';
  const unlocks = ctx.snap.sources.filter((s) => s.blockedBy === 'fda' && s.group !== 'setup');
  const missing = !granted && view.section === 'todo';
  return {
    // Going on without it is allowed, and said plainly: its button is the blue one until then.
    primary: missing ? { label: 'Continue Without It', onClick: ctx.next, quiet: true } : { label: 'Continue', onClick: ctx.next },
    body: (
      <>
        <Hero icon={<SourceIcon id="fda" size={64} />} title="Allow Full Disk Access">
          macOS keeps Messages, Mail, Photos, Notes, Calendar and call history behind one permission. Turn it on once and every source on this Mac can be read.
        </Hero>
        <div className="group-box" style={{ marginTop: 22 }} data-testid="fda-status">
          <div className="status-box">
            <div style={{ marginTop: 1 }}>{granted ? <Checkmark size={20} /> : <StatusGlyph section={view.section} needsYou={view.needsYou} size={20} />}</div>
            <div style={{ flex: 1 }}>
              <div className="big">{granted ? 'Full Disk Access is on' : view.section === 'unavailable' ? 'Nothing on this Mac needs it' : 'Not allowed yet'}</div>
              {!granted && unlocks.length > 0 && <div className="pre">Waiting on it: {unlocks.map((u) => u.name).join(', ')}.</div>}
            </div>
          </div>
          {missing && (
            <div className="actions">
              <Button kind="primary" onClick={() => void api.action('fda', 'open-fda-settings')}>Open System Settings…</Button>
              <Button onClick={() => void api.action('fda', 'recheck')} testAction="recheck">Check Again</Button>
            </div>
          )}
        </div>
        {!granted && view.steps && <Group title="How"><Steps view={view} /></Group>}
        {missing && <div className="note"><Glyph name="info" size={13} /><span>You can go on without it: {unlocks.length ? unlocks.map((u) => u.name).join(', ') : 'those sources'} wait in To Do until it's on, and Full Disk Access in Setup Checks turns it on any time.</span></div>}
      </>
    ),
  };
}

// Confirm sheets for checks whose fix moves things (the library out of iCloud).
function useConfirm() {
  const [confirm, setConfirm] = useState<{ id: string; a: Action } | null>(null);
  const run = (id: string, a: Action) => (a.confirm ? setConfirm({ id, a }) : void api.action(id, a.id));
  const sheet = confirm && (
    <Sheet onClose={() => setConfirm(null)} testId="confirm">
      <h2>{confirm.a.label}?</h2>
      <p>{confirm.a.confirm}</p>
      <div className="sheet-actions">
        <Button onClick={() => setConfirm(null)}>Cancel</Button>
        <Button kind="primary" onClick={() => { void api.action(confirm.id, confirm.a.id, { confirmed: true }); setConfirm(null); }}>Continue</Button>
      </div>
    </Sheet>
  );
  return { run, sheet };
}

const fixFor = (x: SourceView) => x.actions.find((y) => y.primary) ?? x.actions.find((y) => y.id === 'mark-done') ?? x.actions.find((y) => y.id === 'recheck');

function LibraryPage({ ctx }: { ctx: Ctx }) {
  const { run, sheet } = useConfirm();
  const ABOUT: Record<string, string> = {
    corpus_location: 'Your library holds every message and email you have, so it stays in one folder on this Mac and out of iCloud Drive.',
    disk_space: 'A full library takes roughly 10 to 30 GB, plus room for exports while they import.',
    python_env: 'The readers that copy each source into your library run on Python.',
  };
  return (
    <>
      <Hero icon={<SourceIcon id="corpus_location" size={64} />} title="Where your library lives">
        Everything you collect goes into one private folder on this Mac. A quick check that it's in the right place and has room.
      </Hero>
      <div className="group-box" style={{ marginTop: 22 }} data-testid="library">
        {LIBRARY_SOURCES.map((id) => ctx.v(id)).filter((x) => x && x.section !== 'unavailable').map((x) => {
          const a = fixFor(x);
          return (
            <GroupRow key={x.id} testId={`check-${x.id}`} icon={<SourceIcon id={x.id} size={26} />} title={x.name}
              subtitle={<>{x.section === 'done' ? x.status : <span style={{ color: 'var(--orange)' }}>{x.status}</span>}<br />{ABOUT[x.id]}
                {x.section !== 'done' && x.detail && <div className="pre selectable" style={{ marginTop: 4 }}>{x.detail}</div>}
                {x.section !== 'done' && x.notes?.map((n) => <div key={n} style={{ marginTop: 4 }}>{n}</div>)}</>}
              trailing={x.section === 'done' ? <Checkmark size={18} /> : a ? <Button kind={a.primary ? 'primary' : 'default'} onClick={() => run(x.id, a)} testAction={a.id}>{a.label}</Button> : <StatusGlyph section={x.section} needsYou={x.needsYou} />} />
          );
        })}
      </div>
      {sheet}
    </>
  );
}

// What each retention setting does, in plain words: the default that loses data, and the setting that keeps it.
const KEEP_COPY: Record<string, { title: string; risk: string; setting: string }> = {
  retention_messages: { title: 'Messages', risk: 'Messages can delete conversations once they\'re 30 days or a year old.', setting: 'Messages → Settings → General → Keep messages: Forever' },
  retention_safari: { title: 'Safari', risk: 'Safari deletes browsing history after a year unless told otherwise.', setting: 'Safari → Settings → General → Remove history items: Manually' },
  // No risk of its own: the row's status says it, from the real setting ("Transcripts are deleted after 7 days").
  retention_claude: { title: 'Claude Code', risk: '', setting: 'Keep Them changes that one setting in Claude Code, and says first exactly what it changes.' },
  retention_codex: { title: 'Codex', risk: '', setting: '' },
  retention_shell: { title: 'Terminal', risk: '', setting: 'Keep Every Command adds a few lines to your Terminal settings, and says first exactly what it adds.' },
  retention_iphone_messages: { title: 'Messages on the iPhone', risk: 'The iPhone has its own Keep Messages setting and can delete conversations after 30 days or a year.', setting: 'iPhone Settings → Apps → Messages → Keep Messages: Forever' },
  retention_maps: { title: 'Google Maps Timeline', risk: 'Timeline deletes visits older than 3 months unless told otherwise.', setting: 'Google Maps → Your Timeline → ⋯ → Location & privacy settings → Auto-delete Timeline: Don\'t auto-delete' },
  retention_google: { title: 'Google activity and YouTube', risk: 'Newer Google accounts delete search and app activity after 18 months, and YouTube history after 36.', setting: 'Activity controls → Web & App Activity and YouTube History → Auto-delete: Don\'t auto-delete. Tick "Include Chrome history" too.' },
};

function KeepRow({ x, run }: { x: SourceView; run: (id: string, a: Action) => void }) {
  const copy = KEEP_COPY[x.id];
  const a = fixFor(x);
  return (
    <GroupRow testId={`check-${x.id}`} icon={<SourceIcon id={x.id} size={26} />}
      title={<>{copy.title}{x.section === 'done' && <span className="tag">Already keeps everything</span>}</>}
      subtitle={x.section === 'done' ? `${x.status}.` : <><span style={{ color: 'var(--orange)' }}>{copy.risk || `${x.status}.`}</span><br />{copy.setting}</>}
      trailing={x.section === 'done' ? <Checkmark size={18} /> : (
        <>
          {/* A list of settings: plain buttons, as in System Settings, not a row of blue ones. */}
          {a && <Button onClick={() => run(x.id, a)} testAction={a.id}>{a.label}</Button>}
          {a?.id !== 'mark-done' && x.actions.some((y) => y.id === 'mark-done') && <Button onClick={() => void api.action(x.id, 'mark-done')} testAction="mark-done">I've Done It</Button>}
          {x.actions.filter((y) => y.id === 'skip').map((y) => <Button key={y.id} kind="plain" onClick={() => void api.action(x.id, 'skip')} testAction="skip">{y.label}</Button>)}
          {!a && <StatusGlyph section={x.section} needsYou={x.needsYou} />}
        </>
      )} />
  );
}

function KeepPage({ ctx }: { ctx: Ctx }) {
  const { run, sheet } = useConfirm();
  const daily = ctx.snap.settings.autoRefresh;
  const backup = ctx.v('iphone_backup');
  return (
    <>
      <Hero icon={<SourceIcon id="retention_messages" size={64} />} title="Keep more of your history">
        Your library has everything that's there today. From now on, some apps and accounts quietly delete old history after a few
        weeks, months or years. These settings decide how much of it is still around to collect. They don't change anything already collected.
      </Hero>
      {KEEP_GROUPS.map((g) => {
        const rows = g.ids.map((id) => ctx.v(id)).filter((x) => x && x.section !== 'unavailable');
        if (!rows.length) return null;
        return (
          <Group key={g.title} title={g.title} testId={g.title === 'On this Mac' ? 'keep' : undefined}>
            <div className="group-box">{rows.map((x) => <KeepRow key={x.id} x={x} run={run} />)}</div>
          </Group>
        );
      })}
      <Group title="History with no setting" footer="These keep only a short window and have no setting. Reading them regularly is how nothing ages out: each read adds what's new to your library and keeps what it saw before.">
        <div className="group-box">
          <GroupRow testId="keep-daily" icon={<SourceIcon id="app_usage" size={26} />} title="Read this Mac every day"
            subtitle="Screen Time keeps about 4 weeks, the Mac's call log about 6 months, and Chrome about 90 days. Runs while the app is open."
            trailing={<Toggle checked={daily} onChange={(on) => void api.settings({ autoRefresh: on })} label="Read this Mac every day" testId="toggle-daily" />} />
          {backup && backup.section !== 'unavailable' && (
            <GroupRow testId="keep-backup" icon={<SourceIcon id="iphone_backup" size={26} />} title="Back up your iPhone every few weeks"
              subtitle={`The phone keeps call history for months, not years. Each backup the app reads keeps what it saw.${backup.detail ? ` Last: ${backup.detail.replace(/^.*backed up /, '').replace(/\..*$/, '')}.` : ''}`} />
          )}
        </div>
      </Group>
      {sheet}
    </>
  );
}

function mac(ctx: Ctx): PageSpec {
  const list = ctx.snap.sources.filter((s) => s.group === 'mac');
  const counted = list.filter((s) => s.section !== 'unavailable');
  const isRead = (s: SourceView) => s.section === 'done' || s.stage === 'read'; // read this run, saved when the run ends
  const read = counted.filter(isRead).length;
  const busy = list.some((s) => s.section === 'working');
  const ready = list.filter((s) => s.status === 'Ready to read');
  return {
    primary: { label: 'Continue', onClick: ctx.next },
    secondary: busy ? <span className="where" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Spinner size={12} />Keeps reading in the background</span> : undefined,
    body: (
      <>
        <Hero icon={<SourceIcon id="imessage" group="mac" size={64} />} title="Reading your Mac">
          Each source is copied into your library as it's read. You don't need to wait here: it carries on while you go through the next steps.
        </Hero>
        <div style={{ margin: '22px 2px 6px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flex: 1 }}><ProgressBar value={counted.length ? read / counted.length : 0} /></div>
          <span className="where" data-testid="mac-count">{read} of {counted.length} read</span>
        </div>
        {ready.length > 0 && !busy && (
          <div style={{ margin: '10px 0' }}>
            <Banner kind="info">{ready.length} {ready.length === 1 ? 'source is' : 'sources are'} ready to read. <Button kind="plain" onClick={() => void api.action('*', 'run-all-mac')}>Read Everything Now</Button></Banner>
          </div>
        )}
        <div className="group-box" data-testid="mac-sources">
          {list.map((s) => (
            <GroupRow key={s.id} testId={`mac-${s.id}`} icon={<SourceIcon id={s.id} size={26} />} title={s.name}
              subtitle={<>{s.status}<ContentsLines view={s} /></>} trailing={isRead(s) ? <Checkmark size={17} /> : s.stage === 'waiting' ? <Glyph name="clock" size={15} className="waiting-glyph" /> : <StatusGlyph section={s.section} needsYou={s.needsYou} />} />
          ))}
        </div>
      </>
    ),
  };
}

// The iPhone page has something for you to do: not read yet, a newer backup to read, or a read to try again.
const iphoneToDo = (v: SourceView) => v.section === 'todo' || !!v.needsYou || (v.section === 'done' && !!v.actions.find((a) => a.id === 'iphone-run')?.primary);

function IphonePage({ ctx }: { ctx: Ctx }) {
  const view = ctx.v('iphone_backup');
  const [busy, setBusy] = useState(false);
  // Read-only: what only looks or opens a page works; the rest is disabled, and says why.
  const locked = lockedHere(ctx);
  const off = (aid: string) => locked && !READ_ONLY_OK.has(aid);
  const pw = view.actions.find((a) => a.id === 'iphone-run');
  const forget = view.actions.find((a) => a.id === 'forget-phone');
  const act = iphoneToDo(view); // something to do on this page: read it, unlock it, make a backup, allow access
  // Over what was read from another device: asked first, as its page does (status.ts), with Take It Out.
  const [asking, setAsking] = useState<{ password?: string } | null>(null);
  const read = (password?: string, confirmed = false) => {
    if (pw?.confirm && !confirmed) return setAsking({ password });
    setBusy(true);
    void api.action('iphone_backup', 'iphone-run', { ...(password ? { password } : {}), ...(confirmed ? { confirmed } : {}) }).finally(() => setBusy(false));
  };
  return (
    <>
      <Hero icon={<SourceIcon id="iphone_backup" size={64} />} title="Add your iPhone" badge="Highly Recommended">{view.blurb}</Hero>
      <div className="group-box" style={{ marginTop: 22 }} data-testid="iphone-status">
        <div className="status-box">
          <div style={{ marginTop: 1 }}>{view.section === 'done' ? <Checkmark size={20} /> : <StatusGlyph section={view.section} needsYou={view.needsYou} size={20} />}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="big" data-testid="status">{view.status}</div>
            {view.detail && <div className="pre">{view.detail}</div>}
            {view.section === 'working' && !view.needsYou && <ProgressBar />}
          </div>
        </div>
        {act && pw && !pw.input && <div className="actions"><Button kind="primary" onClick={() => read()} disabled={busy || off('iphone-run')} title={lockTitle(off('iphone-run'))}>Read Backup</Button></div>}
        {/* Waiting on something else (Full Disk Access, a Python package): its own buttons, from the status. */}
        {act && !pw && (
          <div className="actions">
            {view.actions.filter((a) => a.id !== 'skip').map((a) => (
              <Button key={a.id} kind={a.primary ? 'primary' : 'default'} onClick={() => void api.action(a.id === 'open-fda-settings' ? 'fda' : 'iphone_backup', a.id)} testAction={a.id}
                disabled={off(a.id)} title={lockTitle(off(a.id))}>{a.label}</Button>
            ))}
          </div>
        )}
        {view.section === 'unavailable' && <div className="actions"><Button onClick={() => void api.action('iphone_backup', 'unskip')} disabled={locked} title={lockTitle(locked)}>Include It Again</Button></div>}
      </div>
      {act && pw?.input === 'password' && <Group title="Unlock the backup"><PasswordForm onSubmit={(p) => read(p)} busy={busy || locked} /></Group>}
      {forget && view.notes?.map((n) => <div key={n} className="note" data-testid="iphone-other"><Glyph name="warning" size={13} /><span>{n}</span></div>)}
      {asking && (
        <Sheet onClose={() => setAsking(null)} testId="confirm">
          <h2>Read Backup?</h2>
          <p>{pw?.confirm}</p>
          <div className="sheet-actions">
            <Button onClick={() => setAsking(null)}>Cancel</Button>
            {forget && <Button kind="destructive" onClick={() => { setAsking(null); void api.action('iphone_backup', 'forget-phone', { confirmed: true }); }} testAction="forget-phone">Take It Out First</Button>}
            <Button kind="primary" onClick={() => { const x = asking; setAsking(null); read(x.password, true); }} testAction="iphone-run-anyway">Read Anyway</Button>
          </div>
        </Sheet>
      )}
      {view.warnings.map((w, k) => <div key={k} style={{ marginTop: 12 }}><Banner kind="warning">{w}</Banner></div>)}
      {view.steps && act && <Group title="Make a backup"><Steps view={view} locked={locked} /></Group>}
      {view.section === 'done' && <PhoneParts view={view} />}
      {view.section === 'working' && view.notes?.map((n) => <div key={n} className="note"><Glyph name="info" size={13} /><span>{n}</span></div>)}
      {view.section === 'working' && <div className="note"><Glyph name="info" size={13} /><span>This keeps going in the background. Continue whenever you like.</span></div>}
      {/* Later is set aside (it comes back in To Do); no iPhone at all is said once, for its checks too. */}
      {act && view.section !== 'done' && <div style={{ display: 'flex', justifyContent: 'center', gap: 14, marginTop: 12 }}>
        <Button kind="plain" onClick={() => void api.action('iphone_backup', 'skip', { reason: 'Not now' }).then(ctx.next)} testAction="iphone-later" disabled={locked} title={lockTitle(locked)}>Back Up Later</Button>
        <Button kind="plain" onClick={() => void api.action('iphone_backup', 'skip', { reason: 'No iPhone' }).then(ctx.next)} testAction="iphone-none" disabled={locked} title={lockTitle(locked)}>I Don't Have an iPhone</Button>
      </div>}
      {locked && <div className="note" data-testid="iphone-locked"><Glyph name="info" size={13} /><span>{READ_ONLY_NOTE}</span></div>}
    </>
  );
}

// One account on the Accounts page, wherever it is: a built-in, a service already added, or one found in your data.
interface Account { id: string; name: string; subtitle: string; tag?: string; rank: number }

// The chosen accounts that are on the page: what "Continue with N" counts.
function listedChoices(ctx: Ctx): string[] {
  const here = new Set(accountChoices(ctx.snap.sources).map((x) => x.id));
  const found = new Set([...(ctx.snap.discovery?.found ?? []).map((f) => `found:${f.slug}`), ...(ctx.snap.discovery?.unmatched ?? []).map((u) => `sender:${u.domain}`)]);
  return [...ctx.draft].filter((id) => here.has(id) || found.has(id));
}

function AccountsPage({ ctx }: { ctx: Ctx }) {
  const found = ctx.snap.discovery?.found ?? [];
  const allFound = found.length + (ctx.snap.discovery?.unmatched.length ?? 0);
  // How long it takes, or for one set up by hand, how it's done.
  const HOW: Record<string, string> = { other_mail: 'Through Mail on this Mac, no waiting', maps_timeline: 'Exported from your phone, no waiting',
    slack: 'Exported by a workspace admin', zoom: 'Downloaded from Zoom\'s web portal' };
  const wait = (id: string) => (BY_ID[id]?.waitHours ? `Takes ${waitRange(BY_ID[id].waitHours!)}` : HOW[id] ?? '');
  const common: Account[] = commonAccounts(ctx.snap.sources).map((x, k) => ({ id: x.id, name: x.name, rank: k,
    subtitle: `${wait(x.id)}${x.optional ? ' · Can be hundreds of GB, so it isn\'t on your list unless you add it' : ''}`, tag: x.section === 'done' ? 'Collected' : undefined }));
  const added: Account[] = accountChoices(ctx.snap.sources).filter((x) => BY_ID[x.id]?.custom)
    .map((x, k) => ({ id: x.id, name: x.name, rank: 100 + k, subtitle: wait(x.id), tag: x.section === 'done' ? 'Collected' : undefined }));
  const fromData = (list: FoundService[]): Account[] => list.map((f, k) => ({ id: `found:${f.slug}`, name: f.name, rank: 1000 + k,
    subtitle: evidenceLine(f), tag: f.export?.url ? 'Export steps' : undefined }));
  const chosen = ctx.draft;
  // Yours: the common ones first, most used first, then the rest in the order you added them.
  const order = [...chosen];
  const byId = new Map([...common, ...added, ...fromData(found)].map((a) => [a.id, a]));
  const mine = order.map((id) => byId.get(id)).filter((a): a is Account => !!a)
    .sort((a, b) => (a.rank < 100 ? a.rank : 100) - (b.rank < 100 ? b.rank : 100) || order.indexOf(a.id) - order.indexOf(b.id));
  // Recommended: common ones you haven't kept, services you added then took out, and the top few found in your data.
  const picks = recommended(found.filter((f) => !chosen.has(`found:${f.slug}`)));
  const rec = [...common.filter((a) => !chosen.has(a.id)), ...added.filter((a) => !chosen.has(a.id)), ...fromData(picks)];
  // Moving a row slides it into the other list (a view transition per row and per list).
  const move = (id: string, on: boolean) => animate(() => {
    const n = new Set(ctx.draft);
    if (on) n.add(id);
    else n.delete(id);
    ctx.setDraft(n);
  }, 'move');
  const [browsing, setBrowsing] = useState<HubFilter | null>(null);
  const [naming, setNaming] = useState<string | null>(null); // adding one that isn't listed, by name
  const locked = lockedHere(ctx);
  const row = (a: Account, on: boolean) => (
    <GroupRow key={a.id} testId={`account-${a.id}`} style={vt(`acct-${a.id.replace(/[^A-Za-z0-9_-]/g, '-')}`)}
      icon={<SourceIcon id={a.id} group="web" size={26} name={a.name} />}
      title={<>{a.name}{a.tag && <span className="tag">{a.tag}</span>}</>} subtitle={a.subtitle}
      trailing={on
        ? <Button size="small" onClick={() => move(a.id, false)} testAction="remove-account" ariaLabel={`Remove ${a.name}`} disabled={locked} title={lockTitle(locked)}>Remove</Button>
        : <Button size="small" onClick={() => move(a.id, true)} testAction="add-account" ariaLabel={`Add ${a.name}`} disabled={locked} title={lockTitle(locked)}>Add</Button>} />
  );
  return (
    <>
      <Hero icon={<GlyphTile glyph="tray" color="blue" size={64} />} title="Which accounts do you use?">
        Pick the ones you use often or have years of history in: they hold the most about you. Each one you keep gets its own
        page with the steps to ask for your data, which arrives anywhere from an hour to 30 days later.
      </Hero>
      <h3 className="page-sub">Your accounts</h3>
      <p className="page-sub-lede">The ones most people use, to start with. Remove any you don't use.</p>
      <div className="group-box" data-testid="accounts" style={vt('acct-mine')}>
        {mine.length ? mine.map((a) => row(a, true)) : <div className="grow"><div className="grow-main"><div className="grow-sub">None yet: add the ones you use from below.</div></div></div>}
      </div>
      {locked && <div className="note" data-testid="accounts-locked"><Glyph name="info" size={13} /><span>{READ_ONLY_NOTE}</span></div>}
      {rec.length > 0 && (
        <div style={vt('acct-rec')}>
          <h3 className="page-sub">Recommended</h3>
          <p className="page-sub-lede">Not added yet: common ones you haven't kept, then the ones your mail, the sites you visit and your apps point to, the ones you seem to use most first.</p>
          <div className="group-box" data-testid="recommended">{rec.map((a) => row(a, false))}</div>
          {allFound > picks.length && <div className="group-footer">The {picks.length} you seem to use most, of {count(allFound)} found in your data.</div>}
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 14 }}>
        {allFound > picks.length && <Button onClick={() => setBrowsing('found')} testAction="see-all-found">See All {count(allFound)} Found…</Button>}
        <Button onClick={() => setBrowsing('all')} testAction="browse-all-services">Browse All Sources…</Button>
      </div>
      {browsing && (
        <Sheet onClose={() => setBrowsing(null)} testId="hub-sheet" width={760}>
          <h2>{browsing === 'found' ? 'Found in your data' : 'All sources'}</h2>
          <Hub snap={ctx.snap} filter={browsing} onAdded={(ids) => ctx.setDraft(new Set([...ctx.draft, ...ids]))}
            onAddOther={(q) => { setBrowsing(null); setNaming(q ?? ''); }} chosen={ctx.draft} onChoose={(id) => ctx.setDraft(new Set([...ctx.draft, id]))} />
          <div className="sheet-actions"><Button kind="primary" onClick={() => setBrowsing(null)}>Done</Button></div>
        </Sheet>
      )}
      {naming !== null && <AddServiceSheet initialName={naming} onClose={() => setNaming(null)} onAdded={(id) => ctx.setDraft(new Set([...ctx.draft, id]))} />}
    </>
  );
}

function exportsList(ctx: Ctx): PageSpec {
  const ids = ctx.steps.filter((s) => s.kind === 'export').map((s) => s.sourceId!);
  const left = ids.filter((x) => !exportHandled(ctx.v(x)));
  // The ones Claude can ask for (shared/request_all.ts): with any, that's the way in, and one by one the other.
  const plan = requestPlan(ctx.snap.sources);
  // Do It for Me said no to: one by one, yourself (it's still on each page, and in AI Settings).
  const claude = ctx.snap.settings.agentExports === false || ctx.snap.setup?.agent?.fix === 'provider' ? [] : [...plan.claude, ...plan.signIn].filter((v) => ids.includes(v.id));
  const after = () => ctx.jump(nextExportStep(ctx.steps, ctx.snap.sources, ids[ids.length - 1], new Set(ids)));
  return {
    primary: left.length ? { label: `${claude.length ? 'One by One: ' : 'Start with '}${ctx.v(left[0]).name}`, onClick: () => ctx.jump(`export:${left[0]}`), quiet: claude.length > 0 }
      : { label: 'Continue', onClick: () => ctx.jump(nextExportStep(ctx.steps, ctx.snap.sources)) },
    // The rest can wait: they stay in To Do, not started, and the setup goes on.
    secondary: left.length ? <Button onClick={after} testAction="exports-later">Do the Rest Later</Button> : undefined,
    body: (
      <>
        <Hero icon={<GlyphTile glyph="tray" color="blue" size={64} />} title="Ask for your data">
          Each service lets you know when your copy is ready, by email or in its app, an hour to 30 days after you ask. Start with the ones you care about most: pick any of
          them to open its page. The longest waits are at the top, so their clocks start soonest.
        </Hero>
        {claude.length > 0 && <AskAllBox ctx={ctx} n={claude.length} onAsked={after} />}
        <div className="group-box" style={{ marginTop: 22 }} data-testid="exports-list">
          {ids.map((x) => {
            const v = ctx.v(x);
            const src = BY_ID[x];
            const done = exportHandled(v);
            // Skipped isn't done: no checkmark, and its page can include it again.
            const skipped = v.section === 'unavailable' || v.deferred;
            return (
              <GroupRow key={x} testId={`exports-${x}`} icon={<SourceIcon id={x} group="web" size={26} />} onClick={() => ctx.jump(`export:${x}`)}
                title={v.name} subtitle={done ? v.status : src.waitHours ? `Takes ${waitRange(src.waitHours)}` : v.status}
                trailing={skipped ? <span className="where">Skipped</span> : done ? <Checkmark size={18} /> : undefined} />
            );
          })}
        </div>
        <div className="group-footer">{left.length ? `${left.length} of ${ids.length} still to ask for.` : 'All asked for.'} You can come back to this list from any of them.</div>
        <ReadyNotice ctx={ctx} />
      </>
    ),
  };
}

// Claude asks for all of them, one after another (Ask for Everything), while you go on with the rest of the setup.
function AskAllBox({ ctx, n, onAsked }: { ctx: Ctx; n: number; onAsked: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="group-box ask-all-box" style={{ marginTop: 22 }} data-testid="ask-all-box">
      <div className="status-box">
        <div style={{ marginTop: 1 }}><AiMark size={20} /></div>
        <div style={{ flex: 1 }}>
          <div className="big">Claude can ask for {n === 1 ? 'it' : `${n} of these`} for you</div>
          <div className="pre">One after another in your {ctx.snap.setup?.agentBrowser?.name ?? 'Chrome'}, while you go on. It tells you if it needs you to sign in or confirm it's you.</div>
        </div>
      </div>
      <div className="actions"><Button kind="primary" ai onClick={() => setOpen(true)} testAction="ask-all">Ask Claude for All…</Button></div>
      {open && <RequestAllSheet snap={ctx.snap} onClose={() => setOpen(false)} onJump={(id) => ctx.jump(`export:${id}`)} onAsked={() => { setOpen(false); onAsked(); }} />}
    </div>
  );
}

// How the app hears that an export is ready, and the one setting that helps: the iPhone's notifications on this Mac.
function ReadyNotice({ ctx }: { ctx: Ctx }) {
  const n = ctx.snap.sources.find((x) => x.id === 'iphone_notifications');
  if (!n || n.section === 'unavailable' || ctx.snap.settings.notificationChecks === false) return null;
  return (
    <>
      <h3 className="page-sub">Knowing when it's ready</h3>
      <p className="page-sub-lede">
        Services say your data is ready by email or with a notification in their app. While you wait, the app watches this Mac's notifications
        for one that sounds like it, and tells you. It's a guess: it can miss one or get it wrong, so keep an eye on your email and the apps too.
        Many of those notifications go to your iPhone, so forward them to this Mac and the app can see them as well.
      </p>
      <div className="group-box" data-testid="ready-notice">
        <GroupRow icon={<SourceIcon id={n.id} size={26} />} title={n.name} subtitle={n.status}
          trailing={n.section === 'done' ? <Checkmark size={18} />
            : <Button size="small" onClick={() => void api.action(n.id, 'open-notification-settings')} testAction="open-notification-settings">Open Notification Settings</Button>} />
      </div>
    </>
  );
}

function exportPage(ctx: Ctx, id: string): PageSpec {
  const view = ctx.v(id);
  const src = BY_ID[id];
  if (src.group === 'guided') return guidedPage(ctx, id);
  const asked = !!view.requestedAt || view.section === 'done' || (view.section === 'working' && !view.needsYou);
  // This one is passed over even before the snapshot shows it asked for.
  const onward = () => ctx.jump(nextExportStep(ctx.steps, ctx.snap.sources, id, ctx.seen));
  const markAndNext = () => void api.action(id, 'mark-requested').then(() => ctx.confirmed(id, onward));
  // Claude can ask for it: that's the footer's button (it works on while you go on), and saying you did is in the page.
  // Not when it was said no to, or isn't there yet with the AI picked: then the page leads with doing it yourself.
  const agent = !asked && ctx.snap.settings.agentExports !== false && ctx.snap.setup?.agent?.fix !== 'provider' && view.actions.find((a) => a.id === 'agent-request');
  // Saying you asked for it is the footer's button while that's the next thing to say (not yet asked, or asked for a
  // new one after the link ran out); otherwise the footer just moves on, quietly when the page has its own next step.
  const mark = view.actions.find((a) => a.id === 'mark-requested');
  const sayAsked = mark && (!asked || view.onTheWay === 'expired');
  const pageHasStep = (view.section === 'todo' || !!view.needsYou) && view.actions.some((a) => a.primary && a.id !== 'mark-requested');
  const primary = agent && ctx.justAsked !== id ? { label: agent.label, onClick: () => ctx.doIt(id, onward), ai: true }
    : sayAsked && ctx.justAsked !== id
      ? { label: mark.label, onClick: markAndNext, quiet: pageHasStep }
      : { label: ctx.justAsked === id ? 'Requested' : 'Continue', onClick: onward, done: ctx.justAsked === id, quiet: pageHasStep };
  const skips = view.actions.some((a) => a.id === 'skip');
  const secondary = (
    <>
      <Button onClick={() => ctx.jump('exports')} testAction="all-exports">All Exports</Button>
      {skips && !asked && <Button onClick={() => void api.action(id, 'skip', { reason: 'Not now' }).then(onward)} testAction="skip-export">Skip for Now</Button>}
    </>
  );
  const statusBox = (
    <div className="group-box" data-testid="export-status">
      <div className="status-box">
        <div style={{ marginTop: 1 }}>{view.section === 'done' ? <Checkmark size={20} /> : view.waiting ? <WaitClock size={20} started={view.requestedAt} /> : <StatusGlyph section={view.section} needsYou={view.needsYou} size={20} />}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="big appear-soft" key={view.status} data-testid="status">{view.status}</div>
          {view.detail && <div className="pre">{view.detail}</div>}
          {view.section === 'working' && !view.waiting && !view.needsYou && <ProgressBar value={view.progress} small />}
        </div>
      </div>
      {view.section !== 'done' && <ExportActions ctx={ctx} view={view} skip={['skip', ...(agent ? ['agent-request'] : sayAsked ? ['mark-requested'] : [])]} onMark={markAndNext} />}
    </div>
  );
  return {
    primary, secondary,
    body: (
      <>
        <Hero icon={<SourceIcon id={id} size={64} />} title={`Request your ${view.name} data`}>{view.blurb}</Hero>
        <div style={{ marginTop: 22 }}>{statusBox}</div>
        {view.section !== 'done' && !view.actions.some((a) => a.id === 'import-found') && <div className="group-footer">{ctx.snap.settings.watchDownloads
          ? 'When the download lands in Downloads, the app takes it from there: this page turns green.' : 'When it\'s downloaded, drop it on this window: this page turns green.'}</div>}
        {view.steps && view.section !== 'done' && <Group title="Steps"><Steps view={view} locked={lockedHere(ctx)} /></Group>}
        {view.notes && view.notes.length > 0 && <div style={{ marginTop: 12 }}>{view.notes.map((n, k) => <div key={k} className="note"><Glyph name="info" size={13} /><span>{n}</span></div>)}</div>}
      </>
    ),
  };
}

// An export page's buttons: whatever its state offers (import what's in Downloads, try again, include it again, answer
// Claude...), apart from the ones in the footer. Pages open in the person's own browser, signed in already.
// onMark: saying you've requested it, as the footer's button does (a checkmark for a beat, then on).
function ExportActions({ ctx, view, skip, onMark }: { ctx: Ctx; view: SourceView; skip: string[]; onMark?: () => void }) {
  const [reply, setReply] = useState('');
  const [form, setForm] = useState<Action | null>(null);
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [gate, setGate] = useState<{ g: Exclude<Gate, null>; go: () => void } | null>(null);
  const id = view.id;
  const src = BY_ID[id];
  // Answering Claude, or carrying on: through the same gate as Do It for Me (the AI picked, Anthropic's data settings).
  const carryOn = (aid: string) => {
    const go = () => void api.action(id, aid, { reply });
    const g = agentGate(ctx.snap);
    if (g) setGate({ g, go });
    else go();
    setReply('');
  };
  const run = (a: Action, payload?: unknown) => {
    if (a.confirm && !confirm) return setConfirm(a);
    if (a.input === 'skip-reason' && payload === undefined) return setForm(a);
    if (a.id === 'mark-requested' && onMark) return onMark();
    void api.action(id, a.id, payload);
  };
  const label = (a: Action) => (a.id === 'open' && a.label === 'Open the Export Page' ? `Open ${view.name} in ${ctx.snap.defaultBrowser}`
    : a.id === 'open-download' && src.downloadUrl ? `Open the Download Page in ${ctx.snap.defaultBrowser}` : a.label);
  const acts = view.actions.filter((a) => !skip.includes(a.id));
  // Only when Claude asked something: carrying on after a quit has nothing to answer.
  const answering = acts.some((a) => a.input === 'reply');
  // Read-only: what only looks or opens a page works; the rest is disabled, and says why.
  const off = (aid: string) => ctx.snap.readOnly && !ctx.snap.demo && !READ_ONLY_OK.has(aid);
  if (!acts.length) return null;
  return (
    <>
      {answering && (
        <div className="agent-reply">
          <input type="text" value={reply} onChange={(e) => setReply(e.target.value)} placeholder={`Answer Claude here, or leave it empty once you've done it in ${ctx.snap.setup?.agentBrowser?.name ?? 'Chrome'}`}
            onKeyDown={(e) => e.key === 'Enter' && carryOn('agent-continue')} data-testid="agent-reply" disabled={off('agent-continue')} />
        </div>
      )}
      <div className="actions" data-testid="export-actions">
        {acts.map((a) => (a.input === 'reply'
          ? <Button key={a.id} kind={a.primary ? 'primary' : 'default'} ai={a.ai} disabled={off(a.id)} onClick={() => carryOn(a.id)} testAction={a.id}>{a.label}</Button>
          : a.id === 'open-inbox' ? <InboxButton key={a.id} view={view} action={a} />
          : a.id.startsWith('agent-') ? <AgentButton key={a.id} snap={ctx.snap} id={id} action={a} />
            : <Button key={a.id} kind={a.primary ? 'primary' : 'default'} disabled={off(a.id)} title={off(a.id) ? READ_ONLY_NOTE : undefined} onClick={() => run(a)} testAction={a.id}>{label(a)}</Button>))}
      </div>
      {form && <SkipForm view={view} action={form} onSubmit={(reason) => { run(form, { reason }); setForm(null); }} onCancel={() => setForm(null)} />}
      {gate && <AgentGateSheet snap={ctx.snap} gate={gate.g} onClose={() => setGate(null)} onOk={() => { const x = gate; setGate(null); x.go(); }} />}
      {confirm && (
        <Sheet onClose={() => setConfirm(null)} testId="confirm">
          <h2>{confirm.label}?</h2>
          <p>{confirm.confirm}</p>
          <div className="sheet-actions">
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            <Button kind="primary" onClick={() => { void api.action(id, confirm.id, { confirmed: true }); setConfirm(null); }}>{confirm.label}</Button>
          </div>
        </Sheet>
      )}
    </>
  );
}

// A service set up by hand rather than requested (Outlook and other mail through Mail, Maps Timeline from the phone,
// Slack, Zoom): its own buttons and steps, and the file it leaves you with, dropped on the window or in Downloads.
function guidedPage(ctx: Ctx, id: string): PageSpec {
  const view = ctx.v(id);
  const onward = () => ctx.jump(nextExportStep(ctx.steps, ctx.snap.sources, id, ctx.seen));
  const done = view.section === 'done';
  const mail = id === 'other_mail';
  const acts = view.actions.filter((a) => !['skip', 'mark-done', 'unmark-done'].includes(a.id));
  return {
    primary: { label: 'Continue', onClick: onward },
    secondary: (
      <>
        <Button onClick={() => ctx.jump('exports')} testAction="all-exports">All Exports</Button>
        {!done && view.section !== 'unavailable' && !view.deferred && (
          <Button onClick={() => void api.action(id, 'skip', { reason: mail ? 'No other mail accounts' : 'Not now' }).then(onward)} testAction="skip-export">
            {mail ? 'I Don\'t Have Any' : 'Skip for Now'}
          </Button>
        )}
      </>
    ),
    body: (
      <>
        <Hero icon={<SourceIcon id={id} size={64} />} title={view.name}>{view.blurb}</Hero>
        <div className="group-box" style={{ marginTop: 22 }} data-testid="export-status">
          <div className="status-box">
            <div style={{ marginTop: 1 }}>{done ? <Checkmark size={20} /> : <StatusGlyph section={view.section} needsYou={view.needsYou} size={20} />}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="big appear-soft" key={view.status} data-testid="status">{view.status}</div>
              {view.detail && <div className="pre">{view.detail}</div>}
              {view.section === 'working' && !view.needsYou && <ProgressBar value={view.progress} small />}
            </div>
          </div>
          {!done && acts.length > 0 && (
            <div className="actions">
              {acts.map((a) => <Button key={a.id} kind={a.primary ? 'primary' : 'default'} onClick={() => void api.action(id, a.id)} testAction={a.id}>{a.label}</Button>)}
            </div>
          )}
        </div>
        {mail && !done && view.section !== 'unavailable' && <Group title="Account"><AccountForm view={view} /></Group>}
        {view.steps && !done && <Group title="Steps"><Steps view={view} /></Group>}
        {view.notes && view.notes.length > 0 && <div style={{ marginTop: 12 }}>{view.notes.map((n, k) => <div key={k} className="note"><Glyph name="info" size={13} /><span>{n}</span></div>)}</div>}
        {!done && view.section !== 'unavailable' && !view.deferred && <div className="drop">{mail ? 'Drop the exported .mbox folders on this window, or put them in Downloads.' : 'Drop the export on this window, or put it in Downloads.'}</div>}
      </>
    ),
  };
}

// Use AI or not, said once, and which agent: Ask, Do It for Me and making sense of new downloads all use it.
// How Homecoming tells you an export is ready, one landed in Downloads, or Claude needs you. macOS asks once, when the
// first notification comes: it's sent here, while you're looking, and macOS's record says whether it was shown.
function notifications(ctx: Ctx): PageSpec {
  const c = ctx.snap.notifyCheck;
  return {
    primary: { label: 'Continue', onClick: ctx.next, quiet: !c || c.state !== 'shown' },
    body: (
      <>
        <Hero icon={<GlyphTile glyph="bell" color="red" size={64} />} title="Notifications">
          Homecoming tells you when an export is ready, when one lands in Downloads, and when Claude needs you to sign in or confirm it's you. macOS asks once whether to allow them.
        </Hero>
        <NotificationsBox snap={ctx.snap} />
        <div className="note"><Glyph name="info" size={13} /><span>Alerts stay on screen until you look; banners go after a few seconds. General → Notifications in Homecoming checks them again any time.</span></div>
      </>
    ),
  };
}

function ai(ctx: Ctx): PageSpec {
  const s = ctx.snap.settings;
  const decided = s.aiOn !== undefined && !!s.aiAgreedAt;
  const decide = (on: boolean) => void api.settings(on ? { aiOn: true, aiAgreedAt: s.aiAgreedAt ?? new Date().toISOString() } : { aiOn: false }).then(ctx.next);
  return {
    primary: decided ? { label: 'Continue', onClick: ctx.next } : { label: 'Turn On AI', onClick: () => decide(true), ai: true },
    secondary: decided ? undefined : <Button onClick={() => decide(false)} testAction="ai-not-now">Not Now</Button>,
    body: (
      <>
        <Hero icon={<AiMark size={64} />} title="AI in Homecoming">
          It's up to you. With it on, you can ask questions about your data, have Do It for Me request and download your exports, and make sense of downloads the app doesn't know yet. Everything that uses AI has this mark.
        </Hero>
        <div style={{ marginTop: decided ? 4 : 22 }}>
          {decided ? <AiSettings snap={ctx.snap} /> : <><AiAgreement snap={ctx.snap} actions={false} /><AiSettings snap={ctx.snap} only="agents" /></>}
        </div>
      </>
    ),
  };
}

function done(ctx: Ctx): PageSpec {
  const now = new Date();
  const prog = progress(ctx.snap.sources, now);
  // What's left for you, every one of it: what needs you, then what's still to start. Each opens its page in the main window.
  const free = ctx.snap.sources.filter((v) => !v.blockedBy && !v.optional);
  const needs = free.filter((v) => v.needsYou);
  const todo = free.filter((v) => !v.needsYou && v.section === 'todo');
  // Sources not started are in To Do; the checks left, in Setup Checks (and who you are, in Your Setup).
  const notStarted = todo.filter((v) => v.group !== 'setup');
  const checks = todo.filter((v) => v.group === 'setup' && v.id !== 'identity');
  // Set aside with Not now: not done either, so it isn't "all set".
  const aside = ctx.snap.sources.filter((v) => v.deferred);
  const left = [...needs, ...todo, ...aside];
  return {
    primary: { label: 'Open Overview', onClick: () => ctx.onFinish() },
    wide: false,
    body: (
      <>
        <Hero icon={<Checkmark size={72} />} title={left.length ? 'That\'s the setup done' : 'You\'re all set for now'}>
          {`The app keeps going on its own: it ${and([ctx.snap.settings.autoRefresh ? 'reads this Mac every day' : '', ctx.snap.settings.watchDownloads ? 'imports each export as it lands in Downloads' : '',
            'lets you know when one should be ready'].filter(Boolean))}.`}
          {needs.length ? ` ${needs.length === 1 ? 'One thing needs' : `${needs.length} things need`} you: they're at the top of To Do.` : ''}
          {notStarted.length ? ` ${notStarted.length === 1 ? 'One source hasn\'t' : `${notStarted.length} sources haven't`} started yet: ${notStarted.length === 1 ? 'it\'s' : 'they\'re'} in To Do.` : ''}
          {aside.length ? ` ${aside.length === 1 ? 'One is' : `${aside.length} are`} set aside for now, under Optional in To Do.` : ''}
          {checks.length ? ` ${checks.length === 1 ? 'One check is' : `${checks.length} checks are`} left in Setup Checks.` : ''}
        </Hero>
        <Group title={`${Math.round(prog.percent * 100)}% collected · ${prog.collected} of ${prog.applicable} sources`}><Timeline phases={prog.phases} /></Group>
        {([['Needs you', needs, 'done-needs'], ['Still to do', todo, 'done-todo']] as const).filter(([, rows]) => rows.length).map(([title, rows, id]) => (
          <Group key={id} title={title} testId={id}>
            {rows.map((v) => <GroupRow key={v.id} testId={`left-${v.id}`} icon={<SourceIcon id={v.id} group={v.group} size={24} />} title={v.name} subtitle={v.status} onClick={() => ctx.onFinish(v.id)} />)}
          </Group>
        ))}
        {prog.waiting.length > 0 && (
          <Group title="On the way">
            {prog.waiting.map((w) => <GroupRow key={w.id} icon={<SourceIcon id={w.id} size={24} />} title={w.name} subtitle={readyIn(w, now)} />)}
          </Group>
        )}
      </>
    ),
  };
}
