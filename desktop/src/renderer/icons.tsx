// Glyphs in the spirit of SF Symbols (drawn here: the real ones aren't available to web content), and the
// System Settings–style colored tiles they sit on.

import { type ReactNode, useEffect, useState } from 'react';
import { BY_ID } from '../shared/catalog.ts';
import { api } from './api.ts';

const G: Record<string, ReactNode> = {
  person: <><circle cx="12" cy="8.2" r="3.6" /><path d="M5 19.5c.9-3.6 3.7-5.4 7-5.4s6.1 1.8 7 5.4" /></>,
  airplane: <path d="M10.6 3.6c0-.9.6-1.6 1.4-1.6s1.4.7 1.4 1.6v5.3l7.1 4.3v2l-7.1-2.2v4.5l2.2 1.7v1.7L12 20.1l-3.6.8v-1.7l2.2-1.7v-4.5l-7.1 2.2v-2l7.1-4.3z" />,
  play: <path d="M8 5.5v13l10.5-6.5z" />,
  house: <><path d="M3.8 11.4 12 4.4l8.2 7" /><path d="M6.2 9.6v9.9h11.6V9.6" /><path d="M10 19.5v-5.2h4v5.2" /></>,
  lock: <><rect x="5.5" y="10.5" width="13" height="9" rx="2" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /></>,
  terminal: <><rect x="3.5" y="5" width="17" height="14" rx="2.5" /><path d="m7.5 10 2.5 2-2.5 2M12.5 15h4" /></>,
  drive: <><rect x="3.5" y="8" width="17" height="8.5" rx="2.2" /><path d="M7 12.3h.01M10 12.3h6" /></>,
  gauge: <><path d="M4.5 16a7.5 7.5 0 1 1 15 0" /><path d="m12 16 3.2-4.6" /><circle cx="12" cy="16" r="1" /></>,
  clock: <><circle cx="12" cy="12" r="8" /><path d="M12 7.5V12l3 2" /></>,
  bubble: <><path d="M12 5c4.4 0 8 2.8 8 6.3S16.4 17.6 12 17.6c-.9 0-1.8-.1-2.6-.3L5.5 19l1.1-3.1C5 14.7 4 13.1 4 11.3 4 7.8 7.6 5 12 5Z" /></>,
  bubbles: <><path d="M10 4.8c3.6 0 6.4 2.2 6.4 5s-2.8 5-6.4 5c-.7 0-1.4-.1-2-.3L5 16l.8-2.5C4.6 12.6 3.6 11.3 3.6 9.8c0-2.8 2.9-5 6.4-5Z" /><path d="M18.3 9.6c1.3.8 2.1 2 2.1 3.4 0 1.2-.6 2.3-1.6 3.1l.6 2.2-2.6-1.1c-.6.2-1.2.2-1.8.2-1.9 0-3.6-.7-4.6-1.8" /></>,
  photo: <><rect x="3.5" y="5.5" width="17" height="13" rx="2.5" /><circle cx="9" cy="10" r="1.6" /><path d="m4 16.5 4.5-4 3.5 3 3-2.5 5 4" /></>,
  note: <><rect x="5" y="3.5" width="14" height="17" rx="2.5" /><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4" /></>,
  calendar: <><rect x="4" y="5.5" width="16" height="14" rx="2.5" /><path d="M4 9.8h16M8.5 3.5v3.5M15.5 3.5v3.5" /></>,
  checklist: <><path d="m4.5 7 1.5 1.5 2.5-3M4.5 13.5 6 15l2.5-3M11.5 7.5h8M11.5 14h8" /></>,
  phone: <><path d="M7.4 4.5h1.9l1.6 3.9-2 1.4a9.6 9.6 0 0 0 5.3 5.3l1.4-2 3.9 1.6v1.9a2 2 0 0 1-2.1 2A14.5 14.5 0 0 1 5.4 6.6a2 2 0 0 1 2-2.1Z" /></>,
  compass: <><circle cx="12" cy="12" r="8" /><path d="m14.8 9.2-1.6 4-4 1.6 1.6-4Z" /></>,
  hourglass: <><path d="M7 4h10M7 20h10M8 4c0 4 8 4 8 8s-8 4-8 8M16 4c0 4-8 4-8 8s8 4 8 8" /></>,
  code: <><path d="m8.5 7.5-4.5 4.5 4.5 4.5M15.5 7.5l4.5 4.5-4.5 4.5M13.5 5.5l-3 13" /></>,
  doc: <><path d="M7 3.5h6.5L18 8v11a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5a1.5 1.5 0 0 1 1-1.5Z" /><path d="M13.5 3.5V8H18" /></>,
  book: <><path d="M12 6.8C10.2 5.5 7.7 4.8 4.5 4.8v12.9c3.2 0 5.7.7 7.5 2 1.8-1.3 4.3-2 7.5-2V4.8c-3.2 0-5.7.7-7.5 2Z" /><path d="M12 6.8v12.9" /></>,
  branch: <><circle cx="7" cy="6" r="2" /><circle cx="7" cy="18" r="2" /><circle cx="17" cy="8" r="2" /><path d="M7 8v8M17 10c0 4-10 2-10 6" /></>,
  wave: <><path d="M4 12h1.5M7.5 8.5v7M11 5.5v13M14.5 8v8M18 10v4M20 12h0" /></>,
  iphone: <><rect x="7" y="2.8" width="10" height="18.4" rx="2.6" /><path d="M10.8 5.2h2.4" /></>,
  tray: <><path d="M4 13.5 6 6h12l2 7.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18Z" /><path d="M4 13.5h4.5l1 2h5l1-2H20M12 4v6.5m-2.5-2.5L12 10.5 14.5 8" /></>,
  camera: <><rect x="4" y="4" width="16" height="16" rx="4.5" /><circle cx="12" cy="12" r="3.6" /><path d="M16.6 7.4h.01" /></>,
  people: <><circle cx="9" cy="8.5" r="3" /><path d="M3.5 18.5c.8-3 3-4.5 5.5-4.5s4.7 1.5 5.5 4.5" /><circle cx="16.5" cy="9" r="2.4" /><path d="M16 14.1c2.2-.1 4 1.2 4.6 3.8" /></>,
  briefcase: <><rect x="3.5" y="7.5" width="17" height="11.5" rx="2.2" /><path d="M9 7.5V6a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 6v1.5M3.5 12.5h17" /></>,
  sparkle: <><path d="M12 3.5c.6 4.4 2.5 7.4 8 8.5-5.5 1.1-7.4 4.1-8 8.5-.6-4.4-2.5-7.4-8-8.5 5.5-1.1 7.4-4.1 8-8.5Z" /></>,
  at: <><circle cx="12" cy="12" r="3.4" /><path d="M15.4 12v1.3a2.6 2.6 0 0 0 5.2 0V12a8.6 8.6 0 1 0-3.4 6.8" /></>,
  music: <><path d="M9 17.5V6.5l10-2.5v11" /><circle cx="6.5" cy="17.5" r="2.5" /><circle cx="16.5" cy="15" r="2.5" /></>,
  envelope: <><rect x="3.5" y="5.5" width="17" height="13" rx="2.2" /><path d="m4 7 8 6 8-6" /></>,
  pin: <><path d="M12 20.5s6-5.6 6-10.5a6 6 0 0 0-12 0c0 4.9 6 10.5 6 10.5Z" /><circle cx="12" cy="10" r="2.2" /></>,
  sync: <><path d="M19 12a7 7 0 0 1-12.3 4.6M5 12a7 7 0 0 1 12.3-4.6" /><path d="M17.5 3.8v3.8h-3.8M6.5 20.2v-3.8h3.8" /></>,
  card: <><rect x="3.5" y="5.5" width="17" height="13" rx="2.2" /><circle cx="9" cy="11" r="2" /><path d="M6 15.8c.6-1.6 1.7-2.4 3-2.4s2.4.8 3 2.4M14.5 10h3M14.5 13h3" /></>,
  hash: <><path d="M9.5 4 8 20M16 4l-1.5 16M4.5 9h15M4 15h15" /></>,
  video: <><rect x="3.5" y="7" width="12" height="10" rx="2.2" /><path d="m15.5 10.5 5-3v9l-5-3" /></>,
  globe: <><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2.6 2.9 2.6 13.1 0 16M12 4c-2.6 2.9-2.6 13.1 0 16" /></>,
  laptop: <><rect x="5" y="5.5" width="14" height="9.5" rx="1.5" /><path d="M3 18.5h18" /></>,
  inbox: <><path d="M4 13.5 6 6h12l2 7.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18Z" /><path d="M4 13.5h4.5l1 2h5l1-2H20" /></>,
  bell: <><path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 1.5H5Z" /><path d="M10 20.5a2.2 2.2 0 0 0 4 0" /></>,
  arrows: <><path d="M19 12a7 7 0 0 1-12.3 4.6M5 12a7 7 0 0 1 12.3-4.6" /><path d="M17.5 3.8v3.8h-3.8M6.5 20.2v-3.8h3.8" /></>,
  check: <><path d="m5 12.5 4.5 4.5L19 7.5" /></>,
  plus: <><path d="M12 5v14M5 12h14" /></>,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.4-4.4" /></>,
  lightbulb: <><path d="M9 14.5c-1.5-1.1-2.5-2.9-2.5-4.9a5.5 5.5 0 0 1 11 0c0 2-1 3.8-2.5 4.9V16H9Z" /><path d="M9.5 18.5h5M10.5 21h3" /></>,
  checkCircle: <><circle cx="12" cy="12" r="8.5" /><path d="m8 12.3 2.8 2.8L16.2 9.5" /></>,
  minusCircle: <><circle cx="12" cy="12" r="8.5" /><path d="M8 12h8" /></>,
  gear: <><path d="M18.79 10.31 L21.10 10.63 L21.10 13.37 L18.79 13.69 L18.00 15.61 L19.40 17.47 L17.47 19.40 L15.61 18.00 L13.69 18.79 L13.37 21.10 L10.63 21.10 L10.31 18.79 L8.39 18.00 L6.53 19.40 L4.60 17.47 L6.00 15.61 L5.21 13.69 L2.90 13.37 L2.90 10.63 L5.21 10.31 L6.00 8.39 L4.60 6.53 L6.53 4.60 L8.39 6.00 L10.31 5.21 L10.63 2.90 L13.37 2.90 L13.69 5.21 L15.61 6.00 L17.47 4.60 L19.40 6.53 L18.00 8.39Z" strokeLinejoin="round" /><circle cx="12" cy="12" r="3" /></>,
  // The Setup Assistant: a signpost, the way through setup (the sparkle is AI's).
  signpost: <><path d="M12 21V3.5M12 5h6l2.2 2.2L18 9.4h-6M12 11.6H6l-2.2 2.2L6 16h6" /></>,
  layers: <><path d="m12 4 8.5 4.5L12 13 3.5 8.5Z" /><path d="m3.5 12.5 8.5 4.5 8.5-4.5M3.5 16l8.5 4.5 8.5-4.5" /></>,
  heart: <><path d="M12 19.5s-7.5-4.6-7.5-10A4.2 4.2 0 0 1 12 7.1a4.2 4.2 0 0 1 7.5 2.4c0 5.4-7.5 10-7.5 10Z" /></>,
  stream: <><circle cx="6" cy="6" r="1.6" /><circle cx="6" cy="12" r="1.6" /><circle cx="6" cy="18" r="1.6" /><path d="M10.5 6h8M10.5 12h8M10.5 18h5M6 7.6v2.8M6 13.6v2.8" /></>,
  chevronRight: <><path d="m9.5 6 6 6-6 6" /></>,
  chevronLeft: <><path d="m14.5 6-6 6 6 6" /></>,
  chevronDown: <><path d="m6 9.5 6 6 6-6" /></>,
  arrowUp: <><path d="M12 19V5.5M6 11l6-6 6 6" /></>,
  compose: <><path d="M19 13.5V18a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18V7a1.5 1.5 0 0 1 1.5-1.5H11" /><path d="m17.2 4.3 2.5 2.5-7.4 7.4-3.3.8.8-3.3Z" /></>,
  trash: <><path d="M4.5 7h15M9.5 7V5.2a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7M6.5 7l.9 11.6a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4L17.5 7M10.2 10.5v6M13.8 10.5v6" /></>,
  reload: <><path d="M19 12a7 7 0 1 1-2.2-5.1M19 4.5V9h-4.5" /></>,
  external: <><path d="M13.5 5H19v5.5M19 5l-8 8M17 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 4 18.5v-10A1.5 1.5 0 0 1 5.5 7H10" /></>,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 7.8h.01" /></>,
  warning: <><path d="M12 4.5 20.5 19h-17Z" /><path d="M12 10v4M12 16.8h.01" /></>,
  sidebar: <><rect x="3.5" y="5" width="17" height="14" rx="2.5" /><path d="M9.5 5v14" /></>,
  shield: <><path d="M12 3.5 19 6v5.5c0 4.2-3 7.6-7 9-4-1.4-7-4.8-7-9V6Z" /><path d="m9 12 2.2 2.2L15.5 10" /></>,
  eye: <><path d="M2.8 12c2.1-4 5.4-6.2 9.2-6.2s7.1 2.2 9.2 6.2c-2.1 4-5.4 6.2-9.2 6.2S4.9 16 2.8 12Z" /><circle cx="12" cy="12" r="3.1" /></>,
};

