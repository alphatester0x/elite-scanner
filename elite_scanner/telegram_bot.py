"""Telegram bot wrapper with persistent update tracking."""
import logging
from typing import Optional
import requests

from .config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    load_last_update_id,
    save_last_update_id,
    save_mode,
    load_mode,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    """Minimal Telegram bot for commands and alerts."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else ""
        self.session = requests.Session()
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured chat."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not configured")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        try:
            resp = self.session.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def handle_commands(self) -> None:
        """Poll Telegram for commands."""
        if not self.token or not self.chat_id:
            return

        last_id = load_last_update_id()

        url = f"{self.base_url}/getUpdates"
        params = {"timeout": 5}
        if last_id > 0:
            params["offset"] = last_id + 1

        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                logger.warning(f"Telegram API error: {data}")
                return

            for upd in data.get("result", []):
                uid = upd["update_id"]
                msg = upd.get("message", {})
                text = msg.get("text", "").lower().strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                save_last_update_id(uid)

                if chat_id != self.chat_id:
                    continue

                if text == "/bounce":
                    save_mode("BOUNCE")
                    self.send_message("💥 Mode diubah ke BOUNCE (Mean Reversion)")
                    logger.info("Mode changed to BOUNCE via Telegram")
                elif text == "/status":
                    mode = load_mode()
                    self.send_message(f"📊 Current mode: <b>{mode}</b>")
                else:
                    logger.debug(f"Unhandled command: {text}")

        except Exception as e:
            logger.error(f"Telegram command handling error: {e}")

    def send_error_alert(self, error: Exception) -> None:
        """Send a formatted error notification."""
        self.send_message(f"❌ Bot Error\n<pre>{str(error)}</pre>")
