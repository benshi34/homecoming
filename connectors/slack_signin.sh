#!/bin/zsh
# Signs slackdump into every Slack workspace your everyday Chrome is signed into, using that browser's session, for
# workspaces whose sign-in Google won't allow in slackdump's own browser. Run it yourself: it reads your Slack session
# from the clipboard, checks each paste, and clears the clipboard when it's done. slackdump keeps what it needs,
# encrypted, in ~/Library/Caches/slackdump; then slackdump export -member-only -workspace <domain> -o <domain>.zip, and drop the zip on the Slack page.
#
#     zsh connectors/slack_signin.sh            every workspace
#     zsh connectors/slack_signin.sh abstract   only those whose name or domain contains a word given
set -u
SNIPPET='copy(Object.values(JSON.parse(localStorage.localConfig_v2).teams).map(t => [t.token, t.domain, t.name].join("\t")).join("\n"))'
wait_enter() { print -n -- "$1  [return]"; read -r _; }

print "1. Chrome: open https://app.slack.com/client and let it load. Open DevTools (Option-Command-I)."
print "   Application > Cookies > https://app.slack.com: copy the value of the cookie named d."
wait_enter "   Copied?"
D=$(pbpaste)
if [[ $D != xoxd-* || ${#D} -gt 1000 ]]; then
  print "   That isn't the d cookie (it starts with xoxd- and is a few hundred characters). Copy it and run this again."
  exit 1
fi

print -rn -- "$SNIPPET" | pbcopy
print "2. The console line is on your clipboard now. In that same DevTools, Console tab: paste it, return."
print "   (Chrome may ask you to type 'allow pasting' first.)"
wait_enter "   Done?"
TEAMS=$(pbpaste)
print -rn -- "" | pbcopy  # your session doesn't sit on the clipboard
if [[ $TEAMS != xox* ]]; then
  print "   The clipboard doesn't have the workspaces. Was the console on the app.slack.com tab? Run this again."
  exit 1
fi

added=0 failed=0
while IFS=$'\t' read -r token domain name; do
  [[ -n $token && -n $domain ]] || continue
  if (( $# )); then
    hit=0; for w in "$@"; do [[ ${domain:l} == *${w:l}* || ${name:l} == *${w:l}* ]] && hit=1; done
    (( hit )) || continue
  fi
  if slackdump workspace new -token "$token" -cookie "$D" "$domain" >/dev/null 2>&1; then
    print "   + $name ($domain)"; (( added++ ))
  else
    print "   x $name ($domain): slackdump couldn't sign in"; (( failed++ ))
  fi
done <<< "$TEAMS"
unset D TEAMS
print "$added signed in, $failed didn't. slackdump workspace list shows them."
print "Now sign out of Slack in Chrome and back in if this session was ever pasted anywhere else."
