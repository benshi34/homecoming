// The main window, laid out like Mail or Notes: a vibrant sidebar of sections (with counts), the sources in
// the chosen section, and the selected source on the right. Overview holds the progress timeline.

import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { ago, count } from '../shared/format.ts';
import { type Phase, progress, readyIn, wayTag } from '../shared/progress.ts';
import { READ_ONLY_NOTE } from '../shared/status.ts';
import { countFor, listFor, listSummary, type Nav, navOf } from '../shared/lists.ts';
import type { Snapshot, SourceView } from '../shared/types.ts';
import { AiPage, AskAiGate } from './ai.tsx';
import { api } from './api.ts';
import { Glyph, SourceIcon } from './icons.tsx';
import { AskPage } from './ask.tsx';
import { ExplorePage, exploreHome, exploreOpen, Num } from './explore.tsx';
import { Hub, type HubFilter } from './hub.tsx';
import { ArrivalBanners, RowCount, useArrivals, WaitClock } from './moments.tsx';
import { AddServiceSheet, Detail, vt } from './parts.tsx';
import { AiMark, animate, Button, Checkmark, Group, GroupRow, ProgressBar, ProgressRing, Sheet, Spinner, Toggle } from './ui.tsx';

export type { Nav } from '../shared/lists.ts';

const NAV: { id: Nav; label: string; glyph: string }[] = [
  { id: 'needs', label: 'Needs You', glyph: 'bell' },
  { id: 'working', label: 'In Progress', glyph: 'arrows' },
  { id: 'done', label: 'Collected', glyph: 'checkCircle' },
  { id: 'unavailable', label: 'Not Collecting', glyph: 'minusCircle' },
];

