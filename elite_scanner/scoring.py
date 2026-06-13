"""Soft scoring engine for BOUNCE mode.

Scoring menilai kualitas setup mean reversion:
- Semakin dalam drop = semakin besar potential reward
- Semakin bagus reversal candle = semakin tinggi probability
- Volume confirmation = kekuatan bounce
"""
import logging
from typing import List, Tuple
from .indicators import IndicatorCache

logger = logging.getLogger(__name__)


def get_grade(score: int, max_score: int) -> Tuple[str, str]:
    ratio = score / max_score if max_score > 0 else 0
    if ratio >= 0.85:
        return "A+", "🏆"
    elif ratio >= 0.75:
        return "A", "🥇"
    elif ratio >= 0.65:
        return "B+", "🥈"
    elif ratio >= 0.55:
        return "B", "🥉"
    else:
        return "C", "⚠️"


def score_bounce(cache: IndicatorCache) -> Tuple[int, int, List[str]]:
    """Score BOUNCE setup.

    Returns: (score, max_score, reasons)
    """
    reasons = []
    score = 0
    max_score = 0

    # ── [3pts] Drop Depth ────────────────────────────────────────────────
    # Drop 20-25% = 1pt, 25-35% = 2pt, 35-45% = 3pt
    max_score += 3
    drop = abs(cache.drop_24h_pct) if cache.drop_24h_pct else 0
    if drop >= 35:
        score += 3
        reasons.append(f"✅ Deep Crash -{drop:.1f}% (High Rebound Potential)")
    elif drop >= 25:
        score += 2
        reasons.append(f"⚠️ Significant Drop -{drop:.1f}% (Good Rebound Potential)")
    elif drop >= 20:
        score += 1
        reasons.append(f"⚠️ Moderate Drop -{drop:.1f}% (Some Rebound Potential)")
    else:
        reasons.append(f"❌ Drop too shallow -{drop:.1f}%")

    # ── [2pts] Reversal Candle Quality ───────────────────────────────────
    max_score += 2
    if cache.body > 2.0 and cache.lower_wick >= 2.0:
        score += 2
        reasons.append(f"✅ Strong Hammer: Body +{cache.body:.1f}%, Wick {cache.lower_wick:.1f}%")
    elif cache.body > 0 and cache.lower_wick >= 1.5:
        score += 1
        reasons.append(f"⚠️ Moderate Reversal: Body +{cache.body:.1f}%, Wick {cache.lower_wick:.1f}%")
    elif cache.body > 0:
        reasons.append(f"⚠️ Weak Bullish Body +{cache.body:.1f}%")
    else:
        reasons.append(f"❌ Bearish Body {cache.body:.1f}%")

    # ── [2pts] RSI Condition ─────────────────────────────────────────────
    max_score += 2
    if cache.rsi_14 is not None:
        if 15 <= cache.rsi_14 <= 25:
            score += 2
            reasons.append(f"✅ Deep Oversold RSI {cache.rsi_14:.1f} (Strong Bounce Zone)")
        elif 25 < cache.rsi_14 <= 35:
            score += 1
            reasons.append(f"⚠️ Oversold RSI {cache.rsi_14:.1f} (Bounce Possible)")
        elif cache.rsi_14 < 15:
            reasons.append(f"❌ Extreme RSI {cache.rsi_14:.1f} (Token May Be Dead)")
        else:
            reasons.append(f"❌ RSI {cache.rsi_14:.1f} (Not Oversold)")
    else:
        reasons.append("❌ RSI tidak tersedia")

    # ── [2pts] Volume Confirmation ───────────────────────────────────────
    max_score += 2
    if cache.vol_r >= 3.0:
        score += 2
        reasons.append(f"✅ Volume Surge {cache.vol_r:.1f}x (Strong Interest)")
    elif cache.vol_r >= 2.0:
        score += 1
        reasons.append(f"⚠️ Volume Spike {cache.vol_r:.1f}x (Moderate Interest)")
    elif cache.vol_r >= 1.0:
        reasons.append(f"⚠️ Volume Normal {cache.vol_r:.1f}x")
    else:
        reasons.append(f"❌ Volume Dry {cache.vol_r:.1f}x (No Interest)")

    # ── [1pt] Volume Trend ───────────────────────────────────────────────
    max_score += 1
    if cache.vol_trend >= 1.5:
        score += 1
        reasons.append(f"✅ Volume Increasing {cache.vol_trend:.1f}x (Accumulation)")
    else:
        reasons.append(f"⚠️ Volume Trend {cache.vol_trend:.1f}x")

    # ── [2pts] EMA Alignment ─────────────────────────────────────────────
    max_score += 2
    if cache.above_ema21 and cache.above_ema9:
        score += 2
        reasons.append("✅ Price Above EMA9 & EMA21 (Bullish Micro Structure)")
    elif cache.above_ema9:
        score += 1
        reasons.append("⚠️ Price Above EMA9 Only (Early Reversal)")
    else:
        reasons.append("❌ Price Below EMA9 (Still Weak)")
    # Extra point: price above EMA50 as additional bullish confirmation
    if cache.above_ema50:
        score += 1
        reasons.append("✅ Price Also Above EMA50 (Strong Trend)")


    # ── [1pt] EMA Cross ──────────────────────────────────────────────────
    max_score += 1
    if cache.cross_up_9_21:
        score += 1
        reasons.append("✅ Fresh EMA9 Cross Above EMA21 (Momentum Shift)")
    else:
        reasons.append("⚠️ No Fresh EMA Cross")

    # ── [1pt] MACD ───────────────────────────────────────────────────────
    max_score += 1
    if cache.macd_line is not None and cache.signal_line is not None:
        if cache.macd_line > cache.signal_line and cache.hist_now is not None and cache.hist_prev is not None and cache.hist_now > cache.hist_prev:
            score += 1
            reasons.append("✅ MACD Bullish & Histogram Growing")
        elif cache.macd_line > cache.signal_line:
            reasons.append("⚠️ MACD Bullish but Flat")
        else:
            reasons.append("❌ MACD Bearish")
    else:
        reasons.append("❌ MACD tidak tersedia")

    # ── [1pt] ATR / Volatility ───────────────────────────────────────────
    max_score += 1
    if cache.atr_pct >= 3.0:
        score += 1
        reasons.append(f"✅ High Volatility ATR {cache.atr_pct:.1f}% (Big Moves Possible)")
    elif cache.atr_pct >= 1.5:
        reasons.append(f"⚠️ Moderate Volatility ATR {cache.atr_pct:.1f}%")
    else:
        reasons.append(f"❌ Low Volatility ATR {cache.atr_pct:.1f}%")

    # ── [1pt] Bollinger Band ─────────────────────────────────────────────
    max_score += 1
    if cache.bb_lower and cache.cc <= cache.bb_lower * 1.02:
        score += 1
        reasons.append("✅ Price at/near BB Lower Band (Statistical Extreme)")
    elif cache.bb_lower and cache.cc <= cache.bb_lower * 1.05:
        reasons.append("⚠️ Price Near BB Lower")
    else:
        reasons.append("❌ Price Not at BB Lower")

    return score, max_score, reasons
