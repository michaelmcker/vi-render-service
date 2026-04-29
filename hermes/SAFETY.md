# Hermes Safety Policy

This document is the canonical statement of what Hermes can and cannot do
on Nikki's behalf. The code enforces it; this file explains it. If the code
ever drifts from this document, the document wins — fix the code.

## Core rules

1. **Hermes never sends email.** All replies go to her Gmail Drafts folder.
   She opens Gmail and sends manually.
2. **Hermes never deletes files** — no Gmail messages, no Drive files, no
   Docs, no Sheets, no folders. Not via Drive, not via the Docs API, not
   via Sheets, not via any path.
3. **Hermes never trashes files or mail.** Move-to-trash is treated as
   destructive and blocked.
4. **Reading is fine.** Mail, calendar, Drive files, Docs, Sheets, Slack
   messages — Hermes can read anything Nikki has access to.
5. **Writing is fine** *except* sending and deleting:
   - Creating new Docs, Sheets, Drive files: ✅
   - Editing existing Docs and Sheets she has access to: ✅
   - Creating Gmail drafts: ✅
   - Posting in Slack as her after she taps approve: ✅
6. **Slack outbound posts require an explicit Telegram tap** to approve the
   draft. There is no auto-post path.
7. **No-draft topics**: Hermes flags but refuses to draft replies for any
   thread classified as `hr`, `personal` (configurable per
   `importance.yaml::email.no_draft_categories`). She writes those manually.
   Per-person `no_draft` flags also block drafting for specific recipients.
8. **LinkedIn**: Hermes only reads via a SECONDARY LinkedIn account she
   creates with a different email — her real account is never automated
   against. Engagement is fully manual: Hermes pings her with a post URL +
   suggested comment text in Telegram; she comments live with her real
   fingers on her phone. Posting/scheduling goes via Buffer's official
   LinkedIn API integration (no automation, no ToS exposure).

## Three layers of enforcement

### Layer 1 — OAuth scopes (Google's edge)

The Google APIs themselves refuse calls outside the granted scopes. Our
scopes are deliberately narrow:

- `gmail.readonly` + `gmail.compose` (draft-creation; send capability is
  technically granted by `gmail.compose` — see Layer 2)
- `calendar.events.readonly` (read-only)
- `documents` (Docs read+write)
- `spreadsheets` (Sheets read+write)
- `drive.readonly` (read all)
- `drive.file` (write only Hermes-owned files via Drive API)

Anything outside these scopes is refused by Google before reaching our code.

### Layer 2 — HTTP transport blocker

`app/google/_safety.py::GoogleSafeHttp` wraps every Google API call. Even
if a scope grants a destructive capability (notably `gmail.compose` includes
send), the HTTP transport refuses the request before it leaves the daemon.

Specifically blocked, regardless of scope:

| API | Blocked operation | URI / method match |
|---|---|---|
| Gmail | Send a message | `/messages/send` |
| Gmail | Send a saved draft | `/drafts/send` |
| Gmail | Move to trash | `/trash` |
| Gmail | Restore from trash | `/untrash` |
| Gmail | Batch delete | `/batchDelete` |
| Gmail | Batch modify (could apply TRASH label) | `/batchModify` |
| Gmail | Permanent delete of message/thread | `DELETE /messages/...` or `DELETE /threads/...` |
| Drive | Delete any file | `DELETE /drive/v[23]/files/...` |
| Drive | Empty trash | `/emptyTrash` |
| Drive | Move file to trash via update | `PATCH/PUT /files/...` with body containing `trashed: true` |

Allowed (so legitimate workflows work):

- `drafts.create`, `drafts.delete` (deleting a Hermes-authored draft)
- `documents.batchUpdate` (editing Doc content)
- `spreadsheets.values.update`, `.append` (editing Sheet content)
- `files.create` (creating new Drive files)
- All read operations across all five APIs

### Layer 3 — Code surface

Module surfaces only expose safe operations:

- `app/google/gmail.py` — `list_unread`, `get_message`, `get_thread`,
  `create_draft`. The name `send` exists only as a tripwire that raises.
- `app/google/calendar.py` — only read functions.
- `app/google/docs.py` — `create`, `read_text`, `append_paragraph`,
  `append_heading`, `append_markdown`. No delete.
- `app/google/sheets.py` — `read_range`, `write_range`, `append_row`,
  `get_metadata`. No delete.
- `app/google/drive.py` — read-only finders + Hermes-folder management
  (when wired up). No delete functions exposed.

## Telegram approval as a fourth checkpoint

Every Slack reply and every Gmail draft preview shows up in Telegram with
`[✅ Approve] [🗑 Discard]` buttons. Drafts only land in Gmail Drafts (or
Slack) after she taps approve. There is no zero-touch outbound path.

## Brain layer: Codex primary, Claude as a tool

