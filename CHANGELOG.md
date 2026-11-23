# What's new in Homecoming

Each version, newest first. The first time Homecoming opens after an update, it shows what's new since the version you had, from the copy of this file inside the app. Once a day, Homecoming reads this file on GitHub to see whether there's a newer version.

To update: **Update**, when Homecoming says there's a new version. Or in Terminal:

```bash
cd ~/Developer/homecoming/desktop
npm run update
```

## 0.5.0

- **35 more services read natively,** each from its own download, with nothing new leaving your Mac: Amazon (orders, Kindle reading), Netflix, Uber, Lyft, DoorDash, Snapchat, Telegram, PayPal, Venmo, Cash App, Apple Card, Coinbase, Robinhood, Chase, Bank of America, Capital One, Tinder, Hinge, Evernote, Day One, Trello, Todoist, Apple Music, Bing searches, Fitbit, Garmin, Letterboxd, Goodreads, IMDb, Trakt, MyAnimeList, The StoryGraph, Instapaper, Raindrop.io and Pocket. Each one's export steps are on its page.
- **Built from public samples:** Letterboxd and Goodreads were checked against real exports; the rest were built from open-source importers' test files and the services' own help pages, and haven't been. If yours reads wrong, say so in an issue, with what the file looks like, and it'll be fixed.
- **Bank and card downloads:** the QFX, QBO or OFX file any bank, card or Apple Card gives for Quicken or QuickBooks is read too, and a transaction in two overlapping downloads is kept once.
- **Fitbit, a day at a time:** steps, distance, calories, floors, heart rate, sleep, blood oxygen, skin temperature and the rest, which Fitbit and Google Takeout write as millions of readings a minute or a few seconds apart, are each read as one record a day, on your clock. Each GPS route from a workout is one record: where it started and ended, how far, how long.
- **Exports no reader knows** can now be XML or gzipped, have several tables in one CSV, rows of more than one kind in a file, and dates in any written form: the mappings behind all of the above are data the app ships, not code, so more can follow the same way.
- **Publishing can't undo the community's work:** a release stops if a fix merged on GitHub isn't in it yet.

## 0.4.0

- **Signal on this Mac:** your chats and calls in Signal Desktop, both sides, and who said what in groups, with reactions, edits and replies. Signal keeps them encrypted, so macOS asks once to let Homecoming use its key; nothing decrypted is written to disk. Signal Desktop has only what reached it since it was linked to your phone.
- **Zotero:** the papers and pages you saved, your notes on them and your highlights in their PDFs, from the Zotero app on this Mac: your library and the groups it syncs.
- **X messages name people:** a direct message's sender, and a one-on-one conversation, are named for the person where your own posts mention or reply to them, not by an account number.
- **A retweet isn't something you made:** What You Made and On This Day count only your own posts on X.
- **Dates written 2024/01/13 are dates:** an export no reader knows, such as Goodreads' library, gets its dates when they're written with slashes.
- **Each git commit once:** a worktree or a second clone of a repository no longer brings its commits in again.
- **Thank you, @nathanjzhao,** who wrote all of these.

## 0.3.0

- **Homecoming tells you when there's a new version:** once a day it reads its list of versions on GitHub, and says so once, in a notification and at the bottom of the sidebar, with what's new in it. Nothing about you is sent. Turn it off in General → Updates; Homecoming → Check for Updates… looks now.
- **Update brings it in:** Homecoming builds the new version from the folder you cloned, puts it in Applications, then quits and opens again. Nothing is installed until you click it. If something is in the way, such as a file you changed, it stops, says what to do, and leaves your Homecoming as it was.
- **Or one command in Terminal:** `npm run update`, in the `desktop` folder, does the same.
- **What's new, once:** the first time Homecoming opens after an update, it shows what changed. It's in the menu bar too: Homecoming → What's New in Homecoming.
- **Which version you have** is in Homecoming → About Homecoming, and at the bottom of General, with the day it was built.
- **Do It for Me works on several sites at once:** 3 unless you change it, each in a tab group of its own in your browser. AI Settings → Do It for Me → Sites at once sets it, from one at a time to 5 at once: more is faster, but uses more of your Claude usage at a time.
- **Ask shows more right in its answers:** a map of where you were, a day as Your Stream has it, a chart over the months, a person, an email, songs, a trip, your calendar, and what a service decided about you. Each is drawn from your library and opens what it shows.
- **Saved Ask answers stay right:** after your library is read again, an answer's citations still open the messages they pointed to, and its photos refresh when the library changes. The first read after this update rebuilds the search index once, so it takes a little longer than usual.
- **The README starts with how to install:** two commands, then open Homecoming and turn on Full Disk Access.

## 0.2.0

The first public release.

- **Request your data:** Homecoming finds the accounts you use, opens each one's download page with the steps, tracks each request, and tells you when your data is ready.
- **Bring it home:** downloads are picked up from Downloads, recognized by what's inside, and read into one library on your Mac. What's on your Mac (Messages, Mail, Photos, Notes, your browsers and more) and an encrypted iPhone backup are read right away.
- **Explore it:** your year, your people, your places and the rhythm of your days, made from your library.
- **Ask:** questions in plain words, with answers that point to the messages and photos they came from. It uses Claude Code or Codex, only when you turn AI on.
- **Do It for Me and Ask for Everything:** Claude requests your exports in your own browser, one after another, and downloads each when it's ready.
- **Your Setup** shows who you are and what's on your Mac that Homecoming uses, and lets you change any of it. **Export Your Library** saves it all in one .zip.
- **Built on your Mac:** `npm run install-app` builds Homecoming and puts it in Applications.
