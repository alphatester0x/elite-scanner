"""Binance API client with retry logic and volume filtering."""
import requests
import time
import logging
from typing import List, Tuple, Optional, Dict, Any
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
        self._trading_status: Optional[Dict[str, str]] = None
        self._ticker_24h: Optional[List[Dict[str, Any]]] = None

    @retry_on_error(max_retries=3, backoff=1.0)
    def _get_trading_symbols(self) -> Dict[str, str]:
        """Fetch exchangeInfo and return dict of symbol -> status for TRADING symbols only."""
        if self._trading_status is not None:
            return self._trading_status

        logger.info("Fetching exchange info for trading status...")
        resp = self.session.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=20)
        resp.raise_for_status()
        data = resp.json()

        trading_status = {}
        for s in data.get("symbols", []):
            symbol = s.get("symbol", "")
            status = s.get("status", "")
            if status == "TRADING" and symbol.endswith("USDT"):
                trading_status[symbol] = status

        self._trading_status = trading_status
        logger.info(f"Found {len(trading_status)} active USDT trading pairs")
        return trading_status

    @retry_on_error(max_retries=3, backoff=1.0)
    def get_active_pairs(self) -> List[str]:
        """Fetch USDT pairs filtered by minimum 24h volume AND trading status."""
        if self._pairs is not None:
            return self._pairs

        trading_symbols = self._get_trading_symbols()

        logger.info(f"Fetching 24h ticker data (min vol: {MIN_QUOTE_VOLUME_USDT:,} USDT)...")
        resp_ticker = self.session.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=30)
        resp_ticker.raise_for_status()
        ticker_data = resp_ticker.json()

        pairs = []
        for s in ticker_data:
            symbol = s.get("symbol", "")
            if symbol not in trading_symbols:
                continue
            quote_vol = float(s.get("quoteVolume", 0))
            if quote_vol < MIN_QUOTE_VOLUME_USDT:
                continue
            pairs.append(symbol)

        self._pairs = pairs
        logger.info(f"Selected {len(pairs)} liquid active USDT pairs")
        return pairs

    @retry_on_error(max_retries=3, backoff=1.0)
    def get_24h_ticker(self) -> List[Dict[str, Any]]:
        """Fetch raw 24h ticker data for ACTIVE TRADING symbols only.

        FIX: Filter out BREAK/DELISTED tokens so they don't appear in scans.
        """
        trading_symbols = self._get_trading_symbols()

        resp = self.session.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", timeout=30)
        resp.raise_for_status()
        raw_data = resp.json()

        # Filter: only TRADING status + USDT pairs
        filtered = []
        for item in raw_data:
            symbol = item.get("symbol", "")
            if symbol not in trading_symbols:
                continue
            filtered.append(item)

        logger.info(f"24h ticker: {len(raw_data)} total, {len(filtered)} active USDT pairs")
        self._ticker_24h = filtered
        return filtered

    @retry_on_error(max_retries=3, backoff=1.0)
    def fetch_klines(self, symbol: str, interval: str, limit: int = 300) -> Optional[Tuple[List[float], List[float], List[float], List[float], List[float]]]:
        """Fetch OHLCV klines from Binance."""
        try:
            resp = self.session.get(
                f"{BINANCE_BASE}/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            raw = resp.json()

            if not isinstance(raw, list) or len(raw) < 50:
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
