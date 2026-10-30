// Every source the app walks the user through. Pure data: the main process, the status logic and the
// tests all read it. Steps and timings come from walking each export for real (what actually
// happened when one person collected their data in October 2026).

import type { DirectoryEntry, ServiceEntry } from './types.ts';

export type Group = 'setup' | 'mac' | 'iphone' | 'web' | 'guided';

export interface Step {
  text: string;
  detail?: string;
  app?: boolean; // about this app (drop the download here), not the service: Do It for Me isn't told it
}

export interface Source {
  id: string;
  name: string;
  group: Group;
  blurb: string;
  // Manifest keys (corpus/manifest.json) this source fills in.
  produces?: string[];
  producesPrefix?: string;
  // Mac and iPhone sources: the connector module that reads it (connectors/<name>.py).
  connector?: string;
  // Web exports: where to request it, and where the finished download lives.
  url?: string;
  downloadUrl?: string;
  steps?: Step[];
  // Typical and worst-case hours from request to download link.
  waitHours?: [number, number];
  // Days the download link stays valid once it's ready.
  expiresDays?: number;
  fileHint?: string;
  // Folder under corpus/imports/ the download goes in.
  importDir?: string;
  optional?: boolean;
  knownGaps?: string[];
  // Web domains the service emails from and serves (to tell a found service is already here).
  domains?: string[];
  // A service the person added, or ticked after it was found in their data (ServiceEntry).
  custom?: 'found' | 'you';
  slug?: string; // a service's slug in data/services.json (its logo is keyed by it)
  // Manifest keys worth a missing-years check (conversations, mail). Other sources have naturally quiet
  // years (few photos in 2015 isn't a gap).
  gapKeys?: string[];
  // Shown as "Can't export" choices when the account can't produce an export.
  cantExport?: string[];
  // Guided sources that leave no file behind (a setting to change): done when the user says so.
  manualDone?: boolean;
  // Guided sources that take a mailbox name from the user.
  asksAccountName?: boolean;
  // Web exports: the cookie that means you're signed in (py/signins.py reads its name and expiry, never its value),
  // so the app can tell whether Claude can do it in Chrome without you. A name ending in * matches by prefix.
  signIn?: { domains: string[]; cookies: string[] };
  // Why Do It for Me can't do it (the Claude in Chrome extension isn't allowed on the site): it's yours to do.
  agentBlocked?: string;
  confirmByEmail?: boolean; // the request only starts once you click the link in the email it sends (Spotify)
  // Its page lists another export too (Google's two, on Takeout): which one is this one's, for Claude. An email's link
  // can't say which, so Claude goes by the page.
  exportIs?: string;
  firstPartOnly?: boolean; // it can run to hundreds of GB: Claude downloads the first part, and asks about the rest
  // A service you added whose export page is known (data/services.json): Claude can request it there.
  exportPage?: boolean;
}

const GOOGLE_CORE = ['gmail', 'google_activity', 'google_calendar', 'google_contacts', 'chrome_synced', 'google_keep',
  'google_chat', 'google_maps_places', 'youtube', 'google_tasks', 'google_saved'];