export function MainWindow({ snap, settingsOpen, setSettingsOpen, onAssistant, nav, setNav, adding, setAdding, focus }: {
  snap: Snapshot; settingsOpen: boolean; setSettingsOpen: (v: boolean) => void; onAssistant: () => void; nav: Nav; setNav: (n: Nav) => void;
  adding: boolean; setAdding: (v: boolean) => void; focus?: { id: string; n: number } | null;
}) {
  const [selected, setSelected] = useState<Partial<Record<Nav, string>>>({});
  const all = snap.sources;
  const groups = useMemo(() => listFor(nav, all), [nav, all]);
  const rows = groups.flatMap((g) => g.rows);
  const selId = (selected[nav] && rows.some((r) => r.id === selected[nav])) ? selected[nav]! : rows[0]?.id;
  const view = all.find((s) => s.id === selId) ?? null;
  const prog = useMemo(() => progress(all, new Date()), [all]);
  const { banners, popped, dismiss } = useArrivals(all);
  // Each time another source is collected, a light sweeps along the sidebar's bar.
  const lastCollected = useRef(prog.collected);
  const [grew, setGrew] = useState(0);
  useEffect(() => {
    if (prog.collected > lastCollected.current) setGrew((n) => n + 1);
    lastCollected.current = prog.collected;
  }, [prog.collected]);

  // After you act on a source it moves (Needs You -> In Progress -> Collected); the selection follows it for a
  // couple of minutes instead of jumping to whatever is next in the old list.
  const follow = useRef<{ id: string; until: number } | null>(null);
  // A source just added: shown as soon as it's in a snapshot, from wherever you added it.
  const pending = useRef<string | null>(null);
  useEffect(() => {
    const p = pending.current && all.find((s) => s.id === pending.current);
    if (p) {
      pending.current = null;
      const n = navOf(p);
      animate(() => {
        setNav(n);
        setSelected((s) => ({ ...s, [n]: p.id }));
      });
      return;
    }
    const f = follow.current;
    if (!f || Date.now() > f.until || nav === 'overview' || nav === 'ask' || nav === 'explore' || rows.some((r) => r.id === f.id)) return;
    const v = all.find((s) => s.id === f.id);
    if (!v) return;
    const n = navOf(v);
    animate(() => {
      setNav(n);
      setSelected((s) => ({ ...s, [n]: v.id }));
    });
  }, [all, nav]);

  const go = (n: Nav, id?: string) => {
    if (follow.current && follow.current.id !== id) follow.current = null;
    if (pending.current && pending.current !== id) pending.current = null; // you went somewhere else meanwhile
    animate(() => {
      setNav(n);
      if (id) setSelected((s) => ({ ...s, [n]: id }));
    });
  };
  const jump = (id: string) => {
    const v = all.find((s) => s.id === id);
    if (v) go(navOf(v), v.id);
  };
  // A notification about a source was clicked: show it.
  useEffect(() => {
    if (focus) jump(focus.id);
  }, [focus?.n]);

  const pick = (id: string) => {
    if (follow.current?.id !== id) follow.current = null;
    animate(() => setSelected((s) => ({ ...s, [nav]: id })));
  };

  const counts: Record<Nav, number> = {
    overview: 0, ask: 0, ai: 0, explore: 0, needs: countFor('needs', all), working: countFor('working', all),
    done: countFor('done', all), unavailable: countFor('unavailable', all),
    setup: countFor('setup', all),
    found: snap.discovery?.found.length ?? 0,
    hub: 0,
  };
  // A service just added (here, from the hub or from the menu) is shown once it's in the list, wherever you were.
  const added = (id: string) => {
    follow.current = { id, until: Date.now() + 120_000 };
    if (all.some((s) => s.id === id)) jump(id);
    else pending.current = id;
  };
  const [addName, setAddName] = useState('');
  const addOther = (q?: string) => {
    setAddName(q ?? '');
    setAdding(true);
  };
  // The hub's tabs and the sidebar agree: In Your Data is Found in Your Data; the others are All Sources.
  const [hubFilter, setHubFilter] = useState<HubFilter>('all');
  const onHubFilter = (f: HubFilter) => {
    if (f === 'found') return go('found');
    setHubFilter(f);
    if (nav !== 'hub') go('hub');
  };
  // Up and down arrows move through the list, as in Mail.
  const onListKey = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const i = rows.findIndex((r) => r.id === selId);
    const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (next) pick(next.id);
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-testid="row-${next?.id}"]`)?.focus());
  };

  return (
    <div className={`window ${nav === 'overview' || nav === 'found' || nav === 'hub' || nav === 'explore' || nav === 'ai' || (nav === 'ask' && snap.settings.aiOn !== true) ? 'wide' : ''}`}>
      <nav className="sidebar drag" data-testid="sidebar">
        <div className="no-drag">
          <SideItem id="overview" label="Overview" glyph="gauge" nav={nav} onClick={() => go('overview')} />
          <SideItem id="ask" label="Ask" glyph="bubble" nav={nav} onClick={() => go('ask')} />
          {/* On Explore already: back to its home page, as a tab bar does. */}
          <SideItem id="explore" label="Explore" glyph="compass" nav={nav} onClick={() => (nav === 'explore' ? exploreHome() : go('explore'))} />
          <div className="sidebar-section">Sources</div>
          {NAV.map((n) => <SideItem key={n.id} id={n.id} label={n.label} glyph={n.glyph} nav={nav} count={counts[n.id]} alert={n.id === 'needs'} onClick={() => go(n.id)} />)}
          {/* Every source there is, yours or not yet, and the ones your data points to: adding one starts on that page. */}
          <SideItem id="hub" label="All Sources" glyph="layers" nav={nav} onClick={() => go('hub')} />
          <SideItem id="found" label="Found in Your Data" glyph="search" nav={nav} count={counts.found || undefined} onClick={() => go('found')} />
          <div className="sidebar-section">This Mac</div>
          <SideItem id="setup" label="Setup Checks" glyph="gear" nav={nav} count={counts.setup || undefined} alert onClick={() => go('setup')} />
          <div className="sidebar-section">Settings</div>
          <SideItem id="ai" label="AI Settings" glyph="sparkle" icon={<AiMark size={16} />} nav={nav} onClick={() => go('ai')} />
        </div>
        <div className="sidebar-foot no-drag" data-testid="sidebar-progress">
          <Num value={prog.collected} /> of {prog.applicable} sources collected
          <div className="foot-bar"><ProgressBar value={prog.percent} small />{grew > 0 && <span className="foot-sweep" key={grew} aria-hidden />}</div>
        </div>
      </nav>

      {nav === 'overview' ? (
        <div className="column grouped">
          <Toolbar title="Overview" onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} snap={snap} />
          <div className="scroll"><Overview snap={snap} onJump={jump} onAssistant={onAssistant} /></div>
        </div>
      ) : nav === 'ask' && snap.settings.aiOn !== true ? (
        <div className="column grouped">
          <Toolbar title="Ask" onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} snap={snap} />
          <div className="scroll"><AskAiGate snap={snap} onSettings={() => go('ai')} /></div>
        </div>
      ) : nav === 'ask' ? (
        <AskPage snap={snap} toolbar={<ToolbarButtons onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} />} />
      ) : nav === 'ai' ? (
        <AiPage snap={snap} toolbar={<ToolbarButtons onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} />} />
      ) : nav === 'explore' ? (
        <ExplorePage snap={snap} onSource={jump} toolbar={<ToolbarButtons onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} />} />
      ) : nav === 'found' || nav === 'hub' ? (
        <div className="column grouped">
          <Toolbar title={nav === 'hub' ? 'All Sources' : 'Found in Your Data'} onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} snap={snap} />
          <div className="scroll"><Hub snap={snap} filter={nav === 'found' ? 'found' : hubFilter} onOpen={added} onAdded={(ids) => ids.length > 1 && added(ids[0])}
            onAddOther={addOther} onFilter={onHubFilter} /></div>
        </div>
      ) : (
        <>
          <div className="column" data-testid="list-column">
            <div className="toolbar drag">
              <div>
                <h1>{nav === 'setup' ? 'Setup Checks' : NAV.find((n) => n.id === nav)!.label}</h1>
                <div className="sub" data-testid="list-summary">{listSummary(nav, groups)}</div>
              </div>
            </div>
            <div className="scroll" style={vt('list')}>
              <div className="list" data-testid="sections" onKeyDown={onListKey}>
                {groups.filter((g) => g.rows.length).map((g) => (
                  <div key={g.title ?? 'main'} data-group={g.title ?? 'main'}>
                    {g.title && <div className="list-section">{g.title}</div>}
                    {g.rows.map((v) => <Row key={v.id} v={v} selected={v.id === selId} onSelect={pick} needsYou={g.needsYou} popped={popped.has(v.id)}
                      unlocks={g === groups[0] ? all.filter((s) => s.blockedBy === v.id && s.group !== 'setup') : []} />)}
                  </div>
                ))}
                {!rows.length && <EmptyList nav={nav} />}
              </div>
            </div>
          </div>
          <div className="column grouped" data-testid="right">
            <Toolbar onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} snap={snap} />
            <div className="scroll">
              <div style={vt('detail')}>{view ? <Detail key={view.id} snap={snap} view={view} onActed={(id) => (follow.current = { id, until: Date.now() + 120_000 })}
                onExplore={(page) => { exploreOpen(page); go('explore'); }} /> : null}</div>
            </div>
          </div>
        </>
      )}
      <ArrivalBanners banners={banners} onOpen={jump} onDismiss={dismiss} />
      {adding && <AddServiceSheet initialName={addName} onClose={() => setAdding(false)} onAdded={added} />}
      {settingsOpen && <SettingsSheet snap={snap} onClose={() => setSettingsOpen(false)} onAssistant={() => { setSettingsOpen(false); onAssistant(); }} />}
    </div>
  );
}

function SideItem({ id, label, glyph, icon, nav, count: n, alert, onClick }: { id: Nav; label: string; glyph: string; icon?: ReactNode; nav: Nav; count?: number; alert?: boolean; onClick: () => void }) {
  return (
    <div className={`side-item ${nav === id ? 'selected' : ''}`} onClick={onClick} data-testid={`nav-${id}`} role="button" tabIndex={0} aria-current={nav === id ? 'page' : undefined}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onClick())}>
      {icon ?? <Glyph name={glyph} size={16} />}
      <span>{label}</span>
      {n !== undefined && n > 0 && <span className={`count ${alert ? 'alert' : ''}`}>{n}</span>}
    </div>
  );
}

function Toolbar({ title, snap, onAssistant, onSettings }: { title?: string; snap: Snapshot; onAssistant: () => void; onSettings: () => void }) {
  return (
    <div className="toolbar drag">
      {title && <h1>{title}</h1>}
      {snap.label && <span className="tag" data-testid="label">{snap.label}</span>}
      {snap.readOnly && !snap.demo && <span className="tag">Read-only</span>}
      <div className="spacer" />
      {snap.jobs.length > 0 && <span className="sub no-drag" style={{ display: 'flex', alignItems: 'center', gap: 6, marginRight: 6 }}><Spinner size={12} />{snap.jobs[0].label}</span>}
      <ToolbarButtons onAssistant={onAssistant} onSettings={onSettings} />
    </div>
  );
}

function ToolbarButtons({ onAssistant, onSettings }: { onAssistant: () => void; onSettings: () => void }) {
  return (
    <>
      <button className="icon-btn no-drag" onClick={onAssistant} title="Setup Assistant" aria-label="Setup Assistant"><Glyph name="sparkle" size={16} /></button>
      <button className="icon-btn no-drag" onClick={onSettings} title="Settings" aria-label="Settings"><Glyph name="gear" size={16} /></button>
    </>
  );
}

function Row({ v, selected, onSelect, unlocks, needsYou, popped }: { v: SourceView; selected: boolean; onSelect: (id: string) => void; unlocks: SourceView[]; needsYou?: boolean; popped?: boolean }) {
  // The dot marks each row the sidebar badge counts.
  const side = needsYou ? <span className="status-dot needs" role="img" aria-label="Needs you" data-testid="needs-dot" />
    : v.section === 'done' && v.group !== 'setup' && v.records > 0 ? <RowCount v={v} popped={!!popped} /> : v.waiting ? <WaitClock size={15} started={v.requestedAt} />
      : v.section === 'working' ? <Spinner size={13} /> : null;
  return (
    <div className={`lrow ${selected ? 'selected' : ''} ${popped ? 'arrived' : ''}`} onClick={() => onSelect(v.id)} data-testid={`row-${v.id}`} data-section={v.section} style={vt(`row-${v.id}`)}
      role="option" aria-selected={selected} tabIndex={selected ? 0 : -1} onFocus={() => !selected && onSelect(v.id)}>
      <SourceIcon id={v.id} group={v.group} size={28} />
      <div className="main">
        <div className="name"><span className="n">{v.name}</span>{v.tag && <span className="tag">{v.tag}</span>}</div>
        <div className="status">{v.status}</div>
        {v.warnings[0] && <div className="warn">{v.warnings[0]}</div>}
        {unlocks.length > 0 && <div className="unlocks">Unlocks {unlocks.map((u) => u.name).join(', ')}</div>}
        {v.section === 'working' && !v.waiting && <div style={{ marginTop: 5 }}><ProgressBar value={v.progress} small /></div>}
      </div>
      <div className="side">{side}</div>
    </div>
  );
}

function EmptyList({ nav }: { nav: Nav }) {
  const text: Partial<Record<Nav, [string, string]>> = {
    needs: ['Nothing needs you', 'Everything that needs a hand is done or on its way.'],
    working: ['Nothing in progress', 'Reading and imports show up here while they run.'],
    done: ['Nothing collected yet', 'Sources land here as they\'re read.'],
    unavailable: ['Collecting everything', 'Sources you skip, and ones that aren\'t on this Mac, show up here. You can include any of them again.'],
  };
  const [h, p] = text[nav] ?? ['', ''];
  return <div className="empty appear"><h2>{h}</h2>{p}</div>;
}

// ---------------------------------------------------------------- overview

export function PhaseMark({ p }: { p: Phase }) {
  if (p.status === 'done') return <div className="tl-mark"><Checkmark size={20} /></div>;
  if (p.status === 'skipped') return <div className="tl-mark"><div className="ring-dot" style={{ opacity: 0.4 }} /></div>;
  return <div className="tl-mark"><div className={`ring-dot ${p.status === 'active' ? 'active' : ''}`} /></div>;
}

export function Timeline({ phases, onPhase }: { phases: Phase[]; onPhase?: (p: Phase) => void }) {
  return (
    <div className="group-box timeline" data-testid="timeline">
      {phases.map((p) => (
        <div key={p.id} className={`tl-item ${p.status} ${onPhase && p.total ? 'clickable' : ''}`} onClick={() => onPhase && p.total && onPhase(p)} data-testid={`phase-${p.id}`} data-status={p.status}>
          <PhaseMark p={p} />
          <div className="tl-main">
            <div className="tl-title">{p.title}</div>
            <div className="tl-detail">{p.detail}</div>
          </div>
          {p.total > 0 && <div className="tl-bar"><ProgressBar value={p.done / p.total} small /></div>}
          <div className="tl-count">{p.total ? `${p.done} of ${p.total}` : '—'}</div>
        </div>
      ))}
    </div>
  );
}

function Overview({ snap, onJump, onAssistant }: { snap: Snapshot; onJump: (id: string) => void; onAssistant: () => void }) {
  const now = new Date();
  const prog = progress(snap.sources, now);
  const next = snap.sources.find((v) => v.id === snap.next);
  return (
    <div className="overview" data-testid="overview">
      <div className="group-box" style={{ marginTop: 6 }}>
        <div className="ov-hero">
          <ProgressRing value={prog.percent} size={104} stroke={10}>
            <div className="pct" data-testid="percent">{Math.round(prog.percent * 100)}%</div>
            <div className="pct-sub">collected</div>
          </ProgressRing>
          <div>
            <h2>{prog.collected} of {prog.applicable} sources in your library</h2>
            <p>{prog.toDo ? `${prog.toDo} ${prog.toDo === 1 ? 'thing needs' : 'things need'} you` : 'Nothing needs you right now'}{prog.waiting.length ? ` · ${prog.waiting.length} ${prog.waiting.length === 1 ? 'export' : 'exports'} on the way` : ''}.</p>
            <div className="ov-stats">
              <span><b>{count(snap.summary.records)}</b> records</span>
              <span><b>{snap.summary.working}</b> in progress</span>
            </div>
          </div>
        </div>
      </div>

      <Group title="Up next">
        {!snap.probeTime ? (
          <div className="next-card" data-testid="next">
            <Spinner size={20} />
            <div style={{ flex: 1 }}><div className="title">Checking this Mac…</div><div className="status">Looking for your sources and settings.</div></div>
          </div>
        ) : next ? (
          <div className="next-card" data-testid="next">
            <SourceIcon id={next.id} group={next.group} size={36} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="title">{next.name}</div>
              <div className="status">{next.status}</div>
            </div>
            <Button kind="primary" onClick={() => onJump(next.id)}>Show</Button>
          </div>
        ) : (
          <div className="next-card" data-testid="next">
            <Checkmark size={28} />
            <div style={{ flex: 1 }}>
              <div className="title">{prog.waiting.length ? 'Waiting on exports' : 'All caught up'}</div>
              <div className="status">{prog.waiting.length ? (snap.settings.watchDownloads ? 'Each export is imported as soon as it lands in Downloads.' : 'When each one comes, add it on its page (Watch Downloads is off in Settings).')
                : 'Everything available is in your library.'}</div>
            </div>
          </div>
        )}
      </Group>

      <Group title="Timeline" footer="Phases run side by side: the Mac keeps reading while exports are on their way.">
        <Timeline phases={prog.phases} onPhase={(p) => onJump(p.sourceIds[0])} />
      </Group>

      {prog.waiting.length > 0 && (
        <Group title="On the way" testId="waiting">
          {prog.waiting.map((w) => {
            const v = snap.sources.find((s) => s.id === w.id)!;
            const tag = wayTag(w);
            return <GroupRow key={w.id} icon={<SourceIcon id={w.id} size={24} />} title={w.name}
              subtitle={`Requested ${ago(v.requestedAt, now)} · ${readyIn(w, now)}`} onClick={() => onJump(w.id)}
              trailing={tag ? <span className="tag" data-testid={`way-${w.id}`} style={{ background: `color-mix(in srgb, var(--${tag.color}) 20%, transparent)`, color: `var(--${tag.color})` }}>{tag.text}</span> : undefined} />;
          })}
        </Group>
      )}

      {!snap.onboarding.done && (
        <div style={{ marginTop: 18, textAlign: 'center' }}><Button onClick={onAssistant} testAction="continue-assistant">Continue in the Setup Assistant</Button></div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- settings

function SettingsSheet({ snap, onClose, onAssistant }: { snap: Snapshot; onClose: () => void; onAssistant: () => void }) {
  const s = snap.settings;
  // Read-only mode: settings that would change what's kept are shown, not changed.
  const locked = snap.readOnly && !snap.demo;
  const lock = (t: ReactNode) => (locked ? <span title={READ_ONLY_NOTE} style={{ opacity: 0.45, pointerEvents: 'none' }}>{t}</span> : t);
  // Claude's checks need it to download what it finds, and Claude Code.
  const agent = s.aiOn === true && !!s.agentExports && s.agentDownloads !== false && snap.agentInstalled !== false;
  return (
    <Sheet onClose={onClose} testId="settings" width={500}>
      <h2>Settings</h2>
      <div className="group-box" style={{ marginTop: 10 }}>
        <GroupRow title="Read this Mac every day" subtitle="Screen Time, Chrome and the call log forget history. Each run keeps what it saw."
          trailing={lock(<Toggle checked={s.autoRefresh} onChange={(v) => void api.settings({ autoRefresh: v })} label="Read this Mac every day" />)} />
        <GroupRow title="Watch Downloads for exports"
          subtitle={s.watchDownloads ? 'An export you asked for is imported as it lands in Downloads. Any other waits on its page for you to say yes.'
            : 'Off: add each download on its page. What Claude downloads for you is still read.'}
          trailing={lock(<Toggle checked={s.watchDownloads} onChange={(v) => void api.settings({ watchDownloads: v })} label="Watch Downloads" testId="toggle-watch" />)} />
        <GroupRow title="Keep working when the window is closed" subtitle="Homecoming stays in the menu bar, reading this Mac and watching for your exports."
          trailing={<Toggle checked={!!s.background} onChange={(v) => void api.settings({ background: v })} label="Keep working when closed" testId="toggle-background" />} />
        <GroupRow title="Open at login" subtitle={s.background ? 'Starts in the menu bar when you log in.' : 'Opens Homecoming when you log in.'}
          trailing={<Toggle checked={!!s.openAtLogin} onChange={(v) => void api.settings({ openAtLogin: v })} label="Open at login" testId="toggle-login" />} />
      </div>

      <div className="group-box" style={{ marginTop: 12 }}>
        <GroupRow title="Look for exports every few hours" testId="settings-checks"
          subtitle={agent ? 'While an export is on its way, Claude opens Chrome now and then to check the service\'s page, or your webmail for the email saying it\'s ready, and downloads it.'
            : 'Needs Do It for Me, with downloads on, in AI Settings.'}
          trailing={agent ? lock(<Toggle checked={s.agentChecks !== false} onChange={(v) => void api.settings({ agentChecks: v })} label="Look for exports every few hours" testId="toggle-checks" />)
            : <span className="tag">Off</span>} />
        <GroupRow title="AI and Do It for Me…" subtitle="Which agent does the work, and what uses it." testId="settings-ai"
          onClick={() => { onClose(); void api.action('*', 'show-ai'); }} />
      </div>

      <div className="group-box" style={{ marginTop: 12 }}>
        <GroupRow title="Your library" subtitle={<code className="selectable">{snap.corpusPath}</code>} />
      </div>
      <div className="sheet-actions" style={{ justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button onClick={() => void api.action('*', 'run-all-mac')} disabled={snap.readOnly} title={locked ? READ_ONLY_NOTE : undefined}>Read This Mac Now</Button>
          <Button onClick={onAssistant}>Setup Assistant…</Button>
        </div>
        <Button kind="primary" onClick={onClose}>Done</Button>
      </div>
    </Sheet>
  );
}
