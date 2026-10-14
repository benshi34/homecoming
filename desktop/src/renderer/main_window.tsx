// The main window, laid out like Mail or Notes: a vibrant sidebar of sections (with counts), the sources in
// the chosen section, and the selected source on the right. Overview holds the progress timeline.

import { useEffect, useMemo, useRef, useState } from 'react';
import { ago, count } from '../shared/format.ts';
import { type Phase, progress, readyIn } from '../shared/progress.ts';
import { countFor, listFor, listSummary, type Nav, navOf } from '../shared/lists.ts';
import type { Snapshot, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { Glyph, SourceIcon } from './icons.tsx';
import { AskPage } from './ask.tsx';
import { ExplorePage, Num } from './explore.tsx';
import { Hub } from './hub.tsx';
import { ArrivalBanners, RowCount, useArrivals, WaitClock } from './moments.tsx';
import { AddServiceSheet, Detail, vt } from './parts.tsx';
import { animate, Button, Checkmark, Group, GroupRow, ProgressBar, ProgressRing, Sheet, Spinner, Toggle } from './ui.tsx';

export type { Nav } from '../shared/lists.ts';

const NAV: { id: Nav; label: string; glyph: string }[] = [
  { id: 'needs', label: 'Needs You', glyph: 'bell' },
  { id: 'working', label: 'In Progress', glyph: 'arrows' },
  { id: 'done', label: 'Collected', glyph: 'checkCircle' },
  { id: 'unavailable', label: 'Not Available', glyph: 'minusCircle' },
];

export function MainWindow({ snap, settingsOpen, setSettingsOpen, onAssistant, nav, setNav, adding, setAdding }: {
  snap: Snapshot; settingsOpen: boolean; setSettingsOpen: (v: boolean) => void; onAssistant: () => void; nav: Nav; setNav: (n: Nav) => void;
  adding: boolean; setAdding: (v: boolean) => void;
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
  useEffect(() => {
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
    animate(() => {
      setNav(n);
      if (id) setSelected((s) => ({ ...s, [n]: id }));
    });
  };
  const jump = (id: string) => {
    const v = all.find((s) => s.id === id);
    if (v) go(navOf(v), v.id);
  };
  const pick = (id: string) => {
    if (follow.current?.id !== id) follow.current = null;
    animate(() => setSelected((s) => ({ ...s, [nav]: id })));
  };

  const counts: Record<Nav, number> = {
    overview: 0, ask: 0, explore: 0, needs: countFor('needs', all), working: countFor('working', all),
    done: countFor('done', all), unavailable: countFor('unavailable', all),
    setup: countFor('setup', all),
    found: snap.discovery?.found.length ?? 0,
    hub: 0,
  };
  // A service just added (here or from the menu) is selected once it shows up.
  const added = (id: string) => {
    follow.current = { id, until: Date.now() + 120_000 };
    jump(id);
  };

  return (
    <div className={`window ${nav === 'overview' || nav === 'found' || nav === 'hub' || nav === 'explore' ? 'wide' : ''}`}>
      <nav className="sidebar drag" data-testid="sidebar">
        <div className="no-drag">
          <SideItem id="overview" label="Overview" glyph="gauge" nav={nav} onClick={() => go('overview')} />
          <SideItem id="ask" label="Ask" glyph="bubble" nav={nav} onClick={() => go('ask')} />
          <SideItem id="explore" label="Explore" glyph="compass" nav={nav} onClick={() => go('explore')} />
          <div className="sidebar-section">Sources</div>
          {NAV.map((n) => <SideItem key={n.id} id={n.id} label={n.label} glyph={n.glyph} nav={nav} count={counts[n.id]} alert={n.id === 'needs'} onClick={() => go(n.id)} />)}
          <div className="sidebar-section">This Mac</div>
          <SideItem id="setup" label="Setup Checks" glyph="gear" nav={nav} count={counts.setup || undefined} alert onClick={() => go('setup')} />
          <div className="sidebar-section">Other Accounts</div>
          <SideItem id="hub" label="All Services" glyph="layers" nav={nav} onClick={() => go('hub')} />
          <SideItem id="found" label="Found in Your Data" glyph="search" nav={nav} count={counts.found || undefined} onClick={() => go('found')} />
          <div className="side-item" onClick={() => setAdding(true)} data-testid="nav-add-service"><Glyph name="plus" size={16} /><span>Add Another Service…</span></div>
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
      ) : nav === 'ask' ? (
        <AskPage snap={snap} toolbar={<ToolbarButtons onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} />} />
      ) : nav === 'explore' ? (
        <ExplorePage snap={snap} toolbar={<ToolbarButtons onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} />} />
      ) : nav === 'found' || nav === 'hub' ? (
        <div className="column grouped">
          <Toolbar title={nav === 'hub' ? 'All Services' : 'Found in Your Data'} onAssistant={onAssistant} onSettings={() => setSettingsOpen(true)} snap={snap} />
          <div className="scroll"><Hub snap={snap} filter={nav === 'found' ? 'found' : 'all'} onOpen={added} onAddOther={() => setAdding(true)} /></div>
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
              <div className="list" data-testid="sections">
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
              <div style={vt('detail')}>{view ? <Detail key={view.id} snap={snap} view={view} onActed={(id) => (follow.current = { id, until: Date.now() + 120_000 })} /> : <div className="empty">Nothing selected.</div>}</div>
            </div>
          </div>
        </>
      )}
      <ArrivalBanners banners={banners} onOpen={jump} onDismiss={dismiss} />
      {adding && <AddServiceSheet onClose={() => setAdding(false)} onAdded={added} />}
      {settingsOpen && <SettingsSheet snap={snap} onClose={() => setSettingsOpen(false)} onAssistant={() => { setSettingsOpen(false); onAssistant(); }} />}
    </div>
  );
}

