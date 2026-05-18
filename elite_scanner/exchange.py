"""Binance API client with retry logic and volume filtering."""
import requests
import time
import logging
from typing import List, Tuple, Optional
from functools import wraps

from .config import BINANCE_BASE, MIN_QUOTE_VOLUME_USDT

logger = logging.getLogger(__name__)


def retry_on_error(max_retries: int = 3, backoff: float = 1.0):
    """Decorator for exponential backoff retry on request failures."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.RequestException, Exception) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        sleep_time = backoff * (2 ** attempt)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt+1}/{max_retries}): {e}. "
                            f"Retrying in {sleep_time:.1f}s..."
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
            raise last_exception
        return wrapper
    return decorator


class BinanceClient:
    """Lightweight Binance spot-data client with automatic retries."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "EliteScanner/2.0",
        })
        self._pairs: Optional[List[str]] = None

    @retry_on_error(max_retries=3, backoff=1.0)
    def get_active_pairs(self) -> List[str]:
        """
        Fetch USDT pairs filtered by minimum 24h volume.
        Caches result for the session.
        """
        if self._pairs is not None:
            return self._pairs

        logger.info(f"Fetching active pairs (min vol: {MIN_QUOTE_VOLUME_USDT:,} USDT)...")
        resp = self.session.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=20)
        resp.raise_for_status()
        data = resp.json()

        pairs = []
        for s in data:
            if not s["symbol"].endswith("USDT"):
                continue
            if s.get("status") != "TRADING":
                continue
            quote_vol = float(s.get("quoteVolume", 0))
            if quote_vol < MIN_QUOTE_VOLUME_USDT:
                continue
            pairs.append(s["symbol"])

        self._pairs = pairs
        logger.info(f"Selected {len(pairs)} liquid USDT pairs")
        return pairs

    @retry_on_error(max_retries=3, backoff=1.0)
    def fetch_klines(self, symbol: str, interval: str, limit: int = 300) -> Optional[Tuple[List[float], List[float], List[float], List[float], List[float]]]:
        """
        Fetch OHLCV klines from Binance.
        Returns (opens, highs, lows, closes, volumes) or None on failure/insufficient data.
        """
        try:
            resp = self.session.get(
                f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            raw = resp.json()

            if not isinstance(raw, list) or len(raw) < 220:
                logger.debug(
                    f"{symbol} [{interval}]: insufficient data "
                    f"({len(raw) if isinstance(raw, list) else 'N/A'} candles)"
                )
                return None

            opens    = [float(c[1]) for c in raw]
            highs    = [float(c[2]) for c in raw]
            lows     = [float(c[3]) for c in raw]
            closes   = [float(c[4]) for c in raw]
            volumes  = [float(c[5]) for c in raw]

            return opens, highs, lows, closes, volumes

        except Exception as e:
            logger.warning(f"Fetch error for {symbol} [{interval}]: {e}")
            return None
