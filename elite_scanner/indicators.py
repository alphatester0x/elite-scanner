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
    """Full EMA series."""
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


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """MACD. Returns (macd_line, signal_line, histogram_now, histogram_prev)."""
    if len(closes) < slow + signal + 1:
        return None, None, None, None

    def _ema_series(data: List[float], n: int) -> List[float]:
        if len(data) < n:
            return []
        k = 2 / (n + 1)
        result = [sum(data[:n]) / n]
        for x in data[n:]:
            result.append(x * k + result[-1] * (1 - k))
        return result

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)

    diff = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[diff:]

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]

    if len(macd_line) < signal + 1:
        return None, None, None, None

    signal_line = _ema_series(macd_line, signal)
    diff_len = len(macd_line) - len(signal_line)
    macd_line_trim = macd_line[diff_len:]

    histogram = [m - s for m, s in zip(macd_line_trim, signal_line)]

    if len(histogram) < 2:
        return None, None, None, None

    return macd_line_trim[-1], signal_line[-1], histogram[-1], histogram[-2]


def bollinger(closes: List[float], n: int = 20, k: int = 2) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Bollinger Bands. Returns (upper, mid, lower)."""
    if len(closes) < n:
        return None, None, None
    mid = sma(closes, n)
    if mid is None:
        return None, None, None
    std = (sum((c - mid) ** 2 for c in closes[-n:]) / n) ** 0.5
    return mid + k * std, mid, mid - k * std


class IndicatorCache:
    """Pre-computes all indicators once per symbol/timeframe."""

    def __init__(self, opens: List[float], highs: List[float], lows: List[float], closes: List[float], vols: List[float], drop_24h: Optional[float] = None):
        self.opens  = opens
        self.highs  = highs
        self.lows   = lows
        self.closes = closes
        self.vols   = vols
        self._drop_24h_ticker = drop_24h  # from 24h ticker, takes precedence over klines-derived

        self.cc = closes[-1]  # current close
        self.co = opens[-1]   # current open
        self.cl = lows[-1]    # current low
        self.ch = highs[-1]   # current high
        self.pc = closes[-2] if len(closes) >= 2 else None  # previous close
        self.pco = opens[-2] if len(opens) >= 2 else None   # previous open
        self.pcl = lows[-2] if len(lows) >= 2 else None     # previous low
        self.pch = highs[-2] if len(highs) >= 2 else None   # previous high

        # High/Low dalam 24 candle terakhir (untuk BOUNCE: ~24h di timeframe 1h)
        self.high_24h = max(highs[-24:]) if len(highs) >= 24 else None
        self.low_24h = min(lows[-24:]) if len(lows) >= 24 else None

        self._compute()

    def _compute(self) -> None:
        # Moving averages
        self.sma_20  = sma(self.closes, 20)
        self.sma_50  = sma(self.closes, 50)
        self.sma_200 = sma(self.closes, 200)

        self.ema_9   = ema(self.closes, 9)
        self.ema_21  = ema(self.closes, 21)
        self.ema_50  = ema(self.closes, 50)

        self.ema_series_9  = ema_series(self.closes, 9)
        self.ema_series_21 = ema_series(self.closes, 21)

        # Momentum / volatility
        self.rsi_14 = rsi(self.closes, 14)
        self.rsi_6  = rsi(self.closes, 6)   # Fast RSI untuk bounce detection
        self.atr_14 = atr(self.highs, self.lows, self.closes, 14)

        # MACD
        self.macd_line, self.signal_line, self.hist_now, self.hist_prev = macd(self.closes, 12, 26, 9)

        # Bollinger
        self.bb_upper, self.bb_mid, self.bb_lower = bollinger(self.closes, 20, 2)

        # Derived metrics
        self.body = (self.cc - self.co) / self.co * 100 if self.co != 0 else 0
        self.prev_body = (self.pc - self.pco) / self.pco * 100 if self.pco and self.pco != 0 else 0

        # Volume
        self.avg_vol_20 = sum(self.vols[-21:-1]) / 20 if len(self.vols) > 21 else 0
        self.vol_r = self.vols[-2] / self.avg_vol_20 if self.avg_vol_20 > 0 and len(self.vols) >= 2 else 0

        # ATR percentage
        self.atr_pct = (self.atr_14 / self.cc * 100) if self.atr_14 and self.cc else 0

        # Drop calculation: gunakan drop_24h dari ticker (konsisten dengan filter awal)
        # cache.drop_24h_pct dari klines bisa beda metodologi; ticker lebih akurat
        self.drop_24h_pct = self._drop_24h_ticker if self._drop_24h_ticker is not None else (
            ((self.cc / self.high_24h - 1) * 100) if self.high_24h and self.high_24h > 0 else 0
        )

        # Lower wick (rejection dari bawah)
        self.lower_wick = (min(self.co, self.cc) - self.cl) / self.cl * 100 if self.cl != 0 else 0
        self.upper_wick = (self.ch - max(self.co, self.cc)) / self.cc * 100 if self.cc != 0 else 0

        # Previous candle lower wick
        self.prev_lower_wick = (min(self.pco, self.pc) - self.pcl) / self.pcl * 100 if self.pcl and self.pcl != 0 else 0

        # Price vs EMAs
        self.above_ema9 = self.cc > self.ema_9 if self.ema_9 else False
        self.above_ema21 = self.cc > self.ema_21 if self.ema_21 else False
        # Additional flag for EMA 50 (used in scoring)
        self.above_ema50 = self.cc > self.ema_50 if self.ema_50 else False

        # EMA cross detection
        self.cross_up_9_21 = False
        if len(self.ema_series_9) >= 2 and len(self.ema_series_21) >= 2:
            self.cross_up_9_21 = (
                self.ema_series_9[-1] > self.ema_series_21[-1]
                and self.ema_series_9[-2] <= self.ema_series_21[-2]
            )

        # Consecutive down candles (berapa candle merah berturut-turut sebelum ini)
        # Start from i=2 to skip the current (still-forming) candle
        self.consecutive_red = 0
        for i in range(2, min(len(self.closes), 11)):
            if self.closes[-i] < self.opens[-i]:
                self.consecutive_red += 1
            else:
                break

        # Volume trend (volume 5 candle terakhir vs 20 candle sebelumnya)
        vol_recent = sum(self.vols[-5:]) / 5 if len(self.vols) >= 5 else 0
        vol_old = sum(self.vols[-25:-5]) / 20 if len(self.vols) >= 25 else 0
        self.vol_trend = vol_recent / vol_old if vol_old > 0 else 0