export const CATALOG: Source[] = [
  // ---------------------------------------------------------------- setup
  {
    id: 'identity', name: 'Who you are', group: 'setup',
    blurb: 'Your names, email addresses and usernames. They decide which messages and emails are yours.',
  },
  {
    id: 'fda', name: 'Full Disk Access', group: 'setup',
    blurb: 'One permission unlocks Messages, Mail, Photos, Notes, Calendar, Reminders, call history, Safari and Screen Time.',
    steps: [
      { text: 'Open System Settings → Privacy & Security → Full Disk Access.' },
      { text: 'Turn on Homecoming.', detail: 'If it isn\'t in the list, choose +, then pick Homecoming in Applications. macOS may ask to quit and reopen it: say yes, and the app carries on where it was.' },
      { text: 'Come back here and choose Check Again.' },
    ],
  },
  {
    id: 'python_env', name: 'Python', group: 'setup',
    blurb: 'The parts of the app that read your data run on Python 3, with two extra pieces: one for iPhone backups and one for PDFs.',
  },
  {
    id: 'corpus_location', name: 'Where your library is', group: 'setup',
    blurb: 'Your library holds every message and email you have. It should stay on this Mac, out of iCloud Drive.',
  },
  {
    id: 'disk_space', name: 'Free space', group: 'setup',
    blurb: 'A full library can take tens of GB: the exports themselves, a decrypted iPhone backup, and the index that makes it searchable.',
  },
  {
    id: 'retention_claude', name: 'Keep Claude Code history', group: 'setup',
    blurb: 'Claude Code deletes its conversation transcripts after 30 days unless it\'s told to keep them.',
  },
  {
    id: 'retention_messages', name: 'Keep messages forever', group: 'setup',
    blurb: 'Messages can delete old conversations after 30 days or a year.',
    steps: [{ text: 'Open Messages → Settings → General.' }, { text: 'Set Keep messages to Forever.' }],
  },
  {
    id: 'retention_safari', name: 'Keep Safari history', group: 'setup',
    blurb: 'Safari removes history after a year by default.',
    steps: [{ text: 'Open Safari → Settings → General.' }, { text: 'Set Remove history items to Manually.' }],
  },
  {
    id: 'retention_iphone_messages', name: 'Keep messages forever on the iPhone', group: 'setup',
    blurb: 'The iPhone has its own Keep Messages setting, separate from the Mac\'s.',
    steps: [{ text: 'On the iPhone, open Settings → Apps → Messages.' }, { text: 'Under Message History, set Keep Messages to Forever.' }],
  },
  {
    id: 'retention_shell', name: 'Keep Terminal history', group: 'setup',
    blurb: 'Terminal keeps only your last 1,000 commands, and not when you ran them, unless told otherwise.',
  },
  {
    id: 'retention_codex', name: 'Codex history', group: 'setup',
    blurb: 'Codex keeps every session until you delete it, so there is nothing to change.',
  },
  {
    id: 'retention_google', name: 'Keep your Google activity', group: 'setup', url: 'https://myactivity.google.com/activitycontrols',
    blurb: 'Google can auto-delete your search, YouTube and synced Chrome history: accounts made since mid-2020 do after 18 months (YouTube after 36).',
    steps: [
      { text: 'Open Activity controls and sign in with your own Google account.' },
      { text: 'Web & App Activity → Auto-delete: choose "Don\'t auto-delete activity".', detail: 'Also tick "Include Chrome history and activity", so Google keeps your Chrome history beyond Chrome\'s own 90 days.' },
      { text: 'YouTube History → Auto-delete: choose "Don\'t auto-delete activity".' },
    ],
  },
  {
    id: 'iphone_notifications', name: 'iPhone notifications on this Mac', group: 'setup', optional: true,
    blurb: 'Services often say your data is ready with a notification on your iPhone. Forwarded to this Mac, the app can notice it and tell you.',
    steps: [
      { text: 'On this Mac, open System Settings → Notifications.' },
      { text: 'Turn on "Allow notifications from iPhone".',
        detail: 'It comes with iPhone Mirroring: macOS 15 and iOS 18 or later, the same Apple Account on both, and not offered in the EU.' },
      { text: 'Choose which iPhone apps may show notifications here, or leave them all on.' },
    ],
  },
  {
    id: 'retention_maps', name: 'Keep your Maps Timeline', group: 'setup',
    blurb: 'Google Maps Timeline now lives on the phone and deletes visits older than 3 months by default.',
    steps: [
      { text: 'On the phone, open Google Maps → your profile picture → Your Timeline.' },
      { text: 'Top-right menu → Location & privacy settings → Auto-delete Timeline.' },
      { text: 'Choose "Don\'t auto-delete activity".' },
    ],
  },

  // ---------------------------------------------------------------- on this Mac
  { id: 'contacts', name: 'Contacts', group: 'mac', connector: 'contacts', produces: ['contacts'],
    blurb: 'The address book. It turns phone numbers and emails into names everywhere else.' },
  { id: 'imessage', name: 'Messages', group: 'mac', connector: 'imessage', produces: ['imessage'], gapKeys: ['imessage'],
    blurb: 'iMessage, SMS and RCS from this Mac, merged with the iPhone backup by message ID.' },
  { id: 'whatsapp', name: 'WhatsApp (desktop app)', group: 'mac', connector: 'whatsapp', produces: ['whatsapp'],
    blurb: 'Your chats in the WhatsApp app on this Mac, both sides, and who said what in groups. Messages the iPhone backup also has are counted once.' },
  { id: 'signal', name: 'Signal (desktop app)', group: 'mac', connector: 'signal_desktop', produces: ['signal'],
    blurb: 'Your chats and calls in Signal on this Mac, both sides, and who said what in groups. Signal keeps them encrypted: macOS asks once to let Homecoming use its key.',
    knownGaps: ['Signal Desktop has only what reached it since it was linked to your phone; older messages stay on the phone.'] },
  { id: 'apple_mail', name: 'Mail', group: 'mac', connector: 'mail_app', produces: ['mail'],
    blurb: 'Every account in Mail on this Mac: Gmail, Outlook and Exchange, iCloud, school and work mail. Mail you also exported is kept once.' },
  { id: 'apple_notes', name: 'Notes', group: 'mac', connector: 'apple_notes', produces: ['apple_notes'],
    blurb: 'Apple Notes. Locked notes are skipped.' },
  { id: 'calendar', name: 'Calendar', group: 'mac', connector: 'calendar_events', produces: ['calendar'],
    blurb: 'Every calendar added in Internet Accounts.' },
  { id: 'reminders', name: 'Reminders', group: 'mac', connector: 'reminders', produces: ['reminders'],
    blurb: 'Apple Reminders, done and open.' },
  { id: 'calls', name: 'Phone and FaceTime calls', group: 'mac', connector: 'calls', produces: ['calls'],
    blurb: 'Call history. The Mac keeps about 6 months, so the app reads it daily.',
    knownGaps: ['The Mac keeps about 6 months of calls and the phone about 9. Older calls are gone unless an earlier run saved them.'] },
  { id: 'browser_history', name: 'Browsing history', group: 'mac', connector: 'browser_history', produces: ['browser_history', 'browser_saved'],
    blurb: 'Pages visited and searches made, in Safari, Chrome, Arc, Edge, Brave, Firefox and the other browsers on this Mac (pick which in Your Setup). Chrome keeps 90 days; Google Takeout has more.' },
  { id: 'app_usage', name: 'Screen Time', group: 'mac', connector: 'app_usage', produces: ['app_usage'],
    blurb: 'Which apps you used and what was playing, on every device on your Apple ID. Kept for about 4 weeks.',
    knownGaps: ['Screen Time keeps about 4 weeks. Daily runs keep the rest.'] },
  { id: 'ai_coding', name: 'Coding assistants', group: 'mac', connector: 'ai_coding', produces: ['ai_coding'],
    blurb: 'Claude Code, Codex, Cursor and VS Code chat: your prompts, the replies and the tool calls you turned down.' },
  { id: 'editor_history', name: 'Code editors', group: 'mac', connector: 'editor_history', produces: ['editor_history'],
    blurb: 'Which files you saved in VS Code, Cursor and similar editors, and when. Not the files themselves.' },
  { id: 'shell_history', name: 'Terminal history', group: 'mac', connector: 'shell_history', produces: ['shell_history'],
    blurb: 'The commands you typed in Terminal. Passwords, tokens and keys in them are replaced with [redacted].' },
  { id: 'setup', name: 'Your setup', group: 'mac', connector: 'setup', produces: ['setup'],
    blurb: 'How you have set up this Mac and the tools you work in: terminal, shell, editor, window manager and coding agent configs, the Dock, keyboard and trackpad settings, your Warp, tmux and AeroSpace layouts, the apps and background jobs you installed, and the machines you reach. Each change is kept, with what changed. Keys and tokens in configs are replaced with [redacted].' },
  { id: 'podcasts', name: 'Podcasts', group: 'mac', connector: 'podcasts', produces: ['podcasts'],
    blurb: 'The shows you follow and the episodes you played in Apple Podcasts.' },
  { id: 'books', name: 'Books', group: 'mac', connector: 'books', produces: ['books'],
    blurb: 'The books in Apple Books, how far you got in each and when you finished, and every passage you highlighted or wrote a note on.' },
  { id: 'photos', name: 'Photos', group: 'mac', connector: 'photos', produces: ['photos', 'shared_photos', 'photos_memories'],
    blurb: 'Dates, places, people and on-device labels for every photo. No pixels are copied. Photos others shared with you (shared albums, Shared with You, a Shared Library) are kept apart, so their places aren\'t taken for yours.' },
  { id: 'apple_maps', name: 'Apple Maps', group: 'mac', connector: 'apple_maps', produces: ['apple_maps'],
    blurb: 'What you searched for and got directions to in Apple Maps, your favorites and guides, the places you rated, and the places Maps says you visited.' },
  { id: 'voice_memos', name: 'Voice Memos', group: 'mac', connector: 'voice_memos', produces: ['voice_memos'],
    blurb: 'Recordings synced to this Mac.' },

  { id: 'notion_local', name: 'Notion (desktop app)', group: 'mac', connector: 'notion_local', produces: ['notion'],
    blurb: 'Pages the Notion app has cached on this Mac, with exact edit times.' },
  { id: 'zotero', name: 'Zotero', group: 'mac', connector: 'zotero', produces: ['zotero'],
    blurb: 'The papers and pages you saved in Zotero, your notes on them and your highlights in their PDFs, from the Zotero app on this Mac: your library and your groups.',
    knownGaps: ['Only what the Zotero app on this Mac has. A library kept only on zotero.org comes in once the app has synced it here.'] },
  { id: 'documents', name: 'Documents', group: 'mac', connector: 'documents', produces: ['documents'],
    blurb: 'Text from documents and spreadsheets in Documents, Desktop, Downloads, iCloud Drive and your cloud drives (OneDrive, Google Drive, Dropbox, Box), and your Obsidian notes. Files only in the cloud are listed, not downloaded.' },
  { id: 'git_commits', name: 'Git commits', group: 'mac', connector: 'git_commits', produces: ['git_commits'],
    blurb: 'Your commits across every repository under Documents, Desktop and your code folders (Developer, Code, Projects...).' },

  // ---------------------------------------------------------------- iPhone
  {
    id: 'iphone_backup', name: 'iPhone backup', group: 'iphone', connector: 'iphone',
    produces: ['health', 'health_samples', 'iphone_contacts'], producesPrefix: 'phone_',
    blurb: 'Everything on the phone: full message history, calls, Health, Safari, WhatsApp, WeChat and app data.',
    steps: [
      { text: 'Connect your iPhone to this Mac with a cable and unlock it.' },
      { text: 'Open Finder and select the iPhone in the sidebar. Trust this computer if asked.' },
      { text: 'Choose "Back up all of the data on your iPhone to this Mac".' },
      { text: 'Turn on "Encrypt local backup" and set a password you will remember.', detail: 'Unencrypted backups leave out call history, Health and Safari.' },
      { text: 'Click Back Up Now and keep the phone connected until it finishes.' },
    ],
  },

  // ---------------------------------------------------------------- web exports
  {
    id: 'google_takeout', name: 'Google', group: 'web', produces: GOOGLE_CORE, gapKeys: ['gmail'],
    signIn: { domains: ['google.com'], cookies: ['SID', '__Secure-1PSID'] },
    blurb: 'Gmail, search and YouTube history, Chrome, Calendar, Contacts, Keep, Tasks, Google Chat, Maps and your saved lists.',
    url: 'https://takeout.google.com/', downloadUrl: 'https://takeout.google.com/manage',
    exportIs: 'the one with Mail, Calendar, Chrome and the rest (not one with only Google Photos and Drive)',
    waitHours: [8, 48], expiresDays: 7, importDir: 'takeout', fileHint: 'takeout-<date>-<n>-001.zip, often several parts',
    steps: [
      { text: 'Sign in with your own Google account. Check the name in the top right.' },
      { text: 'Click "Deselect all", then tick Calendar, Chrome, Contacts, Gemini, Google Chat, Keep, Mail, Maps, Maps (your places), My Activity, Saved, Tasks, and YouTube and YouTube Music.', detail: 'The counter at the top should go up with each tick. Saved holds your Maps lists (Want to go, Favorites, your own). Leave Google Photos and Drive for their own export.' },
      { text: 'My Activity → Multiple formats → Activity records: choose JSON.' },
      { text: 'YouTube and YouTube Music → Multiple formats → history: choose JSON. Under "All YouTube data included", untick videos.' },
      { text: 'Next step: send download link via email, export once, .zip, 50 GB parts (one download, not several). Create export.' },
    ],
    knownGaps: ['Work and school Google accounts need their own export.'],
  },
  {
    id: 'google_photos_drive', name: 'Google Photos and Drive', group: 'web', produces: ['google_photos'],
    signIn: { domains: ['google.com'], cookies: ['SID', '__Secure-1PSID'] },
    blurb: 'Photo times, places and people from Google Photos, and the text of your Drive files (imported as documents). Can be very large.',
    url: 'https://takeout.google.com/', downloadUrl: 'https://takeout.google.com/manage',
    exportIs: 'the one with only Google Photos and Drive', firstPartOnly: true,
    waitHours: [24, 72], expiresDays: 7, importDir: 'takeout', optional: true,
    fileHint: 'takeout-<date>-<n>-001.zip, 50 GB parts',
    steps: [
      { text: 'Create a separate export with only Google Photos and Drive ticked.', detail: 'This can run to hundreds of GB. Check free space first.' },
      { text: 'Choose 50 GB parts, then Create export.' },
      { text: 'Download only as many parts as fit on this Mac or an external drive.' },
    ],
  },
  {
    id: 'instagram', name: 'Instagram', group: 'web', produces: ['instagram', 'instagram_activity'], gapKeys: ['instagram'],
    signIn: { domains: ['instagram.com'], cookies: ['sessionid'] },
    blurb: 'Direct messages (both sides), likes, saves, follows, comments and searches.',
    url: 'https://accountscenter.instagram.com/info_and_permissions/dyi/',
    downloadUrl: 'https://accountscenter.instagram.com/info_and_permissions/dyi/',
    waitHours: [1, 48], expiresDays: 4, importDir: 'instagram', fileHint: 'instagram-<username>-<date>-<id>.zip',
    steps: [
      { text: 'Sign in to Instagram.' },
      { text: 'Export your information → Create export → pick your Instagram account → Export to device.' },
      { text: 'Leave Customize information on All available information. Date range: All time. Format: JSON. Media quality: Higher quality.', detail: 'Instagram defaults to Last year, HTML and Medium. Change all three.' },
      { text: 'Check the Notify email is one you read.' },
      { text: 'Start export. Enter your password again if asked.' },
    ],
  },
  {
    id: 'facebook', name: 'Facebook and Messenger', group: 'web', produces: ['messenger', 'facebook_activity'], gapKeys: ['messenger'],
    signIn: { domains: ['facebook.com'], cookies: ['c_user'] },
    blurb: 'Messenger conversations (both sides), friends, posts, groups, events and searches.',
    url: 'https://accountscenter.facebook.com/info_and_permissions/dyi/',
    downloadUrl: 'https://accountscenter.facebook.com/info_and_permissions/dyi/',
    waitHours: [1, 48], expiresDays: 4, importDir: 'facebook', fileHint: 'facebook-<username>-<date>-<id>.zip',
    steps: [
      { text: 'Sign in to Facebook.' },
      { text: 'Export your information → Create export → pick your Facebook profile → Export to device.' },
      { text: 'Leave Customize information on All available information excluding data logs. Date range: All time. Format: JSON. Media quality: Higher quality.', detail: 'Facebook defaults to Last year, HTML and Medium. Change all three.' },
      { text: 'Check the Notify email is one you read.' },
      { text: 'Start export. Facebook asks for your password here and again at download.' },
    ],
    knownGaps: ['End-to-end encrypted chats (the default since late 2023) are not in this export.'],
  },
  {
    id: 'discord', name: 'Discord', group: 'web', produces: ['discord'], gapKeys: ['discord'],
    blurb: 'Every message you sent in DMs, group DMs and servers.',
    url: 'https://discord.com/app', waitHours: [4, 720], importDir: 'discord', fileHint: 'package.zip',
    steps: [
      { text: 'Sign in. Check it is your main account, not an auto-named secondary one.' },
      { text: 'If Discord asks you to verify your email, do that first. Unverified accounts can\'t export.' },
      { text: 'User Settings (gear) → Data & Privacy → Request my data → Request Data.' },
      { text: 'Tick Account, Messages and Servers. Leave "Your Activity" off (large usage logs).' },
      { text: 'Submit. The link arrives by email, usually within hours (Discord says up to 30 days).' },
    ],
    knownGaps: ['Discord exports only your own messages, never the other side.'],
  },
  {
    id: 'linkedin', name: 'LinkedIn', group: 'web', produces: ['linkedin'],
    signIn: { domains: ['linkedin.com'], cookies: ['li_at'] },
    blurb: 'Connections, positions, searches, reactions, invitations and LinkedIn\'s inferences about you.',
    url: 'https://www.linkedin.com/mypreferences/d/download-my-data', waitHours: [12, 48], importDir: 'linkedin',
    fileHint: 'Complete_LinkedInDataExport_<date>.zip (sometimes .zip.zip)',
    steps: [
      { text: 'Sign in to LinkedIn.' },
      { text: 'Choose "Download larger data archive", then Request archive.' },
      { text: 'The full archive arrives by email in about a day.' },
    ],
  },
  {
    id: 'notion', name: 'Notion', group: 'web', produces: ['notion_export'],
    signIn: { domains: ['notion.so', 'notion.com'], cookies: ['token_v2'] },
    blurb: 'Every page and database in your workspace.',
    url: 'https://app.notion.com/', waitHours: [1, 24], importDir: 'notion', fileHint: 'Export-<id>.zip',
    steps: [
      { text: 'Sign in to Notion.' },
      { text: 'Settings → General → Export → Workspace content: Export.' },
      { text: 'Export format: Markdown & CSV. Page content: Everything. Create folders for subpages: on. Export.' },
      { text: 'The link arrives by email, usually within an hour.' },
    ],
  },
  {
    id: 'chatgpt', name: 'ChatGPT', group: 'web', produces: ['chatgpt'],
    signIn: { domains: ['chatgpt.com'], cookies: ['__Secure-next-auth.session-token*'] },
    blurb: 'Every ChatGPT conversation.',
    url: 'https://chatgpt.com/settings/data-controls', waitHours: [1, 24], expiresDays: 1, importDir: 'chatgpt',
    fileHint: '<id>-<date>.zip with conversations.json',
    steps: [
      { text: 'Sign in to your own ChatGPT account.' },
      { text: 'Settings → Data controls → Export data → Confirm export.' },
      { text: 'The email link expires after 24 hours. Download it soon after it arrives.' },
    ],
    cantExport: ['My account is on a school or work workspace (only admins can export)'],
  },
  {
    id: 'claude_ai', name: 'Claude.ai', group: 'web', produces: ['claude_ai'],
    signIn: { domains: ['claude.ai'], cookies: ['sessionKey'] },
    blurb: 'Every Claude.ai conversation and project.',
    url: 'https://claude.ai/settings/privacy', waitHours: [1, 24], importDir: 'claude', fileHint: 'data-<date>.zip with conversations.json',
    steps: [
      { text: 'Sign in with your own account. Check the name in the bottom left.' },
      { text: 'Settings → Privacy → Export data.' },
      { text: 'The link arrives by email.' },
    ],
    cantExport: ['My account is on a school or work organization (only owners can export)'],
  },
  {
    id: 'x', name: 'X (Twitter)', group: 'web', produces: ['x'],
    signIn: { domains: ['x.com', 'twitter.com'], cookies: ['auth_token'] },
    blurb: 'Your posts (deleted ones too), likes, direct messages and Grok chats.',
    url: 'https://x.com/settings/download_your_data', waitHours: [24, 96], importDir: 'x', fileHint: 'twitter-<date>-<id>.zip',
    steps: [
      { text: 'Sign in to X in your browser.' },
      { text: 'Settings → Your account → Download an archive of your data. Enter your password and the code X sends.' },
      { text: 'Request archive. X notifies you in a day or more. Download it from the same page.' },
    ],
  },
  {
    id: 'reddit', name: 'Reddit', group: 'web', produces: ['reddit'],
    signIn: { domains: ['reddit.com'], cookies: ['reddit_session'] },
    agentBlocked: 'The Claude in Chrome extension isn\'t allowed on reddit.com, so this one is yours to do: the steps below take a couple of minutes.',
    blurb: 'Your posts, comments, votes, saved items and messages.',
    url: 'https://www.reddit.com/settings/data-request', waitHours: [24, 720], importDir: 'reddit', fileHint: 'export_<username>_<date>.zip',
    steps: [
      { text: 'Sign in to Reddit.' },
      { text: 'Under "What type of request is it?", pick the privacy law for where you live.',
        detail: 'In California: California Consumer Privacy Act (CCPA) / California Privacy Rights Act (CPRA). In the EU or UK: General Data Protection Regulation (GDPR). Anywhere else: Other.' },
      { text: 'If it asks for dates, choose all time. Then Submit.' },
      { text: 'Reddit sends a download link to your Reddit inbox (sometimes by email) within 30 days.' },
    ],
  },
  {
    id: 'spotify', name: 'Spotify', group: 'web', produces: ['spotify'], confirmByEmail: true,
    signIn: { domains: ['spotify.com'], cookies: ['sp_dc'] },
    blurb: 'Every song, podcast and audiobook you ever played, your playlists, library and searches, and what Spotify decided about you.',
    url: 'https://www.spotify.com/account/privacy/', waitHours: [72, 720], importDir: 'spotify', fileHint: 'my_spotify_data.zip, one for each part',
    steps: [
      { text: 'Sign in to Spotify.' },
      { text: 'Tick both Account data and Extended streaming history.', detail: 'Account data has your playlists, library, searches and the last year\'s plays. Extended streaming history has every play since you joined.' },
      { text: 'Request data, then confirm in the email Spotify sends.' },
      { text: 'They arrive separately, each in its own email: Account data in about 5 days, Extended streaming history in days, up to 30. Add each one when it comes.' },
    ],
  },

  // ---------------------------------------------------------------- guided (the user does it, the app watches)
  {
    id: 'other_mail', name: 'Outlook and other email', group: 'guided', asksAccountName: true, gapKeys: ['*'],
    blurb: 'Outlook.com, Hotmail, school and work mail. Outlook.com has no web export, so it comes through Mail on this Mac.',
    importDir: 'other_mail',
    steps: [
      { text: 'System Settings → Internet Accounts → add the account with Mail turned on.', detail: 'Outlook.com and Hotmail: choose Microsoft Exchange.' },
      { text: 'Open Mail and leave it open until the mailbox finishes downloading.', detail: 'A large mailbox can take 10 hours or more. The count keeps rising until it is done. Homecoming reads Mail as it goes (Mail, under On This Mac), so there\'s nothing to export.' },
      { text: 'Mail kept somewhere else, like an old .mbox file or another mail app\'s export: give it a name above, then drop it on this page, or choose Add the Download….' },
    ],
  },
  {
    id: 'maps_timeline', name: 'Google Maps Timeline', group: 'guided', produces: ['location_history'], importDir: 'timeline',
    blurb: 'Where you have been. Timeline moved onto the phone in 2024, so Takeout no longer has it.',
    steps: [
      { text: 'On your phone, open Google Maps → your profile picture → Settings.' },
      { text: 'Personal content (or Location & privacy) → Export Timeline data.' },
      { text: 'Save Timeline.json and AirDrop it to this Mac. The app picks it up from Downloads.' },
    ],
  },
  {
    id: 'messages_sync', name: 'Finish Messages in iCloud', group: 'guided', manualDone: true, optional: true,
    blurb: 'The Mac can look complete while missing years. An iPhone backup fills the gap; syncing helps too.',
    steps: [
      { text: 'Open Messages → Settings → iMessage.' },
      { text: 'Turn on Enable Messages in iCloud and click Sync Now.' },
      { text: 'Leave Messages open and the Mac awake until it finishes.' },
    ],
  },
  {
    id: 'iphone_vcard', name: 'iPhone contacts (vCard)', group: 'guided', produces: ['vcard_contacts'], importDir: 'iphone', optional: true,
    blurb: 'Only needed without an iPhone backup: the Mac\'s contacts can be years out of date.',
    steps: [
      { text: 'On the iPhone, open Contacts → Lists → All Contacts.' },
      { text: 'Touch and hold All Contacts → Export, and AirDrop the .vcf to this Mac.' },
    ],
  },
  {
    id: 'whatsapp_chats', name: 'WhatsApp chat exports', group: 'guided', produces: ['whatsapp_export'], importDir: 'whatsapp', optional: true,
    blurb: 'The iPhone backup already has WhatsApp. Export single chats only for history the phone lost.',
    steps: [
      { text: 'In WhatsApp on the phone, open a chat → contact name → Export chat → Without media.' },
      { text: 'AirDrop the zip to this Mac.' },
    ],
  },
  {
    id: 'slack', name: 'Slack', group: 'guided', produces: ['slack'], importDir: 'slack', optional: true,
    blurb: 'Workspace messages, threads and reactions. An admin can export a workspace; anyone can export what they see with slackdump.',
    steps: [
      { text: 'Without admin: install slackdump (brew install slackdump), sign in with slackdump workspace new <workspace>, then run slackdump export -member-only -o slack.zip.' },
      { text: 'Signed in to Slack with Google? Google turns slackdump\'s browser away. Sign it in with your own browser\'s session instead: zsh connectors/slack_signin.sh, which walks you through two pastes from Chrome and signs in every workspace at once.',
        detail: 'By hand: in Chrome on app.slack.com, DevTools, Application, Cookies: the d cookie (xoxd-...). Each workspace\'s token is in localStorage.localConfig_v2 (teams, token). Then slackdump workspace new -token <xoxc-...> -cookie <xoxd-...> <workspace>.' },
      { text: 'Or ask a workspace admin for an export (Settings & administration → Workspace settings → Import/Export data).' },
      { text: 'Drop the export zip here.' },
    ],
  },
  {
    id: 'telegram', name: 'Telegram', group: 'guided', produces: ['telegram'], importDir: 'telegram', optional: true,
    blurb: 'Chats, replies and reactions, from Telegram Desktop.',
    steps: [
      { text: 'In Telegram Desktop: Settings → Advanced → Export Telegram data. Choose the chats, set Format to Machine-readable JSON, and export.' },
      { text: 'The first time you ask, Telegram makes you wait 24 hours and tells you when to come back. Ask again then, from the same Mac.' },
      { text: 'It saves to Downloads/Telegram Desktop, where the app finds it. Or drop the DataExport folder here.' },
    ],
  },
  {
    id: 'zoom', name: 'Zoom transcripts', group: 'guided', produces: ['zoom'], importDir: 'zoom', optional: true,
    blurb: 'Transcripts of recorded meetings.',
    steps: [
      { text: 'zoom.us → Recordings → Cloud recordings → open a meeting → download the transcript (.vtt).' },
      { text: 'Drop the .vtt files here.' },
    ],
  },
];

