// What each iPhone backup source holds, in words, and where it sits on the iPhone page. Keys are the corpus
// sources an iPhone backup produces: phone_<iLEAPP module> from connectors/ileapp.py, plus health.py and
// contacts.py. A module with no entry here is described from the iLEAPP artifacts it wrote.

export const PHONE_GROUPS = [
  'People and messages', 'Money and shopping', 'Travel and places', 'Browsing and searching', 'Notes, calendar and memos',
  'Health', 'Watching and listening', 'How you use the phone', 'Other apps', 'Phone details',
] as const;
export type PhoneGroup = typeof PHONE_GROUPS[number];

const P = 'People and messages', M = 'Money and shopping', T = 'Travel and places', B = 'Browsing and searching',
  N = 'Notes, calendar and memos', H = 'Health', W = 'Watching and listening', U = 'How you use the phone', O = 'Other apps',
  D = 'Phone details';

export const PHONE_SOURCES: Record<string, [string, PhoneGroup]> = {
  iphone_contacts: ['Contacts on the phone', P],
  phone_interactionccontacts: ['Who you messaged, called and shared with, and when', P],
  phone_recents: ['Addresses and numbers you used recently', P],
  phone_blockedcontacts: ['Numbers and addresses you blocked', P],
  phone_draftmessage: ['Unsent message drafts', P],
  phone_whatsapp: ['WhatsApp messages and calls', P],
  phone_whatsappextended: ['WhatsApp group changes and reactions', P],
  phone_wechat: ['WeChat messages and contacts', P],
  phone_corpusxdirectmessages: ['X direct messages', P],
  phone_airbnb: ['Airbnb messages with hosts', P],
  phone_discordacct: ['Discord servers and channels you opened, drafts and sessions', P],
  phone_tiktok: ['TikTok account and contacts', P],

  phone_splitwise: ['Splitwise expenses, balances and groups', M],
  phone_venmo: ['Venmo payments and the people you paid', M],
  phone_corpuswalletpasses: ['Wallet passes: tickets, boarding passes and cards', M],
  phone_amazonshopping: ['Amazon app account and activity', M],

  phone_uberclient: ['Uber pickup and drop-off places, and place searches', T],
  phone_uberplaces: ['Places saved in Uber', T],
  phone_united_airlines: ['United flights, bookings and boarding passes', T],
  phone_personalizationportrait: ['Places the phone learned you go', T],
  phone_weatherapplocations: ['Places in the Weather app', T],
  phone_alltrails: ['AllTrails trails and profile', T],

  phone_safarihistory: ['Safari history', B],
  phone_safariwebsearch: ['What you searched for in Safari', B],
  phone_safarirecentwebsearches: ['Recent Safari searches', B],
  phone_safaritabs: ['Safari tabs', B],
  phone_safaribookmarks: ['Safari bookmarks', B],
  phone_awesearch: ['What you searched for in TikTok', B],
  phone_parsecdcache: ['Search suggestions you picked in Spotlight and Safari', B],
  phone_reddit: ['Subreddits you follow', B],

  phone_notes: ['Notes', N],
  phone_calendarall: ['Calendar events and birthdays', N],
  phone_reminders: ['Reminders', N],
  phone_voicerecordings: ['Voice memos', N],
  phone_notion: ['Notion pages and activity', N],

  health: ['Health by day: activity totals and sleep', H],
  health_samples: ['Health readings: steps, distance, energy, heart rate and more', H],
  phone_health: ['Health achievements and awards', H],

  phone_netflix: ['Netflix: what you watched, profiles and settings', W],
  phone_spotify: ['Spotify account', W],

  phone_amdsqlitedb: ['Which apps you opened, and when', U],
  phone_keyboardinputcontexts: ['Where you typed: apps and keyboard languages', U],
  phone_keyboard: ['Keyboard usage', U],
  phone_installed_apps: ['Apps installed on the phone', U],
  phone_itunesbackupinfo: ['Apps in the backup', U],
  phone_applicationstatedb: ['When each app was last used', U],
  phone_recentapphistory: ['Apps used recently in CarPlay', U],
  phone_tcc: ['What each app is allowed to use: camera, photos, location…', U],
  phone_springboard: ['Home Screen layout and wallpaper', U],
  phone_webclips: ['Home Screen web shortcuts', U],
  phone_applealarms: ['Alarms', U],
  phone_appletimers: ['Timers', U],
  phone_applestopwatch: ['Stopwatch', U],
  phone_appleworldclock: ['World Clock cities', U],

  phone_googlephotos: ['Google Photos app settings', O],
  phone_googledocs: ['Google Docs accounts and app settings', O],
  phone_googlecalendar: ['Google Calendar app settings', O],
  phone_chatgpt: ['ChatGPT app settings', O],

  phone_filesapp: ['Files in iCloud Drive: names, folders and dates', D],
  phone_mmkvcarved: ['App settings and records recovered from app storage', D],
  phone_walstrings: ['Text recovered from app databases', D],
  phone_cloudkitsharing: ['iCloud items you share, and who with', D],
  phone_applewifiplist: ['Wi-Fi networks joined and seen', D],
  phone_bluetoothpairedreg: ['Bluetooth devices paired with the phone', D],
  phone_bluetoothpairedle: ['Bluetooth accessories paired with the phone', D],
  phone_connecteddeviceinformation: ['Watches and devices connected to the phone', D],
  phone_accountconfig: ['Accounts set up on the phone', D],
  phone_accountdata: ['Account details', D],
  phone_locservicesconfig: ['Location Services and Significant Locations settings', D],
  phone_applelocationd: ['Apps that use your location', D],
  phone_timezoneinfo: ['Time zones the phone has been in', D],
  phone_c2paprovenance: ['Where images came from (C2PA labels, including AI-made)', D],
  phone_photosmigration: ['Photos library upgrades', D],
  phone_backupsettings: ['Backup settings', D],
  phone_findmy: ['Find My settings', D],
  phone_messageretention: ['How long Messages keeps messages', D],
  phone_preferencesplist: ['System settings', D],
  phone_apple_atx_images: ['Images cached by the system', D],
  phone_lastbuild: ['iOS versions', D],
};

// "Splitwise - Expense Balances (ledger.db)" -> "Expense Balances": what one iLEAPP artifact holds, without the
// app name or file names. Only for modules PHONE_SOURCES doesn't describe yet.
export function artifactWords(name: string): string {
  return name.replace(/^[^-]+ - /, '').replace(/\s*\([^)]*\)/g, '').replace(/\S+\.(plist|db|sqlite)\b/g, '').replace(/\s+/g, ' ').trim();
}

export interface PhonePart { name: string; records: number; device?: boolean; artifacts?: Record<string, number> }

export function describePart(p: PhonePart): { title: string; group: PhoneGroup } {
  const known = PHONE_SOURCES[p.name];
  const words = [...new Set(Object.entries(p.artifacts ?? {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]).map(([a]) => artifactWords(a)))].filter(Boolean);
  const title = known?.[0] ?? (words.length ? words.join(', ') : 'Other app data');
  return { title, group: p.device ? D : known?.[1] ?? O };
}

// Every part, described and grouped in PHONE_GROUPS order, largest first within a group.
export function phoneGroups(parts: PhonePart[]): { group: PhoneGroup; rows: (PhonePart & ReturnType<typeof describePart>)[] }[] {
  const rows = parts.map((p) => ({ ...p, ...describePart(p) }));
  return PHONE_GROUPS.map((group) => ({ group, rows: rows.filter((r) => r.group === group).sort((a, b) => b.records - a.records) }))
    .filter((g) => g.rows.length > 0);
}
