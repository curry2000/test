#!/usr/bin/env python3
import requests
import os
from datetime import datetime

print("=== OB Script Start ===")

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def get_price(symbol):
    # Try OKX first
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": f"{symbol}-USDT-SWAP"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            price = float(data["data"][0]["last"])
            print(f"{symbol} price (OKX): {price}")
            return price
    except Exception as e:
        print(f"OKX price error: {e}")
    
    # Try Bybit
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": f"{symbol}USDT"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            price = float(data["result"]["list"][0]["lastPrice"])
            print(f"{symbol} price (Bybit): {price}")
            return price
    except Exception as e:
        print(f"Bybit price error: {e}")
    
    # Try CoinGecko
    try:
        coin_id = "bitcoin" if symbol == "BTC" else "ethereum"
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if coin_id in data:
            price = float(data[coin_id]["usd"])
            print(f"{symbol} price (CoinGecko): {price}")
            return price
    except Exception as e:
        print(f"CoinGecko price error: {e}")
    
    return 0

def get_klines(symbol, tf):
    # Try OKX first
    try:
        interval_map = {"15m": "15m", "30m": "30m"}
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": f"{symbol}-USDT-SWAP", "bar": interval_map[tf], "limit": "200"},
            headers=HEADERS,
            timeout=15
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            klines = [{"o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])} for k in reversed(data["data"])]
            print(f"{symbol} {tf} klines (OKX): {len(klines)}")
            return klines
    except Exception as e:
        print(f"OKX klines error: {e}")
    
    # Try Bybit
    try:
        interval_map = {"15m": "15", "30m": "30"}
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={"category": "linear", "symbol": f"{symbol}USDT", "interval": interval_map[tf], "limit": 200},
            headers=HEADERS,
            timeout=15
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            klines = [{"o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])} for k in reversed(data["result"]["list"])]
            print(f"{symbol} {tf} klines (Bybit): {len(klines)}")
            return klines
    except Exception as e:
        print(f"Bybit klines error: {e}")
    
    return []

def find_obs(klines):
    if len(klines) < 10:
        return [], []
    
    bullish, bearish = [], []
    
    for i in range(3, len(klines) - 3):
        is_swing_low = all(klines[i]["l"] < klines[i-j]["l"] and klines[i]["l"] < klines[i+j]["l"] for j in range(1, 4))
        is_swing_high = all(klines[i]["h"] > klines[i-j]["h"] and klines[i]["h"] > klines[i+j]["h"] for j in range(1, 4))
        
        if is_swing_low and i >= 15:
            ref_high = max(k["h"] for k in klines[i-15:i])
            for x in range(i+1, min(len(klines), i+30)):
                if klines[x]["c"] > ref_high:
                    for j in range(x-1, max(i-8, 0), -1):
                        if klines[j]["c"] < klines[j]["o"]:
                            bullish.append({"low": klines[j]["l"], "high": klines[j]["h"], "bl": klines[j]["c"], "bh": klines[j]["o"], "idx": j})
                            break
                    break
        
        if is_swing_high and i >= 15:
            ref_low = min(k["l"] for k in klines[i-15:i])
            for x in range(i+1, min(len(klines), i+30)):
                if klines[x]["c"] < ref_low:
                    for j in range(x-1, max(i-8, 0), -1):
                        if klines[j]["c"] > klines[j]["o"]:
                            bearish.append({"low": klines[j]["l"], "high": klines[j]["h"], "bl": klines[j]["o"], "bh": klines[j]["c"], "idx": j})
                            break
                    break
    
    current_idx = len(klines) - 1
    
    valid_bullish = []
    for ob in bullish:
        if current_idx - ob["idx"] > 180:
            continue
        valid = True
        for i in range(ob["idx"]+1, len(klines)):
            if klines[i]["c"] < ob["low"]:
                valid = False
                break
        if valid:
            valid_bullish.append(ob)
    
    valid_bearish = []
    for ob in bearish:
        if current_idx - ob["idx"] > 180:
            continue
        valid = True
        for i in range(ob["idx"]+1, len(klines)):
            if klines[i]["c"] > ob["high"]:
                valid = False
                break
        if valid:
            valid_bearish.append(ob)
    
    seen = set()
    unique_bull = [ob for ob in valid_bullish if not (f"{ob['bl']:.0f}" in seen or seen.add(f"{ob['bl']:.0f}"))]
    seen = set()
    unique_bear = [ob for ob in valid_bearish if not (f"{ob['bl']:.0f}" in seen or seen.add(f"{ob['bl']:.0f}"))]
    
    return unique_bull, unique_bear

def send_alert(msg):
    if WEBHOOK:
        try:
            requests.post(WEBHOOK, json={"content": msg, "username": "⚠️ API 警報"}, timeout=10)
        except:
            pass

def main():
    api_errors = []
    lines = ["📊 **OB 訂單塊分析**", ""]
    
    for symbol in ["BTC", "ETH"]:
        price = get_price(symbol)
        if price == 0:
            api_errors.append(f"{symbol} 價格 API 全部失敗")
        
        lines.append(f"**{symbol}** ${price:,.2f}")
        lines.append("")
        
        for tf in ["15m", "30m"]:
            klines = get_klines(symbol, tf)
            if len(klines) == 0:
                api_errors.append(f"{symbol} {tf} K線 API 全部失敗")
            bullish, bearish = find_obs(klines)
            
            print(f"{symbol} {tf}: {len(bullish)} bullish, {len(bearish)} bearish")
            
            bullish = sorted(bullish, key=lambda x: x["bh"], reverse=True)[:4]
            bearish = sorted(bearish, key=lambda x: x["bl"])[:4]
            
            lines.append(f"📈 **{tf}**")
            
            if bearish:
                lines.append("🔴 壓力區:")
                for ob in bearish:
                    dist = (ob["bl"] - price) / price * 100 if price > 0 else 0
                    lines.append(f"   ${ob['bl']:,.0f}-${ob['bh']:,.0f} ({dist:+.1f}%)")
            else:
                lines.append("🔴 壓力區: 無")
            
            if bullish:
                lines.append("🟢 支撐區:")
                for ob in bullish:
                    dist = (price - ob["bh"]) / price * 100 if price > 0 else 0
                    lines.append(f"   ${ob['bl']:,.0f}-${ob['bh']:,.0f} ({dist:+.1f}%)")
            else:
                lines.append("🟢 支撐區: 無")
            
            lines.append("")
        
        lines.append("---")
    
    lines.append(f"⏰ {datetime.now().strftime('%H:%M')}")
    
    msg = "\n".join(lines)
    print("MESSAGE:")
    print(msg)
    
    if WEBHOOK:
        try:
            r = requests.post(WEBHOOK, json={"content": msg, "username": "📊 OB 訂單塊"}, timeout=10)
            print(f"Discord: {r.status_code}")
        except Exception as e:
            print(f"Discord error: {e}")
    
    if api_errors:
        error_msg = "⚠️ **API 異常警報**\n\n" + "\n".join(api_errors) + f"\n\n⏰ {datetime.now().strftime('%H:%M')}"
        print(error_msg)
        send_alert(error_msg)
    
    print("=== Done ===")

if __name__ == "__main__":
    main()
