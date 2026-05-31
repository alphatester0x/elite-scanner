"""Hard pre-filters for BOUNCE mode.

BOUNCE strategy: mean reversion pada token yang crash 20-45% dalam 24h.
Filter memastikan token masih "hidup" dan menunjukkan tanda reversal.
"""
import logging
from typing import Optional
from .indicators import IndicatorCache
from .config import MIN_DROP_PCT, MAX_DROP_PCT

logger = logging.getLogger(__name__)


def prefilter_bounce(cache: IndicatorCache, drop_24h: Optional[float] = None) -> bool:
    """Hard filters for BOUNCE (mean reversion) mode.

    Args:
        cache: IndicatorCache dari timeframe 1h
        drop_24h: Drop percentage dari 24h ticker (fallback kalau cache tidak tersedia)

    Returns:
        True jika token lolos semua filter hard
    """
    # ── Filter 1: Drop dalam range yang aman ──────────────────────────────
    # Drop harus signifikan tapi tidak terlalu ekstrem (death spiral)
    drop = cache.drop_24h_pct if cache.drop_24h_pct is not None else (drop_24h or 0)

    if drop > -MIN_DROP_PCT:  # Drop kurang dari 20% (misal -15%)
        return False
    if drop < -MAX_DROP_PCT:  # Drop lebih dari 45% (too risky)
        return False

    # ── Filter 2: Masih ada liquidity ────────────────────────────────────
    if cache.vol_r < 1.0:
        return False

    # ── Filter 3: RSI oversold tapi tidak dead ───────────────────────────
    # RSI < 35 = oversold (bounce potential)
    # RSI < 15 = dead token (avoid)
    if cache.rsi_14 is None:
        return False
    if cache.rsi_14 > 40:  # Belum oversold
        return False
    if cache.rsi_14 < 10:  # Token sudah mati
        return False

    # ── Filter 4: Candle structure menunjukkan rejection ────────────────
    # Lower wick > 1% = buyer stepping in
    if cache.lower_wick < 1.0:
        return False

    # ── Filter 5: Price sudah di atas EMA9 (micro momentum bullish) ──────
    # Ini menandakan reversal sudah mulai, bukan masih free fall
    if not cache.above_ema9:
        return False

    # ── Filter 6: Volatilitas masih ada ──────────────────────────────────
    if cache.atr_pct < 1.5:
        return False

    # ── Filter 7: Bukan death spiral (consecutive red < 8) ───────────────
    if cache.consecutive_red >= 8:
        return False

    # ── Filter 8: Volume trend tidak collapsing ──────────────────────────
    if cache.vol_trend < 0.5:
        return False

    return True
