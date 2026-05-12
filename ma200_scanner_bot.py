============================================================

MULTI MODE CRYPTO SIGNAL BOT

Modes:

- SWING

- ELITE

- SCALP

============================================================

import requests import time import os import json from datetime import datetime from concurrent.futures import ThreadPoolExecutor, as_completed

============================================================

CONFIG

============================================================

MODE_FILE = "mode.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

MAX_WORKERS = 30 MAX_SIGNALS_PER_SCAN = 10

BINANCE_BASE = "https://data-api.binance.vision"

SESSION = requests.Session()

============================================================

INDICATORS

============================================================

def sma(c, n): return sum(c[-n:]) / n if len(c) >= n else None

def sma_p(c, n): return sum(c[-(n+1):-1]) / n if len(c) >= n+1 else None

def ema(c, n): if len(c) < n: return None

k = 2 / (n + 1)
v = sum(c[:n]) / n

for x in c[n:]:
    v = x * k + v * (1 - k)

return v

def rsi(c, n=14): if len(c) < n + 2: return None

d = [c[i+1]-c[i] for i in range(len(c)-1)]

ag = sum(x for x in d[-n:] if x > 0) / n
al = sum(-x for x in d[-n:] if x < 0) / n

return 100 if al == 0 else 100 - 100/(1+ag/al)

def atr(highs, lows, closes, n=14):

if len(closes) < n + 1:
    return None

trs = []

for i in range(1, len(closes)):

    tr = max(
        highs[i] - lows[i],
        abs(highs[i] - closes[i-1]),
        abs(lows[i] - closes[i-1])
    )

    trs.append(tr)

return sum(trs[-n:]) / n

def adx(highs, lows, closes, n=14):

if len(closes) < n + 20:
    return None

plus_dm = []
minus_dm = []
trs = []

for i in range(1, len(closes)):

    up_move = highs[i] - highs[i-1]
    down_move = lows[i-1] - lows[i]

    plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
    minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    tr = max(
        highs[i] - lows[i],
        abs(highs[i] - closes[i-1]),
        abs(lows[i] - closes[i-1])
    )

    trs.append(tr)

atrv = sum(trs[-n:]) / n

if atrv == 0:
    return None

plus_di = (sum(plus_dm[-n:]) / atrv) * 100
minus_di = (sum(minus_dm[-n:]) / atrv) * 100

di_sum = plus_di + minus_di

if di_sum == 0:
    return None

return abs(plus_di - minus_di) / di_sum * 100

============================================================

MODE STORAGE

============================================================

def load_mode():

if not os.path.exists(MODE_FILE):
    save_mode("ELITE")

try:

    with open(MODE_FILE, "r") as f:
        data = json.load(f)
        return data.get("mode", "ELITE")

except:
    return "ELITE"

def save_mode(mode):

with open(MODE_FILE, "w") as f:
    json.dump({"mode": mode}, f)

============================================================

TELEGRAM

============================================================

def send_telegram(message):

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": message,
    "parse_mode": "HTML"
}

try:
    SESSION.post(url, json=payload, timeout=10)
except Exception as e:
    print(e)

LAST_UPDATE_ID = None

def handle_telegram_commands():

global LAST_UPDATE_ID

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

try:

    params = {"timeout": 5}

    if LAST_UPDATE_ID:
        params["offset"] = LAST_UPDATE_ID + 1

    resp = SESSION.get(url, params=params, timeout=10)

    data = resp.json()

    if not data.get("ok"):
        return

    for upd in data["result"]:

        LAST_UPDATE_ID = upd["update_id"]

        msg = upd.get("message", {})

        text = msg.get("text", "").lower()

        chat_id = str(msg.get("chat", {}).get("id"))

        if chat_id != str(TELEGRAM_CHAT_ID):
            continue

        if text == "/elite":
            save_mode("ELITE")
            send_telegram("🔥 Mode diubah ke ELITE")

        elif text == "/swing":
            save_mode("SWING")
            send_telegram("✅ Mode diubah ke SWING")

        elif text == "/scalp":
            save_mode("SCALP")
            send_telegram("⚡ Mode diubah ke SCALP")

        elif text == "/status":
            mode = load_mode()
            send_telegram(f"📊 Current mode: <b>{mode}</b>")

except Exception as e:
    print(f"Telegram command error: {e}")

============================================================

BINANCE

============================================================

def get_pairs():

resp = SESSION.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=20)

data = resp.json()

return [
    s["symbol"] for s in data["symbols"]
    if s["quoteAsset"] == "USDT"
    and s["status"] == "TRADING"
]

def fetch(symbol, interval):

try:

    resp = SESSION.get(
        f"{BINANCE_BASE}/api/v3/klines",
        params={
            "symbol": symbol,
            "interval": interval,
            "limit": 250
        },
        timeout=6
    )

    if resp.status_code != 200:
        return None

    raw = resp.json()

    if len(raw) < 220:
        return None

    return (
        [float(c[1]) for c in raw],
        [float(c[2]) for c in raw],
        [float(c[3]) for c in raw],
        [float(c[4]) for c in raw],
        [float(c[5]) for c in raw],
    )

except Exception:
    return None

============================================================

BTC FILTER

============================================================

def btc_market_bullish():

