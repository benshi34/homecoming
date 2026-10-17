# Homecoming (desktop)

Homecoming is a Mac app that walks you through collecting your whole corpus: setup, every source on this Mac, the iPhone backup, every web export, and the things only you can do, until everything available is in `corpus/`.

```bash
cd desktop
npm ci
npm start
```

To walk through it as a new person would, without touching your corpus:

```bash
npm run fresh              # start, or continue the last fresh run
npm run fresh -- --reset   # start over
npm run fresh -- --delete  # remove it
```

The fresh run reads this Mac's real sources but writes only to `~/Library/Application Support/Homecoming (fresh run)/`: its own corpus, app state and browser sign-ins, a `Downloads/` folder it watches, and `Your exports/`, holding instant APFS clones of every export already in `corpus/imports/`. Move a clone into its `Downloads/` (or drop it on the window) to play "the export email arrived". Its iPhone step checks the backup password and reuses the last iLEAPP run (`--skip-ileapp`), so it takes minutes and leaves the shared iLEAPP results alone. The window shows a "Fresh run" badge.

It uses the connectors in `../connectors/` as they are and writes the same `corpus/` (`CORPUS_DIR` overrides it, as it does for the connectors).

## What you see

The first launch opens the Setup Assistant on a welcome page: what Homecoming is for, then its three steps (request your data, bring it home, explore it), each played on made-up data: the app's own rows, then the real Explore page browsed by a pointer, then an Ask answer (`src/renderer/welcome.tsx`; the data is `src/renderer/examples.ts`, and Explore given it fetches nothing and opens no record). Clicking in the Explore window hands it to you.

After that, one list, sorted by what to do next, with details on the right.

- **Next up**: the single most useful thing to do now. Setup first (Full Disk Access, who you are), then anything time-sensitive (a download that's ready, a file found in Downloads), then the iPhone password, then web exports with the longest waits first, so their clocks start early.
- **Needs you / Working on it / In your corpus / Not available**: each source sits in the section for its current state and moves as things happen. Sources blocked by a setup step fold under that step ("Unlocks Messages, iPhone backup").
- **Setup chips**: identity, Full Disk Access, Python packages, corpus out of iCloud, free space, and the retention settings that otherwise delete history (Messages, Safari, Claude Code, Terminal, Google, Maps Timeline).
- **All Sources** (under Sources, beside Found in Your Data): the hub. Every service the app can collect from, about 2,700, by kind (social, shopping, money, travel...), searchable, so nobody has to remember what they signed up for. The built-in accounts are in it with their status; one click adds any other.
- **Found in Your Data**: the hub narrowed to services your mail (who emails you from account and notification addresses), the sites you visit and the apps on your iPhone and Mac point to, strongest evidence first, plus senders no directory knows.
- **Your Setup** (under Settings): what the app found on this Mac and uses, each changeable (`src/renderer/your_setup.tsx`; the defaults are `src/shared/setup.ts`). Who you are and the region phone numbers without a country code are read in (`connectors/phones.py`, this Mac's region unless picked); each browser found (`connectors/browsers.py`: installed, or with history here) with a switch for reading its history, the browser export pages open in, and the one Do It for Me works in (the default if Claude in Chrome runs in it, else the first of Chrome, Edge, Brave, Arc, Vivaldi, Opera); Mail's accounts, whether Mail and notifications are looked in for "it's ready", and which of your addresses Claude may look in; the agent, its sign-in and keys. The connectors hear of it through the environment (`setupEnv`): `UMP_BROWSERS_SKIP`, `UMP_PHONE_REGION`, `UMP_READY_MAIL=0`, `UMP_READY_NOTIFICATIONS=0`. Changing a browser's switch reads browsing history again; changing the region reads Messages and calls again. With several devices backed up here, "Your iPhone" picks whose backup is read (`phoneDevice` in `src/shared/status.ts`: the one picked, else the one read before, else the newest iPhone's); one read before that isn't yours can be taken out (`bridge.py forget-phone`: the phone's own sources, its copies in Messages and calls, and the decrypted copy), and the decrypted copy starts over whenever the device changes.
- **Ask**: questions about your own data, answered by a model you pick, with the records it used cited (see below).
- **Explore**: things assembled from your data on this Mac, with no model and nothing sent anywhere (see below).
- **Export Your Library** (Settings, by Your library; or the app menu, ⇧⌘E): the library in one .zip, saved where the save dialog says. Your records always go in: `corpus.db`, a file per source (`normalized/`), the stream, the manifest and who you are. Photos and attachments (`media/`) and the downloads as they came (`imports/`, `raw/`) can be left out; each shows its size, with about what the .zip will take and what's free. Anything else in the folder, and links out of it like `raw/iphone` (the decrypted iPhone backup), is left out. Imports wait while it copies, so nothing changes part-way; Stop leaves nothing behind (`py/export_library.py`, `src/main/library_export.ts`).

