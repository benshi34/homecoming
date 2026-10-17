# Parser registry

Which code turns each source into `corpus/normalized/<source>.jsonl`, and the format quirks it handles. Everything here is plain deterministic Python; re-running needs no agent:

```bash
python3 connectors/run_all.py            # every Mac connector and export, then rebuild the index
python3 connectors/run_all.py imports    # just the exports in corpus/imports/
python3 connectors/iphone.py             # the iPhone: decrypt the latest Finder backup, our phone parsers, iLEAPP, index
python3 connectors/rebuild.py            # recompute every source from what's on disk (no downloads/decryption), then index
```

**What stays out of the corpus, and only this:** data that would compromise privacy or security (passwords, keychain,
cookies, tokens, SIM and subscriber identifiers, Siri voice samples, Wallet barcodes), other people's data (Venmo's
public feed, strangers' Bluetooth devices, suggested people), corrupted data (e.g. a 72,722-steps-in-6-minutes glitch)
and stores with nothing about the person (app configuration). Lossy or noisy isn't a reason: raw Health samples sit
next to the daily summaries, spam and deleted mail are kept with `meta.tier`, phone internals with `meta.tier =
"device"`. True duplicates are merged, not dropped. Every exclusion is counted: per source in the manifest's `notes`,
iLEAPP artifacts in `_ileapp_left_out`, export files no parser read in `_imports_unclaimed`.

Siri voice samples and Wallet barcodes are out for good, not pending: neither is needed (decided 2026-10-09).

Exports in `corpus/imports/` are complete snapshots, so their sources are rebuilt from scratch on every run. Local sources that delete their own history (screen time, Chrome, calls, Claude Code) instead keep records from earlier runs the source no longer has (`Writer(accumulate=True)`).

Each run also stamps `corpus/manifest.json` with the exact parser (`file:function`) and the git commit it ran from, plus any connector files edited since that commit, so every source can be traced to the code that produced it. Commit parser changes before a run you want to keep.

Status: ✅ run on my real data · 🧪 written against documented formats and sample exports, not yet run on a real export.

## iPhone (`connectors/iphone.py`, all ✅)

`iphone_backup.py` decrypts the backup into a mirror, `corpus/raw/iphone/files/<domain>/<relativePath>`. Everything below reads that mirror (`common.phone(domain, rel)`).

| Source | Parser | Reads | Helpers |
|---|---|---|---|
| (mirror, no source) | `iphone_backup.py:main` | Finder backup → every file except the keychain and photo thumbnails; incremental via `mirror_state.json` | password: env, stdin, Keychain item or prompt |
| imessage | `imessage.py:main` (+ `messages`, `system_event`, `attachment_file`) | `HomeDomain/Library/SMS/sms.db` first, then the Mac's `chat.db`. Same schema, deduped by message guid; attachments in `MediaDomain/Library/SMS/Attachments/` | `contacts.Resolver` for names |
| calls | `calls.py:main` (+ `add_calls`) | `HomeDomain/Library/CallHistoryDB/CallHistory.storedata` first, then the Mac's; deduped by `ZUNIQUE_ID`, `meta.copy` says which | `contacts.Resolver` |
| iphone_contacts | `contacts.py:iphone_contacts` | `HomeDomain/Library/AddressBook/AddressBook.sqlitedb` (older ABPerson / ABMultiValue schema) | the Resolver reads it first |
| health | `health.py:summaries` | `HealthDomain/Health/healthdb_secure.sqlite`: one record per local day, per sleep session, per body measurement | |
| health_samples | `health.py:samples` | the same database: every live sample (steps, distance, heart rate, sleep stages, Activity rings from `activity_caches`, unidentified types as "Health type n"), with app (`healthdb.sqlite` sources) and device | |
| phone_&lt;module&gt; | iLEAPP `scripts/artifacts/<module>.py` + `ileapp.py:write_module` | everything else iLEAPP parses: WeChat, WhatsApp, Venmo, Splitwise, Notes, Calendar, Reminders, Voice Memos, Safari, app usage, interactions, Airbnb, Netflix, United, Uber, X DMs, Wallet passes, … | [ILEAPP.md](ILEAPP.md): what's left out, custom modules, upstream issues |

