"""Configuration and environment management."""
import os
import json
import logging

# ── Environment ───────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Persistence ───────────────────────────────────────────
UPDATE_ID_FILE = "last_update_id.json"

# ── Exchange ──────────────────────────────────────────────
BINANCE_BASE = "https://data-api.binance.vision"

# ── Scan settings ─────────────────────────────────────────
MIN_QUOTE_VOLUME_USDT = 1_000_000   # 1M USDT — filter micro-caps
SCAN_INTERVAL         = "1h"        # candle timeframe
CANDLES_LIMIT         = 300         # ~12.5 days of 1h candles

# ── Bounce detection thresholds ───────────────────────────
DROP_LOOKBACK_CANDLES = 24          # look back 24 candles = 24h high
MIN_DROP_PCT          = 20.0        # minimum drop from 24h high

# ── Filter thresholds ─────────────────────────────────────
RSI_MAX           = 40.0            # oversold zone (dilonggarkan dari 35)
VOL_RATIO_MIN     = 1.2             # volume spike on drop (dilonggarkan dari 1.5)
BB_LOWER_BUFFER   = 0.05            # within 5% above lower BB (dilonggarkan dari 2%)
MAX_BEAR_BODY_PCT = -4.0            # still crashing if worse than -4%

# ── Scoring thresholds ────────────────────────────────────
MIN_SCORE_RATIO   = 0.55

# ── Performance ───────────────────────────────────────────
MAX_WORKERS          = 10
MAX_SIGNALS_PER_SCAN = 8

# ── Logging ───────────────────────────────────────────────
def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

# ── Update-ID persistence ─────────────────────────────────
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
