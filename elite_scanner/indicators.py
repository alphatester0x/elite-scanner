"""Technical indicators with pre-computation cache."""
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def sma(closes: List[float], n: int) -> Optional[float]:
    """Simple Moving Average."""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """RSI with Wilder's Smoothing (industry standard)."""
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


def ema(closes: List[float], n: int) -> Optional[float]:
    """Exponential Moving Average (last value only)."""
    if len(closes) < n:
        return None
    k = 2 / (n + 1)
    v = sum(closes[:n]) / n
    for x in closes[n:]:
        v = x * k + v * (1 - k)
    return v


def ema_series(closes: List[float], n: int) -> List[float]:
    """Full EMA series for crossover detection."""
    if len(closes) < n:
        return []
    k = 2 / (n + 1)
    result = [sum(closes[:n]) / n]
    for x in closes[n:]:
        result.append(x * k + result[-1] * (1 - k))
    return result


def atr(highs: List[float], lows: List[float], closes: List[float], n: int = 14) -> Optional[float]:
    """Average True Range with Wilder's Smoothing."""
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


def adx(highs: List[float], lows: List[float], closes: List[float], n: int = 14) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """ADX with Wilder's Smoothing. Returns (adx, +DI, -DI)."""
    if len(closes) < n * 2 + 5:
        return None, None, None

    plus_dm_list  = []
    minus_dm_list = []
    tr_list       = []

    for i in range(1, len(closes)):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm_list.append(up if up > down and up > 0 else 0)
        minus_dm_list.append(down if down > up and down > 0 else 0)
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)

    def wilder_smooth(data: List[float], n: int) -> List[float]:
        result = [sum(data[:n])]
        for x in data[n:]:
            result.append(result[-1] - result[-1] / n + x)
        return result

    sm_tr    = wilder_smooth(tr_list, n)
    sm_plus  = wilder_smooth(plus_dm_list, n)
    sm_minus = wilder_smooth(minus_dm_list, n)

    dx_list       = []
    plus_di_list  = []
    minus_di_list = []

    for i in range(len(sm_tr)):
        if sm_tr[i] == 0:
            continue
        pdi = 100 * sm_plus[i] / sm_tr[i]
        mdi = 100 * sm_minus[i] / sm_tr[i]
        plus_di_list.append(pdi)
        minus_di_list.append(mdi)
        dsum = pdi + mdi
        dx_list.append(100 * abs(pdi - mdi) / dsum if dsum != 0 else 0)

    if len(dx_list) < n:
        return None, None, None

    adx_val = sum(dx_list[:n]) / n
    for dx in dx_list[n:]:
        adx_val = (adx_val * (n - 1) + dx) / n

    return (
        adx_val,
        plus_di_list[-1] if plus_di_list else None,
        minus_di_list[-1] if minus_di_list else None,
    )


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    MACD with full histogram history.
    Returns (macd_line, signal_line, histogram_now, histogram_prev).
    histogram_prev is the second-to-last histogram value.
    """
    if len(closes) < slow + signal + 1:  # +1 for prev_hist
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
    signal_line_trim = signal_line

    histogram = [m - s for m, s in zip(macd_line_trim, signal_line_trim)]

    if len(histogram) < 2:
        return None, None, None, None

    return macd_line_trim[-1], signal_line_trim[-1], histogram[-1], histogram[-2]


def bollinger(closes: List[float], n: int = 20, k: int = 2) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Bollinger Bands. Returns (upper, mid, lower)."""
    if len(closes) < n:
        return None, None, None
    mid = sma(closes, n)
    if mid is None:
        return None, None, None
    std = (sum((c - mid) ** 2 for c in closes[-n:]) / n) ** 0.5
    return mid + k * std, mid, mid - k * std


def stochastic(highs: List[float], lows: List[float], closes: List[float], k: int = 14, d: int = 3) -> Tuple[Optional[float], Optional[float]]:
    """Stochastic Oscillator. Returns (%K, %D)."""
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


class IndicatorCache:
    """
    Pre-computes all indicators once per symbol/timeframe.
    Eliminates redundant calculations between filter and scoring stages.
    """

    def __init__(self, opens: List[float], highs: List[float], lows: List[float], closes: List[float], vols: List[float]):
        self.opens  = opens
        self.highs  = highs
        self.lows   = lows
        self.closes = closes
        self.vols   = vols

        self.cc = closes[-1]
        self.co = opens[-1]
        self.cl = lows[-1]
        self.ch = highs[-1]
        self.pc = closes[-2] if len(closes) >= 2 else None

        self._compute()

    def _compute(self) -> None:
        # Moving averages
        self.sma_50  = sma(self.closes, 50)
        self.sma_200 = sma(self.closes, 200)
        self.sma_200_prev = sma(self.closes[:-1], 200)

        self.ema_9   = ema(self.closes, 9)
        self.ema_21  = ema(self.closes, 21)
        self.ema_50  = ema(self.closes, 50)
        self.ema_200 = ema(self.closes, 200)

        self.ema_series_9  = ema_series(self.closes, 9)
        self.ema_series_21 = ema_series(self.closes, 21)

        # Momentum / volatility
        self.rsi_14 = rsi(self.closes, 14)
        self.atr_14 = atr(self.highs, self.lows, self.closes, 14)
        self.adx_14, self.plus_di, self.minus_di = adx(self.highs, self.lows, self.closes, 14)

        # MACD with prev_hist (single computation!)
        self.macd_line, self.signal_line, self.hist_now, self.hist_prev = macd(self.closes, 12, 26, 9)

        # Bands
        self.bb_upper, self.bb_mid, self.bb_lower = bollinger(self.closes, 20, 2)

        # Stochastic
        self.stoch_k, self.stoch_d = stochastic(self.highs, self.lows, self.closes, 14, 3)

        # Derived metrics
        self.body = (self.cc - self.co) / self.co * 100 if self.co != 0 else 0
        self.avg_vol = sum(self.vols[-21:-1]) / 20 if len(self.vols) > 21 else 0
        self.vol_r   = self.vols[-1] / self.avg_vol if self.avg_vol > 0 else 0
        self.atr_pct = (self.atr_14 / self.cc * 100) if self.atr_14 and self.cc else 0

        # Cross detection
        self.cross_up_9_21 = False
        if len(self.ema_series_9) >= 2 and len(self.ema_series_21) >= 2:
            self.cross_up_9_21 = (
                self.ema_series_9[-1] > self.ema_series_21[-1]
                and self.ema_series_9[-2] <= self.ema_series_21[-2]
            )

        # Support proximity
        self.near_ema_21 = False
        self.near_sma_50 = False
        if self.ema_21 and self.cc != 0:
            self.near_ema_21 = abs(self.cc - self.ema_21) / self.ema_21 * 100 < 2.0
        if self.sma_50 and self.cc != 0:
            self.near_sma_50 = abs(self.cc - self.sma_50) / self.sma_50 * 100 < 2.0

        # Lower wick for reversal detection
        self.lower_wick = (min(self.co, self.cc) - self.cl) / self.cl * 100 if self.cl != 0 else 0