// Where a service's download is found once it's ready, with no link in hand: its own page has a download button
// (Takeout's downloads, the Accounts Center's exports, X and LinkedIn settings), or the link only comes by email (Discord).
export const EMAIL_ONLY = new Set(['discord', 'spotify', 'reddit', 'notion', 'chatgpt', 'claude_ai']);
// Its own page, once it's ready, when it shows the download there (a service you added: its export page).
export const downloadPage = (src: Source) => (EMAIL_ONLY.has(src.id) ? undefined : src.downloadUrl ?? (src.custom ? src.url : undefined));

export const BY_ID: Record<string, Source> = Object.fromEntries(CATALOG.map((s) => [s.id, s]));
// Services you set up by hand rather than request (Outlook and other mail through Mail, Maps Timeline from the phone,
// Slack, Telegram and Zoom from their own export pages): accounts like the rest, chosen with them, each with its page. The other
// guided sources (a vCard, WhatsApp chats, Messages in iCloud) fill gaps the Mac and iPhone leave: not accounts.
export const GUIDED_ACCOUNTS = ['other_mail', 'maps_timeline', 'slack', 'telegram', 'zoom'];
export const isAccount = (s: { id: string; group: string }) => s.group === 'web' || GUIDED_ACCOUNTS.includes(s.id);

