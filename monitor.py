import requests
import os
from datetime import datetime, timezone, timedelta
import numpy as np

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

def get_klines(symbol, interval="1h", limit=100):
    urls = [
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}",
        f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={'60' if interval == '1h' else '15'}&limit={limit}"
    ]
    
    for url in urls:
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            
            if "fapi.binance" in url:
                if isinstance(data, list) and len(data) > 0:
                    return data
                print(f"    Binance returned: {str(data)[:100]}")
            else:
                if data.get("result", {}).get("list"):
                    raw = data["result"]["list"]
                    return [[int(k[0]), k[1], k[2], k[3], k[4], k[5]] for k in raw][::-1]
        except Exception as e:
            print(f"    Error from {url[:50]}: {e}")
            continue
    
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
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        tr_list.append(tr)
    return np.mean(tr_list[-period:])

def find_key_levels(highs, lows, closes, atr):
    if len(closes) < 24:
        return None, None
    recent_high = max(highs[-24:])
    recent_low = min(lows[-24:])
    current = closes[-1]
    resistance = recent_high
    support = recent_low
    return support, resistance

def find_order_blocks(klines, swing_length=3):
    if len(klines) < swing_length * 2 + 10:
        return []
    
    opens = [float(k[1]) for k in klines]
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    
    obs = []
    avg_vol = np.mean(volumes[-50:]) if len(volumes) >= 50 else np.mean(volumes)
    
    for i in range(swing_length, len(closes) - swing_length - 1):
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and \
                        all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and \
                       all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        if is_swing_high and volumes[i] > avg_vol * 0.8:
            for j in range(1, min(5, i+1)):
                if closes[i-j] > opens[i-j]:
                    obs.append({
                        "type": "bearish",
                        "top": highs[i-j],
                        "bottom": lows[i-j],
                        "index": i-j
                    })
                    break
        
        if is_swing_low and volumes[i] > avg_vol * 0.8:
            for j in range(1, min(5, i+1)):
                if closes[i-j] < opens[i-j]:
                    obs.append({
                        "type": "bullish",
                        "top": highs[i-j],
                        "bottom": lows[i-j],
                        "index": i-j
                    })
                    break
    
    return obs[-5:] if obs else []

def analyze_symbol(symbol):
    print(f"  Fetching 1H klines...")
    klines_1h = get_klines(symbol, "1h", 100)
    print(f"  Got {len(klines_1h)} 1H candles")
    
    print(f"  Fetching 15M klines...")
    klines_15m = get_klines(symbol, "15m", 100)
    print(f"  Got {len(klines_15m)} 15M candles")
    
    if not klines_1h:
        print(f"  ERROR: No 1H data for {symbol}")
        return None
    
    if not klines_15m:
        print(f"  WARNING: No 15M data, using 1H only")
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
    obs_15m = find_order_blocks(klines_15m)
    
    nearby_obs = []
    for ob in obs_1h + obs_15m:
        distance = abs(current_price - (ob["top"] + ob["bottom"]) / 2) / current_price * 100
        if distance < 3:
            ob["distance"] = distance
            nearby_obs.append(ob)
    
    return {
        "symbol": symbol,
        "price": current_price,
        "change_1h": price_change_1h,
        "change_24h": price_change_24h,
        "rsi_1h": rsi_1h,
        "rsi_15m": rsi_15m,
        "support": support,
        "resistance": resistance,
        "atr": atr,
        "order_blocks": nearby_obs[:3]
    }

def get_rsi_status(rsi):
    if rsi >= 70:
        return "🔴 超買", 0xff0000
    elif rsi <= 30:
        return "🟢 超賣", 0x00ff00
    elif rsi >= 60:
        return "🟡 偏多", 0xffaa00
    elif rsi <= 40:
        return "🟡 偏空", 0xffaa00
    else:
        return "⚪ 中性", 0x808080

def send_discord(analyses):
    if not DISCORD_WEBHOOK or not analyses:
        print("No webhook or no data")
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
            ob_text = ""
            for ob in a["order_blocks"]:
                ob_type = "🟢多方" if ob["type"] == "bullish" else "🔴空方"
                ob_text += f"{ob_type} ${ob['bottom']:,.0f}-${ob['top']:,.0f}\n"
            fields.append({"name": "📦 附近OB", "value": ob_text or "無", "inline": False})
        
        embed = {
            "title": f"📊 {a['symbol']} 技術分析",
            "color": color,
            "fields": fields,
            "footer": {"text": f"更新時間: {now}"}
        }
        embeds.append(embed)
    
    payload = {
        "content": f"**📈 技術分析報告 | {now}**",
        "embeds": embeds
    }
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Discord error: {e}")

def main():
    print("=== Crypto Monitor Start ===")
    print(f"Analyzing {SYMBOLS}...")
    
    analyses = []
    for symbol in SYMBOLS:
        print(f"\nAnalyzing {symbol}...")
        try:
            result = analyze_symbol(symbol)
            if result:
                analyses.append(result)
                print(f"  ✅ Price: ${result['price']:,.2f}")
                print(f"  ✅ RSI(1H): {result['rsi_1h']:.1f}")
                print(f"  ✅ OBs nearby: {len(result['order_blocks'])}")
            else:
                print(f"  ❌ No result for {symbol}")
        except Exception as e:
            print(f"  ❌ Error analyzing {symbol}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\nTotal analyses: {len(analyses)}")
    
    if analyses:
        send_discord(analyses)
        print("✅ Sent to Discord")
    else:
        print("❌ No data to send")

if __name__ == "__main__":
    main()
