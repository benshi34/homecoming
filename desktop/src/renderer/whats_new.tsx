// What's New in Homecoming: what changed in this version, and in any between it and the one you had, from the
// CHANGELOG.md built into the app (shared/version.ts). Shown once after an update, and from the menu bar and General.

import type { ReactNode } from 'react';
import type { Release } from '../shared/version.ts';
import { GlyphTile } from './icons.tsx';
import { Button, Sheet } from './ui.tsx';

// The changelog's words: **bold** and `code`, nothing more.
function words(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((p, i) => (/^\*\*.+\*\*$/.test(p) ? <strong key={i}>{p.slice(2, -2)}</strong>
    : /^`.+`$/.test(p) ? <code key={i}>{p.slice(1, -1)}</code> : p));
}

// Each version's words and bullets, newest first. Here, and in the Update sheet (update_sheet.tsx).
export function ReleaseNotes({ releases }: { releases: Release[] }) {
  return releases.map((r) => (
    <section key={r.version} className="whats-new-release" data-version={r.version}>
      <h3>Version {r.version}</h3>
      {r.text.map((t, i) => <p key={i}>{words(t)}</p>)}
      {r.bullets.length > 0 && <ul>{r.bullets.map((b, i) => <li key={i}>{words(b)}</li>)}</ul>}
    </section>
  ));
}

export function WhatsNewSheet({ releases, onClose }: { releases: Release[]; onClose: () => void }) {
  return (
    <Sheet onClose={onClose} testId="whats-new" width={500}>
      <div className="whats-new-head">
        <GlyphTile glyph="house" color="blue" size={44} />
        <h2>What's New in Homecoming</h2>
      </div>
      <ReleaseNotes releases={releases} />
      <div className="sheet-actions">
        <Button kind="primary" onClick={onClose} testAction="whats-new-done">Continue</Button>
      </div>
    </Sheet>
  );
}