// Domains of the built-in accounts, so a service found in your data that's already here isn't offered again.
const BUILTIN_DOMAINS: Record<string, string[]> = {
  google_takeout: ['google.com', 'gmail.com', 'googlemail.com', 'youtube.com'], google_photos_drive: ['photos.google.com', 'drive.google.com'],
  instagram: ['instagram.com'], facebook: ['facebook.com', 'facebookmail.com', 'messenger.com', 'meta.com'],
  discord: ['discord.com', 'discordapp.com'], linkedin: ['linkedin.com'], notion: ['notion.so', 'notion.com'],
  chatgpt: ['openai.com', 'chatgpt.com'], claude_ai: ['claude.ai', 'anthropic.com'], x: ['x.com', 'twitter.com'],
  reddit: ['reddit.com', 'redditmail.com'], spotify: ['spotify.com'], whatsapp_chats: ['whatsapp.com'], slack: ['slack.com'], telegram: ['telegram.org', 't.me'],
  zoom: ['zoom.us'],
};
for (const [id, d] of Object.entries(BUILTIN_DOMAINS)) BY_ID[id].domains = d;

// ---------------------------------------------------------------- services you add

// Any service can take up to the 30 days data-access laws allow (GDPR, CCPA), and many are done in a day.
export const SERVICE_WAIT: [number, number] = [24, 720];
const BUILTIN_COUNT = CATALOG.length;