// Source -> [glyph, tile color]. Colors are system colors (see styles.css).
const SOURCES: Record<string, [string, string]> = {
  identity: ['person', 'blue'], fda: ['lock', 'gray'], python_env: ['terminal', 'gray'], corpus_location: ['drive', 'gray'],
  disk_space: ['gauge', 'gray'], retention_claude: ['clock', 'orange'], retention_messages: ['clock', 'green'], retention_safari: ['clock', 'blue'],
  retention_codex: ['clock', 'graphite'], retention_shell: ['terminal', 'graphite'], retention_iphone_messages: ['iphone', 'green'], retention_maps: ['pin', 'green'], iphone_notifications: ['bell', 'red'], retention_google: ['clock', 'blue'],
  imessage: ['bubble', 'green'], contacts: ['person', 'brown'], photos: ['photo', 'orange'], apple_notes: ['note', 'yellow'],
  calendar: ['calendar', 'red'], reminders: ['checklist', 'blue'], calls: ['phone', 'green'], browser_history: ['compass', 'blue'],
  app_usage: ['hourglass', 'indigo'], ai_coding: ['code', 'purple'], documents: ['doc', 'blue'], git_commits: ['branch', 'orange'],
  notion_local: ['doc', 'graphite'], voice_memos: ['wave', 'red'], iphone_backup: ['iphone', 'graphite'],
  editor_history: ['code', 'blue'], shell_history: ['terminal', 'graphite'], podcasts: ['wave', 'purple'],
  whatsapp: ['bubble', 'green'], signal: ['bubble', 'blue'], books: ['book', 'orange'], zotero: ['book', 'red'], setup: ['terminal', 'graphite'], machines: ['terminal', 'blue'], apple_maps: ['pin', 'blue'],
  google_takeout: ['tray', 'blue'], google_photos_drive: ['photo', 'teal'], instagram: ['camera', 'pink'], facebook: ['people', 'blue'],
  discord: ['bubbles', 'indigo'], linkedin: ['briefcase', 'blue'], notion: ['doc', 'graphite'], chatgpt: ['sparkle', 'teal'],
  claude_ai: ['sparkle', 'orange'], x: ['at', 'graphite'], reddit: ['bubble', 'orange'], spotify: ['music', 'green'],
  other_mail: ['envelope', 'blue'], apple_mail: ['envelope', 'blue'], maps_timeline: ['pin', 'green'], messages_sync: ['sync', 'green'], iphone_vcard: ['card', 'gray'],
  whatsapp_chats: ['bubble', 'green'], slack: ['hash', 'purple'], zoom: ['video', 'blue'],
};

