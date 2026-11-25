# iLEAPP in the phone pipeline

[iLEAPP](https://github.com/abrignoni/iLEAPP) (MIT) is the maintained open-source iOS artifact parser (~450 modules). We use it for every phone source except the few our own parsers handle better, so apps other people have work without new code from us, and fixes come from upstream.

**How it runs** (`connectors/ileapp.py`, called by `connectors/iphone.py` after decryption):
- Pinned release `ILEAPP_VERSION` (now v2026.4.4), vendored in `connectors/vendor/iLEAPP` with its packages as wheels in `connectors/vendor/ileapp-wheels` (see `vendor/README.md` for what's left out). The venv in `~/Library/Application Support/q1_user_model/tools/` is built from those offline: nothing is downloaded. Bump deliberately with `vendor/update_ileapp.sh`, then re-run and re-check this file.
- Input: our decrypted mirror, laid out as hard links in the phone's own paths (`build_view`), read with `-t fs`. Not `-t itunes`: see issue 1. iLEAPP never sees the backup password.
- Filesystem mode matches or beats iTunes mode on every artifact except issue 22 and a one-row setting. It gains the address book, Notion, the complete Uber store and our modules. A full run takes ~8 minutes and peaks at ~10 GB of working files (2026-10-12: 6 GB of copied files, 2.3 GB of HTML report, the rest timeline and TSV, all deleted after the run).
- Profile: every plugin except `EXCLUDE_MODULES`: Photos.sqlite analysis (`Ph*`), the keychain (saved passwords), SIM identifiers.
- Never all or nothing: a module that raises inside iLEAPP is logged by iLEAPP and listed in `run.json` `failed_artifacts`; the others' results are read. An exit with an error after "Processes completed" (its HTML report, or its run history) still has complete results, so they're read; an exit before it, or without `_lava_artifacts.db`/`_lava_data.lava`, is said in words and what was read from the phone before stays. A run still going after `TIMEOUT` (4 hours) is stopped. iLEAPP failing never stops `iphone.py`: our parsers and the index run all the same.
- Kept: only `_lava_artifacts.db` (one table per artifact) and `_lava_data.lava` (column types, chat-column roles). iLEAPP's copies of files and media and its HTML/TSV/timeline reports (~20 GB) are deleted after each run.
- Custom modules in `connectors/ileapp_modules/` (iLEAPP's own format, loaded with `--custom_artifacts_path`), written so they can go upstream as pull requests.

**How it's imported:**
- One source per iLEAPP module, named `phone_<module>`.
- Tables with a `conversation` data view become messages (thread, text, direction, sender, time, media). `CONVERSATIONS` adds views that modules lack.
- Other tables become dated records whose text is the row's fields.
- Media references resolve to files in our mirror.
- Left out, for one of four reasons only (each artifact listed in `manifest.json` `_ileapp_left_out`):
  - covered by our own parser (`OWNED`): iMessage, calls, Health samples, address book;
  - privacy or security (`PRIVATE_*`): cookies, tokens, secure stores, SIM/cellular/subscriber identifiers, Siri voice samples;
  - other people's data (`OTHER_PEOPLE_NAMES`, `SKIP_ROWS`): strangers' Bluetooth devices, other people's cached posts, Venmo's public feed;
  - nothing about the person (`NO_INFO_CATEGORIES`): Control Center, app manifests, backup settings.
  Besides those, an artifact the adapter couldn't read (its table missing, its metadata incomplete, an error while
  reading it) is listed as "couldn't be read", with its rows; the rest of its module and the other modules are imported.
  The phone's Photos.sqlite is skipped only when the Mac's library is in the corpus (`DUPLICATE_OF`).
- Everything else is imported. Phone internals (Wi-Fi networks, paired devices, alarms, home screen, app use,
  iCloud Drive listing, shares, recovered app records) carry `meta.tier = "device"`. Credential-like fields
  (`SECRET_FIELDS`) are removed from every record.

## Upstream issues (tracked, not reported)

| # | Module | What goes wrong (iOS 26.6.1) | Cause | Our workaround |
|---|---|---|---|---|
| 1 | iTunes reader (`search_files.py`) | Files cut short, e.g. app databases written to during the backup come out "malformed" | Writes `decrypted[0:Size]`. `Size` is read when the backup starts, and files that grow during it are stored in full | Run on our mirror (`-t fs`). `iphone_backup.py` strips PKCS7 padding instead |
| 2 | iTunes reader | Backup passcode written in plain text to the console log, `Screen_Output.html` and `index.html` | Log line "decrypted with passcode …" | Not passed any more; the wrapper redacted earlier runs |
| 3 | CLI | `--itunes_password` only as an argument (visible in the process list) | No env/file option, unlike `--image_password_env` | Not needed with issue 1's workaround |
| 4 | `appleWalletPasses` | Fails on every pass | `open(..., encoding='utf-8')`; some passes are UTF-16 (BOM `FE FF`). Also one row per JSON key, not per pass | `corpusWalletPasses` |
| 5 | `addressBook` | `IndexError` in `remove_unused_rows` (line 48) | Empty `count_rows` | Our `contacts.py` |
| 6 | `DataUsage` | `AttributeError: 'NoneType' object has no attribute 'split'` (line 105) | Null field | None needed |
| 7 | `ZaloChats` | `IndexError` (line 162) | Not investigated (Zalo isn't on this phone) | None |
| 8 | `imeiImsi` | `KeyError: 'CarrierEntitlements'` | Missing plist key | Excluded |
| 9 | `Ph126iOS26REFforAssetAnalysis` | Process killed (SIGKILL) after ~45 min at full CPU on a 2.8 GB Photos.sqlite | Likely memory | All `Ph*` excluded |
| 10 | `whatsApp` | No message id column, so distinct messages (photos sent in the same second) are identical rows | | `KEEP_DUPLICATES` |
| 11 | `Airbnb` | Each message repeated several times | Join fan-out | Exact duplicates collapsed |
| 12 | `weChat` | No conversation view and raw direction (0 = sent). Some bodies are zstd-compressed with WCDB's dictionary and come out as bytes. Group senders are left as a `wxid:\n` prefix | | `CONVERSATIONS`, type labels, prefix split with nicknames from WeChat contacts |
| 13 | `uberClient` | Times 1000× too small (`1692981` = 2023-08-25) | Unit conversion | `TIME_SCALE` |
| 14 | `AMDSQLiteDB` | A third of app-usage events are named `Unknown (<AdamID>)` | No App Store id lookup | `app_names()` maps ids to names from the backup's `Info.plist`. What's left is Apple's built-in apps and deleted apps |
| 15 | `health` | Sleep only from an Apple Watch: third-party sleep (category 63) is ignored. Exact duplicate samples are not removed | | Our `health.py` |
| 16 | `twitterX` | No file found | Reads `Library/Caches/com.atebits.tweetie.direct-message.cache` (caches aren't in backups). Current DMs are in `group.com.atebits.Tweetie2/…/v1/<id>/<id>-dmv2.db` | `corpusXDirectMessages` |
| 18 | `facebookMessenger` | No file found | Reads the main app's `lightspeed-userDatabases`; the share extension's `lightspeed-shareextension-*.db` is ignored | None |
| 19 | `discordChats`, `spotify` | No file found | Read `Library/Caches`, which backups leave out | None |
| 20 | `discordAcct`, `tikTok` | Times of 0 (1970) | | Times before 2000 dropped (`EARLIEST`) |
| 21 | `-t fs` input | Version-dependent modules (`health_heart_rate`, `photosMetadata`, `filesApp`) crash with `InvalidVersion: ''` | The iOS version comes only from `LastBuildInfo.plist`/`SystemVersion.plist`, which backups lack (`-t itunes` reads it from `Info.plist`) | `build_view` writes a `LastBuildInfo.plist` from `Info.plist` |
| 22 | `safariRecentWebSearches` | 0 rows in `-t fs` mode (some in `-t itunes`) | Three `com.apple.mobilesafari.plist` files match. Only the Safari container's has searches, and the module doesn't take it | None (those searches are lost) |
| 24 | `venmo` | "Transactions" mixes in Venmo's cached public and friends feeds: other people's payments. "Users" is everyone in those feeds | | `SKIP_ROWS` keeps the user's private feed and their friends |
| 23 | `iTunesBackupInfo` | Installed apps only in `-t itunes` mode | Reads the backup's root `Info.plist` | `installed_apps()` reads it (`phone_installed_apps`) |
| 25 | `whatsApp` (`whatsAppMessages`, line ~468) | In a group, every message from someone else has the group's name as its Sender Name | `sender = ZPARTNERNAME` for incoming messages, which is the chat's name; who wrote a group message is `ZWAMESSAGE.ZGROUPMEMBER` → `ZWAGROUPMEMBER`, which the module doesn't read | `ileapp.py` takes the sender from `ChatStorage.sqlite` (`whatsapp.group_senders`: the backup's copy, then this Mac's), matched by group, text and time; else "someone in the group" |

**No module yet**: Skype, Xiaohongshu, Apple Journal, and food and shopping apps (order and search histories).

**Checked, nothing to parse** (iLEAPP's "no data" is right): KakaoTalk, LINE, TikTok DMs, voicemail, Podcasts.

**Voicemail** (`voicemail`, iLEAPP's own module): read as `kind: voicemail`, not a row of fields. The caller is named as Contacts names the number, the text is Apple's transcript (or `[voicemail, <duration>, no transcript]`), the audio is in `files`, and one in the phone's deleted voicemails is `deleted`. `ileapp.py:write_artifact`.
