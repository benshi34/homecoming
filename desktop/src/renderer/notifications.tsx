// Whether macOS shows Homecoming's notifications. They're how it tells you an export is ready, one landed in Downloads,
// or Claude needs you; but macOS only lets an app ask, and can keep them without showing them (never asked, or set to
// deliver quietly). So: a test notification, what macOS's own record says of it (main.ts checkNotifications), and
// Homecoming's page in Notification settings when they aren't shown. In the Setup Assistant, Settings and AI Settings.

import { useState } from 'react';
import { ago } from '../shared/format.ts';
import type { NotifyCheck, Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { GlyphTile } from './icons.tsx';
import { Button, Checkmark, GroupRow, Spinner, StatusGlyph } from './ui.tsx';

// On, off or not known, and what to do about it, in words.
export function notifyWords(c: NotifyCheck | undefined, now = new Date()): { tag: string; on: boolean | null; say: string; when?: string } {
  const when = c ? `Checked ${ago(c.at, now)}.` : undefined;
  if (!c) return { tag: 'Not checked', on: null, say: 'Homecoming tells you when an export is ready, or when Claude needs you. Send a test to make sure macOS shows them.' };
  if (c.state === 'shown') return { tag: 'On', on: true, when, say: 'macOS shows them. To keep them on screen until you look, choose Alerts for Homecoming in Notification settings.' };
  if (c.state === 'quiet') return { tag: 'Off', on: false, when, say: 'macOS keeps them in Notification Center without showing them, so you won\'t notice when Claude needs you. In Notification settings, choose Alerts (or Banners) for Homecoming.' };
  if (c.state === 'off') return { tag: 'Off', on: false, when, say: 'They\'re turned off for Homecoming, so you won\'t notice when Claude needs you. In Notification settings, turn on Allow Notifications for Homecoming and choose Alerts.' };
  if (c.state === 'missing') return { tag: 'Off', on: false, when, say: 'macOS didn\'t take the test notification. In Notification settings, allow Homecoming\'s notifications and choose Alerts.' };
  return { tag: 'Can\'t tell', on: null, when, say: 'Sent a test. If it didn\'t show, allow Homecoming\'s notifications in Notification settings and choose Alerts.' };
}

function useTest() {
  const [testing, setTesting] = useState(false);
  const test = () => {
    setTesting(true);
    void api.action('*', 'check-notifications').finally(() => setTesting(false));
  };
  return { testing, test };
}

const openSettings = () => void api.action('*', 'open-app-notifications');

// A row in a settings list: Notifications, On or Off, a test and the way to its settings.
export function NotificationsRow({ snap }: { snap: Snapshot }) {
  const { testing, test } = useTest();
  const w = notifyWords(snap.notifyCheck);
  return (
    <GroupRow icon={<GlyphTile glyph="bell" color={w.on === false ? 'orange' : 'red'} />} chevron={false} testId="notifications-row"
      title={<span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>Notifications<span className={`tag ${w.on ? 'tag-green' : w.on === false ? 'tag-orange' : ''}`} data-testid="notifications-tag">{w.tag}</span></span>}
      subtitle={<span className={w.on === false ? 'warn-text' : undefined}>{w.say}{w.when ? ` ${w.when}` : ''}</span>}
      trailing={(
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Button size="small" disabled={testing} testAction="check-notifications" onClick={test}>{testing ? 'Sending…' : 'Send a Test'}</Button>
          <Button size="small" onClick={openSettings} testAction="open-app-notifications">Open Settings</Button>
        </span>
      )} />
  );
}

// The Setup Assistant's: macOS asks once, when the first notification comes, so it's sent here, while you're looking.
export function NotificationsBox({ snap }: { snap: Snapshot }) {
  const { testing, test } = useTest();
  const c = snap.notifyCheck;
  const w = notifyWords(c);
  return (
    <div className="group-box" style={{ marginTop: 22 }} data-testid="notifications-status">
      <div className="status-box">
        <div style={{ marginTop: 1 }}>{testing ? <Spinner size={20} /> : w.on ? <Checkmark size={20} /> : <StatusGlyph section="needs" size={20} />}</div>
        <div style={{ flex: 1 }}>
          <div className="big">{testing ? 'Sending one…' : w.on ? 'Notifications are on' : w.on === false ? 'macOS isn\'t showing them' : c ? 'Did it show?' : 'Not allowed yet'}</div>
          {(c || !testing) && <div className="pre">{c ? w.say : 'Choose Allow when macOS asks. Then Alerts, in Notification settings, keeps them on screen until you look.'}</div>}
        </div>
      </div>
      <div className="actions">
        {!w.on && <Button kind={c ? 'default' : 'primary'} disabled={testing} onClick={test} testAction="allow-notifications">{c ? 'Check Again' : 'Allow Notifications'}</Button>}
        {c && !w.on && <Button kind="primary" onClick={openSettings} testAction="open-app-notifications">Open Notification Settings…</Button>}
        {w.on && <Button onClick={openSettings} testAction="open-app-notifications">Notification Settings…</Button>}
      </div>
    </div>
  );
}
