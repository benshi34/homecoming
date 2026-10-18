// Your Setup: who you are and what's on this Mac that Homecoming uses, each with a way to change it. Who you are (seen
// and changed here, with any new finds to look at), the region your phone numbers are in, your iPhone, the browsers
// it reads and opens pages in, and Mail's accounts. Everything starts as what was found; a choice here replaces it
// (src/shared/setup.ts). How Homecoming works is in General; what AI does (Claude's browser and inboxes too), in AI Settings.

import { type ReactNode, useEffect, useState } from 'react';
import type { Settings, Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { GlyphTile } from './icons.tsx';
import { IdentityPicker } from './parts.tsx';
import { Button, Group, GroupRow, Toggle } from './ui.tsx';

const REGION = (() => {
  try {
    return new Intl.DisplayNames(['en'], { type: 'region' });
  } catch {
    return null;
  }
})();
const regionName = (r: string) => REGION?.of(r) ?? r;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const set = (patch: Partial<Settings>) => void api.settings(patch);

export function Picker({ value, onChange, options, label, testId }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
  label: string; testId?: string }) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} data-testid={testId}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

// onSource: open a source's page (Mail); onAi: the AI Settings page. editing: who you are is open to change (Up next or a
// notification brought you here for it); onEdited: it's closed again.
export function YourSetupPage({ snap, toolbar, onSource, editing, onEdited }: { snap: Snapshot; toolbar?: ReactNode; onSource: (id: string) => void; onAi: () => void;
  editing?: boolean; onEdited?: () => void }) {
  return (
    <div className="column grouped" data-testid="your-setup">
      <div className="toolbar drag"><h1>Your Setup</h1><div className="spacer" />{toolbar}</div>
      <div className="scroll">
        <div className="ai-page">
          <div className="ai-hero"><GlyphTile glyph="laptop" color="gray" size={40} /><h2>Your Setup</h2>
            <p>Who you are, and what's on this Mac that Homecoming uses: your iPhone, your browsers and Mail. Change anything that's wrong; the rest stays as found.</p></div>
          <You snap={snap} editing={editing} onEdited={onEdited} />
          <Phone snap={snap} />
          <Browsers snap={snap} />
          <Email snap={snap} onSource={onSource} />
        </div>
      </div>
    </div>
  );
}

function You({ snap, editing, onEdited }: { snap: Snapshot; editing?: boolean; onEdited?: () => void }) {
  const id = snap.identity;
  // New addresses or accounts turned up in what came home: to look at, here.
  const check = snap.sources.find((v) => v.id === 'identity');
  const fresh = check?.section === 'todo' && check.status.endsWith('found');
  const [open, setOpen] = useState(!!editing);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (editing) setOpen(true);
  }, [editing]);
  const close = () => {
    setOpen(false);
    onEdited?.();
  };
  const save = (identity: unknown, dismissed: unknown) => {
    setBusy(true);
    setError(null);
    void api.action('identity', 'save-identity', { identity, dismissed }).then((r) => {
      setBusy(false);
      if (r.ok !== false) close();
      else if (r.error && r.error !== 'read-only') setError(r.error);
    });
  };
  const phone = snap.setup.phone;
  const parts = id ? [id.names[0], id.emails.length && plural(id.emails.length, 'email address', 'email addresses'), id.phones.length && plural(id.phones.length, 'phone number'),
    id.usernames.length && plural(id.usernames.length, 'username')].filter(Boolean) : [];
  const mac = phone?.mac;
  const regions = phone?.regions ?? [];
  return (
    <Group title="You" footer="Who you are decides which messages, emails and posts are marked as yours. A phone number saved without its country code is read as one from your region.">
      <GroupRow icon={<GlyphTile glyph="person" color="blue" />} title={id?.names[0] ?? 'Who you are'} chevron={false} testId="setup-identity"
        subtitle={<>{parts.length > 1 ? parts.slice(1).join(' · ') : id ? 'No addresses or numbers yet' : 'Not set yet'}
          {fresh && <span className="warn-text" data-testid="setup-identity-new"><br />{check!.status}: are they yours?</span>}</>}
        trailing={open ? <Button size="small" onClick={close} testAction="setup-identity-close">Done</Button>
          : <Button size="small" kind={fresh ? 'primary' : 'default'} onClick={() => setOpen(true)} testAction="setup-identity-change">{fresh ? 'Review…' : 'Change…'}</Button>} />
      {open && <div className="setup-identity-form" data-testid="setup-identity-form"><IdentityPicker snap={snap} onSubmit={save} busy={busy} />{error && <div className="error">{error}</div>}</div>}
      {phone && (
        <GroupRow icon={<GlyphTile glyph="phone" color="green" />} title="Phone numbers" chevron={false} testId="setup-phone"
          subtitle={phone.known ? `Read as ${regionName(phone.region)} (+${phone.cc})${phone.chosen ? '' : ', this Mac\'s region'}.`
            : `${regionName(phone.region)} isn't one Homecoming knows: numbers without a country code are kept as written.`}
          trailing={<Picker value={snap.settings.phoneRegion ?? ''} onChange={(v) => set({ phoneRegion: v })} label="Phone number region" testId="setup-phone-region"
            options={[{ value: '', label: mac ? `This Mac's region (${regionName(mac)})` : 'This Mac\'s region' },
              ...regions.map((r) => ({ value: r, label: regionName(r) })).sort((a, b) => a.label.localeCompare(b.label))]} />} />
      )}
    </Group>
  );
}

