// The Setup Assistant: one thing per page, like setting up a new Mac. Every page shows live status from the
// same snapshot as the main window, so a step that finishes in the background turns green in place.

import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { BY_ID } from '../shared/catalog.ts';
import { count, waitRange } from '../shared/format.ts';
import { accountChoices, assistantSteps, commonAccounts, defaultChosen, exportHandled, KEEP_GROUPS, LIBRARY_SOURCES, nextExportStep, progress, readyIn, recommended, STEP_GROUPS, type Step, stepIndex } from '../shared/progress.ts';
import type { Action, FoundService, Snapshot, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { Glyph, GlyphTile, SourceIcon } from './icons.tsx';
import { Hub, type HubFilter } from './hub.tsx';
import { Timeline } from './main_window.tsx';
import { AccountForm, AddServiceSheet, ContentsLines, evidenceLine, IdentityPicker, PasswordForm, PhoneParts, Steps, vt } from './parts.tsx';
import { animate, Banner, Button, Checkmark, Group, GroupRow, ProgressBar, Sheet, Spinner, StatusGlyph, Toggle } from './ui.tsx';
import { Welcome } from './welcome.tsx';

interface PageSpec {
  body: ReactNode;
  primary?: { label: string; onClick: () => void; disabled?: boolean };
  secondary?: ReactNode;
  wide?: boolean;
}

export function Assistant({ snap, onFinish, onExit }: { snap: Snapshot; onFinish: () => void; onExit: () => void }) {
  const views = snap.sources;
  const steps = useMemo(() => assistantSteps(views, snap.onboarding.chosen), [views, snap.onboarding.chosen]);
  // The page, by id: when the step list changes (accounts chosen, one dropped), the same page stays up.
  const [at, setAt] = useState(() => steps[stepIndex(steps, snap.onboarding.step)].id);
  // What you last chose, plus services added since (from the hub, or the main window) that you haven't turned down.
  const [draft, setDraft] = useState<Set<string>>(() => new Set([...(snap.onboarding.chosen ?? defaultChosen(views)),
    ...views.filter((x) => BY_ID[x.id]?.custom && x.section !== 'unavailable').map((x) => x.id)]));
  const i = stepIndex(steps, at);
  const step = steps[i];
  const v = (id: string) => views.find((x) => x.id === id)!;

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

  const page = renderStep(step, { snap, v, next, jump, onFinish, steps, index: i, draft, setDraft });
  return (
    <div className="assistant" data-testid="assistant" data-step={step.id}>
      <StepsBar steps={steps} index={i} />
      <div className="page-wrap">
        <div style={vt('page')} key={step.id}>
          <div className={`page ${page.wide ? 'wide' : ''}`}>{page.body}</div>
        </div>
      </div>
      <div className="footer-bar">
        {i > 0 && <Button onClick={back} testAction="assistant-back">Back</Button>}
        {step.kind !== 'done' && <Button kind="plain" onClick={onExit} testAction="assistant-exit">Skip Setup Assistant</Button>}
        <div className="spacer" />
        <span className="where">{i + 1} of {steps.length}</span>
        {page.secondary}
        {page.primary && <Button kind="primary" size="large" onClick={page.primary.onClick} disabled={page.primary.disabled} testAction="assistant-continue">{page.primary.label}</Button>}
      </div>
    </div>
  );
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
  onFinish: () => void;
  steps: Step[];
  index: number;
  draft: Set<string>;
  setDraft: (s: Set<string>) => void;
}

function renderStep(step: Step, ctx: Ctx): PageSpec {
  switch (step.kind) {
    case 'welcome': return welcome(ctx);
    case 'identity': return identity(ctx);
    case 'access': return access(ctx);
    case 'library': return { body: <LibraryPage ctx={ctx} />, primary: { label: 'Continue', onClick: ctx.next } };
    case 'keep': return { body: <KeepPage ctx={ctx} />, primary: { label: 'Continue', onClick: ctx.next } };
    case 'mac': return mac(ctx);
    case 'iphone': return { body: <IphonePage ctx={ctx} />, primary: { label: 'Continue', onClick: ctx.next } };
    case 'accounts': {
      // Found services you ticked become sources first, so their export pages join the steps.
      const apply = () => {
        const picked = [...ctx.draft];
        void api.action('*', 'choose-services', { slugs: picked.filter((x) => x.startsWith('found:')).map((x) => x.slice(6)),
          domains: picked.filter((x) => x.startsWith('sender:')).map((x) => x.slice(7)) })
          .then((r) => api.action('*', 'choose-accounts', { chosen: [...picked.filter((x) => !/^(found|sender):/.test(x)), ...(r.ids ?? [])] }))
          .then(() => ctx.next());
      };
      const n = [...ctx.draft].length;
      return { body: <AccountsPage ctx={ctx} />, primary: { label: n ? `Continue with ${n}` : 'Continue', onClick: apply } };
    }
    case 'exports': return exportsList(ctx);
    case 'export': return exportPage(ctx, step.sourceId!);
    case 'mail': return mail(ctx);
    case 'extras': return extras(ctx);
    case 'done': return done(ctx);
  }
}

// ---------------------------------------------------------------- pages

function welcome(ctx: Ctx): PageSpec {
  return { primary: { label: 'Get Started', onClick: ctx.next }, wide: true, body: <Welcome /> };
}

function identity(ctx: Ctx): PageSpec {
  const view = ctx.v('identity');
  const save = (id: unknown, dismissed: string[]) => void api.action('identity', 'save-identity', { identity: id, dismissed }).then((r) => r.ok && ctx.next());
  const found = ctx.snap.identityCandidates ?? [];
  return {
    primary: { label: 'Continue', onClick: () => (document.getElementById('identity-step') as HTMLFormElement | null)?.requestSubmit() },
    body: (
      <>
        <Hero icon={<SourceIcon id="identity" size={64} />} title="Which of these are you?">
          {found.length
            ? 'These turned up in your data: on this Mac, in your exports and in your chats. Tick the ones that are you. It decides which messages, emails and commits are marked as yours.'
            : 'Your names, email addresses and usernames decide which messages, emails and commits are marked as yours.'}
        </Hero>
        {!found.length && !ctx.snap.identityCandidatesReady && <div className="note" style={{ justifyContent: 'center', marginTop: 14 }}><Spinner size={12} /><span>Looking around this Mac…</span></div>}
        <IdentityPicker snap={ctx.snap} formId="identity-step" busy={false} hideSubmit onSubmit={save} />
        <div className="note"><Glyph name="info" size={13} /><span>Nothing was held back while you went through the steps: everything is collected either way. Exports still on their way will turn up more, and the app asks about them then and re-labels what's already in.</span></div>
        {view.section === 'done' && <div className="note" style={{ justifyContent: 'center' }}><Checkmark size={13} /><span>Saved: {view.status}</span></div>}
      </>
    ),
  };
}

function access(ctx: Ctx): PageSpec {
  const view = ctx.v('fda');
  const granted = view.section === 'done';
  const unlocks = ctx.snap.sources.filter((s) => s.blockedBy === 'fda' && s.group !== 'setup');
  return {
    primary: { label: 'Continue', onClick: ctx.next },
    body: (
      <>
        <Hero icon={<SourceIcon id="fda" size={64} />} title="Allow Full Disk Access">
          macOS keeps Messages, Mail, Photos, Notes, Calendar and call history behind one permission. Turn it on once and every source on this Mac can be read.
        </Hero>
        <div className="group-box" style={{ marginTop: 22 }} data-testid="fda-status">
          <div className="status-box">
            <div style={{ marginTop: 1 }}>{granted ? <Checkmark size={20} /> : <StatusGlyph section={view.section} size={20} />}</div>
            <div style={{ flex: 1 }}>
              <div className="big">{granted ? 'Full Disk Access is on' : view.section === 'unavailable' ? 'Nothing on this Mac needs it' : 'Not allowed yet'}</div>
              {!granted && unlocks.length > 0 && <div className="pre">Waiting on it: {unlocks.map((u) => u.name).join(', ')}.</div>}
            </div>
          </div>
          {!granted && view.section === 'needs' && (
            <div className="actions">
              <Button kind="primary" onClick={() => void api.action('fda', 'open-fda-settings')}>Open System Settings…</Button>
              <Button onClick={() => void api.action('fda', 'recheck')} testAction="recheck">Check Again</Button>
            </div>
          )}
        </div>
        {!granted && view.steps && <Group title="How"><Steps view={view} /></Group>}
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

const fixFor = (x: SourceView) => x.actions.find((y) => y.primary) ?? x.actions.find((y) => y.id === 'mark-done');

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
              subtitle={<>{x.section === 'done' ? x.status : <span style={{ color: 'var(--orange)' }}>{x.status}</span>}<br />{ABOUT[x.id]}</>}
              trailing={x.section === 'done' ? <Checkmark size={18} /> : a ? <Button kind={a.primary ? 'primary' : 'default'} onClick={() => run(x.id, a)} testAction={a.id}>{a.label}</Button> : <StatusGlyph section={x.section} />} />
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
  retention_claude: { title: 'Claude Code', risk: 'Claude Code deletes conversation transcripts after 30 days.', setting: 'The button sets cleanupPeriodDays in ~/.claude/settings.json' },
  retention_codex: { title: 'Codex', risk: '', setting: '' },
  retention_shell: { title: 'Terminal', risk: 'zsh keeps only your last 1,000 commands, and doesn\'t record when you ran them.', setting: 'The button adds four lines to the end of ~/.zshrc: times on, keep a million commands' },
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
      subtitle={x.section === 'done' ? `${x.status}.` : <><span style={{ color: 'var(--orange)' }}>{copy.risk}</span><br />{copy.setting}</>}
      trailing={x.section === 'done' ? <Checkmark size={18} /> : (
        <>
          {a && <Button kind={a.primary ? 'primary' : 'default'} onClick={() => run(x.id, a)} testAction={a.id}>{a.label}</Button>}
          {a?.id !== 'mark-done' && x.actions.some((y) => y.id === 'mark-done') && <Button onClick={() => void api.action(x.id, 'mark-done')} testAction="mark-done">I've Done It</Button>}
          {!a && <StatusGlyph section={x.section} />}
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
      <Group title="Things that can't be changed" footer="These keep only a short window and have no setting. Reading them regularly is how nothing ages out: each read adds what's new to your library and keeps what it saw before.">
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
  const read = counted.filter((s) => s.section === 'done').length;
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
              subtitle={<>{s.status}<ContentsLines view={s} /></>} trailing={s.section === 'done' ? <Checkmark size={17} /> : <StatusGlyph section={s.section} />} />
          ))}
        </div>
      </>
    ),
  };
}

function IphonePage({ ctx }: { ctx: Ctx }) {
  const view = ctx.v('iphone_backup');
  const [busy, setBusy] = useState(false);
  const pw = view.actions.find((a) => a.id === 'iphone-run');
  const read = (password?: string) => {
    setBusy(true);
    void api.action('iphone_backup', 'iphone-run', password ? { password } : undefined).finally(() => setBusy(false));
  };
  return (
    <>
      <Hero icon={<SourceIcon id="iphone_backup" size={64} />} title="Add your iPhone" badge="Highly Recommended" />
      <div className="group-box" style={{ marginTop: 22 }} data-testid="iphone-status">
        <div className="status-box">
          <div style={{ marginTop: 1 }}>{view.section === 'done' ? <Checkmark size={20} /> : <StatusGlyph section={view.section} size={20} />}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="big" data-testid="status">{view.status}</div>
            {view.detail && <div className="pre">{view.detail}</div>}
            {view.section === 'working' && <ProgressBar />}
          </div>
        </div>
        {view.section === 'needs' && pw && !pw.input && <div className="actions"><Button kind="primary" onClick={() => read()} disabled={busy}>Read Backup</Button></div>}
        {view.section === 'needs' && !pw && <div className="actions"><Button kind="primary" onClick={() => void api.action('iphone_backup', 'open-app')}>Open Finder</Button><Button onClick={() => void api.action('iphone_backup', 'recheck')}>Check Again</Button></div>}
        {view.section === 'unavailable' && <div className="actions"><Button onClick={() => void api.action('iphone_backup', 'unskip')}>Include It Again</Button></div>}
      </div>
      {view.section === 'needs' && pw?.input === 'password' && <Group title="Unlock the backup"><PasswordForm onSubmit={read} busy={busy} /></Group>}
      {view.warnings.map((w, k) => <div key={k} style={{ marginTop: 12 }}><Banner kind="warning">{w}</Banner></div>)}
      {view.steps && view.section === 'needs' && <Group title="Make a backup"><Steps view={view} /></Group>}
      {view.section === 'done' && <PhoneParts view={view} />}
      {view.section === 'working' && <div className="note"><Glyph name="info" size={13} /><span>This keeps going in the background. Continue whenever you like.</span></div>}
      {view.section === 'needs' && <div style={{ textAlign: 'center', marginTop: 12 }}><Button kind="plain" onClick={() => void api.action('iphone_backup', 'skip', { reason: 'No iPhone backup for now' }).then(ctx.next)}>I don't have an iPhone backup</Button></div>}
    </>
  );
}

// One account on the Accounts page, wherever it is: a built-in, a service already added, or one found in your data.
interface Account { id: string; name: string; subtitle: string; tag?: string; rank: number }

function AccountsPage({ ctx }: { ctx: Ctx }) {
  const found = ctx.snap.discovery?.found ?? [];
  const allFound = found.length + (ctx.snap.discovery?.unmatched.length ?? 0);
  const wait = (id: string) => (BY_ID[id]?.waitHours ? `Takes ${waitRange(BY_ID[id].waitHours!)}` : '');
  const common: Account[] = commonAccounts(ctx.snap.sources).map((x, k) => ({ id: x.id, name: x.name, rank: k,
    subtitle: `${wait(x.id)}${x.optional ? ' · Can be hundreds of GB, so it starts off' : ''}`, tag: x.section === 'done' ? 'Collected' : undefined }));
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
  const row = (a: Account, on: boolean) => (
    <GroupRow key={a.id} testId={`account-${a.id}`} style={vt(`acct-${a.id.replace(/[^A-Za-z0-9_-]/g, '-')}`)}
      icon={<SourceIcon id={a.id} group="web" size={26} name={a.name} />}
      title={<>{a.name}{a.tag && <span className="tag">{a.tag}</span>}</>} subtitle={a.subtitle}
      trailing={on
        ? <Button size="small" onClick={() => move(a.id, false)} testAction="remove-account" ariaLabel={`Remove ${a.name}`}>Remove</Button>
        : <Button size="small" onClick={() => move(a.id, true)} testAction="add-account" ariaLabel={`Add ${a.name}`}>Add</Button>} />
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
        <Button onClick={() => setBrowsing('all')} testAction="browse-all-services">Browse All Services…</Button>
      </div>
      {browsing && (
        <Sheet onClose={() => setBrowsing(null)} testId="hub-sheet" width={760}>
          <h2>{browsing === 'found' ? 'Found in your data' : 'All services'}</h2>
          <Hub snap={ctx.snap} filter={browsing} onAdded={(ids) => ctx.setDraft(new Set([...ctx.draft, ...ids]))} onAddOther={() => setBrowsing(null)} />
          <div className="sheet-actions"><Button kind="primary" onClick={() => setBrowsing(null)}>Done</Button></div>
        </Sheet>
      )}
    </>
  );
}

function exportsList(ctx: Ctx): PageSpec {
  const ids = ctx.steps.filter((s) => s.kind === 'export').map((s) => s.sourceId!);
  const left = ids.filter((x) => !exportHandled(ctx.v(x)));
  return {
    primary: left.length ? { label: `Start with ${ctx.v(left[0]).name}`, onClick: () => ctx.jump(`export:${left[0]}`) }
      : { label: 'Continue', onClick: () => ctx.jump(nextExportStep(ctx.steps, ctx.snap.sources)) },
    body: (
      <>
        <Hero icon={<GlyphTile glyph="tray" color="blue" size={64} />} title="Ask for your data">
          Each service lets you know when your copy is ready, by email or in its app, an hour to 30 days after you ask. Start with the ones you care about most: pick any of
          them to open its page. The longest waits are at the top, so their clocks start soonest.
        </Hero>
        <div className="group-box" style={{ marginTop: 22 }} data-testid="exports-list">
          {ids.map((x) => {
            const v = ctx.v(x);
            const src = BY_ID[x];
            const done = exportHandled(v);
            return (
              <GroupRow key={x} testId={`exports-${x}`} icon={<SourceIcon id={x} group="web" size={26} />} onClick={() => ctx.jump(`export:${x}`)}
                title={v.name} subtitle={done ? v.status : src.waitHours ? `Takes ${waitRange(src.waitHours)}` : v.status}
                trailing={done ? <Checkmark size={18} /> : undefined} />
            );
          })}
        </div>
        <div className="group-footer">{left.length ? `${left.length} of ${ids.length} still to ask for.` : 'All asked for.'} You can come back to this list from any of them.</div>
        <ReadyNotice ctx={ctx} />
      </>
    ),
  };
}

// How the app hears that an export is ready, and the one setting that helps: the iPhone's notifications on this Mac.
function ReadyNotice({ ctx }: { ctx: Ctx }) {
  const n = ctx.snap.sources.find((x) => x.id === 'iphone_notifications');
  if (!n || n.section === 'unavailable') return null;
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
  const asked = !!view.requestedAt || view.section === 'done' || view.section === 'working';
  // This one is passed over even before the snapshot shows it asked for.
  const onward = () => ctx.jump(nextExportStep(ctx.steps, ctx.snap.sources, id));
  const markAndNext = () => void api.action(id, 'mark-requested').then(onward);
  const primary = view.section === 'done' || asked
    ? { label: 'Continue', onClick: onward }
    : { label: 'I\'ve Requested It', onClick: markAndNext };
  const secondary = (
    <>
      <Button onClick={() => ctx.jump('exports')} testAction="all-exports">All Exports</Button>
      {view.section !== 'done' && !asked && <Button onClick={() => void api.action(id, 'skip', { reason: 'Not now' }).then(onward)} testAction="skip-export">Skip for Now</Button>}
    </>
  );
  const statusBox = (
    <div className="group-box" data-testid="export-status">
      <div className="status-box">
        <div style={{ marginTop: 1 }}>{view.section === 'done' ? <Checkmark size={20} /> : <StatusGlyph section={view.section} size={20} />}</div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="big" data-testid="status">{view.status}</div>
          {view.detail && <div className="pre">{view.detail}</div>}
          {view.section === 'working' && <ProgressBar value={view.progress} small />}
        </div>
      </div>
      {view.section !== 'done' && (
        <div className="actions">
          {/* In the person's own browser: signed in already, with their passwords. */}
          <Button kind="primary" onClick={() => void api.action(id, view.requestedAt && src.downloadUrl ? 'open-download' : 'open')} testAction="open">
            {view.requestedAt && src.downloadUrl ? `Open the Download Page in ${ctx.snap.defaultBrowser}` : `Open ${view.name} in ${ctx.snap.defaultBrowser}`}
          </Button>
          <Button onClick={() => void api.action(id, 'add-file')} testAction="add-file">Add the Download…</Button>
        </div>
      )}
    </div>
  );
  return {
    primary, secondary,
    body: (
      <>
        <Hero icon={<SourceIcon id={id} size={64} />} title={`Request your ${view.name} data`}>{view.blurb}</Hero>
        <div style={{ marginTop: 22 }}>{statusBox}</div>
        {view.section !== 'done' && <div className="group-footer">When the download lands in Downloads, the app takes it from there: this page turns green.</div>}
        {view.steps && view.section !== 'done' && <Group title="Steps"><Steps view={view} /></Group>}
        {view.notes && view.notes.length > 0 && <div style={{ marginTop: 12 }}>{view.notes.map((n, k) => <div key={k} className="note"><Glyph name="info" size={13} /><span>{n}</span></div>)}</div>}
      </>
    ),
  };
}

function mail(ctx: Ctx): PageSpec {
  const view = ctx.v('other_mail');
  return {
    primary: { label: 'Continue', onClick: ctx.next },
    secondary: view.section !== 'done' && view.section !== 'unavailable'
      ? <Button onClick={() => void api.action('other_mail', 'skip', { reason: 'No other mail accounts' }).then(ctx.next)}>I Don't Have Any</Button> : undefined,
    body: (
      <>
        <Hero icon={<SourceIcon id="other_mail" size={64} />} title="Other email accounts">{view.blurb}</Hero>
        <div className="group-box" style={{ marginTop: 22 }}>
          <div className="status-box"><StatusGlyph section={view.section} size={20} /><div className="big">{view.status}</div></div>
          {view.section !== 'done' && <div className="actions"><Button onClick={() => void api.action('other_mail', 'open-internet-accounts')}>Open Internet Accounts…</Button></div>}
        </div>
        <Group title="Account"><AccountForm view={view} /></Group>
        {view.steps && view.section !== 'done' && <Group title="Steps"><Steps view={view} /></Group>}
        <div className="drop">Drop the exported .mbox folders on this window, or put them in Downloads.</div>
      </>
    ),
  };
}

function extras(ctx: Ctx): PageSpec {
  return { primary: { label: 'Continue', onClick: ctx.next }, body: <ExtrasPage ctx={ctx} /> };
}

function ExtrasPage({ ctx }: { ctx: Ctx }) {
  const maps = ctx.v('maps_timeline');
  const optional = ctx.snap.sources.filter((s) => s.group === 'guided' && s.optional);
  const mine = ctx.snap.sources.filter((s) => s.group === 'web' && BY_ID[s.id]?.custom);
  const [adding, setAdding] = useState(false);
  return (
      <>
        <Hero icon={<SourceIcon id="maps_timeline" size={64} />} title="A few more places">
          Google Maps Timeline lives on your phone now. The rest are optional: they're under Needs You whenever you want them.
        </Hero>
        <Group title="Google Maps Timeline">
          <div className="group-box">
            <div className="status-box"><StatusGlyph section={maps.section} size={20} /><div><div className="big">{maps.status}</div></div></div>
          </div>
        </Group>
        {maps.steps && maps.section !== 'done' && <div style={{ marginTop: 10 }}><Steps view={maps} /></div>}
        <Group title="Optional">
          {optional.map((o) => <GroupRow key={o.id} icon={<SourceIcon id={o.id} size={24} />} title={o.name} subtitle={o.blurb} trailing={<StatusGlyph section={o.section} />} />)}
        </Group>
        <Group title="Anything else" testId="your-services"
          footer="A site or app that isn't anywhere in the app, however small: a writing site, a fitness app, a forum. Whatever its download holds is kept, in any format.">
          {mine.map((o) => <GroupRow key={o.id} testId={`mine-${o.id}`} icon={<SourceIcon id={o.id} group="web" size={24} />} title={o.name} subtitle={o.status} trailing={<StatusGlyph section={o.section} />} />)}
          <div className="kv"><Button kind="plain" onClick={() => setAdding(true)} testAction="open-add-service">Add Another Service…</Button><span /></div>
        </Group>
        {adding && <AddServiceSheet onClose={() => setAdding(false)} onAdded={() => undefined} />}
      </>
  );
}

function done(ctx: Ctx): PageSpec {
  const now = new Date();
  const prog = progress(ctx.snap.sources, now);
  return {
    primary: { label: 'Open Overview', onClick: ctx.onFinish },
    wide: false,
    body: (
      <>
        <Hero icon={<Checkmark size={72} />} title="You're all set for now">
          The app keeps going on its own: it reads this Mac every day, imports each export as it lands in Downloads, and lets you know when one should be ready.
        </Hero>
        <Group title={`${Math.round(prog.percent * 100)}% collected · ${prog.collected} of ${prog.applicable} sources`}><Timeline phases={prog.phases} /></Group>
        {prog.waiting.length > 0 && (
          <Group title="On the way">
            {prog.waiting.map((w) => <GroupRow key={w.id} icon={<SourceIcon id={w.id} size={24} />} title={w.name} subtitle={readyIn(w, now)} />)}
          </Group>
        )}
      </>
    ),
  };
}