data = fetch("BTCUSDT", "1d")

if data is None:
    return True

opens, highs, lows, closes, vols = data

ma200 = sma(closes, 200)
e50 = ema(closes, 50)
e200 = ema(closes, 200)

if not ma200 or not e50 or not e200:
    return True

cc = closes[-1]

return cc > ma200 and e50 > e200

============================================================

SCAN LOGIC

============================================================

def scan_symbol(symbol):

signals = []

mode = load_mode()

if mode == "SCALP":
    timeframes = [("15m", "15M"), ("1h", "1H")]
else:
    timeframes = [("4h", "4H"), ("1d", "1D")]

for interval, tf in timeframes:

    data = fetch(symbol, interval)

    if data is None:
        continue

    opens, highs, lows, closes, vols = data

    cc = closes[-1]
    co = opens[-1]
    cl = lows[-1]
    pc = closes[-2]

    body = (cc - co) / co * 100

    avg_v = sum(vols[-21:-1]) / 20
    vol_r = vols[-1] / avg_v if avg_v > 0 else 0

    rsic = rsi(closes)

    atrv = atr(highs, lows, closes)

    if not atrv:
        continue

    atr_pct = atrv / cc * 100

    adxv = adx(highs, lows, closes)

    # ====================================================
    # ELITE MODE
    # ====================================================

    if mode == "ELITE":

        ma200 = sma(closes, 200)
        ma200p = sma_p(closes, 200)

        e50 = ema(closes, 50)
        e200 = ema(closes, 200)

        if not ma200 or not e50 or not e200:
            continue

        ma_slope = ma200 - sma(closes[-20:-1], 20)

        if not (
            e50 > e200 and
            cc > ma200 * 1.02 and
            ma_slope > 0
        ):
            continue

        if not adxv or adxv < 28:
            continue

        if vol_r < 2.5:
            continue

        if body < 1.5:
            continue

        if rsic > 72:
            continue

        if atr_pct < 3:
            continue

        if pc < ma200p and cc > ma200:

            signals.append(
                (
                    symbol,
                    "ELITE_BREAKOUT",
                    tf,
                    f"🔥 ELITE SIGNAL\n"
                    f"ADX: {adxv:.1f}\n"
                    f"VOL: {vol_r:.1f}x\n"
                    f"RSI: {rsic:.1f}\n"
                    f"ATR: {atr_pct:.1f}%"
                )
            )

    # ====================================================
    # WINRATE MODE
    # ====================================================

    elif mode == "SWING":

        ma200 = sma(closes, 200)

        e50 = ema(closes, 50)
        e200 = ema(closes, 200)

        if not ma200 or not e50 or not e200:
            continue

        if not (e50 > e200 and cc > ma200):
            continue

        pullback_pct = (ma200 - cl) / ma200 * 100

        if pullback_pct > 3:
            continue

        lower_wick = (min(co, cc) - cl) / cl * 100

        if lower_wick < 1:
            continue

        if rsic < 40 or rsic > 65:
            continue

        signals.append(
            (
                symbol,
                "WINRATE_PULLBACK",
                tf,
                f"✅ WINRATE SIGNAL\n"
                f"RSI: {rsic:.1f}\n"
                f"Wick: {lower_wick:.1f}%"
            )
        )

    # ====================================================
    # SCALP MODE
    # ====================================================

    elif mode == "SCALP":

        e9 = ema(closes, 9)
        e21 = ema(closes, 21)

        pe9 = ema(closes[:-1], 9)
        pe21 = ema(closes[:-1], 21)

        if not e9 or not e21 or not pe9 or not pe21:
            continue

        cross_up = (
            e9 > e21 and
            pe9 < pe21
        )

        if not cross_up:
            continue

        if vol_r < 2:
            continue

        if body < 0.8:
            continue

        if atr_pct < 1:
            continue

        if rsic < 50 or rsic > 75:
            continue

        signals.append(
            (
                symbol,
                "SCALP_MOMENTUM",
                tf,
                f"⚡ SCALP SIGNAL\n"
                f"RSI: {rsic:.1f}\n"
                f"VOL: {vol_r:.1f}x"
            )
        )

return signals

============================================================

MAIN SCAN

============================================================

def scan_all():

mode = load_mode()

print(f"[{datetime.now()}] SCANNING {mode} MODE")

if mode != "SCALP":

    if not btc_market_bullish():

        send_telegram(
            "⚠️ BTC market bearish. Scan skipped."
        )

        return

pairs = get_pairs()

all_signals = []

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:

    futs = [ex.submit(scan_symbol, p) for p in pairs]

    for f in as_completed(futs):

        try:
            all_signals.extend(f.result())
        except:
            pass

print(f"Signals found: {len(all_signals)}")

for s in all_signals[:MAX_SIGNALS_PER_SCAN]:

    sym, stype, tf, msg = s

    send_telegram(
        f"🪙 <b>{sym}</b> [{tf}]\n\n"
        f"{msg}\n\n"
        f"MODE: {mode}"
    )

    time.sleep(1)

============================================================

RUN

============================================================

if name == "main":

try:
    handle_telegram_commands()
    scan_all()

except Exception as e:

    print(e)

    send_telegram(f"❌ Bot Error

{e}")
