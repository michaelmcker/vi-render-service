"""Telegram bot handlers — commands and inline-button callbacks.

Lives in one file because the surface is small and predictable.
"""
from __future__ import annotations

import logging
from typing import Any

import yaml
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from . import llm, notify, profiles, state
from .config import IMPORTANCE_PATH, Importance, PROMPTS_DIR, env
from .google import gmail
from .slack import actions as slack_actions, auth as slack_auth

log = logging.getLogger("hermes.handlers")

import re as _re
_HANDLERS_EMAIL_RE = _re.compile(r"[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}")


def _extract_email(from_header: str) -> str:
    m = _HANDLERS_EMAIL_RE.search(from_header or "")
    return m.group(0).lower() if m else ""


def _bump_approval_counter() -> None:
    """Track approvals; auto-graduate posture from conservative -> pre_draft
    once the configured threshold is crossed. Pings Nikki once at graduation.
    """
    importance = Importance.load()
    threshold = int(importance.budget.get("adaptive_ramp_threshold", 50))
    n = int(state.kv_get("draft_approvals_count", "0") or "0") + 1
    state.kv_set("draft_approvals_count", str(n))
    posture = state.kv_get("posture", "conservative")
    if posture == "conservative" and n >= threshold:
        state.kv_set("posture", "pre_draft")
        notify.send_text(
            "🎓 *Posture upgrade*\n\n"
            f"You've approved {n} drafts. Hermes is graduating from "
            "conservative (Draft on tap) to pre-drafting on every flagged "
            "item — you'll just edit + approve.\n\n"
            "Send `/posture conservative` to undo.",
            urgent=True, kind="system",
        )

# ────────────────────────── auth gate ──────────────────────────


def _is_nikki(update: Update) -> bool:
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    allowed = env("TELEGRAM_CHAT_ID")
    return chat_id == allowed


async def _gate(update: Update) -> bool:
    if _is_nikki(update):
        return True
    log.warning("ignoring message from non-Nikki chat %s", update.effective_chat)
    return False


# ────────────────────────── commands ──────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    await update.message.reply_text(
        "Hermes online. Try:\n"
        "/health  – connection status\n"
        "/today  – today's briefing snapshot\n"
        "/vip add ceo@acme.com  – add a VIP sender\n"
        "/watch #deals-pipeline  – monitor a Slack channel\n"
        "/quiet 2h  – mute non-urgent pings"
    )


