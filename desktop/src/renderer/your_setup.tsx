// Your Setup: what Homecoming found on this Mac and uses, in one place, each with a way to change it. Who you are, the
// region your phone numbers are in, the browsers it reads and opens pages in (and the one Claude works in), Mail and
// the inboxes Claude may look in, and the agent with its sign-in and keys. Everything starts as what was found; a
// choice here replaces it (src/shared/setup.ts).

import { type ReactNode, useState } from 'react';
import { PROVIDER } from '../shared/ask.ts';
import { CLAUDE_BROWSER_NAMES } from '../shared/setup.ts';
import type { Settings, Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { GlyphTile } from './icons.tsx';
import { AiMark, Button, Group, GroupRow, Toggle } from './ui.tsx';

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

function Picker({ value, onChange, options, label, testId }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
  label: string; testId?: string }) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} data-testid={testId}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

// onSource: open a source's page (who you are, Mail); onAi: the AI Settings page.
export function YourSetupPage({ snap, toolbar, onSource, onAi }: { snap: Snapshot; toolbar?: ReactNode; onSource: (id: string) => void; onAi: () => void }) {
  return (
    <div className="column grouped" data-testid="your-setup">
      <div className="toolbar drag"><h1>Your Setup</h1><div className="spacer" />{toolbar}</div>
      <div className="scroll">
        <div className="ai-page">
          <div className="ai-hero"><GlyphTile glyph="laptop" color="gray" size={40} /><h2>Your Setup</h2>
            <p>What Homecoming found on this Mac and uses: you, your browsers, your email and the agent. Change anything that's wrong; the rest stays as found.</p></div>
          <You snap={snap} onSource={onSource} />
          <Phone snap={snap} />
          <Browsers snap={snap} />
          <Email snap={snap} onSource={onSource} />
          <Agent snap={snap} onAi={onAi} />
        </div>
      </div>
    </div>
  );
}

function You({ snap, onSource }: { snap: Snapshot; onSource: (id: string) => void }) {
  const id = snap.identity;
  const phone = snap.setup.phone;
  const parts = id ? [id.names[0], id.emails.length && plural(id.emails.length, 'email address', 'email addresses'), id.phones.length && plural(id.phones.length, 'phone number'),
    id.usernames.length && plural(id.usernames.length, 'username')].filter(Boolean) : [];
  const mac = phone?.mac;
  const regions = phone?.regions ?? [];
  return (
    <Group title="You" footer="Who you are decides which messages, emails and posts are marked as yours. A phone number saved without its country code is read as one from your region.">
      <GroupRow icon={<GlyphTile glyph="person" color="blue" />} title={id?.names[0] ?? 'Who you are'} chevron={false} testId="setup-identity"
        subtitle={parts.length > 1 ? parts.slice(1).join(' · ') : id ? 'No addresses or numbers yet' : 'Not set yet'}
        trailing={<Button size="small" onClick={() => onSource('identity')} testAction="setup-identity-change">Change…</Button>} />
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
  const claude = su.browsers.filter((b) => b.claude);
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
      <GroupRow icon={<GlyphTile glyph="sparkle" color="purple" />} title="Do It for Me works in" chevron={false} testId="setup-agent-browser"
        subtitle={claude.length ? 'The browser Claude requests and downloads your exports in, through the Claude in Chrome extension.'
          : `Needs ${CLAUDE_BROWSER_NAMES}: the Claude in Chrome extension works only in those.`}
        trailing={claude.length ? <Picker value={su.agentBrowser?.id ?? ''} onChange={(v) => set({ agentBrowser: v })} label="Do It for Me works in" testId="setup-agent-browser-pick"
          options={claude.map((b) => ({ value: b.id, label: b.name }))} /> : <span className="tag">None here</span>} />
    </Group>
  );
}

