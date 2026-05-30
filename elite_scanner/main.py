"""Bounce scanner — scan orchestrator."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Tuple

from .config import (
    setup_logging,
    SCAN_INTERVAL,
    CANDLES_LIMIT,
    DROP_LOOKBACK_CANDLES,
    MAX_WORKERS,
    MAX_SIGNALS_PER_SCAN,
    MIN_SCORE_RATIO,
)
from .exchange import BinanceClient
from .indicators import IndicatorCache
from .filters import prefilter_bounce
from .scoring import score_bounce, get_grade
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

# Diagnostic counters
_stats = {
    "pairs_total":    0,
    "fetch_ok":       0,
    "fetch_fail":     0,
    "prefilter_pass": 0,
    "prefilter_fail": 0,
    "score_ok":       0,
    "score_fail":     0,
    "signals":        0,
}


def _fmt(val, fmt=".2f"):
    if val is None:
        return "None"
    try:
        return f"{val:{fmt}}"
    except Exception:
        return str(val)


def scan_symbol(
    client: BinanceClient,
    symbol: str,
) -> List[Tuple[int, str, str]]:
    """
    Scan a single symbol for a bounce setup.
    Returns list of (score, symbol, message).
    """
    signals = []

    data = client.fetch_klines(symbol, SCAN_INTERVAL, limit=CANDLES_LIMIT)
    if not data:
        _stats["fetch_fail"] += 1
        return signals
    _stats["fetch_ok"] += 1

    opens, highs, lows, closes, vols = data

    try:
        cache = IndicatorCache(
            opens, highs, lows, closes, vols,
            lookback=DROP_LOOKBACK_CANDLES,
        )
    except Exception as e:
        logger.warning(f"Indicator computation failed for {symbol}: {e}")
        return signals

    # Hard filter
    passed, reject_reason = prefilter_bounce(cache)
    if not passed:
        _stats["prefilter_fail"] += 1
        logger.debug(f"[{symbol}] REJECTED | {reject_reason}")
        return signals

    _stats["prefilter_pass"] += 1

    # Scoring
    try:
        score, max_score, reasons = score_bounce(cache)
    except Exception as e:
        logger.error(f"Scoring error for {symbol}: {e}")
        return signals

    ratio = score / max_score if max_score > 0 else 0
    if max_score == 0 or ratio < MIN_SCORE_RATIO:
        _stats["score_fail"] += 1
        logger.debug(
            f"[{symbol}] SCORE GATE FAIL | "
            f"Score={score}/{max_score} ({ratio:.1%}) < {MIN_SCORE_RATIO:.0%}"
        )
        return signals

    _stats["score_ok"] += 1
    _stats["signals"] += 1

    grade, badge = get_grade(score, max_score)
    reason_text  = "\n".join(reasons)

    # Build Telegram message
    msg = (
        f"🪙 <b>{symbol}</b> [1H]\n\n"
        f"🔄 <b>BOUNCE SIGNAL</b> | {badge} Grade {grade} ({score}/{max_score})\n\n"
        f"📉 Drop dari 24h High: <b>{cache.drop_pct:.1f}%</b>\n"
        f"💰 Harga sekarang: <b>{cache.cc:.6g}</b>\n"
        f"📊 RSI: <b>{_fmt(cache.rsi_14, '.1f')}</b> | "
        f"Stoch %K: <b>{_fmt(cache.stoch_k, '.1f')}</b>\n"
        f"📈 ATR: <b>{cache.atr_pct:.2f}%</b> | "
        f"Vol: <b>{cache.vol_r:.1f}x</b>\n\n"
        f"<b>Analisa:</b>\n{reason_text}\n\n"
        f"⚠️ <i>BUKAN financial advice. DYOR, pasang SL.</i>"
    )

    signals.append((score, symbol, msg))
    logger.info(
        f"[{symbol}] SIGNAL | "
        f"Drop={cache.drop_pct:.1f}% | RSI={_fmt(cache.rsi_14, '.1f')} | "
        f"Score={score}/{max_score} ({ratio:.1%}) | Grade={grade}"
    )

    return signals


def scan_all(client: BinanceClient, bot: TelegramBot) -> None:
    """Main scanning orchestrator."""
    logger.info(f"Starting BOUNCE scan | Time: {datetime.now()}")

    for k in _stats:
        _stats[k] = 0

    try:
        pairs = client.get_active_pairs()
    except Exception as e:
        logger.critical(f"Failed to fetch pairs: {e}")
        bot.send_error_alert(e)
        return

    _stats["pairs_total"] = len(pairs)
    all_signals: List[Tuple[int, str, str]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scan_symbol, client, p): p for p in pairs}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result(timeout=30)
                all_signals.extend(result)
            except Exception as e:
                logger.error(f"Scan failed for {symbol}: {e}")

    # Sort by score descending
    all_signals.sort(key=lambda x: x[0], reverse=True)

    logger.info(
        f"Scan complete | "
        f"Pairs: {_stats['pairs_total']} | "
        f"Fetch OK: {_stats['fetch_ok']} | "
        f"Pre-filter pass: {_stats['prefilter_pass']} | "
        f"Score OK: {_stats['score_ok']} | "
        f"Signals: {len(all_signals)}"
    )

    if not all_signals:
        logger.info("No bounce candidates found this scan.")
        return

    sent = 0
    for score, symbol, msg in all_signals[:MAX_SIGNALS_PER_SCAN]:
        if bot.send_message(msg):
            sent += 1
            time.sleep(1)
        else:
            logger.warning(f"Failed to send signal for {symbol}")

    logger.info(f"Sent {sent}/{min(len(all_signals), MAX_SIGNALS_PER_SCAN)} signals")


def main() -> None:
    setup_logging()
    client = BinanceClient()
    bot    = TelegramBot()

    # Validate env vars early — fail fast instead of running full scan then dying
    if not bot.token or not bot.chat_id:
        logger.critical("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Exiting.")
        return

    try:
        bot.handle_commands()
        scan_all(client, bot)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        bot.send_error_alert(e)


if __name__ == "__main__":
    main()