## Ask

Conversations on the left, the chosen one on the right, like Messages. The assistant answers as your assistant ("you"), looks things up with five tools, shows each lookup and how long it took, and cites records as links that open the record.

- **Who does the work**: one of two agent harnesses, the Claude Code or Codex CLI on this Mac, signed in one of these ways (one list, on AI Settings and in Ask's sheet, with what the choice picked needs right under it: its key, its model, the local server):
  - Claude Code with your claude.ai account, or with an Anthropic API key (`claude --bare`: only the key, none of your claude.ai login, hooks, plugins or CLAUDE.md).
  - Codex with your ChatGPT account, with an OpenAI API key (`CODEX_API_KEY`), or on a local model (`codex --oss` with Ollama or LM Studio; `gpt-oss` works best). With a key or a local model Codex gets a settings folder of its own in its run folder, so your ChatGPT sign-in is neither used nor changed.

  Keys are encrypted with the Keychain (Electron's `safeStorage`) and handed only to the process that needs them. Claude Code streams the answer as it's written; Codex sends whole messages. Neither CLI's telemetry is on (`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, Codex's `analytics.enabled=false`).
- **Ready before it's asked**: a question waits until the agent picked can answer: it's on this Mac, its key is saved, and (a local model) something answers at its address, which must be on this Mac (the app asks its `/models`, on localhost only). The box says what's missing and fixes it in place. An agent's own error comes back in plain words with what to do (sign in in Terminal, check the key, open Ollama), its raw words under Details, and Try Again asks the question again in its place; a failed or stopped turn is never sent back to the agent as an earlier answer.
- **Tools** (`py/ask_tools.py`): `sql` (read-only, with `local_time`, `regexp`, `median`), `search` (full text with filters), `python` (in a macOS sandbox: no network, nothing in the home folder but the records, writes only to temp), `read_file` and `view_image` (the file a record points to: a document's original, a photo, a still from a video). Text results are blanked of secrets (`connectors/redact.py`) before any model sees them; photos are sent as they are. The database comes first because it's faster: on six test questions, an agent with it answered in 3.6 minutes in all against 8.6 reading the files.
- **Every lookup runs in the app.** Claude Code runs with its own tools off, in a sandbox that can't read the corpus or the app's data, and reaches the tools through an MCP server. Codex always has a shell, so it runs under a Codex permission profile that closes the home folder (the app's Full Disk Access would otherwise pass to it) and the network; it looks things up with `./ask` in its run folder. Both CLI agents hand each call to the app through a mailbox folder in their run folder, since their sandboxes can't open sockets.
- **Keeping your data out of training**: before a cloud provider's first use, and again every 90 days, a sheet says what that company keeps and which setting keeps it least ("Help improve Claude" off, ChatGPT's "Improve the model for everyone" off, the API's retention period), and the question waits until you confirm. A line under the composer keeps the reminder in view.
- Conversations are saved in the app's data folder (`ask/<id>.json`); nothing is saved by the CLIs (`--no-session-persistence`, `--ephemeral`), so the corpus doesn't read your questions back in as your own prompts.

## The event stream

`connectors/stream.py` turns `corpus.db` into what happened, in order, one local month at a time, and writes it to `corpus/stream/YYYY-MM.jsonl` (one event per line; `months.json` says how many each holds). `build_index.py` runs it after every rebuild, for the months whose records changed, so the files stay current; `python3 connectors/stream.py build --all` rewrites every month, and `month YYYY-MM` prints one. The Your Stream page shows the same events; Ask's python tool reads them with `stream('2026-09')`.

- **Left out**, because they aren't something you did or that happened to you: device bookkeeping from the iPhone backup (its file index, Wi-Fi, app state, permissions), raw Health samples (the day totals and nights of sleep stay), spam and deleted mail, ads you were shown, Screen Time day totals and glances at an app under 2 minutes, iOS's index of whom you contacted (the messages and calls themselves stay), and X's bookkeeping for direct messages.
- **One thing, once**: a page seen by Chrome, Chrome Sync and Google's My Activity; a search in the browser and in My Activity; an event in several calendars; a note, reminder or voice memo on the Mac and the iPhone. The copy closest to where it happened is shown; every copy is kept in the event's `refs`.
- **A run is one event**: messages in one chat until a 45-minute pause; pages and searches on one device until a 10-minute pause; photos until 45 minutes; one app on one device until it's left alone for 10 minutes; YouTube, music and maps until 30 or 15 minutes; commits to one project until 2 hours; an AI session until 45 minutes. Newsletters and notifications are one event a day per mailbox (a Gmail category other than Primary, an automated sender, or "unsubscribe" in it).
- **When data is missing or odd**: an app's data can be absent, partial or shaped in a way no rule expects (a number written as text, a field missing, metadata that isn't an object, a time with no zone). The stream never fails because of it: numbers are read leniently, and a record no rule can describe still becomes a plain event ("N things in App"). Events are ordered by when they happened, whatever zone each is written in. `connectors/tests/test_stream.py` checks every test record in many broken versions, and each app's records on their own.
- **An event**: `start` and `end` (local wall-clock time with its offset; photos and Health keep their own zone), `kind`, `app`, `device`, `title` (one line, plain words), `lines` (the first messages, the sites, the queries, the tracks), `people`, `count` (records in it), `mine` (how many were yours), `refs` (`"source:id"` of every record, which, unlike rowids, survive a rebuild), and `all_day` for a day's totals.

## Explore

Fourteen artifacts, each a tile on the Explore page that opens in place, built by `py/explore.py` from `corpus.db` (read-only) and kept until the database changes (in the app's data folder, `explore-cache/`). Anything that came from a record opens it, in Ask's record sheet.

- **On This Day**: today's date (or any day) in every year of your data: photos, who you talked to, calls, searches, YouTube, what you made and planned, your steps.
- **Your People**: everyone you've talked to one on one (Messages, Instagram, Messenger, Discord, WhatsApp, calls), your ten closest each year, and a page per person: messages by month and hour, who starts conversations (not counted where an export keeps only your side), calls, photos together, busiest days. A name ending in an initial ("Grace H") joins the only matching full name; Photos' first-name tags join the only person you talk to with that first name.
- **Places and Trips**: where your photos were taken, on a map drawn from bundled coastlines (`data/world_land.json`, Natural Earth), and trips: stretches of days whose photos are more than 100 km from where you took photos on the most days in the 90 days around (so home moves when you do).
- **Your Rhythms**: messages, browsing, searches, YouTube, code and photos by weekday and hour, when your busy days wind down each year, steps by weekday. Times are this Mac's zone, or a record's own (photos, Health).
- **Firsts**: your first message with each person, first photo in each place and country, first commit to each project, and the earliest record from each app (a first is as early as your data goes back).
- **What You Made**: a calendar of the days you committed code, wrote, posted, worked with an AI or took photos, with streaks and totals by year.
- **Your Year**: a year as a story, played a slide at a time like Replay or Memories: your people and who was new, messages by app, distance and flights, trips, a photo from each month, what you made, your busiest hour, steps, firsts and your biggest day; then every number at once. Any year with data, the latest by default.
- **Journeys**: every move of more than 150 km between places you were, drawn as great-circle arcs on a dark map that turns to put its seam where the fewest arcs cross. A move is a flight when nothing on the ground is that fast (250 km/h over the whole gap, or 2,500 km within three days); totals by year, countries in the order you first went, and where your days were.
- **Group Chats**: every conversation with two or more others, from any app: who talks, superlatives (talks most, night owl, most emoji, writes the longest), when it was alive, and its own words: ones two or more of you use often and far more there than in your other chats.
- **Listening**: every song played, from Spotify's streaming history, the Mac's Now Playing (music apps only) and YouTube's artist channels ("Artist - Topic"): top artists and songs, all time and by year, your eras (the artist you played most, season by season), songs on repeat in a day, and when you listen. A Spotify play counts from 30 seconds, as Spotify counts it.
- **Moving and Sleep**: Health's steps by month and weekday, your biggest days (and where you were, from that day's photos), days over 10,000 and the longest streak of them, steps on trips against at home; with a sleep tracker, nights by year, bedtimes and how long you sleep by night of the week.
- **Curiosity**: every search, once (the same words in Chrome and Google within the minute count once; searches inside Gmail and the Play Store aren't counted), from Google's My Activity, Safari and Chrome: each year's own topics (words and phrases searched far more that year than in others; a phrase over the words in it), the questions you asked, what you searched again and again, and what you looked up in the weeks before each trip (by every place name the trip's photos give it).
- **Watching**: YouTube (artist channels are songs, in Listening), Netflix on the iPhone, TikTok and video apps the Mac was playing: most-watched channels and shows (episodes count for their show), what you watched again, your longest evenings, how much after midnight.
- **Your Stream**: a month as it happened, every event in order, day by day: conversations, calls, mail, browsing and searches, what you watched and listened to, photos, calendar, notes, code and AI sessions, app use, social activity, Health. Built by `connectors/stream.py` (above). Filter by kind, search the month, jump to a day; open an event for all of it and every record in it. The latest month by default.

A tile without enough to show is locked: greyed, with what it needs and where that comes from ("Needs your listening history: from Spotify, or YouTube in Google Takeout"). It opens to what it would show and the sources that bring it, each with its status and a button to it. The rules are `NEEDS` in `src/renderer/explore.tsx`: Listening wants 50 plays, Curiosity 50 searches, Watching 30 videos, Moving and Sleep two weeks of Health (sleep its own two weeks), and the others something to show at all.

These work from what records are, not which app made them, so they hold for anyone's data: a group is a conversation an app flags as one, or with two or more others in its participants or among its writers (one an export keeps only your side of is left out); a place you were is any photo, video, check-in or location record with coordinates, except a picture saved from a messaging or social app (it carries someone else's location), a photo others shared with you (shared albums, Shared with You, iCloud links, what others added to a Shared Library: `photos.py` keeps those as `shared_photos`) and a point nothing could have reached in time; an app's name comes from what its records say they came from. Lines an app writes itself ("Grace sent an attachment.") are told apart from what people wrote by being word for word the same from three or more people once their names are taken out.

The look follows Apple's summary screens (Photos Memories, Health, Fitness): a bento of tiles, each showing its artifact as a picture (the day's photos, your closest people, a map, a heatmap, a calendar) and one big number, and on each page a hero card in the artifact's color, people as monograms, countries as flags, trips as photo cards. A tile zooms into its page's hero and back (a view transition, `animate(…, 'zoom')`), deeper pages push in from the side, numbers count up, and charts grow in on a spring sampled from a damped spring; Reduce Motion turns all of it off.

