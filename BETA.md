# Homecoming beta: what to try

Thanks for testing. This is the order that finds the most problems. When something goes wrong, [report it](README.md#reporting-a-problem) and keep going.

## Day 1: set up (about an hour, most of it waiting)

1. **Install it** from the [README](README.md#install-and-run), word for word. If any step fails or isn't clear, that's the first thing to report: copy what Terminal printed.
2. **Go through the Setup Assistant** from the welcome page to the end. Turn on Full Disk Access when it asks.
3. **Request at least three exports:** Google, plus the two services you use most. The app opens each download page in your browser and shows the steps beside it. Note any step that didn't match what you saw.
4. **Your iPhone**, if you have one: make the encrypted backup when the app asks. Say how long it took.
5. **"Which of these are you?"**: check that the names, emails and usernames it found are really yours.

## While you wait for exports (a few days)

- **Leave the app open**, or open it every day or two. It refreshes only while it's open.
- **When an export's email arrives,** download the file and leave it in Downloads. The app should pick it up, file it, and read it. Tell us if it didn't, or if it asked about a file it should have recognized.
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
- Any service you use that isn't in All Services, or whose export didn't work.
- Anything that felt like it was doing more with your data than you expected.

## For whoever runs the beta: a clean-Mac install

Do this first. This Mac already has everything installed, so it can't show what a new person's Mac is missing.

1. Make a fresh macOS user: System Settings → Users & Groups → Add User. Log in as them. Skip setting up iCloud, and use your own test accounts.
2. Follow the README's [Install and run](README.md#install-and-run) section exactly, with nothing installed beforehand. Write down:
   - every step that failed or needed something the README didn't mention;
   - how long each step took (the Python install, `npm ci`, the first `npm start`);
   - what macOS asked along the way, such as installing developer tools or allowing Full Disk Access.
3. Check that it opens on the welcome page, and that a Mac source (Notes or Safari works on a new account) reads after you turn on Full Disk Access for Terminal.
4. Remove everything as the README's [Removing everything](README.md#removing-everything) says, then delete the test user.
