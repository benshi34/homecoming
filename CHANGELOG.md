# What's new in Homecoming

Each version, newest first. The first time Homecoming opens after an update, it shows what's new since the version you had, from the copy of this file inside the app. Once a day, Homecoming reads this file on GitHub to see whether there's a newer version.

To update: **Update**, when Homecoming says there's a new version. Or in Terminal:

```bash
cd ~/Developer/homecoming/desktop
npm run update
```

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
