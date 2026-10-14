// The little Markdown the assistant writes: paragraphs, headings, lists, tables, quotes and code, and on lines of their
// own the records it shows rather than cites: [[chat:ROWID]] (that message in its conversation), [[chat:FROM-TO]]
// (those messages and the ones between) and [[photos:ROWID,ROWID]]. Parsed into blocks here (shared, so it can be
// tested); renderer/ask.tsx draws them.

export type Embed = { kind: 'chat'; from: number; to: number | null } | { kind: 'photos'; ids: number[] };
export type Block = { t: 'p' | 'h' | 'code' | 'ul' | 'ol' | 'table' | 'quote' | 'embed'; lines: string[]; level?: number; embed?: Embed };

export const MAX_PHOTOS = 6;
const EMBED = /^\s*\[\[\s*(chat|photos?)\s*:\s*([\d\s,–-]+?)\s*\]\]\s*$/i;

// "[[chat:12-18]]" -> { kind: 'chat', from: 12, to: 18 }; anything else -> null.
export function embedOf(line: string): Embed | null {
  const m = EMBED.exec(line);
  if (!m) return null;
  if (m[1].toLowerCase() === 'chat') {
    const r = /^(\d+)(?:\s*[–-]\s*(\d+))?$/.exec(m[2].trim());
    return r ? { kind: 'chat', from: Number(r[1]), to: r[2] ? Number(r[2]) : null } : null;
  }
  const ids = [...new Set(m[2].split(/[\s,]+/).filter((x) => /^\d+$/.test(x)).map(Number))].slice(0, MAX_PHOTOS);
  return ids.length ? { kind: 'photos', ids } : null;
}
// The key one embed is fetched and remembered by: "chat:12-18", "photos:3,4".
export const embedKey = (e: Embed) => (e.kind === 'chat' ? `chat:${e.from}${e.to ? `-${e.to}` : ''}` : `photos:${e.ids.join(',')}`);
// An embed still being written, as an answer streams in: drawn as nothing until it's whole.
export const partialEmbed = (line: string) => /^\s*\[\[[a-z]*(\s*:[\d\s,–-]*\]?)?\s*$/i.test(line);

export function blocks(text: string): Block[] {
  const out: Block[] = [];
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const isList = (l: string) => /^\s*([-*+]|\d+[.)])\s+/.test(l);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const embed = embedOf(l);
    if (embed) {
      out.push({ t: 'embed', lines: [l.trim()], embed });
    } else if (/^\s*```/.test(l)) {
      const body: string[] = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i]);
      out.push({ t: 'code', lines: body });
    } else if (/^#{1,6}\s/.test(l)) {
      out.push({ t: 'h', lines: [l.replace(/^#+\s*/, '')], level: Math.min(3, l.match(/^#+/)![0].length) });
    } else if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|?[\s:-]+(\|[\s:-]+)+\|?\s*$/.test(lines[i + 1] ?? '')) {
      const rows = [l];
      i++;
      while (i + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[i + 1])) rows.push(lines[++i]);
      out.push({ t: 'table', lines: rows });
    } else if (isList(l)) {
      const ordered = /^\s*\d/.test(l);
      const items = [l];
      const same = (x: string) => isList(x) && /^\s*\d/.test(x) === ordered;
      while (i + 1 < lines.length && (same(lines[i + 1]) || (/^\s{2,}\S/.test(lines[i + 1]) && !isList(lines[i + 1])))) items.push(lines[++i]);
      out.push({ t: ordered ? 'ol' : 'ul', lines: items });
    } else if (/^\s*>/.test(l)) {
      const q = [l.replace(/^\s*>\s?/, '')];
      while (i + 1 < lines.length && /^\s*>/.test(lines[i + 1])) q.push(lines[++i].replace(/^\s*>\s?/, ''));
      out.push({ t: 'quote', lines: q });
    } else if (l.trim()) {
      const p = [l];
      while (i + 1 < lines.length && lines[i + 1].trim() && !/^(#{1,6}\s|\s*```|\s*>|\s*\|)/.test(lines[i + 1]) && !isList(lines[i + 1]) && !embedOf(lines[i + 1])) p.push(lines[++i]);
      out.push({ t: 'p', lines: p });
    }
  }
  return out;
}
