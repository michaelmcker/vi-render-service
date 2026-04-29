#!/usr/bin/env bash
# install_droplet.sh — provision a Hermes droplet from scratch.
#
# Run as root (or via sudo) on a fresh Ubuntu 22.04 / 24.04 droplet.
# Idempotent — safe to re-run if a step fails.
#
# What this does:
#   - System packages (Python, Playwright deps, build tools, etc.)
#   - Creates the unprivileged `hermes` user
#   - Clones the repo into /opt/hermes (or pulls latest if already there)
#   - Builds the Python virtualenv
#   - Installs Playwright Chromium + its OS deps
#   - Drops the systemd units and enables them
#   - Prints the manual next steps the operator still has to do
#
# What this does NOT do:
#   - Sign in to Codex / Claude Code (the operator runs `codex login` /
#     `claude login` as the hermes user manually — these are interactive)
#   - Cloudflare Tunnel setup (separate runbook in CLOUDFLARE.md)
#   - LinkedIn cookie seeding (separate, manual)
#   - .env contents (the operator drops the real .env in place)
#
# Usage:
#   sudo bash install_droplet.sh
#   sudo bash install_droplet.sh --repo https://github.com/your-org/vi-render-service.git --branch claude/hermes-agent-setup-L6Teg

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/michaelmcker/vi-render-service.git}"
REPO_BRANCH="${REPO_BRANCH:-claude/hermes-agent-setup-L6Teg}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/hermes}"
HERMES_USER="${HERMES_USER:-hermes}"

# ── Parse flags ────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)   REPO_URL="$2"; shift 2 ;;
        --branch) REPO_BRANCH="$2"; shift 2 ;;
        --root)   INSTALL_ROOT="$2"; shift 2 ;;
        *) echo "unknown arg: $1"; exit 2 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (try: sudo bash $0)"; exit 1
fi

log() { printf "\n\033[1;32m▸ %s\033[0m\n" "$*"; }

# ── 1. System packages ─────────────────────────────────────────────────
log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    git curl ca-certificates \
    python3.11 python3.11-venv python3-pip \
    build-essential \
    sqlite3 \
    fail2ban \
    tzdata

# Playwright Chromium runtime deps (the playwright `install-deps` command
# below covers most of them; we install the universal subset here too).
apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
    || apt-get install -y --no-install-recommends libasound2

# ── 2. fail2ban basic config (SSH bruteforce defense) ──────────────────
log "Enabling fail2ban for SSH"
systemctl enable --now fail2ban || true

# ── 3. hermes user ─────────────────────────────────────────────────────
log "Creating ${HERMES_USER} user"
if ! id -u "$HERMES_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$HERMES_USER"
fi

# ── 4. /opt/hermes (clone or pull) ─────────────────────────────────────
log "Setting up ${INSTALL_ROOT}"
if [[ ! -d "$INSTALL_ROOT/.git" ]]; then
    if [[ -e "$INSTALL_ROOT" ]]; then
        echo "  ${INSTALL_ROOT} exists but isn't a git repo; aborting"; exit 1
    fi
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_ROOT"
else
    git -C "$INSTALL_ROOT" fetch origin "$REPO_BRANCH"
    git -C "$INSTALL_ROOT" checkout "$REPO_BRANCH"
    git -C "$INSTALL_ROOT" pull --ff-only origin "$REPO_BRANCH"
fi

# We always install from the hermes/ subdirectory of the cloned repo.
APP_ROOT="$INSTALL_ROOT/hermes"
if [[ ! -d "$APP_ROOT" ]]; then
    echo "expected ${APP_ROOT} to exist after clone; aborting"; exit 1
fi

# Common dirs the daemon writes to.
mkdir -p "$APP_ROOT/logs" "$APP_ROOT/secrets"
chmod 700 "$APP_ROOT/secrets"

chown -R "$HERMES_USER:$HERMES_USER" "$INSTALL_ROOT"

# ── 5. Python venv + deps ──────────────────────────────────────────────
log "Building Python venv"
sudo -u "$HERMES_USER" python3.11 -m venv "$APP_ROOT/.venv"
sudo -u "$HERMES_USER" "$APP_ROOT/.venv/bin/pip" install --upgrade pip wheel
sudo -u "$HERMES_USER" "$APP_ROOT/.venv/bin/pip" install -e "$APP_ROOT"

