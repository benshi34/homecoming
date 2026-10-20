# Homecoming

Google, Instagram, your phone, your bank: every service you use keeps a record of your life. But each keeps it in its own place and its own format, behind a download page that's hard to find, in files that are hard to read.

Homecoming is a Mac app that brings it home. It gathers your data into one library on your Mac, puts it in order, and lets you explore it and ask it questions:

1. **Request your data.** It finds the accounts you use, opens each one's download page with the steps, and tells you when your data is ready. What's on your Mac and your iPhone is read right away.
2. **Bring it home.** Each download is recognized by what's inside, filed, and read into one organized library.
3. **Explore it.** Browse what Homecoming makes from your data (your year, your people, your places, the rhythm of your days), or ask questions in plain words and get answers that point to the messages and photos they came from.

**This is version 0, an early release:** it works, with rough edges. Thank you for trying it. [What to try first](WHAT_TO_TRY.md), and [how to tell us what went wrong](#reporting-a-problem).

## What it works with

Homecoming is made for one kind of setup, and works best inside it:

- **A Mac with Apple silicon** (M1 or later). It's built and tested on macOS 26 (Tahoe).
- **Apple's own apps**, read on this Mac: Messages, Mail, Photos, Notes, Calendar, Contacts, Reminders, Voice Memos, Podcasts, Books, Maps, Screen Time and call history. Also WhatsApp for Mac, and the documents in your cloud drives (OneDrive, Google Drive, Dropbox, Box) and Obsidian vaults.
- **An iPhone**, read from an encrypted backup made in Finder. Android phones aren't read; Google Takeout still brings in what Google keeps from one (location, Fit, Chrome).
- **English.** The app is in English, and it reads exports as English-language accounts write them. Google, Instagram, Facebook and the others name their files and labels in your account's language, so an export in another language can come in with less in it (searches as plain page visits, say, or no dates on chats). If an account is set to another language, switch it to English before you request its export.
- **Browsers:** browsing history from Safari, Chrome, Arc, Edge, Brave, Vivaldi, Opera, Firefox and Zen, every profile. Do It for Me works in Chrome, Edge, Brave, Arc, Vivaldi or Opera (the ones the Claude in Chrome extension runs in).
- **Your email:** any account added to Mail on this Mac (Gmail, Outlook and Exchange, iCloud, school and work mail), and Gmail through Google Takeout.

What the app finds on your Mac (your browsers, Mail's accounts, your region) is used as it is. You can see all of it, and change it, in [Your Setup](#settings).

## Your data, and where it goes

Everything Homecoming collects stays on your Mac, in your library (readable by your account only): the `Homecoming` folder in your home folder (`~/Homecoming`) if you use the app, or `corpus/` inside the folder you run it from if you run it from source. The decrypted copy of your iPhone backup, and what's read from it, go in `~/Library/Application Support/q1_user_model`, where iCloud never syncs them. Nothing is uploaded, and if your library would sync to iCloud, the app says so and offers to keep it on this Mac.

Only four things ever leave your Mac, and each is something you start:

- **Asking a question.** Ask sends the model you pick (Claude through Claude Code, or a model through Codex) what it looks up to answer you: the text with secrets such as passwords and keys blanked out, and any photo it looks at as it is. Before a company's model is used for the first time, the app shows what that company keeps and how to turn off training on your data, and waits for you. You can also pick a model that runs on your Mac (through Codex, with Ollama or LM Studio).
- **An export the app doesn't know yet.** It can ask the AI you picked in AI Settings how that export is laid out. The request holds file and field names, plus one example value per field only if you tick that box, and you see it and approve it before it's sent. Without one on this Mac, you copy the request into any AI chat yourself.
- **Requesting your data.** Download pages open in your own browser, signed in as you, like any other site you visit.
- **Do It for Me**, if you turn it on: Claude Code works in your browser through the Claude in Chrome extension, on each service's export page and, if you let it, in the inboxes turned on in AI Settings (only those), for the "your data is ready" email. What's on those pages goes to Anthropic, as when you use Claude in Chrome yourself.

There's no analytics, no account, no update check and no telemetry.

## What it changes on your Mac

It reads, and changes only what you tell it to:

- **Photos and files in iCloud, read only:** photos others shared with you (shared albums, Shared with You, a Shared Library) are kept, but apart from yours, so where they were taken isn't counted as where you were. Documents and files that are only in iCloud ("Optimize Mac Storage") are listed by name, not downloaded.
- **Mail, read only:** every account in Mail on this Mac is read into your library, like Messages and Notes. An email you also have from an export (Gmail in Google Takeout, say) is kept once.
- **Notifications, read only:** while an export is on its way, the app looks for the service's "your data is ready" notification on this Mac, and its email in Mail. They're read from a private copy kept on this Mac (in Caches), and nothing else from them goes into your library. Either can be turned off in General, which removes its copy.
- **Downloads you're expecting** move from `~/Downloads` into your library's `imports/` folder when they arrive. Files on another drive are copied, not moved. Anything you weren't expecting waits for a yes.
- **Two settings, only if you click Keep:** Claude Code's `cleanupPeriodDays` in `~/.claude/settings.json`, so it stops deleting transcripts after 30 days, and a few lines at the end of `~/.zshrc`, marked `# Added by Homecoming`, so Terminal keeps every command and when it ran.
- **Settings in other apps:** Messages, Safari, your iPhone and Google can delete old history. For each one, the app shows you how to keep it, and you change it there yourself.

## What to expect

- **It takes a few days, not an afternoon.** What's on your Mac is read first, while you request the rest. Some services take hours to prepare your download and others take weeks (Spotify can take 30 days), and some links expire within days. The app tracks each one, reminds you, and picks the file up from Downloads.
- **AI, in one place** (optional, off until you turn it on): the Setup Assistant asks once, and AI Settings (under Settings in the sidebar) lets you pick the agent (Claude Code or Codex, with your own sign-in, an API key, or a model on this Mac), shows whether it's signed in, and turns Do It for Me on or off. Everything that uses AI uses the one picked: Ask, making sense of a download, and Do It for Me. Ask and making sense of a download send nothing until you ask. Everything that uses AI carries a sparkle mark.
- **Do It for Me** (optional): Claude Code requests each export in your browser (Chrome, or the one you pick in AI Settings), where you're signed in, and when the service's "your data is ready" email arrives, it downloads it (the one whose link expires soonest first). It stops only when you need to sign in or enter a code, and carries on when you click Continue, or by itself once you've signed in.
- **Ask for Everything**: one sheet, from the Overview, with every export still to ask for. The app checks which services the browser Claude works in is signed in to (from its session cookies' names and expiry dates, never their values or your passwords), so Claude asks for those one after another while you do something else. A sign-in or a site to allow it on is said right away; the rest, once, at the end. The rest you sign in to first (your saved password, a passkey or your password manager fills it in), and Claude does those too. Services you added with a known export page are done by Claude like the built-in ones. Reddit and Patreon are yours to do (Claude in Chrome isn't allowed there), and a service you added with no page but an address gets its request by email, sent from Mail once you say so. The first time, Claude opens each service's site once before it starts, so Claude in Chrome can ask you to allow it on each in the first minute or two, while you're there; after that it runs by itself. The Setup Assistant offers it too, on its exports list (Ask Claude for All), and each export page leads with Do It for Me. While Claude works, the top of the Overview (and a strip in the Setup Assistant) shows each service it's at, how many are done, and anything it's waiting for you to do in your browser, with Stop for one or Stop All.
- **Your iPhone** is read from an encrypted backup on this Mac, made in Finder. The app walks you through it. You'll need the backup's password, and making the backup can take a while.
- **Free space:** the app warns you below 20 GB. A big Google or Photos download can be tens of gigabytes.

## Settings

Every setting has one home, under Settings in the sidebar. ⌘, opens General, and so does Settings… in the menu bar.

- **General:** how Homecoming works.
  - Reading this Mac every day, or now.
  - Watching for exports coming home: in Downloads, and the "your data is ready" email in Mail or notification on this Mac.
  - Notifications: whether macOS shows them, with a test.
  - Keeping working when the window is closed, and opening at login.
  - Your library: where it's kept, and Export.
- **Your Setup:** who you are, and what's on your Mac that Homecoming uses. It starts as what was found, and anything you don't change stays that way.
  - **You:** your names, email addresses, phone numbers and usernames, which decide what's marked as yours. You change them right there. When an export turns up an address that might be yours, it's there to look at, with a count on Your Setup. Also the region your phone numbers are in: a number saved without its country code ("07700 900123") is read as one from there. It starts as your Mac's region (System Settings → General → Language & Region).
  - **iPhone:** when several devices are backed up on this Mac (a family's iPhones, an iPad), which one is yours. Only that one's backup is read, even when another is newer. If one that isn't yours was read before, you can take what came from it out of your library.
  - **Browsers:** each browser on this Mac, with a switch for whether its history is read, and which browser export pages open in (your Mac's default unless you pick another).
  - **Email:** the accounts in Mail on this Mac.
- **AI Settings:** everything AI does.
  - Whether AI is used at all.
  - The agent that does the work, with its sign-in, key or model.
  - Do It for Me: on or off, the browser Claude works in, downloading exports when they're ready, looking for them every few hours, and the inboxes Claude may look in for the email saying one is ready.

**Setup Checks**, under This Mac, are the things to fix or turn on: Full Disk Access, Python, keeping your history, free space.

## Install and run

### Build it on your Mac

Homecoming builds itself into an app in your Applications folder, in about five minutes. Built on your own Mac, it opens like any other app. It isn't offered as a download: macOS warns about any app from a website that isn't signed by a paid Apple developer account, and Homecoming isn't.

You need:

- **A Mac with Apple silicon** (M1 or later).
- **Node.js** from [nodejs.org](https://nodejs.org/) (the LTS installer). Homecoming was built and tested with Node 24.
- **git.** The first time you type `git` in Terminal, macOS offers to install Apple's command line tools, which include it. Say yes, then run the command again.

Then, in Terminal:

```bash
git clone https://github.com/benshi34/homecoming.git ~/Developer/homecoming
cd ~/Developer/homecoming/desktop
npm ci
npm run install-app
```

- `npm ci` installs exactly the versions listed in `desktop/package-lock.json`, and checks each download against its recorded hash.
- `npm run install-app` builds Homecoming.app, with its own Python inside, and puts it in Applications. If an earlier Homecoming is there, it quits it and replaces it. It downloads two things, each checked against a pinned SHA-256: a standalone Python, and one Python package.

Then:

1. **Open Homecoming** from Applications.
2. **Turn on Full Disk Access** when the app asks: System Settings → Privacy & Security → Full Disk Access → Homecoming. Then quit and reopen it.

**Updating:** run the same commands, starting with `git pull`. Your library and progress stay where they are. Each step runs only if the one before it worked, so a failed download or build leaves the Homecoming you have in place.

```bash
cd ~/Developer/homecoming
git pull --ff-only && cd desktop && npm ci && npm run install-app
```

After an update, macOS can turn Full Disk Access off for Homecoming without saying so (the new build is a different app to it). If Homecoming says so, open System Settings → Privacy & Security → Full Disk Access, turn Homecoming off and on again, then quit and reopen it.

### Claude Code or Codex

To ask questions about your data, you'll also want the Claude Code or Codex CLI. If it isn't signed in, **Sign In…** in AI Settings opens its sign-in in your browser (no Terminal needed): sign in there, and Homecoming comes back by itself. Should the page say it can't connect, **Use a Code Instead** opens one that ends with a code to paste into Homecoming. Installed with npm, nvm, Volta, Bun or Homebrew, it's found even when Homecoming is opened from Finder.

### Run from source

For developers working on Homecoming: it runs from Terminal, without building the app.

#### What you need

- **A Mac with Apple silicon** (M1 or later). On an Intel Mac the iPhone backup step can't run.
- **Python 3.14 from [python.org](https://www.python.org/downloads/macos/).** The iPhone backup step uses packages that come with Homecoming and are built for Python 3.14 only. The app looks for python.org's Python first (`/usr/local/bin/python3`).
- **Node.js** ([nodejs.org](https://nodejs.org/)). Homecoming was built and tested with Node 24.
- **git**, if you clone rather than download. The first time you type `git` in Terminal, macOS offers to install it.
- **Optional: the Claude Code or Codex CLI**, signed in, to ask questions about your data.

#### Get the code

Do one of these:

- **Download it.** On the repository page, click the green **Code** button, then **Download ZIP**. Unzip it, rename the folder (`homecoming-main`) to `homecoming`, and move it to a `Developer` folder in your home folder (`~/Developer/homecoming`). To update, download it again the same way.
- **Clone it with git**, which makes updating a one-line command:

  ```bash
  git clone https://github.com/benshi34/homecoming.git ~/Developer/homecoming
  ```

Keep it out of Desktop and Documents. If iCloud syncs those folders, everything you collect would be uploaded to iCloud.

#### Install and start

```bash
cd ~/Developer/homecoming
/usr/local/bin/python3 -m pip install cryptography pypdf
cd desktop
npm ci
npm start
```

`npm ci` installs exactly the versions listed in `desktop/package-lock.json` and checks each download against its recorded hash. `pip` downloads the two Python packages, and the first `npm start` downloads Electron itself (about 300 MB unpacked), checked against the checksums that come with it. After that, nothing is downloaded.

To use a different Python 3.14, start the app with `UMP_PYTHON=/path/to/python3 npm start`.

#### Full Disk Access goes to Terminal

macOS keeps Messages, Mail, Photos, Notes and call history behind Full Disk Access. When you run from source, macOS gives that permission to the app that started Homecoming (usually Terminal), not to Homecoming itself. That means every command you run in Terminal can read those files too.

1. When the app asks, open System Settings → Privacy & Security → Full Disk Access and turn on Terminal.
2. Quit and reopen Terminal (macOS offers to), then run `npm start` again from `desktop/`.
3. When you're done collecting, turn Terminal off in the same list.

#### Updating

If you cloned it:

```bash
cd ~/Developer/homecoming
git pull --ff-only && cd desktop && npm ci && npm start
```

If you downloaded the ZIP, download it again and put the new folder in place of the old one. Keep the old folder's `corpus/`: it's everything you've collected. Move it into the new folder first.

## Reporting a problem

Open an issue on this repository. Issues are public, so anyone can read what you write. Say:

- what you clicked, what you expected, and what happened instead;
- which source it was (Messages, Google, your iPhone...);
- your macOS version, and Intel or Apple silicon.

Each source's detail pane has a **Progress** log, and when you run from source, Terminal shows the app's output; both help. **Read them before you paste.** They can hold file names, account names and bits of your data. Never attach an export or anything from your library. If something about your data looks wrong, describe its shape ("a group chat shows up twice"), not who's in it.

## Removing everything

1. Quit Homecoming.
2. Delete your library: `~/Homecoming`, or `corpus/` in the folder you ran it from. That's everything it collected, including the exports it filed. If you chose Keep It on This Mac, the library is in `corpus.nosync` (or `Homecoming.nosync`) beside a shortcut of the old name: delete both.
3. Delete `~/Library/Application Support/q1_user_model`: the decrypted copy of your iPhone backup and what was read from it.
4. Delete `~/Library/Application Support/Homecoming`: its progress, settings and Ask conversations. If there's a `~/Library/Application Support/User Model` (the app's name before), delete it too. And `~/Library/Caches/Homecoming`: its copies of Mail's index and of your notifications, kept so they aren't copied again every few minutes.
5. If you used Do It for Me: delete the folders in `~/.claude/projects` whose names contain `homecoming-agent`. They're Claude Code's saved sessions of its work in your browser.
6. Drag Homecoming from Applications to the Trash (or delete the folder you ran it from).
7. Turn Homecoming (or Terminal) off in System Settings → Privacy & Security → Full Disk Access.
8. If you clicked Keep for them: remove the lines under `# Added by Homecoming` at the end of `~/.zshrc`, and `cleanupPeriodDays` from `~/.claude/settings.json`.

## Known limits

- **Not signed with an Apple Developer ID**, so it isn't offered as a download. Built on your Mac (above), it opens like any other app.
- **Apple silicon only**, and when run from source, Python 3.14 only, for the iPhone step.
- **Running from source, it works only while it's open.** The app built with `npm run install-app` keeps working in the menu bar when you close its window, and opens at login (General → Keep working when the window is closed).
- **Do It for Me needs Claude Code, signed in with a claude.ai account on Pro, Max, Team or Enterprise, and the Claude in Chrome extension in Chrome, Edge, Brave, Arc, Vivaldi or Opera.** Claude Code turns the browser off when it's signed in with an API key, and Safari and Firefox can't run the extension; AI Settings says which of these is missing. With Codex picked, Do It for Me isn't there yet (it's coming): Codex can drive a browser only inside its own app, not when another app runs it, so pressing Do It for Me says so, and the export's steps are on its page. Before Claude first works in your browser, the app shows what Anthropic keeps and waits for you, as Ask does. It stops when a service wants you to sign in, enter a code or prove you're not a robot. Without it, export pages open in your browser and the steps are in the app.
- **English-language accounts and a Mac with an iPhone** (see [What it works with](#what-it-works-with)).

How it all works: [desktop/README.md](desktop/README.md).
