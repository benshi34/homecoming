// Where your email is, for "Look in Gmail" on an export that's on its way: the webmail an address's domain says
// (Gmail, Outlook, iCloud Mail, Yahoo Mail), opened in your browser and searched for the service where it can be, or
// Mail on this Mac when it's set up. Addresses at other domains (work, school) are found through Mail.

export interface Inbox { id: string; app: string; email?: string }

const WEBMAIL: { app: string; match: RegExp }[] = [
  { app: 'Gmail', match: /^(gmail|googlemail)\.com$/ },
  { app: 'Outlook', match: /^(outlook|hotmail|live|msn)\.[a-z.]+$/ },
  { app: 'iCloud Mail', match: /^(icloud|me|mac)\.com$/ },
  { app: 'Yahoo Mail', match: /^(yahoo|ymail|rocketmail)\.[a-z.]+$/ },
];

// Your inboxes, the one the service said it would write to first (Do It for Me saw it), then by address, Mail last.
export function inboxesFor(emails: string[], appleMail: boolean, first?: string): Inbox[] {
  const seen = new Set<string>();
  const out: Inbox[] = [];
  for (const e of [...(first ? [first] : []), ...emails]) {
    const email = e.trim().toLowerCase();
    const app = WEBMAIL.find((w) => w.match.test(email.split('@')[1] ?? ''))?.app;
    if (!app || seen.has(email)) continue;
    seen.add(email);
    out.push({ id: email, app, email });
  }
  if (appleMail) out.push({ id: 'mail', app: 'Mail' });
  return out;
}

// What a button for these says: the one there is ("Look in Gmail", "Open Mail"), else a choice.
export function inboxLabel(list: Inbox[]): string {
  if (list.length !== 1) return 'Look in Your Email…';
  return list[0].app === 'Mail' ? 'Open Mail' : `Look in ${list[0].app}`;
}

// The page to open: Gmail searched for mail from the service since you asked for it; the others' inboxes (their
// search can't be opened from a link). Null for Mail, which is an app, not a page.
export function inboxUrl(inbox: Inbox, q: { name: string; domains: string[]; since?: string }): string | null {
  switch (inbox.app) {
    case 'Gmail': {
      const from = q.domains.length ? `from:(${q.domains.slice(0, 4).join(' OR ')})` : `"${q.name}"`;
      const d = q.since ? new Date(Date.parse(q.since) - 86400_000) : null;
      const after = d && !Number.isNaN(d.getTime()) ? ` after:${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}` : '';
      return `https://mail.google.com/mail/?authuser=${encodeURIComponent(inbox.email ?? '')}#search/${encodeURIComponent(from + after)}`;
    }
    case 'Outlook': return 'https://outlook.live.com/mail/0/';
    case 'iCloud Mail': return 'https://www.icloud.com/mail/';
    case 'Yahoo Mail': return 'https://mail.yahoo.com/';
    default: return null;
  }
}