# ── 6. Playwright Chromium ─────────────────────────────────────────────
log "Installing Playwright Chromium"
sudo -u "$HERMES_USER" "$APP_ROOT/.venv/bin/playwright" install chromium
# install-deps needs root; covers the long tail of glibc shared libs.
"$APP_ROOT/.venv/bin/playwright" install-deps chromium || true

# ── 7. .env scaffold (only if missing) ─────────────────────────────────
if [[ ! -f "$APP_ROOT/.env" ]]; then
    log "Writing .env stub from .env.example (REVIEW BEFORE STARTING SERVICES)"
    cp "$APP_ROOT/.env.example" "$APP_ROOT/.env"
    chmod 600 "$APP_ROOT/.env"
    chown "$HERMES_USER:$HERMES_USER" "$APP_ROOT/.env"
    NEEDS_ENV=1
else
    log ".env already present; leaving it alone"
    NEEDS_ENV=0
fi

# ── 8. importance.yaml scaffold ────────────────────────────────────────
if [[ ! -f "$APP_ROOT/config/importance.yaml" ]]; then
    cp "$APP_ROOT/config/importance.example.yaml" "$APP_ROOT/config/importance.yaml"
    chown "$HERMES_USER:$HERMES_USER" "$APP_ROOT/config/importance.yaml"
fi

# ── 9. systemd units ───────────────────────────────────────────────────
log "Installing systemd units"
for unit in hermes-daemon hermes-bot hermes-web; do
    src="$APP_ROOT/systemd/${unit}.service"
    dst="/etc/systemd/system/${unit}.service"
    # Patch WorkingDirectory + paths to match $APP_ROOT.
    sed "s|/opt/hermes|$APP_ROOT|g" "$src" > "$dst"
done
systemctl daemon-reload
# Don't enable+start until the operator has filled in .env and verified
# Codex / Claude / Cloudflare are signed in. The next-steps banner below
# tells them what to do.

# ── 10. Print next steps ───────────────────────────────────────────────
cat <<NEXT


╔══════════════════════════════════════════════════════════════════════╗
║  Hermes droplet provisioned ✓                                        ║
╚══════════════════════════════════════════════════════════════════════╝

Manual next steps (in order):

1.  Sign in to the LLM CLIs as the hermes user:
      sudo -u $HERMES_USER -i
      codex login        # use her ChatGPT account
      claude login       # use her Claude Code subscription
      exit

2.  Edit $APP_ROOT/.env with real secrets:
$( [[ $NEEDS_ENV -eq 1 ]] && echo "      sudo -u $HERMES_USER nano $APP_ROOT/.env" )
    Required at minimum:
      TELEGRAM_BOT_TOKEN, TELEGRAM_PRIMARY_CHAT_ID, TELEGRAM_AUTHORIZED_CHAT_IDS
      SLACK_BOT_TOKEN, SLACK_USER_TOKEN, SLACK_APP_TOKEN, SLACK_NIKKI_USER_ID
      HERMES_PUBLIC_URL (the Cloudflare hostname; once Step 4 is done)
      HERMES_WEB_ALLOWED_EMAILS

3.  Cloudflare Tunnel + Access — follow setup/CLOUDFLARE.md.

4.  Bootstrap Google OAuth — visit https://hermes.<your-zone>/connect/google
    in a browser (signed in to Cloudflare Access).

5.  Seed LinkedIn cookies (if Buffer / scraping is in scope):
      sudo -u $HERMES_USER -i
      cd $APP_ROOT
      .venv/bin/python -m app.oauth_setup linkedin-cookies
      exit

6.  Enable + start services:
      sudo systemctl enable --now hermes-daemon
      sudo systemctl enable --now hermes-bot
      sudo systemctl enable --now hermes-web

7.  Tail logs to confirm:
      sudo journalctl -u hermes-daemon -f
      sudo tail -f $APP_ROOT/logs/*.err.log

8.  Open https://hermes.<your-zone> in a browser. Status page should
    light up green. Send /health from Telegram to confirm the bot is alive.

NEXT
