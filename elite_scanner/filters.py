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
    """Hard filters for BOUNCE (mean reversion) mode."""

    # ── Filter 1: Drop dalam range yang aman ─────────────────────────────
    drop = cache.drop_24h_pct if cache.drop_24h_pct is not None else (drop_24h or 0)

    if drop > -MIN_DROP_PCT:      # Drop kurang dari 20%
        return False
    if drop < -MAX_DROP_PCT:      # Drop lebih dari 45% (death spiral)
        return False

    # ── Filter 2: Masih ada liquidity ────────────────────────────────────
    # Dilonggarkan: 0.3x cukup (volume bisa memang rendah saat dump selesai)
    if cache.vol_r < 0.3:
        return False

    # ── Filter 3: RSI oversold ────────────────────────────────────────────
    # Dilonggarkan: 45 (dari 40) — banyak bounce terjadi di RSI 40-45
    # Floor tetap 10 untuk hindari dead token
    if cache.rsi_14 is None:
        return False
    if cache.rsi_14 > 45:
        return False
    if cache.rsi_14 < 10:
        return False

    # ── Filter 4: Lower wick DIHAPUS sebagai hard filter ─────────────────
    # Token baru dump 20%+ di 1h candle sering belum punya wick panjang.
    # Wick sekarang jadi soft score di scoring.py, bukan hard reject.

    # ── Filter 5: above_ema9 DIHAPUS ──────────────────────────────────────
    # Token yang baru crash hampir tidak mungkin di atas EMA9.
    # Filter ini kontradiksi dengan strategi bounce — kalau udah above EMA9
    # berarti udah terlambat entry. EMA alignment masuk ke scoring saja.

    # ── Filter 6: Volatilitas masih ada ──────────────────────────────────
    # Dilonggarkan: 1.0% (dari 1.5%)
    if cache.atr_pct < 1.0:
        return False

    # ── Filter 7: Bukan death spiral ─────────────────────────────────────
    # Dilonggarkan: 10 candle merah (dari 8) — bisa jadi legit oversold
    if cache.consecutive_red >= 10:
        return False

    # ── Filter 8: Volume trend tidak collapsing total ─────────────────────
    # Dilonggarkan: 0.3x (dari 0.5x) — volume wajar drop setelah big dump
    if cache.vol_trend < 0.3:
        return False

    return True
