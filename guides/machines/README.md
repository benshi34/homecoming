# Your other machines

Homecoming can read the same sources from your other Macs and Linux machines (a Mac mini, a cloud workstation, a
server, a Lima or OrbStack VM on this Mac) and keep them beside this Mac's, each marked with the machine it came from.
It's off until you turn it on, because it means connecting to those machines over ssh.

## Turn it on

In Homecoming, Settings > Network, turn on **Other machines**. Each machine found is listed under it with its own switch.

- Your own Tailscale machines and this Mac's running VMs are found by themselves and switched on.
- A machine that's only in your ssh config (`~/.ssh/config`) is listed switched off. Turn it on to read it.
- A Tailscale machine shared with you, or a coworker's on a work network, is never contacted.

Opening Settings doesn't contact any machine. Only a read does, or Check Again.

## Get each machine ready

1. **Remote Login.** On a Mac: System Settings > General > Sharing, turn on Remote Login. On Linux, the ssh server is
   usually on already.

2. **Sign in with a key.** Homecoming signs in without asking, so a password or a phone prompt won't work. From this Mac:

   ```sh
   ssh-keygen -t ed25519        # once, if you don't have a key yet
   ssh-copy-id you@that-machine
   ssh you@that-machine true    # should return without asking for anything
   ```

   Tailscale SSH works too, if you use it.

3. **python3.** Linux has it. On a Mac without it, run `xcode-select --install` there.

4. **Full Disk Access, on a Mac.** macOS keeps Messages, Mail, Safari and external drives from ssh until Remote Login
   is given Full Disk Access. Without it, a read gets "operation not permitted", and the machine's row in Settings says
   what it couldn't read.
   - macOS 13 (Ventura) and later: System Settings > General > Sharing, click (i) next to Remote Login, and turn on
     **Allow full disk access for remote users**. It asks for that Mac's password.
   - Before macOS 13: System Preferences > Security & Privacy > Privacy > Full Disk Access, click the lock, and turn on
     `sshd-keygen-wrapper`. If it isn't listed, click +, press Command-Shift-G, and choose
     `/usr/libexec/sshd-keygen-wrapper`.

   Then choose **Check Again** on the machine's row. It makes one ssh call and reads nothing.

## What happens on the other machine

Each read is one ssh call. It sends Homecoming's readers (no tests, no app) to a new temporary folder there and runs
them with that machine's python3. They read in place, so no copies of its databases are made on its disk. Then the
results come back to this Mac, and the folder is removed.

Your setting for which folders' coding sessions to leave out (`ai_coding.json`) goes along, so that machine leaves out
the same folders. Your network settings don't go, and nothing there goes online.

On Linux, the readers cover agent sessions, terminal history, git commits, documents and your setup. The rest are Mac apps.

## Turn it off

Turn off a machine's switch to stop reading it, or Other machines to stop reading all of them. Turning off **Use the
internet** stops it too. What was already read stays in your library.
