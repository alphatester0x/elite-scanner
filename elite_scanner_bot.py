import requests
import time
import os
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# CONFIG
# ============================================================

MODE_FILE      = "mode.json"
UPDATE_ID_FILE = "last_update_id.json"  # persist via GitHub Actions cache

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

MAX_WORKERS           = 30
MAX_SIGNALS_PER_SCAN  = 10

BINANCE_BASE = "https://data-api.binance.vision"

SESSION = requests.Session()

MIN_SCORE_RATIO = {
    "ELITE": 0.65,
    "SWING": 0.60,
    "SCALP": 0.60,
}

# ============================================================
# MODE STORAGE
# ============================================================

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

# ============================================================
# UPDATE ID STORAGE — persist ke file supaya tidak replay
# command lama saat GitHub Actions runner restart
# ============================================================

def load_last_update_id():
    try:
        with open(UPDATE_ID_FILE, "r") as f:
            return json.load(f).get("last_update_id", None)
    except:
        return None


def save_last_update_id(uid):
    try:
        with open(UPDATE_ID_FILE, "w") as f:
            json.dump({"last_update_id": uid}, f)
    except:
        pass

# ============================================================
# INDICATORS
# ============================================================

def sma(c, n):
    return sum(c[-n:]) / n if len(c) >= n else None


def rsi(c, n=14):
    """RSI dengan Wilder's Smoothing (standar industri)."""
    if len(c) < n + 2:
        return None

    deltas = [c[i + 1] - c[i] for i in range(len(c) - 1)]
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


def ema(c, n):
    if len(c) < n:
        return None
    k = 2 / (n + 1)
    v = sum(c[:n]) / n
    for x in c[n:]:
        v = x * k + v * (1 - k)
    return v


def ema_series(c, n):
    """Return full EMA series untuk perbandingan cross."""
    if len(c) < n:
        return []
    k = 2 / (n + 1)
    result = [sum(c[:n]) / n]
    for x in c[n:]:
        result.append(x * k + result[-1] * (1 - k))
    return result


def atr(highs, lows, closes, n=14):
    """ATR dengan Wilder's Smoothing."""
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


def adx(highs, lows, closes, n=14):
    """ADX dengan Wilder's Smoothing. Return (adx, +DI, -DI)."""
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

    def wilder_smooth(data, n):
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


