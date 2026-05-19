"""Soft scoring engine for each trading mode.

All inputs come from IndicatorCache — zero redundant computation.
"""
import logging
from typing import List, Tuple, Optional
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


def score_elite(cache: IndicatorCache) -> Tuple[int, int, List[str]]:
    reasons = []
    score = 0
    max_score = 0

    # [2pts] Golden Cross Structure
    max_score += 2
    if cache.ema_50 and cache.ema_200 and cache.ema_50 > cache.ema_200:
        score += 2
        reasons.append("✅ EMA50 > EMA200 (Golden Structure)")
    else:
        reasons.append("❌ EMA50 < EMA200 (No Uptrend)")

    # [2pts] Price vs MA200
    max_score += 2
    if cache.sma_200:
        pct = (cache.cc / cache.sma_200 - 1) * 100
        if cache.cc > cache.sma_200 * 1.02:
            score += 2
            reasons.append(f"✅ Price > MA200 +{pct:.1f}%")
        elif cache.cc > cache.sma_200:
            score += 1
            reasons.append(f"⚠️ Price > MA200 +{pct:.1f}% (tipis)")
        else:
            reasons.append("❌ Price di bawah MA200")
    else:
        reasons.append("❌ Price di bawah MA200")

    # [1pt] MA200 Slope (FIXED)
    max_score += 1
    if cache.sma_200 and cache.sma_200_prev and cache.sma_200 > cache.sma_200_prev:
        pct = (cache.sma_200 / cache.sma_200_prev - 1) * 100
        score += 1
        reasons.append(f"✅ MA200 Slope Naik (+{pct:.2f}%)")
    else:
        reasons.append("❌ MA200 Slope Datar/Turun")

    # [2pts] ADX Strength
    max_score += 2
    if cache.adx_14 and cache.plus_di and cache.minus_di:
        if cache.adx_14 >= 30 and cache.plus_di > cache.minus_di:
            score += 2
            reasons.append(f"✅ ADX {cache.adx_14:.1f} Kuat | +DI {cache.plus_di:.1f} > -DI {cache.minus_di:.1f}")
        elif cache.adx_14 >= 25 and cache.plus_di > cache.minus_di:
            score += 1
            reasons.append(f"⚠️ ADX {cache.adx_14:.1f} Cukup | +DI {cache.plus_di:.1f} > -DI {cache.minus_di:.1f}")
        else:
            reasons.append(f"❌ ADX {cache.adx_14:.1f} Lemah atau -DI Dominan")
    else:
        reasons.append("❌ ADX tidak tersedia")

    # [2pts] MACD
    # FIX Bug #3: use `is not None` — macd_line can be 0.0 or negative (falsy but valid)
    max_score += 2
    if cache.macd_line is not None and cache.signal_line is not None and cache.hist_now is not None and cache.hist_prev is not None:
        if cache.macd_line > cache.signal_line and cache.hist_now > cache.hist_prev:
            score += 2
            reasons.append(f"✅ MACD Bullish & Histogram Membesar ({cache.hist_now:.6f})")
        elif cache.macd_line > cache.signal_line:
            score += 1
            reasons.append("⚠️ MACD Bullish tapi Histogram Menyusut")
        else:
            reasons.append("❌ MACD Bearish")
    else:
        reasons.append("❌ MACD tidak tersedia")

    # [2pts] Volume
    max_score += 2
    if cache.vol_r >= 3.0:
        score += 2
        reasons.append(f"✅ Volume Surge {cache.vol_r:.1f}x avg (Sangat Kuat)")
    elif cache.vol_r >= 2.0:
        score += 1
        reasons.append(f"⚠️ Volume {cache.vol_r:.1f}x avg (Cukup)")
    else:
        reasons.append(f"❌ Volume {cache.vol_r:.1f}x avg (Lemah)")

    # [1pt] Candle Body
    max_score += 1
    if cache.body >= 1.2:
        score += 1
        reasons.append(f"✅ Bullish Body +{cache.body:.1f}%")
    else:
        reasons.append(f"❌ Body Lemah {cache.body:.1f}%")

    # [1pt] RSI
    max_score += 1
    if cache.rsi_14:
        if 55 <= cache.rsi_14 <= 70:
            score += 1
            reasons.append(f"✅ RSI {cache.rsi_14:.1f} (Ideal Zone)")
        elif cache.rsi_14 <= 55:
            reasons.append(f"⚠️ RSI {cache.rsi_14:.1f} (Momentum Belum Kuat)")
        else:
            reasons.append(f"⚠️ RSI {cache.rsi_14:.1f} (Mendekati Overbought)")

    # [1pt] ATR
    max_score += 1
    if cache.atr_pct >= 2.5:
        score += 1
        reasons.append(f"✅ ATR {cache.atr_pct:.1f}% (Volatilitas Baik)")
    else:
        reasons.append(f"⚠️ ATR {cache.atr_pct:.1f}% (Volatilitas Rendah)")

    return score, max_score, reasons


