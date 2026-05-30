"""Telegram bot wrapper."""
import logging
from typing import Optional
import requests

from .config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    load_last_update_id,
    save_last_update_id,
)

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self):
        self.token    = TELEGRAM_BOT_TOKEN
        self.chat_id  = str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else ""
        self.session  = requests.Session()
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not configured")
            return False
        try:
            resp = self.session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def handle_commands(self) -> None:
        """Poll for Telegram commands."""
        if not self.token or not self.chat_id:
            return

        last_id = load_last_update_id()
        params  = {"timeout": 5}
        if last_id > 0:
            params["offset"] = last_id + 1

        try:
            resp = self.session.get(f"{self.base_url}/getUpdates", params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                return

            for upd in data.get("result", []):
                uid     = upd["update_id"]
                msg     = upd.get("message", {})
                text    = msg.get("text", "").lower().strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                save_last_update_id(uid)

                if chat_id != self.chat_id:
                    continue

                if text == "/status":
                    self.send_message(
                        "🔄 <b>BOUNCE Scanner</b> aktif\n"
                        "Scan 1h candle, deteksi token drop ≥20% dari 24h high\n"
                        "Mode: /status"
                    )
                elif text == "/help":
                    self.send_message(
                        "📖 <b>Bounce Scanner Commands</b>\n\n"
                        "/status — cek status scanner\n"
                        "/help — tampilkan perintah ini"
                    )
                else:
                    logger.debug(f"Unhandled command: {text}")

        except Exception as e:
            logger.error(f"Telegram command handling error: {e}")

    def send_error_alert(self, error: Exception) -> None:
        self.send_message(f"❌ Bot Error\n<pre>{str(error)}</pre>")
