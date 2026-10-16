// Controls drawn to look and move like AppKit's: push buttons, switches, the spoked spinner, grouped forms,
// sheets. Animations go through the View Transitions API and respect Reduce Motion.

import { type CSSProperties, type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { Glyph } from './icons.tsx';

export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let transitioning = false;

// Runs a state change as an animated view transition: named elements (rows, the detail pane, assistant
// pages) morph from where they were to where they are. direction picks the assistant's slide.
// direction: a page slide ('forward', 'back'), 'move' for things moving within a page (the page itself stays put), or
// 'zoom' for an element growing into the page it opens (Explore's tiles; styles.css names the pair).
export function animate(change: () => void, direction?: 'forward' | 'back' | 'move' | 'zoom') {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => { finished: Promise<void> } };
  if (!doc.startViewTransition || reducedMotion() || transitioning || document.visibilityState !== 'visible') {
    change();
    return;
  }
  document.documentElement.dataset.nav = direction ?? 'none';
  transitioning = true;
  const t = doc.startViewTransition(() => flushSync(change));
  t.finished.finally(() => {
    transitioning = false;
    delete document.documentElement.dataset.nav;
  });
}

// The mark on everything AI does (a four-pointed sparkle in a blue-to-pink gradient), so it's never mistaken for
// the app doing something by itself.
export function AiMark({ size = 13, className = '' }: { size?: number; className?: string }) {
  const id = useId();
  return (
    <svg className={`ai-mark ${className}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <defs><linearGradient id={id} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#4f8ef7" /><stop offset="0.55" stopColor="#9b6cf6" /><stop offset="1" stopColor="#ee6aa7" /></linearGradient></defs>
      <path d="M12 1.6c.6 5 3.2 9.2 10.4 10.4-7.2 1.2-9.8 5.4-10.4 10.4-.6-5-3.2-9.2-10.4-10.4C8.8 10.8 11.4 6.6 12 1.6Z" fill={`url(#${id})`} />
    </svg>
  );
}

export function Button({ children, kind = 'default', size = 'regular', onClick, disabled, type = 'button', testAction, title, ariaLabel, className = '', ai }: {
  children: ReactNode; kind?: 'primary' | 'default' | 'plain' | 'destructive'; size?: 'regular' | 'large' | 'small';
  onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit'; testAction?: string; title?: string; ariaLabel?: string; className?: string;
  ai?: boolean; // done by AI: the sparkle, and a gradient when it's the primary button
}) {
  return (
    <button type={type} className={`btn btn-${kind} btn-${size} ${ai ? 'btn-ai' : ''} ${className}`} onClick={onClick} disabled={disabled} data-action={testAction} title={title} aria-label={ariaLabel}>
      {ai && <AiMark size={size === 'small' ? 11 : 13} />}
      {children}
    </button>
  );
}

export function Toggle({ checked, onChange, label, testId }: { checked: boolean; onChange: (v: boolean) => void; label?: string; testId?: string }) {
  // Flip at once; the saved value catches up a moment later.
  const [on, setOn] = useState(checked);
  useEffect(() => setOn(checked), [checked]);
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} data-testid={testId}
      className={`switch ${on ? 'on' : ''}`} onClick={() => { setOn(!on); onChange(!on); }}>
      <span className="knob" />
    </button>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span className="spinner" style={{ width: size, height: size }} role="progressbar" aria-label="Working">
      {Array.from({ length: 8 }, (_, i) => <i key={i} style={{ transform: `rotate(${i * 45}deg)`, animationDelay: `${(i - 8) * 0.1}s` }} />)}
    </span>
  );
}

