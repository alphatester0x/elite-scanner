"""Entry point and scan orchestrator with diagnostics."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Tuple

from .config import (
    setup_logging,
    load_mode,
    TIMEFRAMES,
    SCALP_HTF_INTERVAL,
    MAX_WORKERS,
    MAX_SIGNALS_PER_SCAN,
    MIN_SCORE_RATIO,
)
from .exchange import BinanceClient
from .indicators import IndicatorCache
from .filters import prefilter_elite, prefilter_swing, prefilter_scalp
from .scoring import score_elite, score_swing, score_scalp, get_grade
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

# Diagnostic counters (thread-safe via GIL)
_stats = {
    "pairs_total": 0,
    "fetch_ok": 0,
    "fetch_fail": 0,
    "prefilter_pass": 0,
    "prefilter_fail": 0,
    "score_ok": 0,
    "score_fail": 0,
    "signals": 0,
}


def _fmt(val, fmt=".2f"):
    """Safe formatter for debug logs."""
    if val is None:
        return "None"
    try:
        return f"{val:{fmt}}"
    except Exception:
        return str(val)


def scan_symbol(
    client: BinanceClient,
    symbol: str,
    mode: str,
) -> List[Tuple[int, str, str, str]]:
    """
    Scan a single symbol across all timeframes for the current mode.
    Returns a list of (score, symbol, tf_label, message).
    """
    signals = []
    timeframes = TIMEFRAMES.get(mode, [])

    # Pre-fetch all timeframe data for this symbol
    tf_data = {}
    for interval, tf_label in timeframes:
        data = client.fetch_klines(symbol, interval)
        if data:
            tf_data[interval] = data

    if not tf_data:
        _stats["fetch_fail"] += 1
        return signals
    _stats["fetch_ok"] += 1

    # For SCALP mode, the 1h data acts as HTF — reuse it instead of re-fetching
    htf_data = None
    if mode == "SCALP" and SCALP_HTF_INTERVAL in tf_data:
        htf_data = tf_data[SCALP_HTF_INTERVAL]

    for interval, tf_label in timeframes:
        if interval not in tf_data:
            continue

        opens, highs, lows, closes, vols = tf_data[interval]

        # Compute all indicators once
        try:
            cache = IndicatorCache(opens, highs, lows, closes, vols)
        except Exception as e:
            logger.warning(f"Indicator computation failed for {symbol} [{interval}]: {e}")
            continue

        # Prepare HTF cache for SCALP (reuse pre-fetched 1h data)
        htf_cache = None
        if mode == "SCALP" and interval == "15m" and htf_data is not None:
            try:
                h_opens, h_highs, h_lows, h_closes, h_vols = htf_data
                htf_cache = IndicatorCache(h_opens, h_highs, h_lows, h_closes, h_vols)
            except Exception as e:
                logger.warning(f"HTF indicator computation failed for {symbol}: {e}")

        # Apply hard filters (fast reject)
        passed = False
        if mode == "ELITE":
            passed = prefilter_elite(cache)
        elif mode == "SWING":
            passed = prefilter_swing(cache)
        elif mode == "SCALP":
            passed = prefilter_scalp(cache, htf_cache)

        if not passed:
            _stats["prefilter_fail"] += 1
            logger.debug(
                f"[{symbol} {tf_label}] REJECTED by prefilter | "
                f"E50={_fmt(cache.ema_50)} E200={_fmt(cache.ema_200)} "
                f"RSI={_fmt(cache.rsi_14, '.1f')} ADX={_fmt(cache.adx_14, '.1f')} "
                f"VOL={_fmt(cache.vol_r, '.1f')}x BODY={_fmt(cache.body, '.1f')}% "
                f"ATR={_fmt(cache.atr_pct, '.1f')}%"
            )
            continue

        _stats["prefilter_pass"] += 1

        # Apply scoring (zero redundant computation)
        try:
            if mode == "ELITE":
                score, max_score, reasons = score_elite(cache)
            elif mode == "SWING":
                score, max_score, reasons = score_swing(cache)
            elif mode == "SCALP":
                score, max_score, reasons = score_scalp(cache, htf_cache)
            else:
                continue
        except Exception as e:
            logger.error(f"Scoring error for {symbol} [{interval}]: {e}")
            continue

        # Score gate
        min_ratio = MIN_SCORE_RATIO.get(mode, 0.60)
        ratio = score / max_score if max_score > 0 else 0
        if max_score == 0 or ratio < min_ratio:
            _stats["score_fail"] += 1
            logger.debug(
                f"[{symbol} {tf_label}] REJECTED by score gate | "
                f"Score={score}/{max_score} ({ratio:.1%}) < {min_ratio:.0%}"
            )
            continue

        _stats["score_ok"] += 1
        _stats["signals"] += 1

        grade, badge = get_grade(score, max_score)
        emoji = {"ELITE": "🔥", "SWING": "✅", "SCALP": "⚡"}[mode]
        reason_text = "\n".join(reasons)

        msg = (
            f"{emoji} <b>{mode} SIGNAL</b> | {badge} Grade {grade} ({score}/{max_score})\n\n"
            f"{reason_text}\n\n"
            f"MODE: {mode}"
        )

        signals.append((score, symbol, tf_label, msg))
        logger.info(f"[{symbol} {tf_label}] SIGNAL | Score={score}/{max_score} ({ratio:.1%})")

    return signals


def scan_all(client: BinanceClient, bot: TelegramBot) -> None:
    """Main scanning orchestrator."""
    mode = load_mode()
    logger.info(f"Starting scan | Mode: {mode} | Time: {datetime.now()}")

    # Reset stats
    for k in _stats:
        _stats[k] = 0

    try:
        pairs = client.get_active_pairs()
    except Exception as e:
        logger.critical(f"Failed to fetch pairs: {e}")
        bot.send_error_alert(e)
        return

    _stats["pairs_total"] = len(pairs)
    all_signals: List[Tuple[int, str, str, str]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scan_symbol, client, p, mode): p for p in pairs}

        for future in as_completed(futures):
            symbol = futures[future]
            try:
                result = future.result(timeout=30)
                all_signals.extend(result)
            except Exception as e:
                logger.error(f"Scan failed for {symbol}: {e}")

    # Prioritize by score descending
    all_signals.sort(key=lambda x: x[0], reverse=True)

    logger.info(
        f"Scan complete | Signals found: {len(all_signals)} | "
        f"Top {MAX_SIGNALS_PER_SCAN} will be sent"
    )

    # Diagnostic summary
    logger.info(
        f"DIAGNOSTICS | Total pairs: {_stats['pairs_total']} | "
        f"Fetch OK: {_stats['fetch_ok']} | Fetch Fail: {_stats['fetch_fail']} | "
        f"Prefilter Pass: {_stats['prefilter_pass']} | Prefilter Fail: {_stats['prefilter_fail']} | "
        f"Score OK: {_stats['score_ok']} | Score Fail: {_stats['score_fail']} | "
        f"Final Signals: {_stats['signals']}"
    )

    sent_count = 0
    for score, symbol, tf_label, msg in all_signals[:MAX_SIGNALS_PER_SCAN]:
        full_msg = f"🪙 <b>{symbol}</b> [{tf_label}]\n\n{msg}"
        if bot.send_message(full_msg):
            sent_count += 1
            time.sleep(1)  # Respect Telegram rate limits
        else:
            logger.warning(f"Failed to send signal for {symbol}")

    logger.info(f"Sent {sent_count}/{min(len(all_signals), MAX_SIGNALS_PER_SCAN)} signals")


def main() -> None:
    setup_logging()
    client = BinanceClient()
    bot = TelegramBot()

    try:
        bot.handle_commands()
        scan_all(client, bot)
    except Exception as e:
        logger.critical(f"Fatal error in main loop: {e}", exc_info=True)
        bot.send_error_alert(e)


if __name__ == "__main__":
    main()
