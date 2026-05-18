"""Hard pre-filters for each trading mode.

Separates mandatory criteria (fast reject) from soft scoring (grade).
"""
import logging
from typing import Optional
from .indicators import IndicatorCache

logger = logging.getLogger(__name__)


def prefilter_elite(cache: IndicatorCache) -> bool:
    """Hard filters for ELITE mode."""
    # Trend structure
    if not (cache.ema_50 and cache.ema_200 and cache.ema_50 > cache.ema_200):
        return False
    if not (cache.sma_200 and cache.cc > cache.sma_200 * 1.01):
        return False

    # MA200 slope (FIXED: compare current vs previous candle)
    if not (cache.sma_200_prev and cache.sma_200 > cache.sma_200_prev):
        return False

    # ADX strength
    if not cache.adx_14 or cache.adx_14 < 25:
        return False
    if cache.plus_di and cache.minus_di and cache.plus_di <= cache.minus_di:
        return False

    # MACD bullish & accelerating
    if cache.macd_line is None or cache.macd_line <= (cache.signal_line or 0):
        return False
    if cache.hist_prev is None or cache.hist_now <= cache.hist_prev:
        return False

    # Volume
    if cache.vol_r < 2.0:
        return False

    # Candle body
    if cache.body < 1.2:
        return False

    # RSI not overbought
    if cache.rsi_14 and cache.rsi_14 > 75:
        return False

    # ATR volatility
    if cache.atr_pct < 2.5:
        return False

    # Golden-cross confirmation: previous close below prev MA200, current above
    if not (cache.pc and cache.sma_200_prev and cache.pc < cache.sma_200_prev and cache.cc > cache.sma_200):
        return False

    return True


def prefilter_swing(cache: IndicatorCache) -> bool:
    """Hard filters for SWING mode."""
    # Trend structure
    if not all([cache.sma_50, cache.sma_200, cache.ema_21, cache.ema_50, cache.ema_200]):
        return False
    if not (cache.ema_50 > cache.ema_200 and cache.cc > cache.sma_200):
        return False

    # Pullback to support
    if not (cache.near_ema_21 or cache.near_sma_50):
        return False

    # RSI pullback zone
    if cache.rsi_14 is None or not (42 <= cache.rsi_14 <= 62):
        return False

    # Bollinger support
    if cache.bb_mid and cache.cc < cache.bb_mid:
        return False

    # Reversal candle
    if cache.lower_wick < 0.8:
        return False

    # Not too bearish body
    if cache.body < -1.5:
        return False

    # Volume not suspiciously high
    if cache.vol_r > 3.0:
        return False

    # ADX alive
    if cache.adx_14 and cache.adx_14 < 20:
        return False

    return True


def prefilter_scalp(cache: IndicatorCache, htf_cache: Optional[IndicatorCache] = None) -> bool:
    """Hard filters for SCALP mode.

    htf_cache: IndicatorCache for higher timeframe (1h) data — reused from
    the 1h timeframe fetch, eliminating the N+1 extra HTTP request problem.
    """
    # EMA cross
    if not cache.cross_up_9_21:
        return False

    # HTF filter — only when 15m and HTF data available
    if htf_cache is not None:
        if htf_cache.ema_50 and htf_cache.ema_200:
            if htf_cache.ema_50 < htf_cache.ema_200:
                return False

    # MACD bullish
    if cache.macd_line is None or cache.macd_line <= (cache.signal_line or 0):
        return False

    # Stochastic zone
    if cache.stoch_k is None or not (25 <= cache.stoch_k <= 70):
        return False

    # Volume
    if cache.vol_r < 1.8:
        return False

    # Body
    if cache.body < 0.6:
        return False

    # ATR
    if cache.atr_pct < 0.8:
        return False

    # RSI
    if cache.rsi_14 is None or not (48 <= cache.rsi_14 <= 72):
        return False

    return True
