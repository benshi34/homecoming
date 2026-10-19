// The hub: every service the app can collect from, by kind, searchable, with what your data says about each.
// Recognizing a service in a list is easier than remembering it.

import { useEffect, useMemo, useState } from 'react';
import { count, list } from '../shared/format.ts';
import { BY_ID, isAccount } from '../shared/catalog.ts';
import { CATEGORIES, type HubRow, hubRows, namedExactly, searchRows, sortRows } from '../shared/hub.ts';
import type { DirectoryEntry, Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { Glyph, SourceIcon } from './icons.tsx';
import { evidenceLine, strongFind } from './parts.tsx';
import { Button, Group, GroupRow, Spinner, StatusGlyph, useReadOnly } from './ui.tsx';

export type HubFilter = 'all' | 'found' | 'here' | 'export';

let cached: DirectoryEntry[] | null = null;
function useDirectory(): DirectoryEntry[] | null {
  const [d, setD] = useState(cached);
  useEffect(() => {
    if (!cached) void api.directory().then((x) => setD((cached = x)));
  }, []);
  return d;
}

const SHOWN = 6;

// onAddOther gets what was searched for, to start the name with. In the Setup Assistant, `chosen` and onChoose make
// the accounts already in the app pickable too (Add puts them on your list): only accounts, since that list is the
// accounts to ask for (this Mac's and the iPhone's are read anyway).
export function Hub({ snap, filter: initial = 'all', onOpen, onAdded, onAddOther, onFilter, chosen, onChoose }: {
  snap: Snapshot; filter?: HubFilter; onOpen?: (sourceId: string) => void; onAdded?: (ids: string[]) => void; onAddOther: (query?: string) => void;
  onFilter?: (f: HubFilter) => void; chosen?: Set<string>; onChoose?: (sourceId: string) => void;
}) {
  const dir = useDirectory();
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<HubFilter>(initial);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [adding, setAdding] = useState<Set<string>>(new Set());
  const locked = useReadOnly(); // read-only mode: nothing is added
  useEffect(() => setFilter(initial), [initial]);
  const rows = useMemo(() => (dir ? hubRows(dir, snap.sources, snap.services, snap.discovery) : []), [dir, snap.sources, snap.services, snap.discovery]);
  const pass = (r: HubRow) => filter === 'all' || (filter === 'found' && !!r.found) || (filter === 'here' && r.state !== 'available')
    || (filter === 'export' && r.exportKnown);
  const shown = rows.filter(pass);
  const pick = (f: HubFilter) => {
    setFilter(f);
    onFilter?.(f);
  };
  const counts = { all: rows.length, found: rows.filter((r) => r.found).length, here: rows.filter((r) => r.state !== 'available').length, export: rows.filter((r) => r.exportKnown).length };
  const suggested = rows.filter((r) => r.found && r.state === 'available' && strongFind(r.found));

  const add = (slugs: string[]) => {
    setAdding((a) => new Set([...a, ...slugs]));
    void Promise.all(slugs.map((slug) => api.action('*', 'add-service', { slug }))).then((rs) => {
      setAdding((a) => new Set([...a].filter((x) => !slugs.includes(x))));
      const ids = rs.map((r) => r.id).filter((x): x is string => !!x);
      onAdded?.(ids);
      if (ids.length === 1) onOpen?.(ids[0]);
    });
  };
  const row = (r: HubRow, withKind = false) => {
    const kind = withKind ? CATEGORIES.find((c) => c.id === r.category)?.label : undefined;
    const sub = [r.domain, kind, r.found ? evidenceLine(r.found) : '', r.state !== 'available' ? r.status : ''].filter(Boolean).join(' · ');
    return (
      <GroupRow key={r.key} testId={`hub-${r.key}`} icon={r.sourceId ? <SourceIcon id={r.sourceId} group={r.group ?? 'web'} size={24} /> : <SourceIcon id={r.key} group="web" size={24} />}
        title={<>{r.name}{r.state === 'built-in' && <span className="tag">Built in</span>}{r.state === 'added' && <span className="tag">Added</span>}
          {r.state === 'available' && r.exportKnown && <span className="tag">Export steps</span>}{r.found && r.state === 'available' && <span className="tag new">In your data</span>}</>}
        subtitle={sub || undefined}
        onClick={r.sourceId && onOpen ? () => onOpen(r.sourceId!) : undefined}
        trailing={r.state === 'available'
          ? (adding.has(r.slug!) ? <Spinner size={14} /> : <Button size="small" onClick={() => add([r.slug!])} testAction="hub-add" disabled={!!locked} title={locked ?? undefined}>Add</Button>)
          : r.sourceId && chosen && onChoose && BY_ID[r.sourceId] && isAccount(BY_ID[r.sourceId]) ? (chosen.has(r.sourceId) ? <span className="where">On your list</span>
            : <Button size="small" onClick={() => onChoose(r.sourceId!)} testAction="hub-choose" disabled={!!locked} title={locked ?? undefined}>Add</Button>)
          : r.section ? <StatusGlyph section={r.section} needsYou={r.needsYou} /> : undefined} />
    );
  };

  if (!dir) return <div className="overview"><div className="note"><Spinner size={12} /><span>Loading the services…</span></div></div>;
  const results = q.trim() ? searchRows(shown, q).slice(0, 120) : null;
  return (
    <div className="overview hub" data-testid="hub">
      <div className="hub-head">
        {filter === 'found'
          ? <p className="lede">Services that turned up on this Mac: in your mail, in the sites you visit, and in the apps you have. Add the ones you use,
            {' '}and each one gets its own page with the steps to get your data out. Nothing is sent anywhere to find them.</p>
          : <p className="lede">Every source the app can collect your data from: {count(counts.here)} already in the app (this Mac's and your iPhone's among them)
            {' '}and {count(rows.length - counts.here)} more services, by kind. The ones your mail, browsing and apps point to come first. Skipped ones are here
            {' '}too, with what's not on this Mac: open one to include it again.</p>}
        {/* One that isn't listed, by name: added from where everything else is. */}
        <Button onClick={() => onAddOther(q.trim())} testAction="hub-add-source"><Glyph name="plus" size={13} strokeWidth={2.2} />Add a Source…</Button>
      </div>
      <div className="hub-bar">
        <div className="search"><Glyph name="search" size={14} /><input type="search" placeholder={`Search ${count(rows.length)} services`} value={q} onChange={(e) => setQ(e.target.value)} autoFocus data-testid="hub-search" /></div>
        <div className="segmented" role="tablist">
          {([['all', 'All'], ['found', 'In Your Data'], ['here', 'In the App'], ['export', 'With Export Steps']] as [HubFilter, string][]).map(([id, label]) => (
            <button key={id} role="tab" aria-selected={filter === id} className={filter === id ? 'on' : ''} onClick={() => pick(id)} data-testid={`hub-filter-${id}`}>
              {label} <span>{count(counts[id])}</span>
            </button>
          ))}
        </div>
      </div>
      {filter === 'found' && suggested.length > 0 && !q && (
        <div className="actions" style={{ padding: '0 0 6px' }}>
          <Button kind="primary" onClick={() => add(suggested.map((r) => r.slug!))} testAction="hub-add-suggested" disabled={!!locked} title={locked ?? undefined}>
            {suggested.length <= 3 ? `Add ${list(suggested.map((r) => r.name))}` : `Add the ${suggested.length} You Clearly Use`}</Button>
          <span className="where">{suggested.length > 3 ? `${list(suggested.map((r) => r.name))}: you` : 'You'} have the app or visit often, and the steps to get your data are known.</span>
        </div>
      )}
      {filter === 'found' && !q && counts.found === 0 && (
        <div className="empty" data-testid="hub-found-none" style={{ padding: '30px 0' }}>
          <h2>Nothing found yet</h2>The app looks through your mail, the sites you visit and your apps once they're read from this Mac. What you use turns up here then.
        </div>
      )}
      {results ? (
        <Group title={results.length ? `${results.length === 120 ? 'First 120' : count(results.length)} matching “${q.trim()}”` : `Nothing matches “${q.trim()}”`} testId="hub-results">
          {results.map((r) => row(r, true))}
          {/* Not when it's listed under that very name. */}
          {!namedExactly(results, q) && <div className="kv"><Button kind="plain" onClick={() => onAddOther(q.trim())} testAction="hub-add-named">Not listed? Add “{q.trim()}” by Name…</Button><span /></div>}
        </Group>
      ) : (
        CATEGORIES.map((c) => {
          const these = sortRows(shown.filter((r) => r.category === c.id && (!r.adult || r.found || r.state !== 'available')));
          if (!these.length) return null;
          const all = open[c.id] || filter !== 'all' || these.length <= SHOWN + 1;
          const nFound = these.filter((r) => r.found).length;
          return (
            <Group key={c.id} title={`${c.label} (${count(these.length)})${nFound && filter === 'all' ? ` · ${nFound} in your data` : ''}`} testId={`hub-kind-${c.id}`}>
              {(all ? these : these.slice(0, SHOWN)).map((r) => row(r))}
              {!all && <div className="kv"><Button kind="plain" onClick={() => setOpen((o) => ({ ...o, [c.id]: true }))} testAction="hub-show-all">Show All {count(these.length)}</Button><span /></div>}
            </Group>
          );
        })
      )}
      {filter === 'found' && !q && (snap.discovery?.unmatched.length ?? 0) > 0 && (
        <Group title={`Not in the directory (${snap.discovery!.unmatched.length})`} testId="hub-unmatched"
          footer="Mail from these comes from account or notification addresses, but no directory knows how to get your data from them. Adding one gives it a drafted access request.">
          {snap.discovery!.unmatched.map((u) => (
            <GroupRow key={u.domain} icon={<SourceIcon id={u.domain} group="web" size={24} />} title={u.name && u.name !== u.domain ? u.name : u.domain}
              subtitle={[u.name && u.name !== u.domain ? u.domain : '', evidenceLine(u)].filter(Boolean).join(' · ')}
              trailing={<Button size="small" disabled={!!locked} title={locked ?? undefined} onClick={() => void api.action('*', 'choose-services', { domains: [u.domain] }).then((r) => {
                onAdded?.(r.ids ?? []);
                if (r.ids?.[0]) onOpen?.(r.ids[0]);
              })}>Add</Button>} />
          ))}
        </Group>
      )}
      <div className="group-footer">Services come from JustDeleteMe and JustGetMyData, two community directories, plus the accounts the app reads itself. Can't find one?
        {' '}<Button kind="plain" onClick={() => onAddOther(q.trim())} testAction="hub-add-other">Add It by Name…</Button></div>
    </div>
  );
}