function SideItem({ id, label, glyph, nav, count: n, alert, onClick }: { id: Nav; label: string; glyph: string; nav: Nav; count?: number; alert?: boolean; onClick: () => void }) {
  return (
    <div className={`side-item ${nav === id ? 'selected' : ''}`} onClick={onClick} data-testid={`nav-${id}`}>
      <Glyph name={glyph} size={16} />
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
      {snap.readOnly && <span className="tag">Read-only</span>}
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
    <div className={`lrow ${selected ? 'selected' : ''} ${popped ? 'arrived' : ''}`} onClick={() => onSelect(v.id)} data-testid={`row-${v.id}`} data-section={v.section} style={vt(`row-${v.id}`)}>
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
    unavailable: ['Everything is available', 'Sources that aren\'t on this Mac, or that you skip, show up here.'],
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
            <h2>{prog.collected} of {prog.applicable} sources in your corpus</h2>
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
              <div className="status">{prog.waiting.length ? 'Each export is imported as soon as it lands in Downloads.' : 'Everything available is in your corpus.'}</div>
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
            return <GroupRow key={w.id} icon={<SourceIcon id={w.id} size={24} />} title={w.name}
              subtitle={`Requested ${ago(v.requestedAt, now)} · ${readyIn(w, now)}`} onClick={() => onJump(w.id)}
              trailing={w.ready ? <span className="tag" style={{ background: 'color-mix(in srgb, var(--green) 20%, transparent)', color: 'var(--green)' }}>Ready</span> : undefined} />;
          })}
        </Group>
      )}

      {!snap.onboarding.done && (
        <div style={{ marginTop: 18, textAlign: 'center' }}><Button onClick={onAssistant}>Continue in the Setup Assistant</Button></div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- settings

function SettingsSheet({ snap, onClose, onAssistant }: { snap: Snapshot; onClose: () => void; onAssistant: () => void }) {
  const s = snap.settings;
  return (
    <Sheet onClose={onClose} testId="settings" width={500}>
      <h2>Settings</h2>
      <div className="group-box" style={{ marginTop: 10 }}>
        <GroupRow title="Read this Mac every day" subtitle="Screen Time, Chrome and the call log forget history. Each run keeps what it saw."
          trailing={<Toggle checked={s.autoRefresh} onChange={(v) => void api.settings({ autoRefresh: v })} label="Read this Mac every day" />} />
        <GroupRow title="Watch Downloads for exports" subtitle="Finished exports are recognized and imported."
          trailing={<Toggle checked={s.watchDownloads} onChange={(v) => void api.settings({ watchDownloads: v })} label="Watch Downloads" />} />
      </div>
      <div className="group-box" style={{ marginTop: 12 }}>
        <GroupRow title="Corpus" subtitle={<code className="selectable">{snap.corpusPath}</code>} />
      </div>
      <div className="sheet-actions" style={{ justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button onClick={() => void api.action('*', 'run-all-mac')} disabled={snap.readOnly}>Read This Mac Now</Button>
          <Button onClick={onAssistant}>Setup Assistant…</Button>
        </div>
        <Button kind="primary" onClick={onClose}>Done</Button>
      </div>
    </Sheet>
  );
}