A message opens its conversation, the way Messages shows it: both sides of that day's exchange and a little either side, with earlier and later a click away (`explore.py thread`). While an artifact is built for the first time, its page shows a ring that fills as its steps finish (`explore.py` reports progress on stderr; `src/main/explore.ts` forwards it), and the tiles fill in one at a time.

Thumbnails come from the record's file or, for photos, Photos' own previews on this Mac (they exist even when the original is only in iCloud). Charts use one blue for single series and a five-step blue for heatmaps, checked for contrast against the window in light and dark mode; each has hover details and a list or table beside it.

## How each kind of source works

| Group | What the app does | What you do |
|---|---|---|
| On this Mac | Reads every present source as soon as it knows who you are, then again whenever a source is a day old while the app is open (Screen Time, Chrome and the call log forget history) | Grant Full Disk Access |
| iPhone backup | Finds Finder backups, notices newer ones, runs `connectors/iphone.py` (decrypt + iLEAPP) | Type the backup password. It's piped to the decryption step and never saved or logged |
| Web exports | Opens the export page in your own browser (signed in already, with your passwords) with the steps in the app, or with **Do It for Me** has Claude Code request it in your browser, Chrome or the one picked in Your Setup (`src/main/export_agent.ts`: `claude -p --chrome` with only the browser tools, the service's steps as its instructions, stopping for sign-ins and codes and carrying on in the same session on Continue). **Ask for Everything** first checks which services the browser it works in is signed in to (`py/signins.py`: each session cookie's site, name and expiry, read in place, never its value), runs Claude through them one after another with one notification at the end, and carries on by itself once a sign-in it stopped for is done. Tracks when you requested it, looks in Apple Mail's index for the service's "your data is ready" email (and takes its download link from the message) and in this Mac's notifications (a guess, shown as "looks ready"; forward the iPhone's notifications to the Mac and those count too), downloads it with Claude once it's ready if you let it (and has Claude look for it every few hours, a setting of its own; Stop Checking turns that off for one service), reminds you when it should be ready and before the link expires, picks the download up from Downloads, files it in `corpus/imports/<source>/` and imports it | Sign in, pick the options, say "I've requested it", or sign in when Do It for Me asks |
| Guided | Shows the steps and watches Downloads for the file (Maps Timeline, mailbox exports, vCards, WhatsApp chats, Slack, Zoom) | The steps on your phone or in Mail |
| Other services | Any service you add, by hand or from Found in Your Data, with its export page when a directory knows it, or a drafted GDPR/CCPA access request when it doesn't. Whatever its download holds is kept, in any format | Request it, drop the download |

