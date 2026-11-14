# Slack

Workspace messages, threads and reactions. An admin can export a workspace; anyone can export what they see with slackdump.

1. Without admin: install slackdump (brew install slackdump), sign in with slackdump workspace new <workspace>, then run slackdump export -member-only -o slack.zip.

2. Signed in to Slack with Google? Google turns slackdump's browser away. Sign it in with your own browser's session instead: zsh connectors/slack_signin.sh, which walks you through two pastes from Chrome and signs in every workspace at once.
   By hand: in Chrome on app.slack.com, DevTools, Application, Cookies: the d cookie (xoxd-...). Each workspace's token is in localStorage.localConfig_v2 (teams, token). Then slackdump workspace new -token <xoxc-...> -cookie <xoxd-...> <workspace>.

3. Or ask a workspace admin for an export (Settings & administration → Workspace settings → Import/Export data).

4. Drop the export zip here.