// A checkmark that draws itself the first time it appears.
export function Checkmark({ size = 18, color = 'var(--green)' }: { size?: number; color?: string }) {
  return (
    <svg className="checkmark" width={size} height={size} viewBox="0 0 24 24" aria-label="Done">
      <circle cx="12" cy="12" r="11" fill={color} />
      <path d="m7 12.4 3.3 3.3L17.2 8.8" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function StatusGlyph({ section, size = 16 }: { section: string; size?: number }) {
  if (section === 'done') return <Checkmark size={size} />;
  if (section === 'working') return <Spinner size={size - 2} />;
  if (section === 'needs') return <span className="status-dot needs" style={{ width: size * 0.55, height: size * 0.55 }} aria-label="Needs you" />;
  return <span className="status-dot off" style={{ width: size * 0.55, height: size * 0.55 }} aria-label="Not available" />;
}

export function ProgressRing({ value, size = 96, stroke = 9, children }: { value: number; size?: number; stroke?: number; children?: ReactNode }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  // Animate from 0 on first paint, then follow the value.
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const t = requestAnimationFrame(() => setShown(Math.max(0, Math.min(1, value))));
    return () => cancelAnimationFrame(t);
  }, [value]);
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} className="ring-track" strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} className="ring-fill" strokeWidth={stroke} fill="none"
          strokeDasharray={c} strokeDashoffset={c * (1 - shown)} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <div className="ring-label">{children}</div>
    </div>
  );
}

export function ProgressBar({ value, small }: { value?: number; small?: boolean }) {
  return (
    <div className={`bar ${value === undefined ? 'indeterminate' : ''} ${small ? 'small' : ''}`} role="progressbar"
      aria-valuenow={value === undefined ? undefined : Math.round(value * 100)}>
      <div style={value !== undefined ? { width: `${Math.max(0, Math.min(1, value)) * 100}%` } : undefined} />
    </div>
  );
}

// The inset grouped box of System Settings.
export function Group({ title, footer, children, testId }: { title?: string; footer?: ReactNode; children: ReactNode; testId?: string }) {
  return (
    <section className="group" data-testid={testId}>
      {title && <h3 className="group-title">{title}</h3>}
      <div className="group-box">{children}</div>
      {footer && <div className="group-footer">{footer}</div>}
    </section>
  );
}

export function GroupRow({ icon, title, subtitle, trailing, onClick, testId, selected, style, chevron = true }: {
  icon?: ReactNode; title: ReactNode; subtitle?: ReactNode; trailing?: ReactNode; onClick?: () => void; testId?: string; selected?: boolean; style?: CSSProperties;
  chevron?: boolean; // a row that picks rather than opens has none
}) {
  return (
    <div className={`grow ${onClick ? 'clickable' : ''} ${selected ? 'selected' : ''}`} onClick={onClick} data-testid={testId} style={style}>
      {icon && <div className="grow-icon">{icon}</div>}
      <div className="grow-main">
        <div className="grow-title">{title}</div>
        {subtitle && <div className="grow-sub">{subtitle}</div>}
      </div>
      {trailing !== undefined && <div className="grow-trailing">{trailing}</div>}
      {onClick && chevron && <Glyph name="chevronRight" size={12} className="grow-chevron" strokeWidth={2.2} />}
    </div>
  );
}

// Sheets open now, oldest first: Escape closes only the one on top (a record opened from a list of them goes back
// to the list).
const openSheets: object[] = [];
export const sheetOpen = () => openSheets.length > 0;

// A window-modal sheet that drops from the top of the window, like AppKit's.
export function Sheet({ children, onClose, testId, width = 460 }: { children: ReactNode; onClose: () => void; testId?: string; width?: number }) {
  const me = useRef({});
  useEffect(() => {
    const token = me.current;
    openSheets.push(token);
    return () => {
      openSheets.splice(openSheets.indexOf(token), 1);
    };
  }, []);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || openSheets[openSheets.length - 1] !== me.current) return;
      e.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="sheet-backdrop" onMouseDown={onClose}>
      <div className="sheet" style={{ width }} onMouseDown={(e) => e.stopPropagation()} data-testid={testId} role="dialog">{children}</div>
    </div>
  );
}

export function Banner({ kind, children }: { kind: 'warning' | 'info' | 'error'; children: ReactNode }) {
  return (
    <div className={`banner banner-${kind}`}>
      <Glyph name={kind === 'info' ? 'info' : 'warning'} size={15} />
      <div>{children}</div>
    </div>
  );
}
