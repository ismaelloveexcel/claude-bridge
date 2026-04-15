"""
Telegram Notifier — sends operator updates at every pipeline stage.
Non-technical operator gets real-time visibility via Telegram without
needing to log into any dashboard.

Setup: create a Telegram bot via @BotFather, get the token and your chat ID,
add them to .env. That's it.
"""

import logging
import os

import httpx

log = logging.getLogger("claude_bridge.notifier")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")


async def notify_telegram(message: str) -> bool:
    """
    Send a Markdown-formatted message to the operator's Telegram.
    Returns True if sent, False if Telegram is not configured or call fails.
    Failures are logged but never raise — notifications must never crash the pipeline.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.debug("Telegram not configured — skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.info("Telegram notification sent.")
            return True
    except Exception as e:
        log.warning("Telegram notification failed: %s", e)
        return False
