# Hermes — Droplet Pivot Plan

## Goal

Move the Hermes runtime from her Mac to a DigitalOcean droplet so the
**operator** (technical user) can manage it remotely. Nikki stays
non-technical: her interface remains Telegram + a small mobile-friendly
web UI for the rare moments when she has to sign into something.

This document is the canonical plan. SAFETY.md remains the canonical
safety policy — both win over conflicting code. If they diverge, fix the
code.

## Security invariants — non-negotiable

These are the rules every commit on this pivot must preserve. Enforced
at multiple layers (network, auth, code, prompt) so no single mistake
breaks them.

1. **Telegram allowlist.** The bot accepts commands and inline taps ONLY
   from chat IDs listed in `TELEGRAM_AUTHORIZED_CHAT_IDS` (Nikki +
   operator). Every other chat is silently ignored — no error, no echo.

2. **Web UI auth at the edge.** The droplet's web UI sits behind
   **Cloudflare Access** with a policy allowing only Nikki's email and
   the operator's email. Cloudflare refuses unauthenticated traffic at
   its edge — Hermes itself never sees it. Zero auth code in our
   codebase; no risk of bypass via app bug.

3. **No exposed Slack endpoints.** Slack integration is bot+user OAuth
   tokens only. Communication is **outbound only** — Socket Mode is an
   outbound WebSocket, all API calls are outbound HTTPS. Hermes does NOT
   expose any inbound webhook for Slack, ever. The Slack signing secret
   in `.env` is unused (kept only for future opt-in).

4. **Google destructive-op block.** `app/google/_safety.py::GoogleSafeHttp`
   refuses any URI matching `/messages/send`, `/drafts/send`, `/trash`,
   `/untrash`, `/batchDelete`, `/batchModify`, plus `DELETE` against
   `/messages/`, `/threads/`, `/drive/v[23]/files/`. Active on every
   Google API client (Gmail, Calendar, Docs, Sheets, Drive). Unchanged
   by the droplet pivot.

5. **Drafts only, never sends.** Gmail replies land in her Drafts —
   she opens Gmail and sends manually. Slack replies require an explicit
   Telegram tap before the user-token posts. No auto-send anywhere.

6. **No-draft topics.** `hr` and `personal` categories cause Hermes to
   refuse drafting even if she taps Draft. Per-person `no_draft` flag
   does the same.

7. **Droplet attack surface.**
   - Inbound ports: `22` (SSH, key-only, root login disabled, fail2ban) and
     **none other** — port 443 is served by `cloudflared` outbound to the
     Cloudflare edge, no listener bound to a public interface.
   - Daemon runs as non-root user `hermes`. Web UI binds to `127.0.0.1`
     only; cloudflared brokers external traffic to it.
   - Secrets at `chmod 600`, owned by `hermes`. `.env` not world-readable.

8. **No public LinkedIn or social endpoints.** LinkedIn scraping is
   outbound-only Playwright. Buffer is outbound API. No webhooks accepted.

9. **Backups never delete.** Drive uploads accumulate; cleanup is manual
   only. Same no-delete policy as the Mac path.

10. **Audit trail.** Every triage, draft, alert, and (future) confirmed
    destructive op is recorded in `state.sqlite`. SQLite + profiles +
    brand are backed up to her Drive twice daily. Operator-readable on
    request via SSH.

## Architecture (after pivot)

### Network topology

```
                  Cloudflare Access (allowlist: 2 emails)
                              │
                              ▼
                   Cloudflare Tunnel (cloudflared)
                              │
                              ▼
                   Droplet (DigitalOcean, Ubuntu)
                   ├─ Public ports: 22 (SSH key only)
                   ├─ cloudflared service → 127.0.0.1:8080 (web UI)
                   ├─ hermes-daemon.service (Telegram out, Slack out, ...)
                   ├─ hermes-bot.service     (Telegram long-poll, out only)
                   └─ hermes-web.service     (FastAPI on 127.0.0.1:8080)
```

No public IP exposure on the droplet other than SSH. `cloudflared` is
outbound; Cloudflare's edge is the only path inbound.

### Services (systemd)

| Unit | What | User | Network |
|---|---|---|---|
| `hermes-daemon.service` | watcher: Gmail + Slack + LinkedIn + briefing + backup + thought-leadership ticks | `hermes` | outbound only |
| `hermes-bot.service` | Telegram long-poll, command dispatch, draft approvals | `hermes` | outbound only |
| `hermes-web.service` | FastAPI on `127.0.0.1:8080` (status, OAuth, LinkedIn refresh, fallback drafts UI) | `hermes` | localhost only |
| `cloudflared.service` | tunnel to Cloudflare edge | dedicated | outbound only |

Each service supervises independently — a bot crash can't take down the
watcher.

### LinkedIn

- Same Playwright + secondary-account approach.
- Routed through a residential proxy (Bright Data / Smartproxy / similar)
  configured via `.env`. Cost: ~$25–50/mo for her volume.
- Initial cookie load done once by the operator via SSH +
  `python -m app.oauth_setup linkedin-cookies` (which runs Playwright
  headed on the droplet via Xvfb or, simpler, the operator runs it on a
  laptop and SCPs the cookie file).
