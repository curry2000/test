import requests
import os
from datetime import datetime, timezone, timedelta
import numpy as np

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

def get_klines(symbol, interval="1h", limit=100):
    base = symbol.replace("USDT", "")
    klines = []
    
    print(f"    [1] Trying OKX...")
    try:
        okx_interval = "1H" if interval == "1h" else "15m"
        okx_symbol = f"{base}-USDT-SWAP"
        url = f"https://www.okx.com/api/v5/market/candles?instId={okx_symbol}&bar={okx_interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            for k in reversed(data["data"]):
                klines.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
            print(f"    ✓ OKX: {len(klines)} candles")
            return klines
        print(f"    ✗ OKX error: {data.get('msg', data.get('code'))}")
    except Exception as e:
        print(f"    ✗ OKX exception: {e}")
    
    print(f"    [2] Trying Binance Spot...")
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            print(f"    ✓ Binance Spot: {len(data)} candles")
            return data
        print(f"    ✗ Binance Spot: empty or error")
    except Exception as e:
        print(f"    ✗ Binance Spot exception: {e}")
    
    print(f"    [3] Trying CoinGecko...")
    try:
        cg_id = "bitcoin" if base == "BTC" else "ethereum" if base == "ETH" else base.lower()
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/ohlc?vs_currency=usd&days=7"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            klines = [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), 0] for k in data]
            print(f"    ✓ CoinGecko: {len(klines)} candles")
            return klines[-limit:]
        print(f"    ✗ CoinGecko: empty")
    except Exception as e:
        print(f"    ✗ CoinGecko exception: {e}")
    
    return []

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 0
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    return np.mean(tr_list[-period:])

def find_key_levels(highs, lows, closes, atr):
    if len(closes) < 24:
        return None, None
    return min(lows[-24:]), max(highs[-24:])

def find_order_blocks(klines, swing_length=3):
    if len(klines) < swing_length * 2 + 10:
        return []
    
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) if len(k) > 5 else 1 for k in klines]
    
    obs = []
    avg_vol = np.mean(volumes[-50:]) if len(volumes) >= 50 else np.mean(volumes) if volumes else 1
    
    for i in range(swing_length, len(closes) - swing_length - 1):
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        if is_swing_high and (avg_vol == 0 or volumes[i] > avg_vol * 0.5):
            for j in range(1, min(5, i+1)):
                if closes[i-j] > opens[i-j]:
                    obs.append({"type": "bearish", "top": highs[i-j], "bottom": lows[i-j], "index": i-j})
                    break
        
        if is_swing_low and (avg_vol == 0 or volumes[i] > avg_vol * 0.5):
            for j in range(1, min(5, i+1)):
                if closes[i-j] < opens[i-j]:
                    obs.append({"type": "bullish", "top": highs[i-j], "bottom": lows[i-j], "index": i-j})
                    break
    
    return obs[-5:] if obs else []

def analyze_symbol(symbol):
    print(f"  Fetching 1H klines...")
    klines_1h = get_klines(symbol, "1h", 100)
    
    if not klines_1h:
        print(f"  ❌ No 1H data")
        return None
    
    print(f"  Fetching 15M klines...")
    klines_15m = get_klines(symbol, "15m", 100)
    if not klines_15m:
        klines_15m = klines_1h
    
    closes_1h = [float(k[4]) for k in klines_1h]
    highs_1h = [float(k[2]) for k in klines_1h]
    lows_1h = [float(k[3]) for k in klines_1h]
    
    current_price = closes_1h[-1]
    price_change_1h = ((current_price - closes_1h[-2]) / closes_1h[-2]) * 100 if len(closes_1h) > 1 else 0
    price_change_24h = ((current_price - closes_1h[-24]) / closes_1h[-24]) * 100 if len(closes_1h) >= 24 else 0
    
    rsi_1h = calculate_rsi(closes_1h)
    rsi_15m = calculate_rsi([float(k[4]) for k in klines_15m])
    
    atr = calculate_atr(highs_1h, lows_1h, closes_1h)
    support, resistance = find_key_levels(highs_1h, lows_1h, closes_1h, atr)
    
    obs_1h = find_order_blocks(klines_1h)
    
    nearby_obs = []
    for ob in obs_1h:
        distance = abs(current_price - (ob["top"] + ob["bottom"]) / 2) / current_price * 100
        if distance < 5:
            ob["distance"] = distance
            nearby_obs.append(ob)
    
    return {
        "symbol": symbol, "price": current_price, "change_1h": price_change_1h,
        "change_24h": price_change_24h, "rsi_1h": rsi_1h, "rsi_15m": rsi_15m,
        "support": support, "resistance": resistance, "atr": atr, "order_blocks": nearby_obs[:3]
    }

