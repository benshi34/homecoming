// General settings: how Homecoming itself behaves. Reading this Mac, watching for exports coming home (Downloads,
// Mail, notifications), notifications, working in the background, and your library. Who you are and what's on this
// Mac are in Your Setup; everything AI does is in AI Settings. ⌘, and the menu bar's Settings… open this page. Then
// updates: whether Homecoming looks for a newer version once a day (main/updates.ts), and looking now. At the bottom,
// quietly, which version this is (as About Homecoming says it), with What's New.

import type { ReactNode } from 'react';
import { ago } from '../shared/format.ts';
import { READ_ONLY_NOTE } from '../shared/status.ts';
import type { Settings, Snapshot } from '../shared/types.ts';
import { buildNote } from '../shared/version.ts';
import { api } from './api.ts';
import { GlyphTile } from './icons.tsx';
import { NotificationsRow } from './notifications.tsx';
import { Button, Group, GroupRow, Toggle } from './ui.tsx';

const set = (patch: Partial<Settings>) => void api.settings(patch);

export function GeneralPage({ snap, toolbar, onAssistant, onExport, onWhatsNew, onUpdate }: { snap: Snapshot; toolbar?: ReactNode; onAssistant: () => void;
  onExport: () => void; onWhatsNew: () => void; onUpdate: () => void }) {
  const s = snap.settings;
  const su = snap.setup;
  // Read-only mode: its switches are shown, not changed (ui.tsx ReadOnly).
  const locked = snap.readOnly && !snap.demo;
  return (
    <div className="column grouped" data-testid="general">
      <div className="toolbar drag"><h1>General</h1><div className="spacer" />{toolbar}</div>
      <div className="scroll">
        <div className="ai-page">
          <div className="ai-hero"><GlyphTile glyph="gear" color="gray" size={40} /><h2>General</h2>
            <p>How Homecoming works: reading this Mac, bringing your exports home, telling you what's happening, and your library. Who you are and what's on this Mac are in Your Setup; what AI does, in AI Settings.</p></div>

          <Group title="This Mac" footer="Screen Time, Chrome and the call log forget history, so Homecoming reads them every day. Each run keeps what it saw.">
            <GroupRow icon={<GlyphTile glyph="laptop" color="blue" />} title="Read this Mac every day" chevron={false} testId="general-daily"
              trailing={<Toggle checked={s.autoRefresh} onChange={(v) => set({ autoRefresh: v })} label="Read this Mac every day" testId="toggle-daily" />} />
            <GroupRow icon={<GlyphTile glyph="reload" color="blue" />} title="Read this Mac now" chevron={false} subtitle="Every source on this Mac, read again now."
              trailing={<Button size="small" onClick={() => void api.action('*', 'run-all-mac')} disabled={locked} title={locked ? READ_ONLY_NOTE : undefined} testAction="run-all-mac">Read Now</Button>} />
          </Group>

          <Group title="Exports coming home" footer="While an export is on its way, Homecoming looks for the file, and for the service's &quot;your data is ready&quot; email and notification. It reads a private copy of each, kept on this Mac; nothing else from them goes into your library. Turning one off removes its copy.">
            <GroupRow icon={<GlyphTile glyph="tray" color="indigo" />} title="Watch Downloads for exports" chevron={false} testId="general-watch"
              subtitle={s.watchDownloads ? 'An export you asked for is imported as it lands in Downloads. Any other waits on its page for you to say yes.'
                : 'Off: add each download on its page. What Claude downloads for you is still read.'}
              trailing={<Toggle checked={s.watchDownloads} onChange={(v) => set({ watchDownloads: v })} label="Watch Downloads" testId="toggle-watch" />} />
            <GroupRow icon={<GlyphTile glyph="envelope" color="blue" />} title="Look in Mail for &quot;your data is ready&quot;" chevron={false} testId="general-mail"
              subtitle={su.mail.accounts.length ? `In ${su.mail.accounts.join(', ')}, in Mail on this Mac.` : 'Mail on this Mac has no accounts yet.'}
              trailing={<Toggle checked={su.mail.checks} onChange={(v) => set({ mailChecks: v })} label="Look in Mail" testId="toggle-mail-checks" />} />
            <GroupRow icon={<GlyphTile glyph="bell" color="red" />} title="Look in notifications" chevron={false} testId="general-notification-checks"
              subtitle="The ones in Notification Center on this Mac, and the iPhone's if they come here."
              trailing={<Toggle checked={su.mail.notifications} onChange={(v) => set({ notificationChecks: v })} label="Look in notifications" testId="toggle-notification-checks" />} />
          </Group>

          <Group title="Notifications" testId="settings-notifications" footer="How Homecoming tells you an export is ready, one came home, or Claude needs you.">
            <NotificationsRow snap={snap} />
          </Group>

          <Group title="When the window is closed">
            <GroupRow icon={<GlyphTile glyph="layers" color="gray" />} title="Keep working when the window is closed" chevron={false}
              subtitle="Homecoming stays in the menu bar, reading this Mac and watching for your exports."
              trailing={<Toggle checked={!!s.background} onChange={(v) => set({ background: v })} label="Keep working when closed" testId="toggle-background" />} />
            {/* Only the installed app can: one run from Terminal would add Electron itself, so it says so instead. */}
            <GroupRow icon={<GlyphTile glyph="play" color="gray" />} title="Open at login" chevron={false}
              subtitle={snap.packaged === false ? 'Only the installed app opens at login (npm run install-app). Run from Terminal, open it yourself.'
                : s.background ? 'Starts in the menu bar when you log in.' : 'Opens Homecoming when you log in.'}
              trailing={snap.packaged === false ? <span className="tag">Installed app only</span>
                : <Toggle checked={!!s.openAtLogin} onChange={(v) => set({ openAtLogin: v })} label="Open at login" testId="toggle-login" />} />
          </Group>

          {snap.update && <Updates snap={snap} onUpdate={onUpdate} />}

          <Group title="Your library">
            <GroupRow icon={<GlyphTile glyph="drive" color="gray" />} title="Where it's kept" chevron={false} subtitle={<code className="selectable">{snap.corpusPath}</code>}
              trailing={<Button size="small" onClick={onExport} testAction="settings-export">Export…</Button>} />
          </Group>

          <Group>
            <GroupRow icon={<GlyphTile glyph="signpost" color="blue" />} title="Setup Assistant" subtitle="Go through setting up again, step by step." onClick={onAssistant} testId="general-assistant" />
          </Group>

          {snap.build && (
            <div className="about-line" data-testid="general-version">
              <span className="selectable">Homecoming {snap.build.version}{buildNote(snap.build) && ` (${buildNote(snap.build)})`}</span>
              <button className="link" onClick={onWhatsNew} data-action="general-whats-new">What's New</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Looking for a newer Homecoming: once a day unless it's off, or now. Found, it's a click to what's new and Update.
function Updates({ snap, onUpdate }: { snap: Snapshot; onUpdate: () => void }) {
  const u = snap.update!;
  const off = u.how === 'off';
  const when = u.checking ? 'Looking now…' : u.checkedAt ? `Last looked ${ago(u.checkedAt, new Date())}.` : 'Not looked yet.';
  return (
    <Group title="Updates" testId="general-updates"
      footer="It fetches one public file, Homecoming's list of versions (CHANGELOG.md on github.com/benshi34/homecoming). GitHub sees that this Mac asked, from its internet address, and nothing about you or your library. Nothing is installed until you click Update.">
      <GroupRow icon={<GlyphTile glyph="sync" color="blue" />} title="Look for updates every day" chevron={false}
        subtitle={off ? 'Not in the demo or read-only mode.' : 'Homecoming tells you when there\'s a newer version, and what\'s new in it.'}
        trailing={<Toggle checked={u.checks} onChange={(v) => set({ updateChecks: v })} label="Look for updates every day" testId="toggle-updates" />} />
      <GroupRow icon={<GlyphTile glyph="house" color="blue" />} chevron={false} testId="general-update-status"
        title={u.available ? `Homecoming ${u.available.version} is out` : `Homecoming ${snap.build?.version ?? ''}`} subtitle={when}
        trailing={u.available
          ? <Button size="small" kind="primary" onClick={onUpdate} testAction="general-see-update">See What's New…</Button>
          : <Button size="small" onClick={() => void api.update('check')} disabled={off || u.checking} testAction="update-check">Check Now</Button>} />
    </Group>
  );
}