- Re-login when LinkedIn invalidates: she taps a Telegram button →
  operator gets a notification → operator handles via SSH.

### Granola

Confirmed: pulling via Granola API instead of filesystem tail. Module
goes from stub to working in **Phase 2**. Auth pattern depends on what
Granola exposes (OAuth or API key) — settled in that phase.

## Two-user model

Two distinct chat IDs in `.env`:

- `TELEGRAM_PRIMARY_CHAT_ID` — Nikki. All briefings, draft pings, urgent
  alerts go here.
- `TELEGRAM_AUTHORIZED_CHAT_IDS` — comma-separated allowlist (Nikki +
  operator). Either can issue commands; messages from any other chat are
  ignored.

System pings (token expired, daemon crashed, cookie refresh needed)
broadcast to ALL authorized IDs, so the operator sees the operational
state without spam from Nikki's actual workflow.

Privacy: Nikki's mail/Slack content is never broadcast to the operator's
chat. Operator only sees:

- System health pings
- Errors / failures
- Anything the operator explicitly fetches via a command

Logs and SQLite stay on the droplet — the operator reads via SSH when
needed. Nothing is forwarded to a separate audit channel.

## Phases (one commit each — review-stoppable)

### Phase 1 — This commit
- `PLAN.md` (this file)
- Multi-user Telegram: `TELEGRAM_PRIMARY_CHAT_ID` + `TELEGRAM_AUTHORIZED_CHAT_IDS`
- `notify.send_text` routes alerts vs system pings correctly
- `handlers._is_authorized` replaces `_is_nikki`
- systemd unit files for `hermes-daemon` / `hermes-bot` / `hermes-web`
- (No code regressions — daemon/bot still work on the Mac under launchd)

### Phase 2 — Granola via API
- `app/granola.py` — real client (poll or webhook depending on what their API offers)
- `.env` — `GRANOLA_API_KEY` (and base URL if needed)
- Daemon hook: poll Granola periodically, queue follow-up suggestions

### Phase 3 — Web UI scaffold
- `app/web/` — FastAPI app
- Routes: `/` (status), `/connect/google`, `/connect/slack`,
  `/linkedin/refresh`, `/drafts` (fallback), `/logs` (tail)
- Mobile-first templates (Jinja + Tailwind via CDN)
- Bound to `127.0.0.1:8080` only

### Phase 4 — Web-app OAuth client
- Google OAuth client type swaps from "Desktop app" → "Web application"
- Stable public callback URL: `https://hermes.<domain>/oauth/google/callback`
- `app/google/auth.py` — accept the new flow; `app/oauth_setup.py google`
  delegates to the web UI rather than a local browser
- Slack install URL similarly served from the web UI

### Phase 5 — Cloudflare Access + tunnel docs
- README section: "Cloudflare zone setup", "Access policy creation"
- Sample `cloudflared` config
- Confirms: only `nikki@vi…` and `<operator>@vi…` can reach the URL

### Phase 6 — Residential proxy slot
- `app/linkedin/playwright_scanner.py` — accept `PROXY_SERVER`,
  `PROXY_USERNAME`, `PROXY_PASSWORD` from `.env`, pass to Playwright's
  `proxy=` arg
- Doc: which providers (Bright Data preferred) and the cost model

### Phase 7 — Droplet setup script
- `setup/install_droplet.sh` — idempotent provisioning:
  - Create `hermes` user
  - Install Python, Playwright deps, Codex CLI, Claude Code, cloudflared
  - Clone or copy the repo into `/opt/hermes`
  - Create `.venv`, install requirements
  - Drop systemd units, enable + start
  - Print the next manual step (env vars, OAuth seeding)

### Phase 8 — Canonical README
- Replace current README with a single shareable doc covering:
  - What Hermes is, what it does, what it can't
  - The full droplet setup runbook
  - Day-to-day usage from her side (Telegram + occasional /portal link)
  - Troubleshooting + when to escalate to the operator
- Sized as one MD file the operator can share with her or her IT.

## Open questions to resolve as we go

| Question | Default if unresolved |
|---|---|
| Cloudflare zone — does VI already own a domain we can route through? | Use a free `*.workers.dev` subdomain via Cloudflare Worker stub if needed. |
| Granola API auth model | Stub until we see their docs; Phase 2 unblocks. |
| Buffer for LinkedIn posting — still in scope? | Yes by default; trivial to disable. |
| Operator visibility on her drafts | Default: not visible to operator unless explicitly fetched. Override per-flag if you want a copy. |
| Residential proxy provider | Default: Bright Data (most reputable, "LinkedIn-clean" pools). |

## Cost (running, monthly)

| Item | Estimate |
|---|---|
| DigitalOcean droplet (2GB RAM Basic) | $12 |
| Residential proxy (low-volume Bright Data) | $25–50 |
| Cloudflare (Free tier covers Tunnel + Access) | $0 |
| Buffer (Essentials plan, LinkedIn API access) | $6 |
| **Total** | **~$45–70/mo** |

Apollo + ChatGPT + Claude Code + Slack + Google Workspace continue as
existing subscriptions; no incremental charge from the pivot.