// imports.py names a catch-all source after the export's folder: <folder>_other (records), <folder>_files (media).
export const serviceKey = (folder: string) => folder.toLowerCase().replace(/\W+/g, '_');

// Services people add that Claude in Chrome isn't allowed on (it refuses the site), by their slug in data/services.json.
const AGENT_BLOCKED: Record<string, string> = {
  patreon: 'The Claude in Chrome extension isn\'t allowed on patreon.com, so this one is yours to do: its steps take a couple of minutes.',
};
// The sign-in cookie of some services people add, like the built-in ones' (py/signins.py reads its name and expiry).
const SERVICE_SIGN_INS: Record<string, { domains: string[]; cookies: string[] }> = {
  github: { domains: ['github.com'], cookies: ['user_session'] },
  tiktok: { domains: ['tiktok.com'], cookies: ['sessionid'] },
  netflix: { domains: ['netflix.com'], cookies: ['NetflixId'] },
  steam: { domains: ['steampowered.com', 'steamcommunity.com'], cookies: ['steamLoginSecure'] },
  duolingo: { domains: ['duolingo.com'], cookies: ['jwt_token'] },
};

export function serviceSource(e: ServiceEntry): Source {
  const steps: Step[] = e.notes ? [{ text: e.notes }] : [
    { text: `Sign in to ${e.name} and look in Settings or Privacy for "Download your data". It may be called Export, Request your data or Your information.` },
    { text: 'No download? Ask for one: services have to send a copy of your data within about 30 days of an access request (GDPR in Europe, CCPA in California, and similar laws elsewhere).',
      detail: e.email ? `Draft a request writes the email to ${e.email} for you to send.` : 'Draft a request writes the email for you to send.' },
  ];
  steps.push({ text: 'When it arrives, drop it on this page or choose Add the Download….', app: true,
    detail: `Once you've said you requested it, a download in Downloads with "${e.name}" in its name is picked up by itself.` });
  const key = serviceKey(e.folder);
  return {
    id: e.id, name: e.name, group: 'web', custom: e.from, slug: e.slug, domains: e.domains, steps, waitHours: SERVICE_WAIT, importDir: e.folder,
    url: e.url ?? e.site ?? (e.domains[0] ? `https://${e.domains[0]}` : undefined),
    exportPage: !!e.url, agentBlocked: AGENT_BLOCKED[e.slug], signIn: SERVICE_SIGN_INS[e.slug],
    blurb: `Your ${e.name} account. Everything in its download is kept, whatever the format.`,
    produces: [key, `${key}_other`, `${key}_files`], // read with a mapping (mapped_exports.py), else the catch-alls
  };
}

