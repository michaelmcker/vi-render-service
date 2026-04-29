"""Telegram bot — long-poll, dispatch to handlers."""
from __future__ import annotations

import logging

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from . import handlers
from .config import env

log = logging.getLogger("hermes.bot")


def build_app() -> Application:
    app = Application.builder().token(env("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("health", handlers.cmd_health))
    app.add_handler(CommandHandler("today", handlers.cmd_today))
    app.add_handler(CommandHandler("vip", handlers.cmd_vip))
    app.add_handler(CommandHandler("watch", handlers.cmd_watch))
    app.add_handler(CommandHandler("unwatch", handlers.cmd_watch))
    app.add_handler(CommandHandler("quiet", handlers.cmd_quiet))
    app.add_handler(CommandHandler("posture", handlers.cmd_posture))
    app.add_handler(CallbackQueryHandler(handlers.on_callback))
    return app


def run() -> None:
    app = build_app()
    log.info("Telegram bot starting (long-poll)")
    app.run_polling(close_loop=False, stop_signals=None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    run()
