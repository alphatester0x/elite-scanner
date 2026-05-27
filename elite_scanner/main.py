"""Entry point and scan orchestrator for BOUNCE mode."""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Tuple

from .config import (
    setup_logging,
    load_mode,
    TIMEFRAMES,
    MAX_WORKERS,
    MAX_SIGNALS_PER_SCAN,
    MIN_SCORE_RATIO,
    MIN_DROP_PCT,
    MAX_DROP_PCT,
)
from .exchange import BinanceClient
from .indicators import IndicatorCache
from .filters import prefilter_bounce
from .scoring import score_bounce, get_grade
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

# Diagnostic counters
_stats = {
    "pairs_total": 0,
    "fetch_ticker_ok": 0,
    "fetch_ticker_fail": 0,
    "drop_filtered": 0,
    "fetch_klines_ok": 0,
    "fetch_klines_fail": 0,
    "prefilter_pass": 0,
    "prefilter_fail": 0,
    "score_ok": 0,
    "score_fail": 0,
    "signals": 0,
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
    drop_24h: float,
) -> List[Tuple[int, str, str, str]]:
    """Scan a single symbol for BOUNCE signals."""
    signals = []
    interval, tf_label = TIMEFRAMES["BOUNCE"][0]
    
    # DEBUG: Start scan
    logger.info(f"[DEBUG {symbol}] Starting scan | Drop24h={drop_24h:.1f}%")

    data = client.fetch_klines(symbol, interval, limit=300)
    if not data:
        _stats["fetch_klines_fail"] += 1
        logger.info(f"[DEBUG {symbol}] FETCH FAILED: No klines data")  # <-- TAMBAH INI
        return signals
    _stats["fetch_klines_ok"] += 1
    logger.info(f"[DEBUG {symbol}] FETCH OK: {len(data[0])} candles")  # <-- TAMBAH INI
    
    opens, highs, lows, closes, vols = data
    
    try:
        cache = IndicatorCache(opens, highs, lows, closes, vols)
        logger.info(
            f"[DEBUG {symbol}] CACHE OK: "
            f"Drop={_fmt(cache.drop_24h_pct)}% | "
            f"RSI={_fmt(cache.rsi_14, '.1f')} | "
            f"Wick={_fmt(cache.lower_wick, '.1f')}% | "
            f"AboveEMA9={cache.above_ema9} | "
            f"VolR={_fmt(cache.vol_r, '.1f')}x | "
            f"ATR={_fmt(cache.atr_pct, '.1f')}% | "
            f"RedStreak={cache.consecutive_red} | "
            f"VolTrend={_fmt(cache.vol_trend, '.1f')}x"
        )
    except Exception as e:
        logger.warning(f"[DEBUG {symbol}] CACHE FAILED: {e}")  # <-- TAMBAH INI
        return signals

    # Apply hard filters
    if not prefilter_bounce(cache, drop_24h=drop_24h):
        _stats["prefilter_fail"] += 1
        logger.info(f"[DEBUG {symbol}] PREFILTER REJECTED")  # <-- TAMBAH INI
        return signals
    
    _stats["prefilter_pass"] += 1
    logger.info(f"[DEBUG {symbol}] PREFILTER PASSED")  # <-- TAMBAH INI
    
    # Apply scoring
    try:
        score, max_score, reasons = score_bounce(cache)
    except Exception as e:
        logger.error(f"[DEBUG {symbol}] SCORING ERROR: {e}")
        return signals
    
    # Score gate
    ratio = score / max_score if max_score > 0 else 0
    if max_score == 0 or ratio < MIN_SCORE_RATIO:
        _stats["score_fail"] += 1
        logger.info(f"[DEBUG {symbol}] SCORE REJECTED: {score}/{max_score} ({ratio:.1%})")
        return signals
    
    _stats["score_ok"] += 1
    _stats["signals"] += 1
    logger.info(f"[DEBUG {symbol}] SIGNAL GENERATED: {score}/{max_score}")

    # ... (sisanya sama, msg building dll)

        return signals

    _stats["score_ok"] += 1
    _stats["signals"] += 1

    grade, badge = get_grade(score, max_score)

    # Target rebound calculation
    drop = abs(cache.drop_24h_pct) if cache.drop_24h_pct else 0
    target_10pct = cache.cc * 1.10
    target_50fib = cache.high_24h - (cache.high_24h - cache.low_24h) * 0.5 if cache.high_24h and cache.low_24h else None

    reason_text = "\n".join(reasons)

    msg = (
        f"🪙 <b>{symbol}</b> [{tf_label}]\n\n"
        f"💥 <b>BOUNCE SIGNAL</b> | {badge} Grade {grade} ({score}/{max_score})\n\n"
        f"📉 <b>Drop:</b> -{drop:.1f}% dalam 24h\n"
        f"💰 <b>Current Price:</b> {cache.cc:.6f}\n"
        f"📊 <b>RSI:</b> {cache.rsi_14:.1f} | <b>Vol:</b> {cache.vol_r:.1f}x avg\n"
        f"🕯️ <b>Candle:</b> Body +{cache.body:.1f}%, Lower Wick {cache.lower_wick:.1f}%\n\n"
        f"🎯 <b>Targets:</b>\n"
        f"   • +10% Rebound: {target_10pct:.6f}\n"
        f"   • 50% Fibonacci: {target_50fib:.6f if target_50fib else 'N/A'}\n"
        f"   • 24h High: {cache.high_24h:.6f if cache.high_24h else 'N/A'}\n\n"
        f"{reason_text}\n\n"
        f"⚠️ <b>Risk:</b> Set stop-loss di bawah {cache.low_24h:.6f if cache.low_24h else 'recent low'}"
    )

    signals.append((score, symbol, tf_label, msg))
    logger.info(f"[{symbol} {tf_label}] SIGNAL | Score={score}/{max_score} ({ratio:.1%}) | Drop=-{drop:.1f}%")

    return signals