const kindOf = (product: string) => (/^iPad/.test(product) ? 'iPad' : /^iPod/.test(product) ? 'iPod' : /^iPhone/.test(product) ? 'iPhone' : 'device');
const backedUp = (d: string | null) => (d ? new Date(d).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'unknown');

// Your iPhone: when a family's devices are backed up on this Mac, the one whose backup is read. Read before and not
// picked now: what came from it can be taken out of the library.
function Phone({ snap }: { snap: Snapshot }) {
  const su = snap.setup;
  const [sure, setSure] = useState(false);
  if (!su.devices.length) return null;
  const many = su.devices.length > 1;
  const other = su.deviceRead;
  return (
    <Group title="iPhone" testId="setup-iphone"
      footer="Your iPhone is read from its backup on this Mac. Only that device's backup is read, even if another one's is newer.">
      <GroupRow icon={<GlyphTile glyph="iphone" color="gray" />} title="Your iPhone" chevron={false} testId="setup-device"
        subtitle={many ? `${su.devices.length} devices are backed up on this Mac: pick yours.` : 'The device backed up on this Mac.'}
        trailing={<Picker value={su.device ?? ''} onChange={(v) => { setSure(false); set({ iphoneDevice: v }); }} label="Your iPhone" testId="setup-device-pick"
          options={su.devices.map((d) => ({ value: d.udid, label: `${d.device} (${kindOf(d.product)}, backed up ${backedUp(d.date)})` }))} />} />
      {other && (
        <GroupRow icon={<GlyphTile glyph="warning" color="orange" />} title={`What was read from ${other.device} is still in your library`} chevron={false}
          testId="setup-device-read"
          subtitle={sure ? `Its messages, calls, Health and apps come out, and the decrypted copy of its backup is deleted. What this Mac has of its own stays. If it's an older phone of yours, keep it.`
            : 'If it isn\'t yours, take it out. If it\'s an older phone of yours, keep it: its history is yours too.'}
          trailing={sure ? (
            <span style={{ display: 'flex', gap: 8 }}>
              <Button size="small" onClick={() => setSure(false)} testAction="setup-device-keep">Keep It</Button>
              <Button size="small" kind="destructive" testAction="setup-device-forget"
                onClick={() => void api.action('iphone_backup', 'forget-phone', { confirmed: true }).then(() => setSure(false))}>Take It Out</Button>
            </span>
          ) : <Button size="small" onClick={() => setSure(true)} testAction="setup-device-forget-ask">Take It Out…</Button>} />
      )}
    </Group>
  );
}

function Browsers({ snap }: { snap: Snapshot }) {
  const s = snap.settings;
  const su = snap.setup;
  const off = s.historyOff ?? [];
  const apps = su.browsers.filter((b) => b.app);
  return (
    <Group title="Browsers" testId="setup-browsers"
      footer="Turning a browser's history off stops reading it from now on; what was already read stays in your library.">
      {su.browsers.map((b) => (
        <GroupRow key={b.id} icon={<GlyphTile glyph="compass" color={b.read && b.history ? 'blue' : 'gray'} />} title={b.name} chevron={false} testId={`setup-browser-${b.id}`}
          subtitle={!b.history ? 'No history on this Mac yet' : `${b.profiles > 1 ? `${plural(b.profiles, 'profile')} · ` : ''}${b.read ? 'History read' : 'History not read'}${b.app ? '' : ' (the app isn\'t in Applications)'}`}
          trailing={b.history ? <Toggle checked={b.read} label={`Read ${b.name} history`} testId={`toggle-history-${b.id}`}
            onChange={(v) => set({ historyOff: v ? off.filter((x) => x !== b.id) : [...off, b.id] })} /> : undefined} />
      ))}
      {!su.browsers.length && <GroupRow icon={<GlyphTile glyph="compass" color="gray" />} title="No browsers found" subtitle="Safari's history needs Full Disk Access." chevron={false} />}
      <GroupRow icon={<GlyphTile glyph="external" color="blue" />} title="Open export pages in" chevron={false} testId="setup-page-browser"
        subtitle="Where each service's download page opens, signed in as you."
        trailing={<Picker value={su.pageBrowser ?? ''} onChange={(v) => set({ pageBrowser: v })} label="Open export pages in" testId="setup-page-browser-pick"
          options={[{ value: '', label: `${su.macBrowser} (this Mac's default)` }, ...apps.map((b) => ({ value: b.id, label: b.name }))]} />} />
    </Group>
  );
}

function Email({ snap, onSource }: { snap: Snapshot; onSource: (id: string) => void }) {
  const accounts = snap.setup.mail.accounts;
  return (
    <Group title="Email" testId="setup-email"
      footer="Looking in Mail for &quot;your data is ready&quot; is in General; the inboxes Claude may look in, in AI Settings.">
      <GroupRow icon={<GlyphTile glyph="envelope" color="blue" />} title="Mail on this Mac" testId="setup-mail" onClick={() => onSource('apple_mail')}
        subtitle={accounts.length ? `${accounts.join(', ')}: read into your library` : 'No accounts in Mail. Add one in System Settings → Internet Accounts to have it read.'} />
    </Group>
  );
}
