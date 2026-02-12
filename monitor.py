import requests
import os
from datetime import datetime, timezone, timedelta
import numpy as np

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

CONFIDENCE_TABLE = {
    "rsi_high_bearish": 75,
    "normal_bearish": 65,
    "high_vol_bullish": 45,
    "high_vol_bearish": 40,
    "rsi_low_bullish": 37,
    "normal_bullish": 35,
}

def get_klines(symbol, interval, limit):
    base = symbol.replace("USDT", "")
    okx_symbol = f"{base}-USDT-SWAP"
    
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={okx_symbol}&bar={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]), 
                    "close": float(k[4]), "volume": float(k[5])} for k in reversed(data["data"])]
    except:
        pass
    
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list):
            return [{"open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                    "close": float(k[4]), "volume": float(k[5])} for k in data]
    except:
        pass
    
    return []

def calculate_rsi(klines, period=14):
    if len(klines) < period + 1:
        return 50
    closes = [k["close"] for k in klines]
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def rsi_emoji(rsi):
    if rsi <= 30: return "🔴"
    elif rsi >= 70: return "🟢"
    return "⚪"

def find_order_blocks(klines, swing_length=3):
    if len(klines) < swing_length * 2 + 5:
        return []
    
    obs = []
    avg_vol = np.mean([k["volume"] for k in klines[-50:]]) if len(klines) >= 50 else np.mean([k["volume"] for k in klines])
    closes = [k["close"] for k in klines]
    
    for i in range(swing_length, len(klines) - swing_length - 1):
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and \
                        all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and \
                       all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        vol_ratio = klines[i]["volume"] / avg_vol if avg_vol > 0 else 1
        rsi_at_ob = calculate_rsi(klines[:i+1])
        
        if is_swing_high and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] > klines[i-j]["open"]:
                    obs.append({"type": "bearish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                               "vol_ratio": vol_ratio, "rsi": rsi_at_ob, "index": i})
                    break
        
        if is_swing_low and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] < klines[i-j]["open"]:
                    obs.append({"type": "bullish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                               "vol_ratio": vol_ratio, "rsi": rsi_at_ob, "index": i})
                    break
    
    return obs

def get_confidence(ob):
    high_vol = ob.get("vol_ratio", 1) > 1.2
    rsi = ob.get("rsi", 50)
    
    if ob["type"] == "bearish":
        if rsi > 65:
            return CONFIDENCE_TABLE["rsi_high_bearish"]
        elif high_vol:
            return CONFIDENCE_TABLE["high_vol_bearish"]
        else:
            return CONFIDENCE_TABLE["normal_bearish"]
    else:
        if rsi < 35:
            return CONFIDENCE_TABLE["rsi_low_bullish"]
        elif high_vol:
            return CONFIDENCE_TABLE["high_vol_bullish"]
        else:
            return CONFIDENCE_TABLE["normal_bullish"]

def analyze_symbol(symbol):
    klines_15m = get_klines(symbol, "15m", 96)
    klines_30m = get_klines(symbol, "30m", 96)
    klines_1h = get_klines(symbol, "1H", 72)
    klines_4h = get_klines(symbol, "4H", 42)
    
    if not klines_15m and not klines_1h:
        return None
    
    klines_main = klines_15m or klines_1h
    current_price = klines_main[-1]["close"]
    
    rsi_15m = calculate_rsi(klines_15m) if klines_15m else 50
    rsi_30m = calculate_rsi(klines_30m) if klines_30m else 50
    rsi_1h = calculate_rsi(klines_1h) if klines_1h else 50
    rsi_4h = calculate_rsi(klines_4h) if klines_4h else 50
    
    all_obs = []
    for tf_name, klines, swing in [("15M", klines_15m, 2), ("1H", klines_1h, 3), ("4H", klines_4h, 3)]:
        if not klines:
            continue
        for ob in find_order_blocks(klines, swing)[-5:]:
            ob["tf"] = tf_name
            mid = (ob["top"] + ob["bottom"]) / 2
            ob["distance"] = (current_price - mid) / current_price * 100
            ob["confidence"] = get_confidence(ob)
            all_obs.append(ob)
    
    bullish_obs = sorted([ob for ob in all_obs if ob["type"] == "bullish" and ob["distance"] > 0],
                        key=lambda x: x["distance"])[:3]
    bearish_obs = sorted([ob for ob in all_obs if ob["type"] == "bearish" and ob["distance"] < 0],
                        key=lambda x: abs(x["distance"]))[:3]
    
    highs = [k["high"] for k in klines_1h] if klines_1h else [current_price]
    lows = [k["low"] for k in klines_1h] if klines_1h else [current_price]
    support = min(lows[-24:]) if len(lows) >= 24 else min(lows)
    resistance = max(highs[-24:]) if len(highs) >= 24 else max(highs)
    
    return {
        "symbol": symbol,
        "price": current_price,
        "rsi": {"15m": rsi_15m, "30m": rsi_30m, "1h": rsi_1h, "4h": rsi_4h},
        "support": support,
        "resistance": resistance,
        "bullish_obs": bullish_obs,
        "bearish_obs": bearish_obs
    }

def format_message(analyses):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    lines = [f"📊 **技術分析** | {now}", ""]
    
    for a in analyses:
        base = a["symbol"].replace("USDT", "")
        rsi = a["rsi"]
        
        lines.append(f"**{base}: ${a['price']:,.2f}**")
        lines.append(f"RSI → 15分:{rsi_emoji(rsi['15m'])}{rsi['15m']:.0f} | 30分:{rsi_emoji(rsi['30m'])}{rsi['30m']:.0f} | 1時:{rsi_emoji(rsi['1h'])}{rsi['1h']:.0f} | 4時:{rsi_emoji(rsi['4h'])}{rsi['4h']:.0f}")
        
        sup_dist = (a["price"] - a["support"]) / a["price"] * 100
        res_dist = (a["resistance"] - a["price"]) / a["price"] * 100
        lines.append(f"📍 支撐 ${a['support']:,.0f} ({sup_dist:.1f}%) | 阻力 ${a['resistance']:,.0f} ({res_dist:.1f}%)")
        
        lines.append("📦 OB:")
        
        if a["bullish_obs"]:
            for ob in a["bullish_obs"][:2]:
                lines.append(f"   🟢 [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f} | 📈做多 {ob['confidence']}%")
        else:
            lines.append("   🟢 (無接近的多方OB)")
        
        if a["bearish_obs"]:
            for ob in a["bearish_obs"][:2]:
                lines.append(f"   🔴 [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f} | 📉做空 {ob['confidence']}%")
        else:
            lines.append("   🔴 (無接近的空方OB)")
        
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("🔴<30超賣 | ⚪中性 | 🟢>70超買")
    lines.append("信心%=30天回測勝率")
    
    return "\n".join(lines)

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("No webhook")
        return
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def main():
    print("=== Crypto Monitor Start ===")
    
    analyses = []
    for symbol in SYMBOLS:
        print(f"Analyzing {symbol}...")
        result = analyze_symbol(symbol)
        if result:
            analyses.append(result)
            print(f"  OK: ${result['price']:,.2f}")
    
    if analyses:
        message = format_message(analyses)
        print("\n" + message)
        send_discord(message)
    else:
        print("No data")

if __name__ == "__main__":
    main()
