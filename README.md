# Homecoming

Google, Instagram, your phone, your bank: every service you use keeps a record of your life. But each keeps it in its own place and its own format, behind a download page that's hard to find, in files that are hard to read.

Homecoming is a Mac app that brings it home. It gathers your data into one library on your Mac, puts it in order, and lets you explore it and ask it questions:

1. **Request your data.** It finds the accounts you use, opens each one's download page with the steps, and tells you when your data is ready. What's on your Mac and your iPhone is read right away.
2. **Bring it home.** Each download is recognized by what's inside, filed, and read into one organized library.
3. **Explore it.** Browse what Homecoming makes from your data (your year, your people, your places, the rhythm of your days), or ask questions in plain words and get answers that point to the messages and photos they came from.

**This is a beta.** Thank you for trying it. [How to tell us what went wrong](#reporting-a-problem).

## Your data, and where it goes

Everything Homecoming collects stays on your Mac, in your library: the `Homecoming` folder in your home folder (`~/Homecoming`) if you use the app, or `corpus/` inside the folder you run it from if you run it from source. The decrypted copy of your iPhone backup, and what iLEAPP reads from it, go in `~/Library/Application Support/q1_user_model`, where iCloud never syncs them. Nothing is uploaded, and if your library would sync to iCloud, the app says so and offers to keep it on this Mac.

Only three things ever leave your Mac, and each is something you start:

- **Asking a question.** Ask sends the model you pick (Claude through Claude Code, or a model through Codex) what it looks up to answer you: the text with secrets such as passwords and keys blanked out, and any photo it looks at as it is. Before a company's model is used for the first time, the app shows what that company keeps and how to turn off training on your data, and waits for you. You can also pick a model that runs on your Mac (through Codex, with Ollama or LM Studio).
- **An export the app doesn't know yet.** It can ask Claude how that export is laid out. The request holds file and field names, plus one example value per field only if you tick that box, and you see it and approve it before it's sent. Without the Claude Code CLI or an API key, you copy the request into any Claude chat yourself.
- **Requesting your data.** Download pages open in your own browser, signed in as you, like any other site you visit.

There's no analytics, no account, no update check and no telemetry.

## What it changes on your Mac

It reads, and changes only what you tell it to:

- **Apple Mail and notifications, read only:** while an export is on its way, the app looks for the service's "your data is ready" email in Apple Mail and for its notification, on this Mac. Nothing else in them is kept.
- **Downloads you're expecting** move from `~/Downloads` into your library's `imports/` folder when they arrive. Files on another drive are copied, not moved. Anything you weren't expecting waits for a yes.
- **Two settings, only if you click Keep:** Claude Code's `cleanupPeriodDays` in `~/.claude/settings.json`, so it stops deleting transcripts after 30 days, and a few lines at the end of `~/.zshrc`, marked `# Added by Homecoming`, so Terminal keeps every command and when it ran.
- **Settings in other apps:** Messages, Safari, your iPhone and Google can delete old history. For each one, the app shows you how to keep it, and you change it there yourself.

## What to expect

- **It takes a few days, not an afternoon.** What's on your Mac is read first, while you request the rest. Some services take hours to prepare your download and others take weeks (Spotify can take 30 days), and some links expire within days. The app tracks each one, reminds you, and picks the file up from Downloads.
- **AI, in one place** (optional, off until you turn it on): the Setup Assistant asks once, and the AI page lets you pick the agent (Claude Code or Codex, with your own sign-in, an API key, or a model on this Mac) and turn each use on or off. Everything that uses AI carries a sparkle mark.
- **Do It for Me** (optional): Claude Code requests each export in your Chrome, where you're signed in, and when the service's "your data is ready" email arrives in Apple Mail, it downloads it. It stops only when you need to sign in or enter a code, and carries on when you click Continue.
- **Your iPhone** is read from an encrypted backup on this Mac, made in Finder. The app walks you through it. You'll need the backup's password, and making the backup can take a while.
- **Free space:** the app warns you below 20 GB. A big Google or Photos download can be tens of gigabytes.

## Install and run

### Download the app

You need a Mac with Apple silicon (M1 or later). Everything else comes inside the app.

1. **Download** `Homecoming-0.1.0-arm64.dmg` from the [latest release](https://github.com/benshi34/homecoming/releases/latest). The repository is private, so accept GitHub's invitation email and sign in first.
2. **Open it** and drag Homecoming into Applications.
3. **Open Homecoming** from Applications. macOS says it can't check the app for malicious software, because it isn't signed with an Apple Developer ID yet. Click **Done**. Then open System Settings → Privacy & Security, scroll down to "Homecoming was blocked", click **Open Anyway**, and confirm. You only do this once.
4. **Turn on Full Disk Access** when the app asks: System Settings → Privacy & Security → Full Disk Access → Homecoming. Then quit and reopen it.

To ask questions about your data, you'll also want the Claude Code or Codex CLI, signed in.

**Updating:** download the new `.dmg` and drag Homecoming into Applications again, replacing the old one. Your library and progress stay where they are.

### Run from source

For developers, or if you'd rather build it yourself.

#### What you need

- **A Mac with Apple silicon** (M1 or later). On an Intel Mac the iPhone backup step can't run.
- **Python 3.14 from [python.org](https://www.python.org/downloads/macos/).** The iPhone backup step uses packages that come with Homecoming and are built for Python 3.14 only. The app looks for python.org's Python first (`/usr/local/bin/python3`).
- **Node.js** ([nodejs.org](https://nodejs.org/)). Homecoming was built and tested with Node 24.
- **git**, if you clone rather than download. The first time you type `git` in Terminal, macOS offers to install it.
- **Optional: the Claude Code or Codex CLI**, signed in, to ask questions about your data.

#### Get the code

The repository is private during the beta. Accept the invitation email from GitHub first, then do one of these:

- **Download it.** On the repository page, click the green **Code** button, then **Download ZIP**. Unzip it, rename the folder (`homecoming-main`) to `homecoming`, and move it to a `Developer` folder in your home folder (`~/Developer/homecoming`). To update, download it again the same way.
- **Clone it with git**, which makes updating a one-line command. Sign git in to GitHub first: install the [GitHub CLI](https://cli.github.com/), then run `gh auth login`, then `gh auth setup-git`. Then:

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

`npm ci` installs exactly the versions listed in `desktop/package-lock.json` and checks each download against its recorded hash. Setup downloads those packages and the two Python packages, and the first `npm start` downloads Electron itself (about 300 MB unpacked), checked against the checksums that come with it. After that, nothing is downloaded.

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
git pull
cd desktop
npm ci
npm start
```

If you downloaded the ZIP, download it again and put the new folder in place of the old one. Keep the old folder's `corpus/`: it's everything you've collected. Move it into the new folder first.

## Reporting a problem

Open an issue on this repository. Say:

- what you clicked, what you expected, and what happened instead;
- which source it was (Messages, Google, your iPhone...);
- your macOS version, and Intel or Apple silicon.

Each source's detail pane has a **Progress** log, and when you run from source, Terminal shows the app's output; both help. **Read them before you paste.** They can hold file names, account names and bits of your data. Never attach an export or anything from your library. If something about your data looks wrong, describe its shape ("a group chat shows up twice"), not who's in it.

## Removing everything

1. Quit Homecoming.
2. Delete your library: `~/Homecoming`, or `corpus/` in the folder you ran it from. That's everything it collected, including the exports it filed.
3. Delete `~/Library/Application Support/q1_user_model`: the decrypted copy of your iPhone backup and what iLEAPP read from it.
4. Delete `~/Library/Application Support/Homecoming`: its progress, settings and Ask conversations.
5. Drag Homecoming from Applications to the Trash (or delete the folder you ran it from).
6. Turn Homecoming (or Terminal) off in System Settings → Privacy & Security → Full Disk Access.
7. If you clicked Keep for them: remove the lines under `# Added by Homecoming` at the end of `~/.zshrc`, and `cleanupPeriodDays` from `~/.claude/settings.json`.

## Known limits

- **Not signed with an Apple Developer ID yet**, so macOS asks you to allow it the first time (Open Anyway, above).
- **Apple silicon only**, and when run from source, Python 3.14 only, for the iPhone step.
- **Running from source, it works only while it's open.** The app from the .dmg keeps working in the menu bar when you close its window, and opens at login (Settings → Keep working when the window is closed).
- **Do It for Me needs Claude Code and the Claude in Chrome extension**, even if you pick Codex for the rest: Codex can drive a browser only inside its own app, not when another app runs it. It stops when a service wants you to sign in, enter a code or prove you're not a robot. Without it, export pages open in your browser and the steps are in the app.

How it all works: [desktop/README.md](desktop/README.md).