## Mac sources (one connector each, all ✅)

| Source | Parser | Reads | Helpers |
|---|---|---|---|
| contacts | `contacts.py:mac_contacts` | AddressBook `*.abcddb` | |
| apple_notes | `apple_notes.py:main` | `NoteStore.sqlite` (gzip → protobuf) | |
| calendar | `calendar_events.py:main` | `Calendar.sqlitedb` | |
| reminders | `reminders.py:main` | Reminders `Data-*.sqlite` | |
| browser_history | `browser_history.py:main` | Safari `History.db`; every Chromium browser's `<profile>/History` (Chrome, Arc, Edge, Brave, Vivaldi, Opera...; the table is `browsers.py`); Firefox and Zen `places.sqlite`. Browsers turned off in Your Setup (`UMP_BROWSERS_SKIP`) aren't read | |
| app_usage | `app_usage.py:main` | Biome `App.InFocus`, `Media.NowPlaying` | `segb.py` (SEGB file reader) |
| ai_coding | `ai_coding.py:main` | `~/.claude/projects`, `~/.codex/sessions` | |
| photos | `photos.py:main` | `Photos.sqlite`, `search/psi.sqlite`; what others shared (ZBUNDLESCOPE 1 iCloud link, 2 shared album with ZCLOUDISMYASSET for yours, 3 Shared with You; a Shared Library's contributor via ZASSETCONTRIBUTOR → ZSHAREPARTICIPANT.ZISCURRENTUSER) goes to `shared_photos` | |
| voice_memos | `voice_memos.py:main` | `CloudRecordings.db` (no recordings synced yet, so 0 records) | |
| notion | `notion_local.py:main` | Notion desktop `notion.db` | |
| documents | `documents.py:main` | Documents, Desktop, Downloads, iCloud Drive; a file only in iCloud (`.icloud` placeholder, or flagged dataless since macOS 14) is listed, not read; one read before keeps its text | `common.cloud_only` |
| git_commits | `git_commits.py:main` | `git log` across local repos; a repo with any `.git` file only in iCloud is skipped (git would download it); git runs only when it's a real one (`common.git_bin`) | `identity.py` |
| mail | `mail_app.py:main` | Mail.app `~/Library/Mail/V*/<account>/**/*.emlx`, every account; Sent/Drafts mark mail as yours, Junk/Deleted get `meta.tier`; unchanged files aren't read again (`corpus/raw/mail/read.json`); the same Message-ID from an export is indexed once (`build_index.py`) | `email_parse.py` |

Per-source gotchas for these are below.

## Exports dropped into `corpus/imports/` (all in `imports.py`)

`imports.entries()` walks loose files, zips and zips inside zips; each parser below gets every entry and claims the ones it understands. Unclaimed document files fall through to `other_documents`.

| Source | Parser | Matches | Status |
|---|---|---|---|
| gmail | `google` | `*.mbox` | ✅ |
| hotmail (or any folder name) | `google` | `*.mbox` and Mail.app's `<Folder>.mbox/mbox` outside Takeout; source = the folder under `corpus/imports/`; Sent/Drafts mark mail as yours, Junk/Deleted are skipped | ✅ |
| google_activity | `google` | `My Activity/*/MyActivity.json`, YouTube `watch-history.json` / `search-history.json` | ✅ |
| chrome_synced | `google` | `Chrome/History.json` | ✅ |
| google_calendar | `google` | `*.ics` | ✅ |
| google_contacts | `google` | `*.vcf` under `Takeout/` or `Contacts/` | ✅ |
| vcard_contacts | `google` | any other `*.vcf` (e.g. iPhone export) | ✅ |
| google_keep | `google` | `Keep/*.json` | ✅ |
| google_maps_places | `google` | `Saved Places.json`, `Reviews.json`, labeled places | ✅ |
| google_photos | `google` | `Google Photos/**/*.json` sidecars | 🧪 |
| location_history | `google` → `location_history` | `Timeline.json`, `location-history.json`, Semantic Location History | 🧪 |
| google_chat | `google_chat` | `Google Chat/Groups/*/{group_info,messages}.json` + attachments | ✅ |
| linkedin | `csv_exports` (+ `linkedin_rows`) | messages, Connections, Shares, Comments, and the files in `LINKEDIN_FILES` | ✅ |
| reddit | `csv_exports` | `comments.csv`, `posts.csv`, `messages.csv` | 🧪 |
| chatgpt, claude_ai | `ai_exports` | `conversations.json` | 🧪 |
| discord | `discord` | `Messages/index.json`, `Messages/c*/{channel.json,messages.json\|csv}`, `Account/user.json` (friends list, for DM names) | ✅ |
| instagram, messenger | `meta` | `messages/*/*/message_N.json` (DMs, both sides, incl. message requests) + their photos and videos | ✅ |
| instagram_activity, facebook_activity | `meta` (+ `meta_item`) | the data files matched by `META_FILES`: likes, saves, follows, searches, comments, posts, views, interest inferences, profile | ✅ |
| x | `x_archive` | `data/tweets.js`, `direct-messages*.js`, `like.js` | 🧪 |
| spotify | `spotify` | `Streaming_History_*.json`, `StreamingHistory*.json` | 🧪 |
| whatsapp_export | `whatsapp` | exported chat `.txt` (only needed without a phone backup; `phone_whatsapp` has everything) | 🧪 |
| slack | `slack` | `users.json` + `<channel>/<date>.json` | 🧪 |
| zoom | `zoom` | `*.vtt` | 🧪 |
| notion_export | `notion_export` | `Export-<uuid>/**/*.md` pages and `*_all.csv` database tables, plus their attachments | ✅ |
| imported_documents | `other_documents` | any leftover pdf/docx/pptx/pages/md/txt/html/ipynb | ✅ |
| &lt;export&gt;_other | `other_data` | any leftover .json/.csv/.js in an export: one record per item (security files, viewer assets and mail indexes excepted: `LEFTOVER_SECURITY`, `LEFTOVER_NO_INFO`) | ✅ |
| &lt;export&gt;_files | `other_files` | any leftover image/audio/video, copied to `corpus/media/<export>/` | ✅ |

Shared helpers: `common.py` (record schema, `Writer`, manifest), `identity.py` (`is_me` from `corpus/identity.json`), `contacts.py` (`Resolver`, `parse_vcards`), `email_parse.py` (mbox streaming, MIME → text), `browser_history.classify` (search URLs), `documents.py` (pdf / textutil / pptx / iWork text).

## Format quirks the parsers rely on

Found on real exports in Oct 2026. If an export stops parsing, check these first.

**Google Takeout**
- The download page's "Part N" doesn't match the file name: Part 2 was `takeout-…-4-001.zip`. One product can fill a zip by itself (all of Mail was one 7 GB mbox in one zip).
- My Activity and YouTube history must be requested as JSON; the default HTML isn't parsed.
- Gmail: Spam and Trash are dropped using the `X-Gmail-Labels` header; a mail counts as sent by me if it's labeled Sent or comes from an address in `identity.json`.
- Keep writes every note twice (`.json` and `.html`); only the JSON is used. `archive_browser.html` at the root is skipped.
- Google Chat: `created_date` looks like `Wednesday, June 8, 2016 at 3:55:41 AM UTC` with a narrow no-break space (U+202F) before AM/PM. An attachment's `export_name` differs from the file on disk: `?` is written as `_`, and repeated names in a conversation become `X.jpg`, `X(1).jpg`, `X(2).jpg` (taken to be in message order). Attachments are copied as-is to `corpus/media/google_chat/<people> [<id>]/` and listed in `meta.files`.

**vCards**
- vCard 3.0 with folded lines and grouped properties (`item1.TEL`). `contacts.Resolver` reads every `.vcf` in `corpus/imports/` (loose files first, then inside zips) before the Mac's AddressBook, so phone exports win.

**LinkedIn**
- Files now carry a member id (`Shares_<member id>.csv`); it's stripped before matching names.
- `Connections.csv` starts with a `Notes:` preamble before the header row.
- `Ad_Targeting.csv` repeats column names, so it's read with `csv.reader`, not `DictReader`.
- Date formats differ by file: `Jul 2025`, `2025/09/16 21:54:21 UTC`, `9/3/26, 7:30 PM`, `Tue Sep 22 00:27:49 UTC 2026`, `2026-09-22 13:39:25`.
- The "complete" archive has no `messages.csv` when there are no messages, and downloads named `….zip.zip`.

**Meta (Instagram, Facebook)**
- Accounts Center exports Instagram and Facebook separately unless both profiles are linked there. Choose JSON (default is HTML), All time (Facebook defaults to Last year), Higher media quality, and the notify address (it defaulted to an old work email). "Start export" asks for the password again, and the download link expires 4 days after it's ready.
- All text is UTF-8 that was decoded as latin-1 (`â¦` for `…`); `fix_meta` re-encodes it.
- Two layouts in one export: newer files are lists of `{timestamp, media, label_values: [{label, value | href | timestamp_value | media | dict | vec}]}`, older ones use `string_map_data` / `string_list_data`. `meta_item` flattens either into label/value pairs.
- Messenger: threads sit in `messages/{inbox,filtered_threads,message_requests,e2ee_cutover}/`. Chats that became end-to-end encrypted (Messenger's default since late 2023) are not in the export; `e2ee_cutover/` holds only their history from before the switch, so Messenger volume collapses after 2023 (10k messages in 2022, 52 in 2026). The rest is in Messenger → Settings → End-to-end encrypted chats → Message storage → Download secure storage data.
- Facebook's older files use plain items (`{"name": …, "timestamp": …}`); `meta_item` keeps their text fields too. `META_SKIP` drops Facebook's own suggestions (people you may know, suggested friends).
- Media `uri`s are relative to the export root (`your_instagram_activity/messages/inbox/<thread>/photos/<id>.jpg`, `media/posts/…`); files are copied to `corpus/media/<instagram|facebook>/<uri>`.

**Discord**
- The package arrived within hours, not the 30 days Discord quotes.
- The data package holds only messages you sent (DMs, group DMs, server channels). Categories are chosen at request time (Account, Messages, Servers used here).
- `Messages/index.json` names many DMs `"None"` or `Direct Message with Unknown Participant`; those are named from the friends list in `Account/user.json`. Recipients who aren't friends stay as user ids. `Attachments` are CDN links, kept as text (they may have expired).

**Notion (Export all workspace content)**
- Markdown & CSV, with "Create folders for subpages". Files sit under `Export-<uuid>/<section>/` (sections such as Private & Shared, and one per teamspace); each page is `<Title> <32-hex page id>.md`, its subpages in a folder named after it, and each database is written twice (`X <id>.csv` and `X <id>_all.csv`; only `_all` is kept).
- Pages carry no dates and every zip entry is stamped with the export time. Only database rows have `Created time` / `Last edited time` lines, so most pages come out undated (`meta.ts_from` is empty). The parser deliberately doesn't borrow dates from the local Notion cache: each parser reads only its own export, and joining sources is a separate step.
- Links between pages are URL-encoded relative paths (`Trip%20Ideas/…md`); they're reduced to the linked page's title, and links to other files resolve to attachments.

**iPhone backups (Finder, encrypted)**
- Ticking "Encrypt local backup" starts a backup at once, even with the iCloud option still selected. A backup that ends without `Info.plist` is incomplete: Manage Backups lists it as "Unknown, 12/31/00".
- Decryption (iOS 10.2+): PBKDF2-SHA256 (DPSL, DPIC = 10M rounds) then PBKDF2-SHA1 (SALT, ITER) unwraps the class keys in `BackupKeyBag`; `Manifest.db` and each file are AES-256-CBC with a zero IV; per-file keys sit in the `Files.file` NSKeyedArchiver plist. Uses the `cryptography` package, already on this Mac.
- A file is stored at `<backup>/<id[:2]>/<id>` with `id = sha1("<domain>-<relativePath>")`, so files can be located without decrypting the manifest. That's how the needed ones were staged where a terminal without Full Disk Access could read them.
- Don't cut decrypted files to the manifest's `Size`. It's read when the backup starts, and files that grow during the backup are stored in full: 167 files here, mostly the X app's DM databases, up to 2 MB longer. Strip the PKCS7 padding instead. iLEAPP's own iTunes reader has this bug, which is why it runs on our mirror.
- The keychain (`KeychainDomain`) holds saved website, Wi-Fi and mail passwords that unlock with the backup password. It's never decrypted.
- The phone's `sms.db` has the same schema as the Mac's `chat.db` and the same message guids. Same for `CallHistory.storedata` (`ZUNIQUE_ID`).
- The phone's Photos.sqlite is the same iCloud library as the Mac's (matched by `ZCLOUDASSETGUID`), so it isn't parsed again. The backup holds no photo originals when iCloud Photos is on, only thumbnails.
- Opening a mirror database with a writable SQLite connection changes the file (checkpoint, vacuum). Read-only connections are safe but create empty `-wal`/`-shm` files next to it.

**Apple Health (`healthdb_secure.sqlite`)**
- Only encrypted backups include Health. Samples are `samples` (data_type, start/end in Apple-epoch seconds) → `objects` (provenance) → `data_provenances` (`tz_name`, `origin_product_type`, `source_id`); values are in `quantity_samples` or `category_samples`. App names (`sources`) live in the other file, `healthdb.sqlite`.
- Data types are bare numbers. Mapped here by units and typical values: 7 steps, 8 distance (m), 12 flights, 10 active kcal, 9 resting kcal, 5 heart rate (per second, ×60), 61 respiratory rate (per second), 173 headphone dB, 187 walking speed, 188 step length, 182 double support, 194 walking asymmetry, 63 sleep (0 in bed, 1 asleep, 2 awake, 3 core, 4 deep, 5 REM), 2 height, 3 weight. Unmapped types are counted in the manifest notes.
- `objects.type` 2 = a deleted sample with no value. Eight Sleep deletes and rewrites thousands on every sync.
- Exact duplicate samples are common (6.5k here): Eight Sleep writes each sleep stage twice per sync and re-syncs nights, and step samples were duplicated around a phone switch. Without dedup, nights add up to 30+ h of sleep.
- Glitches exist: one 2019 sample said 72,722 steps and 40 km in six minutes. Samples over 250 steps, 400 m or 20 flights per minute are dropped.
- Each phone counts its own steps. When two phones overlap (old and new phone in the same pocket), take the larger total per day, never the sum.
- Each sample's own `tz_name` gives local days with no other source. Sleep sessions are samples within 2 h of each other.

## Adding a format

1. Write a function `name(es, W, used)` in `imports.py`: match entries by path or columns, `used.add(e.path)` for each claimed file, write records through `W("<source>")`.
2. Add it to `PARSERS` and add an `AV["<source>"]` line saying where the export comes from.
3. Add a row above, and its quirks.

## Synthetic regression checks

Run `python3 -m unittest discover -s connectors/tests -p 'test_*.py'`. Fixtures cover Mail.app and Takeout
mailboxes, encrypted-file padding and backup growth, phone/Mac message and call deduplication, contacts,
Health duplicate/outlier handling, iLEAPP message mapping, and the custom Wallet and X parsers. Tests use
temporary data only; they do not decrypt a real backup, run iLEAPP, or change the personal corpus.