async def cmd_health(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    rows = []
    for name, check in [("Gmail", _check_gmail), ("Slack", _check_slack),
                        ("Claude CLI", _check_claude)]:
        ok, detail = check()
        rows.append(f"{'✅' if ok else '❌'} {name} — {detail}")
    await update.message.reply_text("\n".join(rows))


async def cmd_today(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    from .state import conn
    with conn() as c:
        rows = c.execute(
            "SELECT source, priority, summary FROM seen_messages "
            "WHERE seen_at > strftime('%s','now','-1 day') "
            "AND priority IN ('urgent','today') "
            "ORDER BY seen_at DESC LIMIT 30"
        ).fetchall()
    if not rows:
        await update.message.reply_text("Nothing flagged yet today. Quiet inbox.")
        return
    lines = [f"• [{r['source']}] {r['priority']}: {r['summary']}" for r in rows]
    await update.message.reply_text("\n".join(lines))


async def cmd_vip(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    args = (update.message.text or "").split()[1:]
    if len(args) < 2 or args[0] not in ("add", "remove", "list"):
        await update.message.reply_text("usage: /vip add|remove <email> | /vip list")
        return
    importance = _load_importance_writable()
    vips = importance.setdefault("email", {}).setdefault("vip_senders", [])
    if args[0] == "list":
        await update.message.reply_text("VIPs:\n" + "\n".join(f"• {v}" for v in vips) if vips else "No VIPs set.")
        return
    target = args[1].lower()
    if args[0] == "add" and target not in vips:
        vips.append(target)
    elif args[0] == "remove" and target in vips:
        vips.remove(target)
    _save_importance(importance)
    await update.message.reply_text(f"OK. {len(vips)} VIPs configured.")


async def cmd_watch(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    args = (update.message.text or "").split()[1:]
    if not args:
        await update.message.reply_text("usage: /watch #channel  or  /unwatch #channel")
        return
    importance = _load_importance_writable()
    channels = importance.setdefault("slack", {}).setdefault("monitor_channels", [])
    ch = args[0] if args[0].startswith("#") else f"#{args[0]}"
    cmd = (update.message.text or "").split()[0].lstrip("/")
    if cmd == "watch" and ch not in channels:
        channels.append(ch)
    elif cmd == "unwatch" and ch in channels:
        channels.remove(ch)
    _save_importance(importance)
    await update.message.reply_text(f"Watching {len(channels)} channels.")


async def cmd_fill(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Run /fill-spreadsheet for a given sheet URL."""
    if not await _gate(update):
        return
    args = (update.message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text(
            "usage: `/fill <sheet_url_or_id>`\n\n"
            "If no recipe is saved for the sheet, Hermes will ask you to set one "
            "with `/recipe <sheet> set <instructions>` first.",
            parse_mode="Markdown",
        )
        return
    from . import fill_spreadsheet
    sheet_id = fill_spreadsheet.parse_sheet_id(args[1].strip())
    if not sheet_id:
        await update.message.reply_text("Couldn't parse a sheet id from that.")
        return
    await update.message.reply_text("📊 Running fill — this may take a minute or two…")
    try:
        result = fill_spreadsheet.run_for_sheet(sheet_id)
    except Exception as e:
        log.exception("/fill failed")
        await update.message.reply_text(f"⚠️ Fill failed: {e}")
        return
    if result.get("status") == "needs_recipe":
        await update.message.reply_text(
            "🪄 *No recipe yet for this sheet.*\n\n"
            "Send instructions in plain English describing how each column "
            "should be filled, then re-run `/fill`.\n\n"
            f"`/recipe {sheet_id} set col B = Apollo headcount; col C = "
            "most recent funding round from web; ...`",
            parse_mode="Markdown",
        )
        return
    if result.get("status") != "ok":
        await update.message.reply_text(f"⚠️ {result.get('message', 'unknown')}")
        return
    note_blob = "\n".join(f"  • {n}" for n in result.get("notes", [])[:10])
    await update.message.reply_text(
        f"✅ *{result['title']}*\n"
        f"Rows written: {result['rows_written']}/{result['rows_processed']}\n"
        + (f"\nNotes:\n{note_blob}" if note_blob else ""),
        parse_mode="Markdown",
    )


async def cmd_recipe(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Inspect or set a spreadsheet recipe."""
    if not await _gate(update):
        return
    text = update.message.text or ""
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await update.message.reply_text(
            "usage:\n"
            "  `/recipe <sheet>`           — show saved recipe\n"
            "  `/recipe <sheet> set <text>` — replace recipe",
            parse_mode="Markdown",
        )
        return
    from . import fill_spreadsheet
    sheet_id = fill_spreadsheet.parse_sheet_id(parts[1])
    if not sheet_id:
        await update.message.reply_text("Couldn't parse a sheet id from that.")
        return

    if len(parts) == 2:
        recipe = profiles.get_recipe(sheet_id)
        if not recipe:
            await update.message.reply_text("No recipe saved for this sheet.")
        else:
            instr = recipe.get("instructions", "")[:3500]
            await update.message.reply_text(
                f"*Recipe for {recipe.get('title', sheet_id)}*\n\n```\n{instr}\n```",
                parse_mode="Markdown",
            )
        return

    # /recipe <sheet> set <text>
    rest = parts[2]
    if not rest.lower().startswith("set "):
        await update.message.reply_text(
            "second argument must be `set <text>`. Run with no arg to view the saved recipe.",
            parse_mode="Markdown",
        )
        return
    instructions = rest[4:].strip()
    if not instructions:
        await update.message.reply_text("Need recipe text after `set`.")
        return
    fill_spreadsheet.save_recipe(sheet_id, instructions)
    await update.message.reply_text(f"✅ Recipe saved. Re-run `/fill {sheet_id}` to apply.",
                                    parse_mode="Markdown")


async def cmd_prep(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a pre-call prep brief for an upcoming meeting."""
    if not await _gate(update):
        return
    arg = " ".join((update.message.text or "").split()[1:])
    await update.message.reply_text("📋 Building prep brief — check back in ~30s…")
    from . import pre_call_prep
    try:
        result = pre_call_prep.run(arg)
    except Exception as e:
        log.exception("/prep failed")
        await update.message.reply_text(f"⚠️ Prep failed: {e}")
        return
    if result.get("status") == "no_meeting":
        await update.message.reply_text("No upcoming meeting found in the next 48h.")
        return
    if result.get("status") != "ok":
        await update.message.reply_text(f"⚠️ Prep failed: {result.get('reason', 'unknown')}")
        return
    title = result.get("title", "Prep")
    link = result.get("doc_link", "")
    await update.message.reply_text(
        f"✅ *{title}*\n\n{link}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Open Doc", url=link)],
        ]) if link else None,
    )


async def cmd_posture(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    args = (update.message.text or "").split()[1:]
    valid = ("conservative", "pre_draft")
    if not args:
        cur = state.kv_get("posture", "conservative")
        n = state.kv_get("draft_approvals_count", "0")
        await update.message.reply_text(
            f"Posture: *{cur}* — {n} drafts approved\n\n"
            "Set with `/posture conservative` or `/posture pre_draft`.",
            parse_mode="Markdown",
        )
        return
    if args[0] not in valid:
        await update.message.reply_text(f"Posture must be one of: {', '.join(valid)}")
        return
    state.kv_set("posture", args[0])
    await update.message.reply_text(f"Posture set to *{args[0]}*.", parse_mode="Markdown")


async def cmd_quiet(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    args = (update.message.text or "").split()[1:]
    if not args:
        await update.message.reply_text("usage: /quiet 2h | /quiet off")
        return
    if args[0] == "off":
        state.kv_set("quiet_until", "0")
        await update.message.reply_text("Quiet mode off.")
        return
    import re, time as _t
    m = re.match(r"^(\d+)([hm])$", args[0])
    if not m:
        await update.message.reply_text("usage: /quiet 2h | /quiet 30m | /quiet off")
        return
    seconds = int(m.group(1)) * (3600 if m.group(2) == "h" else 60)
    state.kv_set("quiet_until", str(int(_t.time()) + seconds))
    await update.message.reply_text(f"Muted non-urgent pings for {args[0]}.")


# ────────────────────────── inline-button callbacks ──────────────────────────

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _gate(update):
        return
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    parts = data.split(":")
    op = parts[0]
    try:
        if op == "email_draft":
            await _email_draft(q, parts[1])
        elif op == "email_view":
            await _email_view(q, parts[1])
        elif op == "email_snooze":
            state.snooze("gmail", parts[1], int(parts[2]))
            await q.edit_message_reply_markup(None)
            await q.message.reply_text("Snoozed.")
        elif op == "email_mute":
            state.snooze("gmail", parts[1], 30 * 86400)
            await q.message.reply_text("Muted thread for 30d.")
        elif op == "slack_draft":
            await _slack_draft(q, channel=parts[1], ts=parts[2])
        elif op == "slack_react":
            slack_actions.react_as_her(parts[1], parts[2], "thumbsup")
            await q.message.reply_text("Reacted 👍")
        elif op == "slack_snooze":
            state.snooze("slack", f"{parts[1]}:{parts[2]}", int(parts[3]))
            await q.message.reply_text("Snoozed.")
        elif op == "approve_email_draft":
            d = state.get_pending_draft(int(parts[1]))
            if not d:
                await q.message.reply_text("Draft expired.")
                return
            gmail.create_draft(d["thread_id"], d["payload"]["in_reply_to"], d["body"])
            state.update_draft_status(int(parts[1]), "approved")
            # Capture as a voice sample so future drafts get sharper.
            try:
                profiles.capture_voice_sample(
                    context=d["payload"].get("voice_context") or "default",
                    body=d["body"],
                    recipient_email=d["payload"].get("recipient_email", ""),
                    source="approved-draft",
                )
                _bump_approval_counter()
            except Exception:
                log.exception("voice capture failed (non-fatal)")
            await q.message.reply_text("✅ Draft saved to your Gmail Drafts. Open Gmail to review and send.")
        elif op == "approve_slack_draft":
            d = state.get_pending_draft(int(parts[1]))
            if not d:
                await q.message.reply_text("Draft expired.")
                return
            slack_actions.post_as_her(d["payload"]["channel"], d["body"],
                                      thread_ts=d["payload"].get("thread_ts"))
            state.update_draft_status(int(parts[1]), "approved")
            try:
                profiles.capture_voice_sample(
                    context="internal",  # Slack defaults to internal voice
                    body=d["body"],
                    source="approved-draft",
                )
                _bump_approval_counter()
            except Exception:
                log.exception("voice capture failed (non-fatal)")
            await q.message.reply_text("✅ Posted in Slack.")
        elif op == "discard_draft":
            state.update_draft_status(int(parts[1]), "discarded")
            await q.message.reply_text("Discarded.")
    except Exception as e:
        log.exception("callback failed: %s", data)
        await q.message.reply_text(f"Something broke: {e}")


# ────────────────────────── draft flows ──────────────────────────

async def _email_draft(q, message_id: str) -> None:
    msg = gmail.get_message(message_id)
    thread = gmail.get_thread(msg["thread_id"])
    importance = Importance.load()

    # Recipient + no-draft check.
    recipient_email = _extract_email(msg.get("from", ""))
    no_draft_categories = importance.email.get("no_draft_categories",
                                               ["hr", "personal"])
    saved_triage = state.get_triage("gmail", message_id) or {}
    saved_category = (saved_triage.get("category") or "").lower()
    if saved_category in no_draft_categories:
        await q.message.reply_text(
            "🚫 *Hermes won't auto-draft this thread*\n\n"
            f"Detected category: `{saved_category}`. These threads are off-limits "
            "for auto-drafting per your safety policy. Reply manually so the "
            "words come from you.",
            parse_mode="Markdown",
        )
        return
    person = profiles.get_person(recipient_email) if recipient_email else None
    if person and person.no_draft:
        await q.message.reply_text(
            "🚫 *Hermes won't auto-draft for this recipient*\n\n"
            f"`{recipient_email}` is flagged no-draft. Reply manually.",
            parse_mode="Markdown",
        )
        return

    # Pull profile context (recipient notes, account notes, voice samples,
    # pricing if the thread mentions money).
    voice_context = profiles.infer_voice_context(recipient_email) if recipient_email else "default"
    body_lower = (msg.get("body") or "").lower()
    touches_money = any(k in body_lower for k in
                        ("price", "pricing", "discount", "quote", "contract",
                         "renewal", "msa", "sow", "$"))
    profile_blob = profiles.build_context(
        recipient_email=recipient_email,
        account_slug=profiles.domain_slug(profiles.domain_from_email(recipient_email)) if recipient_email else "",
        voice_context=voice_context,
        touches_money=touches_money,
    )

    voice_yaml = yaml.safe_dump(importance.voice, sort_keys=False)
    thread_text = "\n\n---\n\n".join(
        f"From: {m['from']}\nTo: {m['to']}\nSubject: {m['subject']}\n\n{m.get('body','')[:2000]}"
        for m in thread["messages"]
    )
    payload = (
        (f"CONTEXT:\n{profile_blob}\n\n" if profile_blob else "")
        + f"VOICE:\n{voice_yaml}\n\n"
        + f"THREAD (oldest first):\n{thread_text}\n\n"
        + f"INSTRUCTION:\n"
    )
    body = llm.run(PROMPTS_DIR / "draft_reply.md", payload)
    if isinstance(body, dict):
        body = str(body)
    body = body.strip()
    if body.startswith("{{HOLD}}"):
        await q.message.reply_text(f"⏸ Holding off: {body.removeprefix('{{HOLD}}:').strip()}")
        return
    draft_id = state.save_pending_draft(
        "gmail", msg["thread_id"], body,
        {"in_reply_to": msg["id"], "subject": msg["subject"],
         "recipient_email": recipient_email, "voice_context": voice_context},
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Save to Drafts", callback_data=f"approve_email_draft:{draft_id}"),
        InlineKeyboardButton("🗑 Discard", callback_data=f"discard_draft:{draft_id}"),
    ]])
    await q.message.reply_text(f"_Draft preview_\n\n{body}", reply_markup=keyboard, parse_mode="Markdown")


async def _email_view(q, message_id: str) -> None:
    msg = gmail.get_message(message_id)
    body = msg.get("body") or msg.get("snippet", "")
    text = (
        f"*From:* {msg['from']}\n*Subject:* {msg['subject']}\n\n"
        f"{body[:3500]}"
    )
    await q.message.reply_text(text, parse_mode="Markdown")


async def _slack_draft(q, *, channel: str, ts: str) -> None:
    msgs = slack_actions.fetch_thread(channel, ts) if ts else slack_actions.fetch_recent(channel)
    importance = Importance.load()
    voice_yaml = yaml.safe_dump(importance.voice, sort_keys=False)
    payload = (
        f"VOICE:\n{voice_yaml}\n\n"
        f"THREAD:\n{slack_actions.thread_to_text(msgs)}\n\n"
        f"INSTRUCTION:\n"
    )
    body = llm.run(PROMPTS_DIR / "slack_draft_reply.md", payload)
    if isinstance(body, dict):
        body = str(body)
    body = body.strip()
    if body.startswith("{{REACT}}"):
        emoji = body.removeprefix("{{REACT}}:").strip()
        slack_actions.react_as_her(channel, ts, emoji)
        await q.message.reply_text(f"Reacted {emoji}.")
        return
    if body.startswith("{{HOLD}}"):
        await q.message.reply_text(f"⏸ Holding off: {body.removeprefix('{{HOLD}}:').strip()}")
        return
    draft_id = state.save_pending_draft(
        "slack", f"{channel}:{ts}", body,
        {"channel": channel, "thread_ts": ts},
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Post in Slack", callback_data=f"approve_slack_draft:{draft_id}"),
        InlineKeyboardButton("🗑 Discard", callback_data=f"discard_draft:{draft_id}"),
    ]])
    await q.message.reply_text(f"_Slack draft_\n\n{body}", reply_markup=keyboard, parse_mode="Markdown")


# ────────────────────────── helpers ──────────────────────────

def _load_importance_writable() -> dict[str, Any]:
    if IMPORTANCE_PATH.exists():
        return yaml.safe_load(IMPORTANCE_PATH.read_text()) or {}
    example = IMPORTANCE_PATH.parent / "importance.example.yaml"
    return yaml.safe_load(example.read_text()) or {}


def _save_importance(d: dict[str, Any]) -> None:
    IMPORTANCE_PATH.write_text(yaml.safe_dump(d, sort_keys=False, default_flow_style=False))


def _check_gmail() -> tuple[bool, str]:
    try:
        from .google.auth import get_credentials
        get_credentials()
        return True, "ok"
    except Exception as e:
        return False, str(e)[:80]


def _check_slack() -> tuple[bool, str]:
    try:
        slack_auth.bot_client().auth_test()
        return True, "ok"
    except Exception as e:
        return False, str(e)[:80]


def _check_claude() -> tuple[bool, str]:
    try:
        out = llm.run(PROMPTS_DIR / "triage.md", "ping", expect_json=False, timeout=20)
        return True, "ok"
    except Exception as e:
        return False, str(e)[:80]
