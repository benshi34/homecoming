# Homecoming: what to try

Thanks for trying Homecoming. This is the order that finds the most problems. When something goes wrong, [report it](README.md#reporting-a-problem) and keep going.

## Day 1: set up (about an hour, most of it waiting)

1. **Install it** as the [README](README.md#build-it-on-your-mac) says: build it on your Mac. If any step fails or isn't clear, that's the first thing to report.
2. **Go through the Setup Assistant** from the welcome page to the end. Turn on Full Disk Access when it asks.
3. **Request at least three exports:** Google, plus the two services you use most. Try **Do It for Me** on at least one (it needs Claude Code signed in with a paid claude.ai plan, and the Claude in Chrome extension in Chrome, Edge, Brave, Arc, Vivaldi or Opera): say where it got stuck, or picked the wrong options. For the others, the app opens each download page in your browser and shows the steps beside it. Note any step that didn't match what you saw.
4. **Your iPhone**, if you have one: make the encrypted backup when the app asks. Say how long it took.
5. **"Which of these are you?"**: check that the names, emails and usernames it found are really yours.
6. **Your Setup** (under Settings in the sidebar): check what it found. Are your browsers, Mail's accounts and your phone region right? Change one, and say whether the app did what you expected.

## While you wait for exports (a few days)

- **Closing the window is fine:** Homecoming keeps working in the menu bar, and opens at login. (Run from source, leave it open instead.)
- **When an export's email arrives,** the app should notice it in Mail (or in your notifications) and say it's ready. With Do It for Me on, it downloads it by itself; otherwise download the file and leave it in Downloads. Either way the app should pick it up, file it, and read it. Tell us if it didn't, or if it asked about a file it should have recognized.
- **Look at what came in:** each source's numbers and dates. Do they look about right for you?

## Explore and Ask

- **Explore:** open every tile. Is anything wrong, missing or confusing? A person split in two, a trip that wasn't one, a year that looks empty? Describe the shape of it, not who it is.
- **Ask:** ask three questions you already know the answers to. Were the answers right? Do the cited records open, and are they the right ones?

## Try to break it

- Quit the app while it's reading something, then open it again.
- Say no to Full Disk Access at first, then turn it on later.
- Type the wrong iPhone backup password.
- Drop a file the app shouldn't know onto the window.

## What we most want to hear

- Any step where you didn't know what to do next.
- Anything that took much longer than the app said it would.
- Any service you use that isn't in All Sources, or whose export didn't work.
- Anything that felt like it was doing more with your data than you expected.

## Before a release: a clean-Mac install

For whoever makes a release. Do this before each one. This Mac already has everything installed, so it can't show what a new person's Mac is missing.

1. Make a fresh macOS user: System Settings → Users & Groups → Add User. Log in as them. Skip setting up iCloud, and use your own test accounts.
2. Follow the README's [Build it on your Mac](README.md#build-it-on-your-mac) steps exactly, with nothing installed beforehand. Write down:
   - every step that failed or needed something the README didn't mention;
   - how long each step took (installing Node and git, `npm ci`, `npm run install-app`);
   - what macOS asked along the way, such as installing developer tools or allowing Full Disk Access.
3. Check that it opens on the welcome page, and that a Mac source (Notes or Safari works on a new account) reads after you turn on Full Disk Access for Homecoming (or Terminal, from source).
4. Remove everything as the README's [Removing everything](README.md#removing-everything) says, then delete the test user.
