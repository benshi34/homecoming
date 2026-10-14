# Homecoming

Google, Instagram, your phone, your bank: every service you use keeps a record of your life. But each keeps it in its own place and its own format, behind a download page that's hard to find, in files that are hard to read.

Homecoming is a Mac app that brings it home. It gathers your data into one library on your Mac, puts it in order, and lets you explore it and ask it questions:

1. **Request your data.** It finds the accounts you use, opens each one's download page with the steps, and tells you when your data is ready. What's on your Mac and your iPhone is read right away.
2. **Bring it home.** Each download is recognized by what's inside, filed, and read into one organized library.
3. **Explore it.** Browse what Homecoming makes from your data (your year, your people, your places, the rhythm of your days), or ask questions in plain words and get answers that point to the messages and photos they came from.

**This is a beta.** Thank you for trying it. [How to tell us what went wrong](#reporting-a-problem).

## Your data, and where it goes

Everything Homecoming collects stays in one folder on your Mac, `corpus/` inside the folder you install it in. It isn't uploaded anywhere, and if that folder would sync to iCloud, the app says so and offers to keep it on this Mac.

Only three things ever leave your Mac, and each is something you start:

- **Asking a question.** Ask sends the model you pick (Claude through Claude Code, or a model through Codex) what it looks up to answer you: the text with secrets such as passwords and keys blanked out, and any photo it looks at as it is. Before a company's model is used for the first time, the app shows what that company keeps and how to turn off training on your data, and waits for you. You can also pick a model that runs on your Mac (through Codex, with Ollama or LM Studio).
- **An export the app doesn't know yet.** It can ask Claude how that export is laid out. The request holds file and field names, plus one example value per field only if you tick that box, and you see it and approve it before it's sent. Without the Claude Code CLI or an API key, you copy the request into any Claude chat yourself.
- **Requesting your data.** Download pages open in your own browser, signed in as you, like any other site you visit.

There's no analytics, no account, no update check and no telemetry.

## What it changes on your Mac

It reads, and changes only what you tell it to:

- **Downloads you're expecting** move from `~/Downloads` into `corpus/imports/` when they arrive. Files on another drive are copied, not moved. Anything you weren't expecting waits for a yes.
- **Two settings, only if you click Keep:** Claude Code's `cleanupPeriodDays` in `~/.claude/settings.json`, so it stops deleting transcripts after 30 days, and a few lines at the end of `~/.zshrc`, marked `# Added by Homecoming`, so Terminal keeps every command and when it ran.
- **Settings in other apps:** Messages, Safari, your iPhone and Google can delete old history. For each one, the app shows you how to keep it, and you change it there yourself.

## What to expect

- **It takes a few days, not an afternoon.** What's on your Mac is read first, while you request the rest. Some services take hours to prepare your download and others take weeks (Spotify can take 30 days), and some links expire within days. The app tracks each one, reminds you, and picks the file up from Downloads.
- **Your iPhone** is read from an encrypted backup on this Mac, made in Finder. The app walks you through it. You'll need the backup's password, and making the backup can take a while.
- **Free space:** the app warns you below 20 GB. A big Google or Photos download can be tens of gigabytes.

## Install and run

### What you need

- **A Mac with Apple silicon** (M1 or later). On an Intel Mac the iPhone backup step can't run.
- **Python 3.14 from [python.org](https://www.python.org/downloads/macos/).** The iPhone backup step uses packages that come with Homecoming and are built for Python 3.14 only. The app looks for python.org's Python first (`/usr/local/bin/python3`).
- **Node.js** ([nodejs.org](https://nodejs.org/)). Homecoming was built and tested with Node 24.
- **git.** The first time you type `git` in Terminal, macOS offers to install it.
- **Optional: the Claude Code or Codex CLI**, signed in, to ask questions about your data.

### Install and start

Clone it somewhere outside Desktop and Documents. If iCloud syncs those folders, everything you collect would be uploaded to iCloud.

```bash
git clone https://github.com/benshi34/homecoming.git ~/Developer/homecoming
cd ~/Developer/homecoming
/usr/local/bin/python3 -m pip install cryptography pypdf
cd desktop
npm ci
npm start
```

`npm ci` installs exactly the versions listed in `desktop/package-lock.json` and checks each download against its recorded hash. Setup downloads those packages and the two Python packages, and the first `npm start` downloads Electron itself (about 300 MB unpacked), checked against the checksums that come with it. After that, nothing is downloaded.

To use a different Python 3.14, start the app with `UMP_PYTHON=/path/to/python3 npm start`.

### Full Disk Access goes to Terminal

macOS keeps Messages, Mail, Photos, Notes and call history behind Full Disk Access. When you run from source, macOS gives that permission to the app that started Homecoming (usually Terminal), not to Homecoming itself. That means every command you run in Terminal can read those files too.

1. When the app asks, open System Settings → Privacy & Security → Full Disk Access and turn on Terminal.
2. Quit and reopen Terminal (macOS offers to), then run `npm start` again from `desktop/`.
3. When you're done collecting, turn Terminal off in the same list.

### Updating

```bash
cd ~/Developer/homecoming
git pull
cd desktop
npm ci
npm start
```

## Reporting a problem

Open an issue on this repository. Say:

- what you clicked, what you expected, and what happened instead;
- which source it was (Messages, Google, your iPhone...);
- your macOS version, and Intel or Apple silicon.

Each source's detail pane has a **Progress** log, and Terminal shows the app's output; both help. **Read them before you paste.** They can hold file names, account names and bits of your data. Never attach an export or anything from `corpus/`. If something about your data looks wrong, describe its shape ("a group chat shows up twice"), not who's in it.

## Removing everything

1. Quit Homecoming.
2. Delete `corpus/` in the folder you installed it in (or the whole folder). That's everything it collected, including the exports it filed.
3. Delete `~/Library/Application Support/Homecoming`: its progress, settings and Ask conversations.
4. Turn Terminal off in System Settings → Privacy & Security → Full Disk Access.
5. If you clicked Keep for them: remove the lines under `# Added by Homecoming` at the end of `~/.zshrc`, and `cleanupPeriodDays` from `~/.claude/settings.json`.

## Known limits

- **It's a development build**, run from source. A signed app you can download is planned.
- **Apple silicon and Python 3.14 only**, for the iPhone step.
- **It refreshes only while it's open.** Leave it open while you wait for downloads, or open it every day or two.
- **It doesn't fill in export forms for you.** Download pages open in your browser; the steps are in the app.

How it all works: [desktop/README.md](desktop/README.md).
