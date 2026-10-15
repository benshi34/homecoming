// Root: the Setup Assistant until it's finished (or skipped), the main window after. Snapshot changes that
// move sources between sections run as view transitions, so rows glide to where they now belong.

import { type CSSProperties, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { setServices } from '../shared/catalog.ts';
import type { Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { Assistant } from './assistant.tsx';
import { Glyph } from './icons.tsx';
import { MainWindow, type Nav } from './main_window.tsx';
import { animate } from './ui.tsx';

// What changes the layout: which section each source is in, and the order. Status text alone doesn't.
const layoutOf = (s: Snapshot) => s.sources.map((v) => `${v.id}:${v.section}:${v.blockedBy ?? ''}`).join('|');

function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [toasts, setToasts] = useState<{ id: number; text: string; kind: string }[]>([]);
  const [assistant, setAssistant] = useState<boolean | null>(null); // null: follow onboarding.done
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [nav, setNav] = useState<Nav>('overview');
  const [dragging, setDragging] = useState(false);
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null); // a source to show (its notification was clicked)
  const layout = useRef('');

  useEffect(() => {
    void api.snapshot().then((s) => {
      setServices(s.services ?? []);
      layout.current = layoutOf(s);
      setSnap(s);
    });
    const off = api.onSnapshot((s) => {
      setServices(s.services ?? []);
      const l = layoutOf(s);
      if (l !== layout.current) {
        layout.current = l;
        animate(() => setSnap(s));
      } else setSnap(s);
    });
    let n = 0;
    const offT = api.onToast((t) => {
      const id = ++n;
      setToasts((ts) => [...ts.filter((x) => x.text !== t.text).slice(-2), { id, ...t }]);
      setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), t.kind === 'error' ? 9000 : 5000);
    });
    const offM = api.onMenu((cmd) => {
      if (cmd === 'show-settings') setSettingsOpen(true);
      if (cmd === 'add-service') animate(() => { setAssistant(false); setAdding(true); });
      if (cmd === 'show-hub') animate(() => { setAssistant(false); setNav('hub'); });
      if (cmd === 'show-assistant') animate(() => setAssistant(true));
      if (cmd === 'show-overview') animate(() => { setAssistant(false); setNav('overview'); });
      if (cmd.startsWith('open-source:')) animate(() => { setAssistant(false); setFocus({ id: cmd.slice(12), n: Date.now() }); });
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

  const showAssistant = assistant ?? !snap.onboarding.done;
  const finish = () => {
    void api.onboarding({ done: true });
    animate(() => {
      setAssistant(false);
      setNav('overview');
    });
  };
  const style = snap.accent ? ({ '--accent': snap.accent } as CSSProperties) : undefined;
  return (
    <div style={{ height: '100%', ...style }} data-testid="app" data-mode={showAssistant ? 'assistant' : 'main'}>
      {showAssistant
        ? <Assistant snap={snap} onFinish={finish} onExit={finish} />
        : <MainWindow snap={snap} settingsOpen={settingsOpen} setSettingsOpen={setSettingsOpen} nav={nav} setNav={setNav} focus={focus}
          adding={adding} setAdding={setAdding} onAssistant={() => animate(() => setAssistant(true))} />}
      <div className="toasts" data-testid="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <Glyph name={t.kind === 'error' ? 'warning' : 'checkCircle'} size={16} />
            <span>{t.text}</span>
          </div>
        ))}
      </div>
      {dragging && <div className="dropping" />}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
