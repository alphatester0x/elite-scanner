"""Scoring engine for BOUNCE mode.

Each criterion adds points toward max_score.
Final score / max_score >= MIN_SCORE_RATIO to fire a signal.
"""
import logging
from typing import Tuple, List
from .indicators import IndicatorCache

logger = logging.getLogger(__name__)


def get_grade(score: int, max_score: int) -> Tuple[str, str]:
    """Letter grade + badge based on score ratio."""
    if max_score == 0:
        return "?", "⬜"
    ratio = score / max_score
    if ratio >= 0.85:
        return "S", "🟣"
    elif ratio >= 0.75:
        return "A", "🟡"
    elif ratio >= 0.65:
        return "B", "🟢"
    else:
        return "C", "🔵"


def score_bounce(cache: IndicatorCache) -> Tuple[int, int, List[str]]:
    """
    Score a symbol for bounce entry quality.
    Returns (score, max_score, reasons).
    """
    score     = 0
    max_score = 0
    reasons: List[str] = []

    # ── Core: drop magnitude ─────────────────────────────────────────────────
    # Bigger drop = more potential upside on bounce
    # -20% to -29%: 1pt | -30% to -39%: 2pts | -40%+: 3pts
    max_score += 3
    drop = abs(cache.drop_pct)
    if drop >= 40:
        score += 3
        reasons.append(f"🔥 Mega dump: -{drop:.1f}% dari 24h high (max bounce potential)")
    elif drop >= 30:
        score += 2
        reasons.append(f"💥 Dump besar: -{drop:.1f}% dari 24h high")
    else:
        score += 1
        reasons.append(f"📉 Drop -{drop:.1f}% dari 24h high (memenuhi syarat minimum)")

    # ── RSI depth ────────────────────────────────────────────────────────────
    # The lower the RSI the more oversold = higher bounce probability
    max_score += 2
    if cache.rsi_14 is not None:
        if cache.rsi_14 <= 20:
            score += 2
            reasons.append(f"✅ RSI ekstrem oversold: {cache.rsi_14:.1f} (sangat kuat)")
        elif cache.rsi_14 <= 28:
            score += 2
            reasons.append(f"✅ RSI oversold dalam: {cache.rsi_14:.1f}")
        else:
            score += 1
            reasons.append(f"⚠️ RSI oversold: {cache.rsi_14:.1f}")
    else:
        reasons.append("❌ RSI tidak tersedia")

    # ── RSI turning up ────────────────────────────────────────────────────────
    # RSI slope positive = momentum sudah mulai balik
    max_score += 2
    if cache.rsi_slope is not None:
        if cache.rsi_slope >= 3.0:
            score += 2
            reasons.append(f"✅ RSI mulai naik kuat (+{cache.rsi_slope:.1f} dalam 3 candle)")
        elif cache.rsi_slope >= 0.5:
            score += 1
            reasons.append(f"⚠️ RSI mulai naik tipis (+{cache.rsi_slope:.1f})")
        else:
            reasons.append(f"❌ RSI masih turun ({cache.rsi_slope:.1f})")
    else:
        reasons.append("❌ RSI slope tidak tersedia")

    # ── Stochastic ────────────────────────────────────────────────────────────
    max_score += 2
    if cache.stoch_k is not None and cache.stoch_d is not None:
        if cache.stoch_cross_up and cache.stoch_k < 25:
            score += 2
            reasons.append(f"✅ Stoch cross up di zona oversold (%K={cache.stoch_k:.1f})")
        elif cache.stoch_k < 20:
            score += 1
            reasons.append(f"⚠️ Stoch sangat oversold (%K={cache.stoch_k:.1f}, belum cross)")
        elif cache.stoch_k < 30:
            score += 1
            reasons.append(f"⚠️ Stoch oversold (%K={cache.stoch_k:.1f})")
        else:
            reasons.append(f"❌ Stoch belum oversold (%K={cache.stoch_k:.1f})")
    else:
        reasons.append("❌ Stochastic tidak tersedia")

    # ── MACD histogram ────────────────────────────────────────────────────────
    # Histogram mulai mengecil (momentum bearish melemah) = tanda reversal
    max_score += 2
    if cache.macd_line is not None and cache.hist_now is not None and cache.hist_prev is not None:
        hist_improving = cache.hist_now > cache.hist_prev  # histogram naik (less negative or positive)
        macd_bearish   = cache.macd_line < 0               # masih di bawah nol (wajar saat oversold)
        if hist_improving and macd_bearish:
            score += 2
            reasons.append(f"✅ MACD histogram membaik (momentum bearish melemah)")
        elif hist_improving:
            score += 1
            reasons.append(f"⚠️ MACD histogram naik tapi line sudah positif")
        else:
            reasons.append(f"❌ MACD histogram masih memburuk")
    else:
        reasons.append("❌ MACD tidak tersedia")

    # ── Lower wick / candle structure ────────────────────────────────────────
    # Panjang lower wick = buyers mulai masuk, tolak harga bawah
    max_score += 2
    if cache.lower_wick_pct >= 60:
        score += 2
        reasons.append(f"✅ Lower wick sangat panjang ({cache.lower_wick_pct:.0f}% dari range) — buyer rejection")
    elif cache.lower_wick_pct >= 40:
        score += 1
        reasons.append(f"⚠️ Lower wick sedang ({cache.lower_wick_pct:.0f}%)")
    else:
        reasons.append(f"❌ Lower wick pendek ({cache.lower_wick_pct:.0f}%) — belum ada buyer")

    # ── Bullish engulfing ─────────────────────────────────────────────────────
    max_score += 2
    if cache.bullish_engulfing:
        score += 2
        reasons.append("✅ Bullish engulfing candle — konfirmasi reversal kuat")
    else:
        reasons.append("➖ Tidak ada bullish engulfing (opsional)")

    # ── Volume on current candle ─────────────────────────────────────────────
    # Volume naik di candle terkini = buyers masuk
    max_score += 2
    if cache.vol_r >= 3.0:
        score += 2
        reasons.append(f"✅ Volume candle terkini sangat tinggi ({cache.vol_r:.1f}x avg)")
    elif cache.vol_r >= 1.8:
        score += 1
        reasons.append(f"⚠️ Volume candle terkini di atas rata-rata ({cache.vol_r:.1f}x)")
    else:
        reasons.append(f"❌ Volume candle terkini rendah ({cache.vol_r:.1f}x)")

    # ── Bollinger Band position ───────────────────────────────────────────────
    # Makin dekat / di bawah lower BB = makin oversold secara statistik
    max_score += 1
    if cache.bb_lower_dist_pct is not None:
        if cache.bb_lower_dist_pct <= 0:
            score += 1
            reasons.append(f"✅ Harga DI BAWAH lower Bollinger Band (extreme oversold)")
        else:
            reasons.append(f"➖ Harga {cache.bb_lower_dist_pct:.1f}% di atas lower BB")
    else:
        reasons.append("➖ Bollinger Band tidak tersedia")

    # ── Proximity to key MAs (bonus context) ─────────────────────────────────
    max_score += 1
    if cache.sma_200 and cache.cc < cache.sma_200:
        score += 1
        reasons.append(f"✅ Harga di bawah SMA200 — area support historis potensial")
    elif cache.sma_200:
        reasons.append(f"➖ Harga di atas SMA200 (bukan area support dalam)")
    else:
        reasons.append("➖ SMA200 tidak tersedia")

    return score, max_score, reasons