def score_swing(cache: IndicatorCache) -> Tuple[int, int, List[str]]:
    reasons = []
    score = 0
    max_score = 0

    # [2pts] Trend Structure
    max_score += 2
    if cache.ema_50 and cache.ema_200 and cache.ema_50 > cache.ema_200 and cache.sma_200 and cache.cc > cache.sma_200:
        score += 2
        reasons.append("✅ Uptrend Kuat (EMA50 > EMA200, Price > MA200)")
    elif cache.ema_50 and cache.ema_200 and cache.ema_50 > cache.ema_200:
        score += 1
        reasons.append("⚠️ Uptrend Parsial (EMA50 > EMA200 tapi Price < MA200)")
    else:
        reasons.append("❌ Tidak Ada Uptrend")

    # [2pts] Pullback ke Support
    max_score += 2
    if cache.near_ema_21 and cache.near_sma_50:
        score += 2
        reasons.append("✅ Pullback ke EMA21 & MA50 (Double Support)")
    elif cache.near_ema_21:
        e21_dist = (cache.cc / cache.ema_21 - 1) * 100 if cache.ema_21 else 0
        score += 2
        reasons.append(f"✅ Pullback ke EMA21 ({e21_dist:+.1f}%)")
    elif cache.near_sma_50:
        ma50_dist = (cache.cc / cache.sma_50 - 1) * 100 if cache.sma_50 else 0
        score += 2
        reasons.append(f"✅ Pullback ke MA50 ({ma50_dist:+.1f}%)")
    else:
        e21_dist  = abs(cache.cc - cache.ema_21) / cache.ema_21 * 100 if cache.ema_21 else 999
        ma50_dist = abs(cache.cc - cache.sma_50) / cache.sma_50 * 100 if cache.sma_50 else 999
        reasons.append(f"❌ Jauh dari Support (EMA21: {e21_dist:.1f}%, MA50: {ma50_dist:.1f}%)")

    # [1pt] RSI Pullback Zone
    max_score += 1
    if cache.rsi_14 and 42 <= cache.rsi_14 <= 62:
        score += 1
        reasons.append(f"✅ RSI {cache.rsi_14:.1f} (Pullback Zone Sehat)")
    elif cache.rsi_14:
        reasons.append(f"⚠️ RSI {cache.rsi_14:.1f} ({'Oversold' if cache.rsi_14 < 42 else 'Terlalu Panas'})")

    # [2pts] Reversal Candle
    max_score += 2
    if cache.lower_wick >= 2.0 and cache.body > 0:
        score += 2
        reasons.append(f"✅ Hammer Kuat: Wick {cache.lower_wick:.1f}%, Body +{cache.body:.1f}%")
    elif cache.lower_wick >= 0.8:
        score += 1
        reasons.append(f"⚠️ Lower Wick {cache.lower_wick:.1f}% (Lemah)")
    else:
        reasons.append("❌ Tidak Ada Reversal Candle")

    # [1pt] Bollinger Band
    max_score += 1
    if cache.bb_mid and cache.cc > cache.bb_mid:
        score += 1
        reasons.append("✅ Price di Atas BB Mid (Support Dinamis)")
    else:
        reasons.append("❌ Price di Bawah BB Mid")

    # [1pt] ADX
    max_score += 1
    if cache.adx_14 and cache.adx_14 >= 20:
        score += 1
        reasons.append(f"✅ ADX {cache.adx_14:.1f} (Trend Masih Hidup)")
    else:
        reasons.append(f"⚠️ ADX {cache.adx_14:.1f if cache.adx_14 else '?'} (Trend Lemah)")

    # [1pt] Volume Pullback
    max_score += 1
    if 0.5 <= cache.vol_r <= 1.5:
        score += 1
        reasons.append(f"✅ Volume Pullback Normal {cache.vol_r:.1f}x (Sehat)")
    elif cache.vol_r > 1.5:
        reasons.append(f"⚠️ Volume Tinggi Saat Pullback {cache.vol_r:.1f}x (Waspadai)")
    else:
        reasons.append(f"⚠️ Volume Sangat Sepi {cache.vol_r:.1f}x")

    return score, max_score, reasons