function Email({ snap, onSource }: { snap: Snapshot; onSource: (id: string) => void }) {
  const s = snap.settings;
  const su = snap.setup;
  const off = s.inboxesOff ?? [];
  const browser = su.agentBrowser?.name ?? 'your browser';
  const accounts = su.mail.accounts;
  return (
    <>
      <Group title="Email" testId="setup-email"
        footer="While an export is on its way, Homecoming looks for the service's &quot;your data is ready&quot; email and notification. It keeps nothing else from them.">
        <GroupRow icon={<GlyphTile glyph="envelope" color="blue" />} title="Mail on this Mac" testId="setup-mail" onClick={() => onSource('apple_mail')}
          subtitle={accounts.length ? `${accounts.join(', ')}: read into your library` : 'No accounts in Mail. Add one in System Settings → Internet Accounts to have it read.'} />
        <GroupRow icon={<GlyphTile glyph="inbox" color="blue" />} title="Look in Mail for &quot;your data is ready&quot;" chevron={false}
          trailing={<Toggle checked={su.mail.checks} onChange={(v) => set({ mailChecks: v })} label="Look in Mail" testId="toggle-mail-checks" />} />
        <GroupRow icon={<GlyphTile glyph="bell" color="red" />} title="Look in notifications" subtitle="The ones in Notification Center on this Mac, and the iPhone's if they come here." chevron={false}
          trailing={<Toggle checked={su.mail.notifications} onChange={(v) => set({ notificationChecks: v })} label="Look in notifications" testId="toggle-notification-checks" />} />
      </Group>
      <Group title="Inboxes Claude may look in" testId="setup-inboxes"
        footer={`With Do It for Me on, Claude looks in these, in ${browser}, for the one email saying an export is ready, and opens only that.`}>
        {su.inboxes.map((x) => (
          <GroupRow key={x.email} icon={<GlyphTile glyph="at" color={x.on ? 'blue' : 'gray'} />} title={x.email} subtitle={x.app} chevron={false} testId={`setup-inbox-${x.email}`}
            trailing={<Toggle checked={x.on} label={`Claude may look in ${x.email}`} testId={`toggle-inbox-${x.email}`}
              onChange={(v) => set({ inboxesOff: v ? off.filter((e) => e !== x.email.toLowerCase()) : [...off, x.email.toLowerCase()] })} />} />
        ))}
        {!su.inboxes.length && <GroupRow icon={<GlyphTile glyph="at" color="gray" />} title="No email addresses yet" subtitle="Add yours to who you are." onClick={() => onSource('identity')} />}
      </Group>
    </>
  );
}

function Agent({ snap, onAi }: { snap: Snapshot; onAi: () => void }) {
  const a = snap.ask;
  const p = PROVIDER[a.settings.provider];
  const sign = a.signIn?.[p?.harness ?? 'claude-code'];
  const keys = [a.keys.anthropic && 'Anthropic', a.keys.openai && 'OpenAI'].filter(Boolean);
  const agent = snap.setup.agent;
  return (
    <Group title="AI" footer="Keys are kept in this Mac's Keychain and handed only to the agent that needs them.">
      <GroupRow icon={<AiMark size={22} />} title="Agent" onClick={onAi} testId="setup-agent"
        subtitle={`${p?.name ?? 'None'}${sign?.state === 'in' ? `, signed in${sign.who ? ` as ${sign.who}` : ''}${sign.plan ? ` (${sign.plan})` : ''}` : sign?.state === 'out' ? ', not signed in' : ''}${snap.settings.aiOn === true ? '' : '. AI is off.'}`} />
      <GroupRow icon={<GlyphTile glyph="sparkle" color="purple" />} title="Do It for Me" onClick={onAi} testId="setup-agent-ready"
        subtitle={agent.ok ? `Can work in ${snap.setup.agentBrowser?.name ?? 'your browser'}${snap.settings.agentExports ? '' : ' (off)'}` : agent.why} />
      <GroupRow icon={<GlyphTile glyph="lock" color="gray" />} title="API keys" onClick={onAi} testId="setup-keys" subtitle={keys.length ? `Saved: ${keys.join(' and ')}` : 'None saved'} />
    </Group>
  );
}