The main agent operates on **Codex** (her ChatGPT subscription, invoked
via `codex exec`). All Hermes LLM calls default to Codex. `claude -p` is
one of the tools Codex can call when Claude is a better fit (typically:
voice-grounded drafting, longer creative synthesis).

Both backends are CLI subprocesses on the daemon Mac — no API keys, both
covered by her existing subscriptions. If a contributor ever wants to
switch a specific prompt to Claude permanently:

```
LLM_BACKEND_DRAFT_REPLY=claude
```

in `.env` pins `prompts/draft_reply.md` to Claude. No code change needed.

Both backends pass through the same Hermes tooling (Google APIs gated by
`GoogleSafeHttp`, Slack gated by Telegram approval, etc.). The brain swap
does NOT change the safety guarantees in this document — those are
enforced at the HTTP transport layer, the Slack post-as-her gate, and the
no-draft category check, all of which are downstream of the LLM call.

## If you ever need to add a destructive operation

Don't do it casually. Required steps:

1. **Update this document** with the rationale (Why this op? Why now? What
   are the alternatives?).
2. **Carve a specific exception** in `app/google/_safety.py` with a code
   comment pointing at the SAFETY.md change.
3. **Gate the call site** through `app.policy.require_double_confirm()`.
   This sends a confirmation prompt to Telegram with a one-time token.
   Nikki must reply `/confirm <token>` within 5 minutes for the op to proceed.
4. **Audit log** the action in `state.notify_log` with kind
   `destructive_confirmed` so any past mistake is traceable.
5. **Code review** by someone other than the author.

## Out-of-scope by design

These are intentionally NOT capabilities of Hermes:

- Sending email autonomously
- Replying in Slack without a Telegram tap
- Deleting messages, files, calendar events, or Slack messages
- Moving files between folders that Hermes did not create
- Sharing files with new people
- Modifying calendar events
- Creating Slack channels, inviting users, modifying memberships
- Updating Salesforce records (those go through Zapier with explicit Zaps
  she configures)

## Profile store (accumulated memory)

Hermes builds memory over time in `state.sqlite` + `profiles/` markdown:

- `state.sqlite` tables: `people`, `accounts`, `spreadsheet_recipes`,
  `voice_samples`, `network`.
- `profiles/people/<email-slug>.md` — per-person notes appended after
  every interaction.
- `profiles/accounts/<domain-slug>.md` — per-company history.
- `profiles/spreadsheets/<sheet_id>.md` — verbatim recipes for `/fill`.
- `profiles/voice/<context>.md` — voice samples and rules per context.
- `brand/` — `icp.md`, `product.md`, `pricing.md`, `network.md` (semi-static
  company knowledge; pricing is auto-injected into any draft prompt that
  touches money).

All of this is local-only. `profiles/` and `brand/` are gitignored.
Approved drafts are captured as voice samples (raw text) so future drafts
get sharper over time. She can view via Telegram or open the markdown
files directly.

## Backups

Twice daily (default 7am + 7pm her time), Hermes uploads a timestamped zip
of `state.sqlite + profiles/ + brand/ + config/importance.yaml + a 90-day
calendar export` to a "Hermes Backups" folder in her Drive.

Backups deliberately exclude credentials (`.env`, OAuth tokens, LinkedIn
cookies). If the Mac dies, she re-runs OAuth flows on a new Mac and
restores the latest backup zip — all accumulated memory comes back.

Backups are never deleted by Hermes (no-delete policy applies). Storage
cost is trivial (typically <50MB per zip). She can manually clean the
folder once a year if she cares.

## Token storage

Long-term credentials live in `~/hermes/secrets/` with mode 0600:

- `google_client.json` — OAuth client credentials
- `google_token.json` — refresh token for her Google account
- `linkedin_secondary_cookies.json` — secondary-account session for
  Playwright scanning (NOT her real LinkedIn)
- `.env` (in `~/hermes/`) — Slack tokens, Telegram bot token, Apollo key,
  Buffer token, Zapier secrets

These are equivalent in power to her account passwords. The Mac must have:

- FileVault enabled
- Screen lock with no grace period
- No shared user accounts
- A unique Mac login password, not reused elsewhere

## Auditability

Every notification, classification, draft, and (future) confirmed destructive
op is logged to `state.sqlite`:

- `seen_messages` — every email/Slack message Hermes triaged, including
  the full triage JSON (priority, category, signal_matches, etc.)
- `pending_drafts` — every draft Hermes created and whether it was approved
- `notify_log` — every Telegram alert sent
- `voice_samples` — captured drafts after she approved them
- `people`, `accounts`, `spreadsheet_recipes` — profile state
- `kv` — operational state (posture, last-run timestamps, confirmation tokens)

Per the audit clause from the interview: she + sponsor/IT can review the
SQLite + profiles markdown directly on her Mac with permission. Nothing
exfils automatically — backups go only to her own Drive.