Downloads are recognized by their contents, not their names (`py/bridge.py identify`), so renamed files, `.zip.zip`, unzipped folders and multi-part Takeouts all land in the right place. An export you were expecting is imported on arrival; anything else waits for a yes. Files on another volume are copied, never moved.

Every import runs each `imports.py` parser on its own (`bridge.resilient_imports`), so one malformed export marks only its own row as failed instead of blocking every other import, and the sources a failing parser was writing keep their previous records rather than a half-read version. Export files that iCloud's "Optimize Mac Storage" has moved to the cloud are downloaded before parsing (`brctl download`); reading a 2 GB mailbox on demand can time out partway. That function mirrors `imports.main()`; `test_bridge.py` fails if the two drift apart.

## Services the app doesn't know

The long tail (a writing site, a gym, a forum) is handled without a parser per service:

1. **Every service is listed** in the hub, by kind (`data/categories.json`, sorted once by Claude from each service's name and domains), so finding yours is recognition, not recall.
2. **Which services you use** comes from evidence, not memory: `bridge.py discover-services` matches mail senders, visited sites and installed apps against `data/services.json`, about 2,650 services built by `scripts/build_services.py` from two MIT-licensed directories (JustDeleteMe for names and domains, JustGetMyData for export steps; notices in `data/THIRD_PARTY.md`). `--check-links` drops export pages and services that no longer exist (`data/link_check.json`); `npm run icons` matches them to brand logos from Simple Icons (`data/service_icons.json`); a unit test checks that every service opens its export page, else its home page, never a page for deleting the account. Senders no directory knows are listed too, by the name they go by.
3. **Nothing is lost**: a service you add files its download in `corpus/imports/<folder>/`, and `imports.py`'s catch-alls keep every JSON/CSV item, document and media file, with times when one is found.
4. **Structure comes after**: Claude reads the download's structure (file names, field names, kinds of values; one example value per field only if you tick it) and writes a mapping, which is data, never code: which files hold posts or comments, and which fields are the time, text and author. `bridge.py try-mapping` runs it over the whole download for a preview; once you use it, `connectors/mapped_exports.py` reads that folder with it before the catch-alls. The request goes to the agent Ask uses, signed in the same way (account, key or local model), with no tools, once that provider's data settings are confirmed; with AI off, asking goes through the one-time AI agreement. Without an agent, copy what's sent into any AI chat and paste the reply back.
5. **The next person starts with it**: tick "Add it to the app's mapping library" and the mapping goes to `data/mappings/<service>.json`; anyone who adds that service later starts with it.

## Layout

```
src/shared/catalog.ts   every source: group, steps, URLs, wait and expiry, what it produces; services you add
src/shared/contents.ts  what a source holds, in words; src/shared/phone.ts: every iPhone source, described
src/shared/hub.ts       the hub: built-ins, services you added and the directory, each once, by kind
src/shared/status.ts    pure: probe + stats + saved state + jobs -> one view per source
src/main/main.ts        window, IPC, actions, downloads, reminders, daily refresh
src/shared/setup.ts     Your Setup: the browser Do It for Me works in, whether it can run, what the connectors are told
src/main/jobs.ts        one connector run at a time (they share manifest.json and corpus.db)
src/main/downloads.ts   Downloads watcher, where files go, moving them
src/renderer/app.tsx    the interface; src/renderer/welcome.tsx, the welcome page (examples.ts, its made-up data)
src/main/ask.ts         Ask: the providers, the tool workers and mailbox, conversations, keys
src/shared/ask.ts       Ask: providers, what each keeps of your data, the events of an answer
src/renderer/ask.tsx    the Ask page; src/shared/markdown.ts parses the answers
py/bridge.py            the app's only way into the connectors; prints JSON
py/ask_tools.py         Ask's tools over the corpus; py/ask_prompt.md, the assistant's instructions
../connectors/stream.py the event stream: corpus.db as events in order, a month at a time, into corpus/stream/
py/explore.py           Explore's artifacts; src/main/explore.ts runs it, src/renderer/explore.tsx shows them
py/export_library.py    Export Your Library's .zip; src/main/library_export.ts runs it, src/renderer/export_sheet.tsx shows it
data/services.json      services and their domains and export steps (scripts/build_services.py)
```

App state (requests, ticked steps, skips, files seen) lives in `~/Library/Application Support/Homecoming/state.json` (until 2026-10 the app was called User Model; its folder is renamed the first time Homecoming starts).

## Tests

```bash
npm test             # all three suites below
npm run test:unit    # status logic, queue, downloads, catalog cross-checks; Ask against fake providers and CLIs
npm run test:py      # bridge.py: probe, identify, stats, real connectors in a sandbox; Ask's tools and their sandbox
npm run test:e2e     # the real app driven by Playwright
npm run test:clis    # Ask: the real Claude Code and Codex CLIs, signed in with a key, against stand-in model servers
npm run test:real    # this Mac's real data (below); run it before every release
```

The end-to-end tests launch the app against a sandbox: a fake `HOME` (Claude Code sessions, a git repo, a fake encrypted backup), a throwaway corpus, a fake Downloads folder, and a local site standing in for the export pages. The real `imports.py` parses fixture exports for every format. `real_data.test.ts` also runs on this Mac's real data: read-only over the real corpus (checked byte for byte afterwards), and the real Mac connectors reading the real Library into a temporary corpus. `walk_real.test.ts` goes through the Setup Assistant from the welcome page to the end as a new person would, on the real Mac, into a throwaway corpus it deletes afterwards. It then waits for Explore, and fails if the app or anything it starts connects to anything but this Mac. `recovery.test.ts` kills the app in the middle of a read and checks that the next launch finishes it. Screenshots land in `test-results/`.

**Packaging:** `npm run package` builds `release/Homecoming.app` and `release/Homecoming-<version>-arm64.dmg` for Apple silicon (`scripts/package_mac.mjs`). The app holds the built interface, `py/` and `data/` in `Resources/app`, `connectors/` (vendored iLEAPP and its wheels included) in `Resources/connectors`, and its own Python 3.14 in `Resources/python`, with cryptography and pypdf installed and everything compiled ahead of time. So nothing is installed or downloaded when it runs, and it never writes into itself (`PYTHONDONTWRITEBYTECODE`). Packaged, the library is `~/Homecoming` and Full Disk Access goes to Homecoming itself. The two downloads the build makes (a [python-build-standalone](https://github.com/astral-sh/python-build-standalone) build and pypdf's wheel) are pinned by SHA-256. Electron is the copy `npm ci` installed. `UMP_APP=release/Homecoming.app/Contents/MacOS/Homecoming npm run test:e2e` runs the end-to-end tests against the packaged app. `npm run icon` redraws `build/icon.icns` from `build/icon.svg`.

**Releasing:** `python3 desktop/scripts/release_copy.py OUT` makes the release copy (the app, `README.md` and `WHAT_TO_TRY.md`, nothing else) and checks it for personal data against the corpus. To update the release repo, clone it, replace everything but `.git` with a new copy, then commit and push.

Environment variables used by the tests (and handy for trying things safely): `UMP_READONLY=1` (never move files or run connectors), `UMP_NO_AUTORUN=1`, `UMP_USER_DATA`, `UMP_DOWNLOADS`, `UMP_PYTHON`, `UMP_URLS` (JSON `{sourceId: url}`), `UMP_IPHONE_MODULE`, `UMP_EXTERNAL_LOG` (write links and mail drafts to a file instead of opening them), `UMP_APPLICATIONS` (where to look for Mac apps), `UMP_CLAUDE_CMD` (the Claude Code CLI, for mappings and Ask), `UMP_CODEX_CMD`, `UMP_ANTHROPIC_URL` and `UMP_OPENAI_URL` (where Claude Code and Codex reach the API when signed in with a key), `UMP_ASK_ANTHROPIC_KEY` and `UMP_ASK_OPENAI_KEY` (keys that skip the Keychain), `UMP_MAPPING_LIBRARY`, and Your Setup's own (`UMP_BROWSERS_SKIP`, `UMP_PHONE_REGION`, `UMP_READY_MAIL`, `UMP_READY_NOTIFICATIONS`), which the app sets from its settings. `test/fakes/` has the stand-ins: a streaming Anthropic API and a local model server, and fake Claude Code and Codex CLIs that call the real tools.

## Not done yet

- **Signing.** `npm run package` builds an app signed ad hoc, so macOS asks once (Open Anyway). A Developer ID signature and notarization would remove that.
- **Daily refresh only while the app is open.** A login item or LaunchAgent would keep it going.
- **The app doesn't click through export sites for you.** Export pages open in your own browser (an app's built-in browser can't sign in with Google, and loses your saved logins and passwords); the steps sit in the app.