const GROUP: Record<string, [string, string]> = { setup: ['gear', 'gray'], mac: ['laptop', 'blue'], iphone: ['iphone', 'graphite'], web: ['globe', 'purple'], guided: ['person', 'orange'] };

export function Glyph({ name, size = 16, className, strokeWidth = 1.8 }: { name: string; size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{G[name] ?? G.globe}</svg>
  );
}

// A glyph on a coloured tile, for pages about no one source.
export function GlyphTile({ glyph, color, size = 28 }: { glyph: string; color: string; size?: number }) {
  return (
    <span className={`tile tile-${color}`} style={{ width: size, height: size, borderRadius: size * 0.24 }} aria-hidden="true">
      <Glyph name={glyph} size={size * 0.62} strokeWidth={size > 40 ? 1.6 : 1.9} />
    </span>
  );
}

// Brand logos (data/service_icons.json, from Simple Icons via scripts/build_icons.mjs), loaded once for every icon.
let brands: Record<string, [string, string]> | null = null;
let loading: Promise<void> | null = null;
function useBrands(): Record<string, [string, string]> | null {
  const [, bump] = useState(0);
  useEffect(() => {
    if (brands) return;
    let live = true;
    loading ??= api.icons().then((b) => void (brands = b), () => void (brands = {}));
    void loading.then(() => live && bump((n) => n + 1));
    return () => {
      live = false;
    };
  }, []);
  return brands;
}

