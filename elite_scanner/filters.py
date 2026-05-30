"""Hard pre-filters for bounce detection.

Fast-reject layer — eliminates symbols before expensive scoring.
A symbol that passes all filters here is a candidate for bounce entry.
"""
import logging
from .indicators import IndicatorCache
from .config import (
    MIN_DROP_PCT,
    RSI_MAX,
    VOL_RATIO_MIN,
    BB_LOWER_BUFFER,
    MAX_BEAR_BODY_PCT,
)

logger = logging.getLogger(__name__)


def prefilter_bounce(cache: IndicatorCache) -> tuple[bool, str]:
    """
    Hard filters for BOUNCE mode.
    Returns (passed: bool, reject_reason: str).
    reject_reason is empty string if passed.
    """

    # 1. MUST have dropped >= MIN_DROP_PCT from the 24h high
    #    This is the core condition of the entire strategy.
    if cache.drop_pct > -MIN_DROP_PCT:
        return False, f"drop={cache.drop_pct:.1f}% < -{MIN_DROP_PCT}%"

    # 2. RSI must be in oversold territory — confirms price exhaustion
    if cache.rsi_14 is None or cache.rsi_14 > RSI_MAX:
        rsi_str = f"{cache.rsi_14:.1f}" if cache.rsi_14 is not None else "None"
        return False, f"RSI={rsi_str} > {RSI_MAX} (not oversold)"

    # 3. Volume confirmation — the drop must have happened on real selling
    #    pressure, not just thin air. Protects against slow bleeds.
    if cache.drop_vol_r < VOL_RATIO_MIN:
        return False, f"drop_vol_r={cache.drop_vol_r:.2f}x < {VOL_RATIO_MIN}x"

    # 4. Price near lower Bollinger Band — confirms extreme overextension
    if cache.bb_lower_dist_pct is None or cache.bb_lower_dist_pct > BB_LOWER_BUFFER * 100:
        dist_str = f"{cache.bb_lower_dist_pct:.1f}%" if cache.bb_lower_dist_pct is not None else "None"
        return False, f"bb_lower_dist={dist_str} > {BB_LOWER_BUFFER*100:.0f}% (too far from lower BB)"

    # 5. Latest candle not still crashing hard
    #    A massive red body on the latest candle means the dump is not done.
    if cache.body < MAX_BEAR_BODY_PCT:
        return False, f"body={cache.body:.1f}% < {MAX_BEAR_BODY_PCT}% (still crashing)"

    # 6. ATR sanity — must have some volatility (avoid dead coins)
    if cache.atr_pct < 0.5:
        return False, f"atr_pct={cache.atr_pct:.2f}% < 0.5% (no volatility)"

    return True, ""
