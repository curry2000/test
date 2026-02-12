#!/usr/bin/env python3
import requests
import os
from datetime import datetime

print("=== OB Script Start ===")

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
print(f"Webhook URL exists: {bool(WEBHOOK)}")
print(f"Webhook URL length: {len(WEBHOOK)}")

def get_price(symbol):
    try:
        print(f"Getting price for {symbol}...")
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            price = float(data["result"]["list"][0]["lastPrice"])
            print(f"{symbol} price: {price}")
            return price
    except Exception as e:
        print(f"Price error for {symbol}: {e}")
    return 0

def get_klines(symbol, tf):
    try:
        print(f"Getting klines for {symbol} {tf}...")
        interval_map = {"15m": "15", "30m": "30"}
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "interval": interval_map[tf],
                "limit": 200
            },
            timeout=15
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            klines = [{"o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4])} for k in reversed(data["result"]["list"])]
            print(f"Got {len(klines)} klines for {symbol} {tf}")
            return klines
    except Exception as e:
        print(f"Klines error for {symbol} {tf}: {e}")
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
    unique_bull = []
    for ob in valid_bullish:
        key = f"{ob['bl']:.0f}"
        if key not in seen:
            seen.add(key)
            unique_bull.append(ob)
    
    seen = set()
    unique_bear = []
    for ob in valid_bearish:
        key = f"{ob['bl']:.0f}"
        if key not in seen:
            seen.add(key)
            unique_bear.append(ob)
    
    return unique_bull, unique_bear

def main():
    print("Building message...")
    lines = ["📊 **OB 訂單塊分析**", ""]
    
    for symbol in ["BTC", "ETH"]:
        price = get_price(symbol)
        lines.append(f"**{symbol}** ${price:,.2f}")
        lines.append("")
        
        for tf in ["15m", "30m"]:
            klines = get_klines(symbol, tf)
            bullish, bearish = find_obs(klines)
            
            print(f"{symbol} {tf}: {len(bullish)} bullish, {len(bearish)} bearish OBs")
            
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
    print("=" * 50)
    print("MESSAGE:")
    print(msg)
    print("=" * 50)
    
    if WEBHOOK:
        print("Sending to Discord...")
        try:
            r = requests.post(
                WEBHOOK,
                json={"content": msg, "username": "📊 OB 訂單塊"},
                timeout=10
            )
            print(f"Discord response: {r.status_code} - {r.text[:100] if r.text else 'empty'}")
        except Exception as e:
            print(f"Discord error: {e}")
    else:
        print("NO WEBHOOK URL - skipping Discord send")
    
    print("=== OB Script End ===")

if __name__ == "__main__":
    main()