def score_scalp(cache: IndicatorCache, htf_cache: Optional[IndicatorCache] = None) -> Tuple[int, int, List[str]]:
    reasons = []
    score = 0
    max_score = 0

    # [3pts] EMA Cross
    max_score += 3
    if cache.cross_up_9_21:
        score += 3
        reasons.append("✅ EMA9 Cross EMA21 ke Atas (Fresh Signal!)")
    elif cache.ema_series_9 and cache.ema_series_21 and cache.ema_series_9[-1] > cache.ema_series_21[-1]:
        score += 1
        reasons.append("⚠️ EMA9 > EMA21 (Cross sudah lama, bukan fresh)")
    else:
        reasons.append("❌ EMA9 < EMA21 (Bearish)")

    # [2pts] HTF Filter
    max_score += 2
    if htf_cache is not None:
        if htf_cache.ema_50 and htf_cache.ema_200:
            if htf_cache.ema_50 > htf_cache.ema_200:
                score += 2
                reasons.append("✅ HTF 1H Bullish (EMA50 > EMA200)")
            else:
                reasons.append("❌ HTF 1H Bearish (Scalp Melawan Trend)")
        if htf_cache.rsi_14:
            reasons.append(f"ℹ️ HTF RSI: {htf_cache.rsi_14:.1f}")
    else:
        score += 1
        reasons.append("ℹ️ HTF data tidak tersedia")

    # [2pts] MACD
    # FIX Bug #3: use `is not None` — macd_line can be 0.0 or negative (falsy but valid)
    max_score += 2
    if cache.macd_line is not None and cache.signal_line is not None and cache.hist_now is not None and cache.hist_prev is not None:
        if cache.macd_line > cache.signal_line and cache.hist_now > cache.hist_prev:
            score += 2
            reasons.append("✅ MACD Bullish & Accelerating")
        elif cache.macd_line > cache.signal_line:
            score += 1
            reasons.append("⚠️ MACD Bullish tapi Melambat")
        else:
            reasons.append("❌ MACD Bearish")
    else:
        reasons.append("❌ MACD tidak tersedia")

    # [1pt] Stochastic
    max_score += 1
    # FIX Bug #4: use `is not None` — stoch_k can be 0.0 (falsy but valid)
    if cache.stoch_k is not None and cache.stoch_d is not None:
        if 25 <= cache.stoch_k <= 70 and cache.stoch_k > cache.stoch_d:
            score += 1
            reasons.append(f"✅ Stoch %K {cache.stoch_k:.1f} > %D {cache.stoch_d:.1f} (Bullish)")
        else:
            reasons.append(f"⚠️ Stoch %K {cache.stoch_k:.1f} | %D {cache.stoch_d:.1f}")

    # [1pt] Volume
    max_score += 1
    if cache.vol_r >= 2.5:
        score += 1
        reasons.append(f"✅ Volume Surge {cache.vol_r:.1f}x")
    elif cache.vol_r >= 1.8:
        score += 1
        reasons.append(f"⚠️ Volume {cache.vol_r:.1f}x (Cukup)")
    else:
        reasons.append(f"❌ Volume Lemah {cache.vol_r:.1f}x")

    # [1pt] RSI
    max_score += 1
    if cache.rsi_14 and 48 <= cache.rsi_14 <= 72:
        score += 1
        reasons.append(f"✅ RSI {cache.rsi_14:.1f} (Momentum Zone)")
    elif cache.rsi_14:
        reasons.append(f"⚠️ RSI {cache.rsi_14:.1f}")

    return score, max_score, reasons