// An added service keeps the link and steps it had when it was added, but data/services.json gets re-checked by
// hand: bring each one up to date with it at launch. The same service there has its slug and shares a domain (a
// mail sender added by name can share a slug by chance).
export function refreshServices(list: ServiceEntry[], dir: DirectoryEntry[]): ServiceEntry[] | null {
  const bySlug = new Map(dir.map((d) => [d.slug, d]));
  let changed = false;
  const out = list.map((e) => {
    const d = bySlug.get(e.slug);
    if (!d || !d.domains.some((x) => e.domains.includes(x))) return e;
    const now = { url: d.export?.url, notes: d.export?.notes, email: d.export?.email ?? d.privacy_email };
    if (now.url === e.url && now.notes === e.notes && now.email === e.email) return e;
    changed = true;
    return { ...e, ...now };
  });
  return changed ? out : null;
}

// The services the person added become sources like any other. Called with the saved list whenever it changes,
// by the main process and the window alike.
export function setServices(list: ServiceEntry[]): void {
  for (const s of CATALOG.splice(BUILTIN_COUNT)) delete BY_ID[s.id];
  for (const e of list) {
    if (BY_ID[e.id]) continue;
    const s = serviceSource(e);
    CATALOG.push(s);
    BY_ID[s.id] = s;
  }
}

