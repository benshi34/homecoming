// Root: the Setup Assistant until it's finished (or skipped), the main window after. Snapshot changes that
// move sources between sections run as view transitions, so rows glide to where they now belong.

import { type CSSProperties, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { setServices } from '../shared/catalog.ts';
import { setPhoneRegion } from '../shared/identity.ts';
import type { Snapshot } from '../shared/types.ts';
import type { Release } from '../shared/version.ts';
import { api } from './api.ts';
import { Assistant } from './assistant.tsx';
import { Celebrations } from './celebrate.tsx';
import { ExportSheet } from './export_sheet.tsx';
import { Glyph } from './icons.tsx';
import { MainWindow, type Nav } from './main_window.tsx';
import { UpdateSheet } from './update_sheet.tsx';
import { WhatsNewSheet } from './whats_new.tsx';
import { animate, ReadOnly } from './ui.tsx';
import { READ_ONLY_NOTE } from '../shared/status.ts';

// What changes the layout: which section each source is in, and the order. Status text alone doesn't.
const layoutOf = (s: Snapshot) => s.sources.map((v) => `${v.id}:${v.section}:${v.blockedBy ?? ''}`).join('|');

function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [toasts, setToasts] = useState<{ id: number; text: string; kind: string; undo?: { sourceId: string; action: string }; about?: string }[]>([]);
  const [assistant, setAssistant] = useState<boolean | null>(null); // null: follow onboarding.done
  const [exportOpen, setExportOpen] = useState(false); // Export Your Library
  // What's New: from the menu bar or General (this version's); and the one shown once after an update, closed.
  const [whatsNew, setWhatsNew] = useState<Release[] | null>(null);
  const [newSeen, setNewSeen] = useState(false);
  const [updateOpen, setUpdateOpen] = useState(false); // a newer Homecoming: its sheet
  const [adding, setAdding] = useState(false);
  const [nav, setNav] = useState<Nav>('overview');
  const [dragging, setDragging] = useState(false);
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null); // a source to show (its notification was clicked)
  const layout = useRef('');
  // The Setup Assistant, opened again (from the toolbar or the menu): kept open across a restart until it's left.
  const openAssistant = () => {
    setAssistant(true);
    void api.onboarding({ open: true });
  };
  const showWhatsNew = () => void api.whatsNew('get').then((r) => r.length && setWhatsNew(r));
  const toMain = () => {
    setAssistant(false);
    void api.onboarding({ open: false });
  };

  useEffect(() => {
    void api.snapshot().then((s) => {
      setServices(s.services ?? []);
      setPhoneRegion(s.setup?.phone);
      layout.current = layoutOf(s);
      setSnap(s);
    });
    const off = api.onSnapshot((s) => {
      setServices(s.services ?? []);
      setPhoneRegion(s.setup?.phone);
      const l = layoutOf(s);
      if (l !== layout.current) {
        layout.current = l;
        animate(() => setSnap(s));
      } else setSnap(s);
    });
    let n = 0;
    const offT = api.onToast((t) => {
      const id = ++n;
      // A newer one about the same source takes the older one's place (skipped, then set aside: only the last is so).
      setToasts((ts) => [...ts.filter((x) => x.text !== t.text && !(t.about && x.about === t.about)).slice(-2), { id, ...t }]);
      setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), t.kind === 'error' || t.undo ? 9000 : 5000);
    });
    const offM = api.onMenu((cmd) => {
      if (cmd === 'show-settings') animate(() => { toMain(); setNav('general'); });
      if (cmd === 'show-export') setExportOpen(true);
      if (cmd === 'show-whats-new') showWhatsNew();
      if (cmd === 'show-update') setUpdateOpen(true);
      if (cmd === 'add-service') animate(() => { toMain(); setAdding(true); });
      if (cmd === 'show-hub') animate(() => { toMain(); setNav('hub'); });
      if (cmd === 'show-assistant') animate(() => openAssistant());
      if (cmd === 'show-overview') animate(() => { toMain(); setNav('overview'); });
      if (cmd === 'show-ai') animate(() => { toMain(); setNav('ai'); });
      if (cmd === 'show-setup') animate(() => { toMain(); setNav('yoursetup'); });
      if (cmd.startsWith('open-source:')) animate(() => { toMain(); setFocus({ id: cmd.slice(12), n: Date.now() }); });
    });
    return () => {
      off();
      offT();
      offM();
    };
  }, []);

  // Files dropped anywhere go to the source on screen, else wherever their contents say they belong.
  useEffect(() => {
    const over = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes('Files')) {
        e.preventDefault();
        setDragging(true);
      }
    };
    const leave = (e: DragEvent) => !e.relatedTarget && setDragging(false);
    const drop = (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const files = [...(e.dataTransfer?.files ?? [])];
      const onScreen = document.querySelector('[data-testid=detail]')?.getAttribute('data-source')
        ?? document.querySelector('[data-testid=assistant]')?.getAttribute('data-step')?.replace(/^export:/, '').replace(/^mail$/, 'other_mail');
      const target = onScreen && snap?.sources.find((v) => v.id === onScreen && ['web', 'guided'].includes(v.group)) ? onScreen : null;
      if (files.length) void api.dropFiles(files, target);
    };
    window.addEventListener('dragover', over);
    window.addEventListener('dragleave', leave);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragover', over);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('drop', drop);
    };
  }, [snap]);

  if (!snap) return <div className="window wide"><div className="sidebar drag" /><div className="column"><div className="empty">Checking this Mac…</div></div></div>;

  // Left part-way, it stays left (the Overview offers to carry on) until it's finished.
  const showAssistant = assistant ?? (!!snap.onboarding.open || (!snap.onboarding.done && !snap.onboarding.skippedAt));
  const leave = (patch: Partial<Snapshot['onboarding']>) => {
    void api.onboarding({ ...patch, open: false });
    animate(() => {
      setAssistant(false);
      setNav('overview');
    });
  };
  // Finished; from a row on the last page, straight to that source.
  const finish = (showId?: string) => {
    leave({ done: true });
    if (showId) setFocus({ id: showId, n: Date.now() });
  };
  const exit = () => leave({ skippedAt: new Date().toISOString() });
  // What's new since the version you had, over whatever is open, until it's closed: then it isn't shown again.
  const newOnes = whatsNew ?? (newSeen ? null : snap.whatsNew ?? null);
  const closeNew = () => {
    if (snap.whatsNew && !newSeen) {
      setNewSeen(true);
      void api.whatsNew('seen');
    }
    setWhatsNew(null);
  };
  const style = snap.accent ? ({ '--accent': snap.accent } as CSSProperties) : undefined;
  return (
    <ReadOnly.Provider value={snap.readOnly && !snap.demo ? READ_ONLY_NOTE : null}>
    <div style={{ height: '100%', ...style }} data-testid="app" data-mode={showAssistant ? 'assistant' : 'main'}>
      {showAssistant
        ? <Assistant snap={snap} onFinish={finish} onExit={exit} />
        : <MainWindow snap={snap} nav={nav} setNav={setNav} focus={focus}
          adding={adding} setAdding={setAdding} onAssistant={() => animate(() => openAssistant())} onExport={() => setExportOpen(true)} onWhatsNew={showWhatsNew}
          onUpdate={() => setUpdateOpen(true)} />}
      {exportOpen && <ExportSheet snap={snap} onClose={() => setExportOpen(false)} />}
      {newOnes && <WhatsNewSheet releases={newOnes} onClose={closeNew} />}
      {updateOpen && !newOnes && <UpdateSheet snap={snap} onClose={() => setUpdateOpen(false)} />}
      <div className="toasts" data-testid="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <Glyph name={t.kind === 'error' ? 'warning' : 'checkCircle'} size={16} />
            <span>{t.text}</span>
            {t.undo && <button className="toast-undo" data-action="toast-undo" onClick={() => {
              void api.action(t.undo!.sourceId, t.undo!.action);
              setToasts((ts) => ts.filter((x) => x.id !== t.id));
            }}>Undo</button>}
          </div>
        ))}
      </div>
      {dragging && <div className="dropping"><div className="dropping-label">{dropLabel(snap)}</div></div>}
      {/* A source coming home, an export asked for: worth a moment, in the Setup Assistant and the window alike. */}
      <Celebrations sources={snap.sources} loaded={snap.loaded !== false} />
    </div>
    </ReadOnly.Provider>
  );
}

// What happens to files dropped now: the source on screen gets them, else they go wherever their contents say.
function dropLabel(snap: Snapshot): string {
  const onScreen = document.querySelector('[data-testid=detail]')?.getAttribute('data-source')
    ?? document.querySelector('[data-testid=assistant]')?.getAttribute('data-step')?.replace(/^export:/, '');
  const v = onScreen ? snap.sources.find((x) => x.id === onScreen && ['web', 'guided'].includes(x.group)) : undefined;
  return v ? `Drop to add it to ${v.name}` : 'Drop an export to add it to your library';
}

createRoot(document.getElementById('root')!).render(<App />);