def macd(closes, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, histogram)."""
    if len(closes) < slow + signal:
        return None, None, None

    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)

    diff     = len(ema_fast) - len(ema_slow)
    ema_fast = ema_fast[diff:]

    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]

    if len(macd_line) < signal:
        return None, None, None

    signal_line = ema_series(macd_line, signal)
    diff_len    = len(macd_line) - len(signal_line)
    macd_line   = macd_line[diff_len:]
    histogram   = [m - s for m, s in zip(macd_line, signal_line)]

    return macd_line[-1], signal_line[-1], histogram[-1]


def bollinger(closes, n=20, k=2):
    """Return (upper, mid, lower)."""
    if len(closes) < n:
        return None, None, None
    mid = sma(closes, n)
    std = (sum((c - mid) ** 2 for c in closes[-n:]) / n) ** 0.5
    return mid + k * std, mid, mid - k * std


def stochastic(highs, lows, closes, k=14, d=3):
    """Return (%K, %D)."""
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

# ============================================================
# SCORING ENGINE
# ============================================================

def score_elite(closes, highs, lows, opens, vols):
    reasons   = []
    score     = 0
    max_score = 0

    cc  = closes[-1]
    co  = opens[-1]
    pc  = closes[-2]

    body  = (cc - co) / co * 100
    avg_v = sum(vols[-21:-1]) / 20
    vol_r = vols[-1] / avg_v if avg_v > 0 else 0

    rsic             = rsi(closes)
    atrv             = atr(highs, lows, closes)
    atr_pct          = atrv / cc * 100 if atrv else 0
    adxv, pdi, mdi   = adx(highs, lows, closes)
    macd_l, sig_l, hist = macd(closes)
    prev_hist        = macd(closes[:-1])[2]

    ma200     = sma(closes, 200)
    ma200_old = sma(closes[-210:-10], 200)
    e50       = ema(closes, 50)
    e200      = ema(closes, 200)

    # [2pts] Golden Cross Structure
    max_score += 2
    if e50 and e200 and e50 > e200:
        score += 2
        reasons.append("✅ EMA50 > EMA200 (Golden Structure)")
    else:
        reasons.append("❌ EMA50 < EMA200 (No Uptrend)")

    # [2pts] Price vs MA200
    max_score += 2
    if ma200 and cc > ma200 * 1.02:
        score += 2
        reasons.append(f"✅ Price > MA200 +{((cc / ma200 - 1) * 100):.1f}%")
    elif ma200 and cc > ma200:
        score += 1
        reasons.append(f"⚠️ Price > MA200 +{((cc / ma200 - 1) * 100):.1f}% (tipis)")
    else:
        reasons.append("❌ Price di bawah MA200")

    # [1pt] MA200 Slope
    max_score += 1
    if ma200 and ma200_old and ma200 > ma200_old:
        score += 1
        reasons.append(f"✅ MA200 Slope Naik (+{((ma200 / ma200_old - 1) * 100):.2f}%)")
    else:
        reasons.append("❌ MA200 Slope Datar/Turun")

    # [2pts] ADX Strength
    max_score += 2
    if adxv and pdi and mdi:
        if adxv >= 30 and pdi > mdi:
            score += 2
            reasons.append(f"✅ ADX {adxv:.1f} Kuat | +DI {pdi:.1f} > -DI {mdi:.1f}")
        elif adxv >= 25 and pdi > mdi:
            score += 1
            reasons.append(f"⚠️ ADX {adxv:.1f} Cukup | +DI {pdi:.1f} > -DI {mdi:.1f}")
        else:
            reasons.append(f"❌ ADX {adxv:.1f} Lemah atau -DI Dominan")
    else:
        reasons.append("❌ ADX tidak tersedia")

    # [2pts] MACD
    max_score += 2
    if macd_l and sig_l and hist and prev_hist:
        if macd_l > sig_l and hist > prev_hist:
            score += 2
            reasons.append(f"✅ MACD Bullish & Histogram Membesar ({hist:.6f})")
        elif macd_l > sig_l:
            score += 1
            reasons.append("⚠️ MACD Bullish tapi Histogram Menyusut")
        else:
            reasons.append("❌ MACD Bearish")
    else:
        reasons.append("❌ MACD tidak tersedia")

    # [2pts] Volume
    max_score += 2
    if vol_r >= 3.0:
        score += 2
        reasons.append(f"✅ Volume Surge {vol_r:.1f}x avg (Sangat Kuat)")
    elif vol_r >= 2.0:
        score += 1
        reasons.append(f"⚠️ Volume {vol_r:.1f}x avg (Cukup)")
    else:
        reasons.append(f"❌ Volume {vol_r:.1f}x avg (Lemah)")

    # [1pt] Candle Body
    max_score += 1
    if body >= 1.2:
        score += 1
        reasons.append(f"✅ Bullish Body +{body:.1f}%")
    else:
        reasons.append(f"❌ Body Lemah {body:.1f}%")

    # [1pt] RSI
    max_score += 1
    if rsic:
        if 55 <= rsic <= 70:
            score += 1
            reasons.append(f"✅ RSI {rsic:.1f} (Ideal Zone)")
        elif rsic <= 55:
            reasons.append(f"⚠️ RSI {rsic:.1f} (Momentum Belum Kuat)")
        else:
            reasons.append(f"⚠️ RSI {rsic:.1f} (Mendekati Overbought)")

    # [1pt] ATR
    max_score += 1
    if atr_pct >= 2.5:
        score += 1
        reasons.append(f"✅ ATR {atr_pct:.1f}% (Volatilitas Baik)")
    else:
        reasons.append(f"⚠️ ATR {atr_pct:.1f}% (Volatilitas Rendah)")

    return score, max_score, reasons


def score_swing(closes, highs, lows, opens, vols):
    reasons   = []
    score     = 0
    max_score = 0

    cc = closes[-1]
    co = opens[-1]
    cl = lows[-1]
    ch = highs[-1]

    body       = (cc - co) / co * 100
    avg_v      = sum(vols[-21:-1]) / 20
    vol_r      = vols[-1] / avg_v if avg_v > 0 else 0
    lower_wick = (min(co, cc) - cl) / cl * 100

    rsic             = rsi(closes)
    atrv             = atr(highs, lows, closes)
    atr_pct          = atrv / cc * 100 if atrv else 0
    adxv, pdi, mdi   = adx(highs, lows, closes)
    bb_upper, bb_mid, bb_lower = bollinger(closes)

    ma50  = sma(closes, 50)
    ma200 = sma(closes, 200)
    e21   = ema(closes, 21)
    e50   = ema(closes, 50)
    e200  = ema(closes, 200)

    near_e21  = abs(cc - e21) / e21 * 100 < 2.0 if e21 else False
    near_ma50 = abs(cc - ma50) / ma50 * 100 < 2.0 if ma50 else False

    # [2pts] Trend Structure
    max_score += 2
    if e50 and e200 and e50 > e200 and ma200 and cc > ma200:
        score += 2
        reasons.append("✅ Uptrend Kuat (EMA50 > EMA200, Price > MA200)")
    elif e50 and e200 and e50 > e200:
        score += 1
        reasons.append("⚠️ Uptrend Parsial (EMA50 > EMA200 tapi Price < MA200)")
    else:
        reasons.append("❌ Tidak Ada Uptrend")

    # [2pts] Pullback ke Support
    max_score += 2
    if near_e21 and near_ma50:
        score += 2
        reasons.append("✅ Pullback ke EMA21 & MA50 (Double Support)")
    elif near_e21:
        score += 2
        reasons.append(f"✅ Pullback ke EMA21 ({((cc / e21 - 1) * 100):+.1f}%)")
    elif near_ma50:
        score += 2
        reasons.append(f"✅ Pullback ke MA50 ({((cc / ma50 - 1) * 100):+.1f}%)")
    else:
        e21_dist  = abs(cc - e21) / e21 * 100 if e21 else 999
        ma50_dist = abs(cc - ma50) / ma50 * 100 if ma50 else 999
        reasons.append(f"❌ Jauh dari Support (EMA21: {e21_dist:.1f}%, MA50: {ma50_dist:.1f}%)")

    # [1pt] RSI Pullback Zone
    max_score += 1
    if rsic and 42 <= rsic <= 62:
        score += 1
        reasons.append(f"✅ RSI {rsic:.1f} (Pullback Zone Sehat)")
    elif rsic:
        reasons.append(f"⚠️ RSI {rsic:.1f} ({'Oversold' if rsic < 42 else 'Terlalu Panas'})")

    # [2pts] Reversal Candle
    max_score += 2
    if lower_wick >= 2.0 and body > 0:
        score += 2
        reasons.append(f"✅ Hammer Kuat: Wick {lower_wick:.1f}%, Body +{body:.1f}%")
    elif lower_wick >= 0.8:
        score += 1
        reasons.append(f"⚠️ Lower Wick {lower_wick:.1f}% (Lemah)")
    else:
        reasons.append("❌ Tidak Ada Reversal Candle")

    # [1pt] Bollinger Band
    max_score += 1
    if bb_mid and cc > bb_mid:
        score += 1
        reasons.append("✅ Price di Atas BB Mid (Support Dinamis)")
    else:
        reasons.append("❌ Price di Bawah BB Mid")

    # [1pt] ADX
    max_score += 1
    if adxv and adxv >= 20:
        score += 1
        reasons.append(f"✅ ADX {adxv:.1f} (Trend Masih Hidup)")
    else:
        reasons.append(f"⚠️ ADX {adxv:.1f if adxv else '?'} (Trend Lemah)")

    # [1pt] Volume Pullback
    max_score += 1
    if 0.5 <= vol_r <= 1.5:
        score += 1
        reasons.append(f"✅ Volume Pullback Normal {vol_r:.1f}x (Sehat)")
    elif vol_r > 1.5:
        reasons.append(f"⚠️ Volume Tinggi Saat Pullback {vol_r:.1f}x (Waspadai)")
    else:
        reasons.append(f"⚠️ Volume Sangat Sepi {vol_r:.1f}x")

    return score, max_score, reasons


def score_scalp(closes, highs, lows, opens, vols, interval, symbol):
    reasons   = []
    score     = 0
    max_score = 0

    cc    = closes[-1]
    co    = opens[-1]
    body  = (cc - co) / co * 100
    avg_v = sum(vols[-21:-1]) / 20
    vol_r = vols[-1] / avg_v if avg_v > 0 else 0

    rsic             = rsi(closes)
    atrv             = atr(highs, lows, closes)
    atr_pct          = atrv / cc * 100 if atrv else 0
    macd_l, sig_l, hist = macd(closes)
    prev_hist        = macd(closes[:-1])[2]
    stoch_k, stoch_d = stochastic(highs, lows, closes)

    e9_s  = ema_series(closes, 9)
    e21_s = ema_series(closes, 21)
    min_len = min(len(e9_s), len(e21_s))
    e9_s  = e9_s[-min_len:]
    e21_s = e21_s[-min_len:]

    cross_up = (
        len(e9_s) >= 2 and len(e21_s) >= 2
        and e9_s[-1] > e21_s[-1]
        and e9_s[-2] <= e21_s[-2]
    )

    # [3pts] EMA Cross
    max_score += 3
    if cross_up:
        score += 3
        reasons.append("✅ EMA9 Cross EMA21 ke Atas (Fresh Signal!)")
    elif e9_s and e21_s and e9_s[-1] > e21_s[-1]:
        score += 1
        reasons.append("⚠️ EMA9 > EMA21 (Cross sudah lama, bukan fresh)")
    else:
        reasons.append("❌ EMA9 < EMA21 (Bearish)")

    # [2pts] HTF Filter
    max_score += 2
    if interval == "15m":
        htf_data = fetch(symbol, "1h")
        if htf_data:
            _, htf_h, htf_l, htf_c, _ = htf_data
            htf_e50  = ema(htf_c, 50)
            htf_e200 = ema(htf_c, 200)
            htf_rsi  = rsi(htf_c)
            if htf_e50 and htf_e200:
                if htf_e50 > htf_e200:
                    score += 2
                    reasons.append("✅ HTF 1H Bullish (EMA50 > EMA200)")
                else:
                    reasons.append("❌ HTF 1H Bearish (Scalp Melawan Trend)")
            if htf_rsi:
                reasons.append(f"ℹ️ HTF RSI: {htf_rsi:.1f}")
        else:
            reasons.append("⚠️ HTF data tidak tersedia")
    else:
        score += 1
        reasons.append("ℹ️ Timeframe 1H (HTF filter skip)")

    # [2pts] MACD
    max_score += 2
    if macd_l and sig_l and hist and prev_hist:
        if macd_l > sig_l and hist > prev_hist:
            score += 2
            reasons.append("✅ MACD Bullish & Accelerating")
        elif macd_l > sig_l:
            score += 1
            reasons.append("⚠️ MACD Bullish tapi Melambat")
        else:
            reasons.append("❌ MACD Bearish")
    else:
        reasons.append("❌ MACD tidak tersedia")

    # [1pt] Stochastic
    max_score += 1
    if stoch_k and stoch_d:
        if 25 <= stoch_k <= 70 and stoch_k > stoch_d:
            score += 1
            reasons.append(f"✅ Stoch %K {stoch_k:.1f} > %D {stoch_d:.1f} (Bullish)")
        else:
            reasons.append(f"⚠️ Stoch %K {stoch_k:.1f} | %D {stoch_d:.1f}")

    # [1pt] Volume
    max_score += 1
    if vol_r >= 2.5:
        score += 1
        reasons.append(f"✅ Volume Surge {vol_r:.1f}x")
    elif vol_r >= 1.8:
        score += 1
        reasons.append(f"⚠️ Volume {vol_r:.1f}x (Cukup)")
    else:
        reasons.append(f"❌ Volume Lemah {vol_r:.1f}x")

    # [1pt] RSI
    max_score += 1
    if rsic and 48 <= rsic <= 72:
        score += 1
        reasons.append(f"✅ RSI {rsic:.1f} (Momentum Zone)")
    elif rsic:
        reasons.append(f"⚠️ RSI {rsic:.1f}")

    return score, max_score, reasons


def get_grade(score, max_score):
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

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }
    try:
        SESSION.post(url, json=payload, timeout=10)
    except Exception as e:
        print(e)


def handle_telegram_commands():
    """
    Baca command Telegram.
    Dua lapis proteksi agar command lama tidak di-replay:
      1. offset  — skip update_id yang sudah diproses (via file cache)
      2. timestamp — skip pesan yang dikirim sebelum bot ini jalan
                     (fallback kalau cache belum ada / hilang)
    """
    last_id  = load_last_update_id()
    boot_time = int(time.time())  # waktu script ini mulai jalan

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    try:
        params = {"timeout": 5}
        if last_id is not None:
            params["offset"] = last_id + 1  # skip update yang sudah diproses

        resp = SESSION.get(url, params=params, timeout=10)
        data = resp.json()

        if not data.get("ok"):
            return

        for upd in data["result"]:
            uid     = upd["update_id"]
            msg     = upd.get("message", {})
            text    = msg.get("text", "").lower().strip()
            chat_id = str(msg.get("chat", {}).get("id"))
            msg_ts  = msg.get("date", 0)  # unix timestamp pesan

            # Selalu update last_id dulu, biar tidak di-replay meski di-skip
            save_last_update_id(uid)

            # Skip pesan lama (dikirim sebelum run ini mulai)
            # Toleransi 30 detik untuk pesan yang baru masuk saat boot
            if msg_ts < boot_time - 30:
                print(f"[SKIP] Old message (ts={msg_ts}): {text}")
                continue

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

# ============================================================
# BINANCE
# ============================================================

def get_pairs():
    resp = SESSION.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=20)
    data = resp.json()
    return [
        s["symbol"] for s in data["symbols"]
        if s["quoteAsset"] == "USDT"
        and s["status"] == "TRADING"
    ]


def fetch(symbol, interval, limit=300):
    try:
        resp = SESSION.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=6,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json()
        if len(raw) < 220:
            return None
        return (
            [float(c[1]) for c in raw],  # opens
            [float(c[2]) for c in raw],  # highs
            [float(c[3]) for c in raw],  # lows
            [float(c[4]) for c in raw],  # closes
            [float(c[5]) for c in raw],  # volumes
        )
    except:
        return None

# ============================================================
# SCAN SYMBOL
# ============================================================

def scan_symbol(symbol):
    mode    = load_mode()
    signals = []

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
        ch = highs[-1]
        pc = closes[-2]

        body  = (cc - co) / co * 100
        avg_v = sum(vols[-21:-1]) / 20
        vol_r = vols[-1] / avg_v if avg_v > 0 else 0

        rsic           = rsi(closes)
        atrv           = atr(highs, lows, closes)
        if not atrv:
            continue
        atr_pct        = atrv / cc * 100
        adxv, pdi, mdi = adx(highs, lows, closes)

        # ── ELITE ─────────────────────────────────────────────
        if mode == "ELITE":

            ma200     = sma(closes, 200)
            ma200_prev = sma(closes[:-1], 200)
            e50       = ema(closes, 50)
            e200      = ema(closes, 200)

            if not all([ma200, ma200_prev, e50, e200]):
                continue
            if not (e50 > e200 and cc > ma200 * 1.01):
                continue
            ma200_old = sma(closes[-210:-10], 200)
            if not ma200_old or ma200 <= ma200_old:
                continue
            if not adxv or adxv < 25:
                continue
            if pdi and mdi and pdi <= mdi:
                continue

            macd_l, sig_l, hist = macd(closes)
            if macd_l is None or macd_l <= sig_l:
                continue
            prev_hist = macd(closes[:-1])[2]
            if prev_hist is None or hist <= prev_hist:
                continue
            if vol_r < 2.0:
                continue
            if body < 1.2:
                continue
            if rsic and rsic > 75:
                continue
            if atr_pct < 2.5:
                continue
            if not (pc < ma200_prev and cc > ma200):
                continue

            score, max_score, reasons = score_elite(closes, highs, lows, opens, vols)

        # ── SWING ─────────────────────────────────────────────
        elif mode == "SWING":

            ma50  = sma(closes, 50)
            ma200 = sma(closes, 200)
            e21   = ema(closes, 21)
            e50   = ema(closes, 50)
            e200  = ema(closes, 200)

            if not all([ma50, ma200, e21, e50, e200]):
                continue
            if not (e50 > e200 and cc > ma200):
                continue

            near_e21  = abs(cc - e21) / e21 * 100 < 2.0
            near_ma50 = abs(cc - ma50) / ma50 * 100 < 2.0
            if not (near_e21 or near_ma50):
                continue
            if rsic is None or not (42 <= rsic <= 62):
                continue

            bb_upper, bb_mid, bb_lower = bollinger(closes)
            if bb_mid and cc < bb_mid:
                continue

            lower_wick = (min(co, cc) - cl) / cl * 100
            if lower_wick < 0.8:
                continue
            if body < -1.5:
                continue
            if vol_r > 3.0:
                continue
            if adxv and adxv < 20:
                continue

            score, max_score, reasons = score_swing(closes, highs, lows, opens, vols)

        # ── SCALP ─────────────────────────────────────────────
        elif mode == "SCALP":

            e9_s  = ema_series(closes, 9)
            e21_s = ema_series(closes, 21)
            min_len = min(len(e9_s), len(e21_s))
            e9_s  = e9_s[-min_len:]
            e21_s = e21_s[-min_len:]

            if len(e9_s) < 2 or len(e21_s) < 2:
                continue

            cross_up = e9_s[-1] > e21_s[-1] and e9_s[-2] <= e21_s[-2]
            if not cross_up:
                continue

            if interval == "15m":
                htf_data = fetch(symbol, "1h")
                if htf_data:
                    _, htf_h, htf_l, htf_c, _ = htf_data
                    htf_e50  = ema(htf_c, 50)
                    htf_e200 = ema(htf_c, 200)
                    if htf_e50 and htf_e200 and htf_e50 < htf_e200:
                        continue

            macd_l, sig_l, hist = macd(closes)
            if macd_l is None or macd_l <= sig_l:
                continue

            stoch_k, stoch_d = stochastic(highs, lows, closes)
            if stoch_k is None or not (25 <= stoch_k <= 70):
                continue
            if vol_r < 1.8:
                continue
            if body < 0.6:
                continue
            if atr_pct < 0.8:
                continue
            if rsic is None or not (48 <= rsic <= 72):
                continue

            score, max_score, reasons = score_scalp(
                closes, highs, lows, opens, vols, interval, symbol
            )

        else:
            continue

        # ── Score Gate ────────────────────────────────────────
        min_ratio = MIN_SCORE_RATIO.get(mode, 0.60)
        if max_score == 0 or score / max_score < min_ratio:
            continue

        grade, badge = get_grade(score, max_score)
        emoji = {"ELITE": "🔥", "SWING": "✅", "SCALP": "⚡"}[mode]
        reason_text = "\n".join(reasons)

        signals.append((
            score,
            symbol,
            tf,
            (
                f"{emoji} <b>{mode} SIGNAL</b> | {badge} Grade {grade} ({score}/{max_score})\n\n"
                f"{reason_text}\n\n"
                f"MODE: {mode}"
            ),
        ))

    return signals

# ============================================================
# MAIN
# ============================================================

def scan_all():
    mode = load_mode()
    print(f"[{datetime.now()}] SCANNING {mode}")

    pairs       = get_pairs()
    all_signals = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(scan_symbol, p) for p in pairs]
        for f in as_completed(futs):
            try:
                all_signals.extend(f.result())
            except:
                pass

    # Prioritaskan sinyal dengan score tertinggi
    all_signals.sort(key=lambda x: x[0], reverse=True)

    print(f"Signals found: {len(all_signals)}")

    for sig in all_signals[:MAX_SIGNALS_PER_SCAN]:
        score, symbol, tf, msg = sig
        send_telegram(f"🪙 <b>{symbol}</b> [{tf}]\n\n{msg}")
        time.sleep(1)


if __name__ == "__main__":
    try:
        handle_telegram_commands()
        scan_all()
    except Exception as e:
        print(e)
        send_telegram(f"❌ Bot Error\n{e}")
