"""Configuration and environment management."""
import os
import json
import logging
from typing import Dict

# ── Environment ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Persistence ──────────────────────────────────────────
MODE_FILE      = "mode.json"
UPDATE_ID_FILE = "last_update_id.json"

# ── Performance ─────────────────────────────────────────
MAX_WORKERS          = 10
MAX_SIGNALS_PER_SCAN = 10

# Filter out illiquid pairs (24h quote volume in USDT)
MIN_QUOTE_VOLUME_USDT = 500_000

# ── BOUNCE Mode Config ──────────────────────────────────
MIN_DROP_PCT = 20.0   # Minimum drop untuk dianggap "crash"
MAX_DROP_PCT = 45.0   # Maximum drop: >45% dianggap too risky

# Scoring Threshold — dilonggarkan dari 0.60 ke 0.50
# Dengan filter yang lebih ketat di atas, scoring bisa lebih permisif
MIN_SCORE_RATIO = 0.50

# ── Exchange ──────────────────────────────────────────────
BINANCE_BASE = "https://data-api.binance.vision"

# ── Timeframes ────────────────────────────────────────────
TIMEFRAMES = {
    "BOUNCE": [("1h", "1H")],
}

# ── Logging ───────────────────────────────────────────────
def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

# ── Mode persistence ──────────────────────────────────────
def load_mode() -> str:
    if not os.path.exists(MODE_FILE):
        save_mode("BOUNCE")
    try:
        with open(MODE_FILE, "r") as f:
            return json.load(f).get("mode", "BOUNCE")
    except Exception:
        logging.getLogger(__name__).warning("Failed to load mode, defaulting to BOUNCE")
        return "BOUNCE"


def save_mode(mode: str) -> None:
    with open(MODE_FILE, "w") as f:
        json.dump({"mode": mode}, f)

# ── Update-ID persistence ───────────────────────────────
def load_last_update_id() -> int:
    try:
        with open(UPDATE_ID_FILE, "r") as f:
            return json.load(f).get("last_update_id", 0)
    except Exception:
        return 0


def save_last_update_id(uid: int) -> None:
    try:
        with open(UPDATE_ID_FILE, "w") as f:
            json.dump({"last_update_id": uid}, f)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to save update_id: {e}")
