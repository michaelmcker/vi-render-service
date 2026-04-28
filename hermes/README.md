# Hermes

Personal sales-assistant daemon for Nikki (head of sales, Vertical Impression).
Runs on her dedicated Mac at home. Watches Gmail + Slack, classifies importance,
pushes alerts and one-tap draft replies to Telegram. All LLM work goes through
her Claude Code subscription via `claude -p` — no API keys, no extra spend.

## Architecture in one paragraph

A Python daemon (`app.daemon`) polls Gmail and Slack, classifies each new item
with `claude -p`, and sends Telegram alerts for anything that matters. A separate
bot process (`app.bot`) listens to Telegram for her commands and inline-button
taps; "Draft reply" buttons run another `claude -p` pass and stage a draft she
approves with one tap. Both processes run under `launchd` and survive reboots.
The Mac stays behind the home NAT — every connection is outbound. Chrome Remote
Desktop is the fallback if she ever needs to redo OAuth from the road.

## What's wired up in v1

| Capability | Status |
|---|---|
| Gmail triage → Telegram alerts | Working |
| Gmail draft replies (button-triggered) | Working |
| Calendar read (briefing context) | Working |
| Slack mentions/DMs/monitored channels → Telegram alerts | Working |
| Slack reply drafts posted as her | Working |
| Morning briefing | Working |
| Telegram commands: `/health`, `/today`, `/vip`, `/watch`, `/quiet` | Working |
| Drive / Docs / Sheets | Stub (extra OAuth required when wired up) |
| Apollo direct API | Stub |
| Salesforce via Zapier | Stub |
| Granola transcripts | Stub |
| Web research (Playwright) | Stub |
| Claude Code slash commands (`/research-account`, `/fill-spreadsheet`, `/win-loss`) | Stub |

## Install

Run on Nikki's Mac, signed in as her user. Steps 1–4 are one-time.

### 1. System prerequisites

```bash
# Homebrew (skip if already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install python@3.11
# Claude Code: install per https://docs.claude.com/en/docs/claude-code  then `claude login`
```

Confirm `claude -p "hi"` returns a response from the Mac terminal under her user.

### 2. Project layout

```bash
git clone <this-repo> ~/hermes-source
mkdir -p ~/hermes
cp -r ~/hermes-source/hermes/* ~/hermes/
cd ~/hermes
python3.11 -m venv .venv
.venv/bin/pip install -e .
mkdir -p logs output
cp .env.example .env
cp config/importance.example.yaml config/importance.yaml
```

### 3. Telegram

1. On her phone, open Telegram → search for **@BotFather** → `/newbot` → name it
   `Hermes` (or anything). Copy the bot token into `.env` as `TELEGRAM_BOT_TOKEN`.
2. Have her open a chat with the new bot and send `/start`.
3. From the Mac:
   ```bash
   curl -s "https://api.telegram.org/bot$(grep TELEGRAM_BOT_TOKEN .env | cut -d= -f2)/getUpdates"
   ```
   Find `"chat":{"id":<NUMBER>}` and put `<NUMBER>` in `.env` as `TELEGRAM_CHAT_ID`.
4. Test: `python -m app.oauth_setup test-telegram` — she should see a ping.

### 4. Google (Gmail + Calendar)

1. **Cloud Console** (`console.cloud.google.com`):
   - New project: `hermes-nikki`.
   - APIs & Services → Library → enable: Gmail API, Google Calendar API.
   - APIs & Services → OAuth consent screen → User Type **Internal** → fill app
     name + support email. (Internal requires VI to be on Google Workspace.)
   - Add the scopes listed in `app/google/auth.py` (gmail.readonly,
     gmail.compose, calendar.readonly, openid, userinfo.email).
   - Credentials → Create → OAuth client ID → **Desktop app** → Download JSON.
   - Move the JSON to `~/hermes/secrets/google_client.json`.
2. Run the OAuth flow on the Mac:
   ```bash
   cd ~/hermes && .venv/bin/python -m app.oauth_setup google
   ```
   Sign in as `nikki@verticalimpression.com`, accept consent, refresh token
   saves to `secrets/google_token.json`.

**Why these scopes** — `gmail.readonly + gmail.compose` permits read and draft
creation only. The Google API rejects any call to delete, trash, or send mail
at the edge — even if the daemon's code were buggy, those operations are
impossible. `calendar.readonly` is read-only for the same reason. Drive, Docs,
and Sheets are intentionally NOT requested in v1.

### 5. Slack

1. Create the app:
   - `api.slack.com/apps` → **Create New App** → **From manifest** → pick the
     VI workspace → paste the contents of `manifests/slack_app_manifest.yaml`
     → **Create**.
   - Settings → Basic Information → **App-Level Tokens** → Generate, scope
     `connections:write`. Copy → `.env` as `SLACK_APP_TOKEN`.
   - Copy the **Signing Secret** → `.env` as `SLACK_SIGNING_SECRET`.
   - Click **Install to Workspace** → consent. Workspace admin will need to
     approve. Once installed:
     - Bot User OAuth Token (`xoxb-…`) → `SLACK_BOT_TOKEN`
     - User OAuth Token   (`xoxp-…`) → `SLACK_USER_TOKEN`
   - Look up Nikki's user ID: in Slack, click her profile → ⋯ → **Copy member ID**.
     Put it in `.env` as `SLACK_NIKKI_USER_ID`.
