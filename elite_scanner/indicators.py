"""Technical indicators with pre-computation cache."""
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def sma(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """RSI with Wilder's Smoothing."""
    if len(closes) < n + 2:
        return None
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains  = [x if x > 0 else 0 for x in deltas]
    losses = [-x if x < 0 else 0 for x in deltas]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for i in range(n, len(deltas)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def rsi_series(closes: List[float], n: int = 14) -> List[float]:
    """Full RSI series for slope detection."""
    if len(closes) < n + 2:
        return []
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains  = [x if x > 0 else 0 for x in deltas]
    losses = [-x if x < 0 else 0 for x in deltas]
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    result = []
    if avg_loss == 0:
        result.append(100.0)
    else:
        result.append(100 - (100 / (1 + avg_gain / avg_loss)))
    for i in range(n, len(deltas)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        if avg_loss == 0:
            result.append(100.0)
        else:
            result.append(100 - (100 / (1 + avg_gain / avg_loss)))
    return result


def ema(closes: List[float], n: int) -> Optional[float]:
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    v = sum(closes[:n]) / n
    for x in closes[n:]:
        v = x * k + v * (1 - k)
    return v


def ema_series(closes: List[float], n: int) -> List[float]:
    if len(closes) < n:
        return []
    k = 2 / (n + 1)
    result = [sum(closes[:n]) / n]
    for x in closes[n:]:
        result.append(x * k + result[-1] * (1 - k))
    return result


def atr(highs: List[float], lows: List[float], closes: List[float], n: int = 14) -> Optional[float]:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        trs.append(tr)
    atr_val = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr_val = (atr_val * (n - 1) + tr) / n
    return atr_val


def bollinger(closes: List[float], n: int = 20, k: int = 2) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Returns (upper, mid, lower)."""
    if len(closes) < n:
        return None, None, None
    mid = sma(closes, n)
    if mid is None:
        return None, None, None
    std = (sum((c - mid) ** 2 for c in closes[-n:]) / n) ** 0.5
    return mid + k * std, mid, mid - k * std


def stochastic(highs: List[float], lows: List[float], closes: List[float], k: int = 14, d: int = 3) -> Tuple[Optional[float], Optional[float]]:
    """Returns (%K, %D)."""
    if len(closes) < k + d:
        return None, None
    k_vals = []
    for i in range(k, len(closes) + 1):
        h = max(highs[i - k:i])
        l = min(lows[i - k:i])
        c = closes[i - 1]
        if (h - l) != 0:
            k_vals.append(100 * (c - l) / (h - l))
    if len(k_vals) < d:
        return None, None
    d_val = sum(k_vals[-d:]) / d
    return k_vals[-1], d_val


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """Returns (macd_line, signal_line, hist_now, hist_prev)."""
    if len(closes) < slow + signal + 1:
        return None, None, None, None
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    diff = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[diff:]
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    if len(macd_line) < signal + 1:
        return None, None, None, None
    signal_line = ema_series(macd_line, signal)
    diff_len = len(macd_line) - len(signal_line)
    macd_line_trim = macd_line[diff_len:]
    histogram = [m - s for m, s in zip(macd_line_trim, signal_line)]
    if len(histogram) < 2:
        return None, None, None, None
    return macd_line_trim[-1], signal_line[-1], histogram[-1], histogram[-2]


class IndicatorCache:
    """
    Pre-computes all indicators once per symbol.
    Also computes bounce-specific metrics: 24h drop, RSI slope, etc.
    """

    def __init__(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        vols: List[float],
        lookback: int = 24,
    ):
        self.opens   = opens
        self.highs   = highs
        self.lows    = lows
        self.closes  = closes
        self.vols    = vols
        self.lookback = lookback

        self.cc = closes[-1]   # current close
        self.co = opens[-1]    # current open
        self.cl = lows[-1]
        self.ch = highs[-1]
        self.pc = closes[-2] if len(closes) >= 2 else None

        self._compute()

    def _compute(self) -> None:
        # ── Bounce core: 24h drop ────────────────────────────────
        # Look at the last `lookback` candles (excluding current) for the high
        window_highs  = self.highs[-(self.lookback + 1):-1]
        self.high_24h = max(window_highs) if window_highs else self.ch

        # % drop from that high to current close
        if self.high_24h > 0:
            self.drop_pct = (self.cc - self.high_24h) / self.high_24h * 100
        else:
            self.drop_pct = 0.0

        # ── Momentum ─────────────────────────────────────────────
        self.rsi_14  = rsi(self.closes, 14)

        # RSI slope: is RSI turning up? (current vs 3 candles ago)
        rsi_s = rsi_series(self.closes, 14)
        self.rsi_slope = None
        if len(rsi_s) >= 4:
            self.rsi_slope = rsi_s[-1] - rsi_s[-4]   # positive = turning up

        self.stoch_k, self.stoch_d = stochastic(self.highs, self.lows, self.closes, 14, 3)

        # Stoch cross up: %K crossed above %D
        self.stoch_cross_up = False
        if self.stoch_k is not None and self.stoch_d is not None:
            # Check previous stoch values
            if len(self.closes) >= 18:
                prev_k, prev_d = stochastic(self.highs[:-1], self.lows[:-1], self.closes[:-1], 14, 3)
                if prev_k is not None and prev_d is not None:
                    self.stoch_cross_up = (prev_k <= prev_d) and (self.stoch_k > self.stoch_d)

        self.macd_line, self.signal_line, self.hist_now, self.hist_prev = macd(self.closes)

        # ── Volume ───────────────────────────────────────────────
        self.avg_vol = sum(self.vols[-21:-1]) / 20 if len(self.vols) > 21 else 0
        self.vol_r   = self.vols[-1] / self.avg_vol if self.avg_vol > 0 else 0

        # Volume during the drop window (avg of lookback candles)
        drop_vols = self.vols[-(self.lookback + 1):-1]
        avg_drop_vol = sum(drop_vols) / len(drop_vols) if drop_vols else 0
        self.drop_vol_r = avg_drop_vol / self.avg_vol if self.avg_vol > 0 else 0

        # ── Bollinger Bands ──────────────────────────────────────
        self.bb_upper, self.bb_mid, self.bb_lower = bollinger(self.closes, 20, 2)

        # Distance from lower BB (positive = above lower band)
        self.bb_lower_dist_pct = None
        if self.bb_lower and self.bb_lower > 0:
            self.bb_lower_dist_pct = (self.cc - self.bb_lower) / self.bb_lower * 100

        # ── Moving averages (for context) ────────────────────────
        self.ema_21  = ema(self.closes, 21)
        self.sma_50  = sma(self.closes, 50)
        self.sma_200 = sma(self.closes, 200)

        # ── ATR ──────────────────────────────────────────────────
        self.atr_14  = atr(self.highs, self.lows, self.closes, 14)
        self.atr_pct = (self.atr_14 / self.cc * 100) if self.atr_14 and self.cc else 0

        # ── Candle structure ─────────────────────────────────────
        self.body = (self.cc - self.co) / self.co * 100 if self.co != 0 else 0

        # Lower wick ratio — long lower wick = rejection / buyer interest
        candle_range = self.ch - self.cl
        lower_wick_abs = min(self.co, self.cc) - self.cl
        self.lower_wick_pct = (lower_wick_abs / candle_range * 100) if candle_range > 0 else 0

        # ── Engulfing candle detection ────────────────────────────
        # Bullish engulfing: current candle is green and body engulfs previous candle
        self.bullish_engulfing = False
        if self.pc is not None and len(self.opens) >= 2:
            prev_open  = self.opens[-2]
            prev_close = self.closes[-2]
            if (self.cc > self.co and          # current green
                    prev_close < prev_open and     # previous red
                    self.co <= prev_close and       # current opens at/below prev close
                    self.cc >= prev_open):          # current closes at/above prev open
                self.bullish_engulfing = True