def scan_all(client: BinanceClient, bot: TelegramBot) -> None:
    """Main scanning orchestrator for BOUNCE mode."""
    mode = load_mode()
    logger.info(f"Starting BOUNCE scan | Time: {datetime.now()}")

    # Reset stats
    for k in _stats:
        _stats[k] = 0

    # Step 1: Fetch 24h ticker data untuk filter drop
    try:
        ticker_data = client.get_24h_ticker()
        _stats["fetch_ticker_ok"] = 1
    except Exception as e:
        logger.critical(f"Failed to fetch 24h ticker: {e}")
        bot.send_error_alert(e)
        return

    # Step 2: Filter token yang drop 20-45% dan masih liquid
    bounce_candidates = []
    for item in ticker_data:
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue

        quote_vol = float(item.get("quoteVolume", 0))
        if quote_vol < 500_000:
            continue

        price_change_pct = float(item.get("priceChangePercent", 0))

        if price_change_pct > -MIN_DROP_PCT:
            continue
        if price_change_pct < -MAX_DROP_PCT:
            continue

        bounce_candidates.append((symbol, price_change_pct))

    _stats["pairs_total"] = len(bounce_candidates)
    _stats["drop_filtered"] = len(bounce_candidates)

    logger.info(f"Found {len(bounce_candidates)} candidates with {MIN_DROP_PCT}-{MAX_DROP_PCT}% drop in 24h")

    if not bounce_candidates:
        bot.send_message(f"📊 <b>BOUNCE Scan Complete</b>\nNo tokens found with {MIN_DROP_PCT}-{MAX_DROP_PCT}% drop today.")
        return

    all_signals: List[Tuple[int, str, str, str]] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scan_symbol, client, symbol, drop_pct): symbol 
            for symbol, drop_pct in bounce_candidates
        }

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
        f"Scan complete | Candidates: {_stats['drop_filtered']} | "
        f"Klines OK: {_stats['fetch_klines_ok']} | "
        f"Prefilter Pass: {_stats['prefilter_pass']} | "
        f"Score OK: {_stats['score_ok']} | "
        f"Final Signals: {_stats['signals']}"
    )

    # Send signals
    sent_count = 0
    for score, symbol, tf_label, msg in all_signals[:MAX_SIGNALS_PER_SCAN]:
        if bot.send_message(msg):
            sent_count += 1
            time.sleep(1)
        else:
            logger.warning(f"Failed to send signal for {symbol}")

    # Summary message
    summary = (
        f"📊 <b>BOUNCE Scan Summary</b>\n\n"
        f"Candidates scanned: {_stats['drop_filtered']}\n"
        f"Signals found: {_stats['signals']}\n"
        f"Signals sent: {sent_count}\n\n"
        f"Filters: Drop {MIN_DROP_PCT}-{MAX_DROP_PCT}% | 1h timeframe | Min score {MIN_SCORE_RATIO:.0%}"
    )
    bot.send_message(summary)

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