2. In any channel she wants Hermes to monitor, type `/invite @Hermes`.
3. Test: `python -m app.oauth_setup test-slack`.

### 6. Apollo & Salesforce-via-Zapier (optional in v1)

- Apollo > Settings > Integrations > API → Generate. Paste into `.env` as
  `APOLLO_API_KEY`. (Stub — not wired into v1 paths yet.)
- Zapier: create a "Catch Hook" Zap that posts to the right Salesforce action.
  Paste the catch-hook URL into `.env` as `ZAPIER_SALESFORCE_WEBHOOK`. Also set
  `ZAPIER_SHARED_SECRET` to a random string and configure the Zap to verify
  the `X-Hermes-Sig` header against it. (Stub.)

### 7. Run as services

```bash
# Copy plists to LaunchAgents (per-user, runs whenever she's logged in)
cp launchd/com.vi.hermes.daemon.plist ~/Library/LaunchAgents/
cp launchd/com.vi.hermes.bot.plist ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.vi.hermes.daemon.plist
launchctl load ~/Library/LaunchAgents/com.vi.hermes.bot.plist

# Watch logs:
tail -f logs/daemon.err.log logs/bot.err.log
```

To unload:
```bash
launchctl unload ~/Library/LaunchAgents/com.vi.hermes.daemon.plist
launchctl unload ~/Library/LaunchAgents/com.vi.hermes.bot.plist
```

### 8. Mac hardening

- Turn on FileVault: System Settings → Privacy & Security → FileVault.
- Tighten screen lock: System Settings → Lock Screen → "Require password
  immediately after sleep" (or 0 minutes).
- Don't share the user account.
- The Mac stays at home; nothing routes inbound to it.

## Day-to-day

She doesn't need a terminal for normal use. Everything is Telegram:

- Urgent emails / Slack messages arrive as pings with `[Draft reply] [Snooze]
  [Mute thread]` buttons.
- 7am daily briefing message lists everything for the day.
- `/health` — connection status.
- `/today` — what's flagged so far.
- `/vip add ceo@acme.com` — add a sender to the VIP list.
- `/watch #deals-pipeline` — start monitoring a Slack channel.
- `/quiet 2h` — mute non-urgent pings for 2 hours.

For drafting: she taps **Draft reply**, Hermes shows a preview, she taps
**✅ Save to Drafts** (email) or **✅ Post in Slack** (slack). Email replies
land in her Gmail Drafts folder — she opens Gmail and sends manually. Slack
replies post as her on tap (since Slack has no drafts equivalent).

## When something breaks while she's traveling

The Mac is at home. If a token genuinely needs reauth (rare — Google refresh
tokens last years), use **Chrome Remote Desktop** from her phone:
1. `remotedesktop.google.com` → tap her Mac.
2. Open Terminal → `cd ~/hermes && .venv/bin/python -m app.oauth_setup google`.
3. Complete the consent in the Mac's browser (which she's controlling remotely).
4. Done — daemon picks up the new token automatically.

For most failures, `/health` in Telegram tells her exactly what's broken.

## Project layout

```
hermes/
├── README.md                  ← this file
├── pyproject.toml
├── .env.example
├── config/
│   └── importance.example.yaml
├── prompts/                   ← claude -p system prompts
├── secrets/                   ← OAuth tokens, gitignored
├── manifests/
│   └── slack_app_manifest.yaml
├── launchd/                   ← per-user services
├── cli/                       ← Claude Code slash commands
└── app/                       ← Python package
    ├── daemon.py              ← always-on watcher
    ├── bot.py                 ← Telegram bot
    ├── handlers.py            ← bot command + button handlers
    ├── classify.py            ← email triage glue
    ├── notify.py              ← outbound Telegram
    ├── llm.py                 ← claude -p wrapper
    ├── state.py               ← sqlite (seen ids, drafts, snoozes)
    ├── config.py              ← env + importance.yaml loader
    ├── oauth_setup.py         ← one-time OAuth + connectivity tests
    ├── google/                ← gmail (read+drafts), calendar (read), stubs
    ├── slack/                 ← events, DMs, actions, triage
    ├── apollo.py              ← stub
    ├── salesforce.py          ← stub (Zapier route)
    ├── granola.py             ← stub
    └── research.py            ← stub (local Playwright)
```

## Security posture

- Refresh tokens (`secrets/google_token.json`, Slack tokens in `.env`) are the
  long-term credentials. Treat the Mac like a laptop holding her email
  password — FileVault, locked screen, no shared user.
- All daemon connections are outbound. Nothing inbound, no public URL,
  no port forwarding, no tunnel.
- Gmail scopes block delete/trash/send at the API edge.
- `app/google/gmail.py::send` is a tripwire that raises if any future code path
  ever tries to send mail.
- Telegram bot is gated to `TELEGRAM_CHAT_ID` only — messages from any other
  chat are ignored.
- Slack user token = full impersonation. Same risk profile as her Slack
  password.