def get_rsi_status(rsi):
    if rsi >= 70: return "🔴 超買", 0xff0000
    elif rsi <= 30: return "🟢 超賣", 0x00ff00
    elif rsi >= 60: return "🟡 偏多", 0xffaa00
    elif rsi <= 40: return "🟡 偏空", 0xffaa00
    else: return "⚪ 中性", 0x808080

def send_discord(analyses):
    if not DISCORD_WEBHOOK:
        print("No DISCORD_WEBHOOK set")
        return
    if not analyses:
        print("No analyses to send")
        return
    
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M")
    
    embeds = []
    for a in analyses:
        rsi_status, color = get_rsi_status(a["rsi_1h"])
        
        fields = [
            {"name": "💰 現價", "value": f"${a['price']:,.2f}", "inline": True},
            {"name": "📈 1H變動", "value": f"{a['change_1h']:+.2f}%", "inline": True},
            {"name": "📊 24H變動", "value": f"{a['change_24h']:+.2f}%", "inline": True},
            {"name": "📉 RSI(1H)", "value": f"{a['rsi_1h']:.1f} {rsi_status}", "inline": True},
            {"name": "📉 RSI(15M)", "value": f"{a['rsi_15m']:.1f}", "inline": True},
            {"name": "📏 ATR", "value": f"${a['atr']:,.2f}", "inline": True},
        ]
        
        if a["support"] and a["resistance"]:
            support_dist = (a["price"] - a["support"]) / a["price"] * 100
            resist_dist = (a["resistance"] - a["price"]) / a["price"] * 100
            fields.append({"name": "🟢 支撐", "value": f"${a['support']:,.2f} ({support_dist:.1f}%)", "inline": True})
            fields.append({"name": "🔴 阻力", "value": f"${a['resistance']:,.2f} ({resist_dist:.1f}%)", "inline": True})
        
        if a["order_blocks"]:
            ob_text = "\n".join([f"{'🟢多方' if ob['type']=='bullish' else '🔴空方'} ${ob['bottom']:,.0f}-${ob['top']:,.0f}" for ob in a["order_blocks"]])
            fields.append({"name": "📦 附近OB", "value": ob_text, "inline": False})
        
        embeds.append({"title": f"📊 {a['symbol']} 技術分析", "color": color, "fields": fields, "footer": {"text": f"更新: {now}"}})
    
    payload = {"content": f"**📈 技術分析報告 | {now}**", "embeds": embeds}
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"Discord response: {r.status_code}")
        if r.status_code != 200:
            print(f"Discord body: {r.text[:200]}")
    except Exception as e:
        print(f"Discord error: {e}")

def main():
    print("=== Crypto Monitor Start ===")
    
    analyses = []
    for symbol in SYMBOLS:
        print(f"\n[{symbol}]")
        try:
            result = analyze_symbol(symbol)
            if result:
                analyses.append(result)
                print(f"  ✅ ${result['price']:,.2f} | RSI: {result['rsi_1h']:.1f} | OB: {len(result['order_blocks'])}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    print(f"\n=== Results: {len(analyses)}/{len(SYMBOLS)} ===")
    send_discord(analyses)

if __name__ == "__main__":
    main()