// Folder names imports.py and the catalog already use: a service can't share one.
export function reservedFolders(): Set<string> {
  return new Set(CATALOG.slice(0, BUILTIN_COUNT).flatMap((s) => [s.id, s.importDir ?? s.id, ...(s.produces ?? [])].map(serviceKey)));
}

// What bridge.py's identify() calls each kind of download, and the source it belongs to. Kept 1:1 with
// source ids so a recognized file always has a home.
export const KIND_TO_SOURCE: Record<string, string> = {
  google_takeout: 'google_takeout', google_photos_drive: 'google_photos_drive', instagram: 'instagram',
  facebook: 'facebook', discord: 'discord', linkedin: 'linkedin', notion: 'notion', chatgpt: 'chatgpt',
  claude_ai: 'claude_ai', x: 'x', reddit: 'reddit', spotify: 'spotify', slack: 'slack', telegram: 'telegram', zoom: 'zoom',
  whatsapp_chats: 'whatsapp_chats', iphone_vcard: 'iphone_vcard', maps_timeline: 'maps_timeline', mailbox: 'other_mail',
};

export const MAC_CONNECTORS = CATALOG.filter((s) => s.group === 'mac').map((s) => s.connector!);

// connectors/imports.py's parsers and the sources whose files each one reads. When a parser fails, its
// error belongs to one of these, not to whichever export happened to trigger the run.
export const IMPORT_PARSER_SOURCES: Record<string, string[]> = {
  ai_exports: ['chatgpt', 'claude_ai'],
  google: ['google_takeout', 'other_mail', 'iphone_vcard', 'maps_timeline'],
  youtube: ['google_takeout'],
  google_chat: ['google_takeout'],
  discord: ['discord'],
  meta: ['instagram', 'facebook'],
  x_archive: ['x'],
  csv_exports: ['linkedin', 'reddit'],
  spotify: ['spotify'],
  whatsapp: ['whatsapp_chats'],
  slack: ['slack'],
  telegram: ['telegram'],
  zoom: ['zoom'],
  notion_export: ['notion'],
  other_documents: ['google_photos_drive', 'notion'],
  // Exports read with a mapping Claude wrote (connectors/mapped_exports.py): services you added. main.ts adds
  // those, and adds them to the catch-alls below, when it attributes an import's errors.
  mapped_exports: [],
  // Fitbit's series by the minute, a record a day: in Takeout, or in a Fitbit download you added (main.ts adds those).
  fitbit_days: ['google_takeout'],
  // Catch-alls: structured files and media in any export that no parser above read (imports.py).
  other_data: ['google_takeout', 'discord', 'x', 'linkedin', 'instagram', 'facebook', 'notion'],
  other_files: ['google_takeout', 'discord', 'x', 'instagram', 'facebook', 'notion'],
};