const LETTER_COLORS = ['blue', 'purple', 'pink', 'red', 'orange', 'green', 'teal', 'indigo', 'brown', 'graphite'];

// A source's icon. Services (built-in web accounts, added ones, ones found in your data or listed in the directory:
// ids "svc_...", "found:<slug>", "dir:<slug>", "sender:<domain>") show their brand's logo when there is one, else
// the first letter of their name; the app's own sources keep their glyphs.
export function SourceIcon({ id, group, size = 28, name }: { id: string; group?: string; size?: number; name?: string }) {
  const logos = useBrands();
  const src = BY_ID[id];
  const key = src?.custom ? (src.slug ?? id) : id.replace(/^(found|dir|sender):/, '');
  const radius = size * 0.24;
  const brand = logos?.[key];
  if (brand) {
    const [hex, d] = brand;
    const [r, g, b] = [0, 2, 4].map((k) => parseInt(hex.slice(k, k + 2), 16) / 255);
    const light = 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.72; // a pale brand colour gets a dark logo
    return (
      <span className="tile" style={{ width: size, height: size, borderRadius: radius, background: `linear-gradient(#${hex}, color-mix(in srgb, #${hex} 86%, #000))` }}
        aria-hidden="true" data-logo={key}>
        <svg viewBox="0 0 24 24" width={size * 0.56} height={size * 0.56} fill={light ? '#1d1d1f' : '#fff'}><path d={d} /></svg>
      </span>
    );
  }
  const service = !!src?.custom || /^(found|dir|sender):/.test(id);
  if (service || (!SOURCES[id] && name)) {
    const label = (name ?? src?.name ?? key).replace(/^[^\p{L}\p{N}]+/u, '');
    const hash = [...key].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
    return (
      <span className={`tile tile-${LETTER_COLORS[hash % LETTER_COLORS.length]}`} style={{ width: size, height: size, borderRadius: radius }} aria-hidden="true">
        <span style={{ fontSize: size * 0.5, fontWeight: 600, lineHeight: 1 }}>{(label[0] ?? '?').toUpperCase()}</span>
      </span>
    );
  }
  const [glyph, color] = SOURCES[id] ?? GROUP[group ?? ''] ?? ['globe', 'gray'];
  return (
    <span className={`tile tile-${color}`} style={{ width: size, height: size, borderRadius: radius }} aria-hidden="true">
      <Glyph name={glyph} size={size * 0.62} strokeWidth={size > 40 ? 1.6 : 1.9} />
    </span>
  );
}
