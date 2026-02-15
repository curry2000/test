import requests
import os
import numpy as np
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

POSITIONS = [
    {"name": "BTC 幣本位", "symbol": "BTCUSDT", "entry": 73985.4, "liquidation": 40336, "direction": "LONG", "leverage": 20, "platform": "OKX"},
    {"name": "ETH 幣本位", "symbol": "ETHUSDT", "entry": 2227.92, "liquidation": 1234, "direction": "LONG", "leverage": 20, "platform": "OKX"},
    {"name": "BTC U本位", "symbol": "BTCUSDT", "entry": 86265.28, "liquidation": 45675.82, "direction": "LONG", "leverage": 30, "platform": "Binance"},
]

def get_price(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol.replace('USDT','')}-USDT-SWAP"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0]["last"])
    except:
        pass
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        return float(r.json().get("price", 0))
    except:
        pass
    return 0

def get_klines(symbol, interval, limit):
    base = symbol.replace("USDT", "")
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={base}-USDT-SWAP&bar={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in reversed(data["data"])]
    except:
        pass
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if isinstance(data, list):
            return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in data]
    except:
        pass
    return []

def calc_rsi(klines):
    if len(klines) < 15:
        return 50
    closes = [k["close"] for k in klines]
    gains, losses = [], []
    for i in range(1, min(15, len(closes))):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses) if sum(losses) > 0 else 0.001
    return 100 - (100 / (1 + avg_gain / avg_loss))

def find_obs(klines, current):
    bull, bear = [], []
    for i in range(2, len(klines)-1):
        prev, curr, nxt = klines[i-1], klines[i], klines[i+1]
        if prev["close"] < prev["open"] and curr["close"] > curr["open"] and nxt["close"] > nxt["open"]:
            if nxt["close"] > prev["open"] and current > prev["close"]:
                bull.append({"top": prev["open"], "bottom": prev["close"]})
        if prev["close"] > prev["open"] and curr["close"] < curr["open"] and nxt["close"] < nxt["open"]:
            if nxt["close"] < prev["open"] and current < prev["close"]:
                bear.append({"top": prev["close"], "bottom": prev["open"]})
    return bull, bear

def analyze_levels(symbol):
    result = {}
    for interval, label in [("1h","1H"), ("4h","4H"), ("1d","1D")]:
        klines = get_klines(symbol, interval if "h" in interval else "1D", 100)
        if not klines:
            continue
        current = klines[-1]["close"]
        rsi = calc_rsi(klines)
        bull, bear = find_obs(klines, current)
        
        recent = klines[-24:] if len(klines) >= 24 else klines
        support = min(k["low"] for k in recent)
        resistance = max(k["high"] for k in recent)
        
        result[label] = {
            "rsi": rsi,
            "support": support,
            "resistance": resistance,
            "bull_ob": bull[-1] if bull else None,
            "bear_ob": bear[-1] if bear else None
        }
    return result

def get_action_advice(pos, price, levels):
    entry = pos["entry"]
    liq = pos["liquidation"]
    pnl_pct = (price - entry) / entry * 100
    liq_dist = (price - liq) / price * 100
    
    if liq_dist < 20:
        risk = "🔴高風險"
    elif liq_dist < 35:
        risk = "🟡中風險"
    else:
        risk = "🟢低風險"
    
    advice = []
    
    rsi_4h = levels.get("4H", {}).get("rsi", 50)
    rsi_1h = levels.get("1H", {}).get("rsi", 50)
    
    bull_1h = levels.get("1H", {}).get("bull_ob")
    bull_4h = levels.get("4H", {}).get("bull_ob")
    bear_1h = levels.get("1H", {}).get("bear_ob")
    bear_4h = levels.get("4H", {}).get("bear_ob")
    
    stop_zone = None
    if bull_4h:
        stop_zone = bull_4h["bottom"]
    elif bull_1h:
        stop_zone = bull_1h["bottom"]
    
    if pnl_pct < -15 and pos.get("leverage", 20) >= 30:
        advice.append("⚠️ 虧損大+高槓桿，不建議再加倉")
        advice.append("💡 等反彈到壓力區考慮減倉降風險")
        
        if bear_1h:
            dist = abs(price - bear_1h["bottom"]) / price * 100
            advice.append(f"🎯 減倉目標: ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f} ({dist:.1f}%)")
        if bear_4h:
            advice.append(f"🎯 4H減倉目標: ${bear_4h['bottom']:,.0f}-${bear_4h['top']:,.0f}")
        
        if rsi_4h < 25:
            advice.append("📊 4H RSI超賣，可能短線反彈，可等反彈後減倉")
        
        if stop_zone:
            advice.append(f"🛑 止損參考: 跌破 ${stop_zone:,.0f}")
        
        advice.append("💡 虧損較大，嚴格控制風險")
    else:
        add_zone = None
        if bull_4h:
            mid = (bull_4h["top"] + bull_4h["bottom"]) / 2
            dist = (price - mid) / price * 100
            if dist < 3:
                add_zone = bull_4h
                advice.append(f"📍 接近4H OB支撐 ${bull_4h['bottom']:,.0f}-${bull_4h['top']:,.0f}，可小量補倉")
            elif dist < 5:
                add_zone = bull_4h
                advice.append(f"👀 4H OB支撐在 ${bull_4h['bottom']:,.0f}-${bull_4h['top']:,.0f}，等回調到此區再補")
        
        if bull_1h and not add_zone:
            mid = (bull_1h["top"] + bull_1h["bottom"]) / 2
            dist = (price - mid) / price * 100
            if dist < 2:
                advice.append(f"📍 接近1H OB支撐 ${bull_1h['bottom']:,.0f}-${bull_1h['top']:,.0f}，可小量補倉")
        
        if stop_zone:
            advice.append(f"🛑 止損參考: 跌破 ${stop_zone:,.0f} (4H OB破)")
        
        if bear_1h:
            dist = abs(price - bear_1h["bottom"]) / price * 100
            if dist < 2:
                advice.append(f"⚠️ 接近1H壓力 ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f}，考慮部分減倉鎖利")
            else:
                advice.append(f"🎯 上方壓力: ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f}")
        
        if bear_4h:
            advice.append(f"🎯 4H壓力: ${bear_4h['bottom']:,.0f}-${bear_4h['top']:,.0f}")
        
        if rsi_4h < 25:
            advice.append("📊 4H RSI超賣，可能反彈")
        elif rsi_4h > 75:
            advice.append("📊 4H RSI超買，小心回調")
        
        if rsi_1h < 30:
            advice.append("📊 1H RSI超賣，短線可能反彈")
        elif rsi_1h > 70:
            advice.append("📊 1H RSI超買，短線注意回調")
        
        if pnl_pct > -3:
            advice.append("💡 接近回本，耐心持有")
        elif pnl_pct > -10:
            advice.append("💡 虧損可控，等待反彈")
    
    return {
        "name": pos["name"],
        "price": price,
        "entry": entry,
        "pnl_pct": pnl_pct,
        "liq": liq,
        "liq_dist": liq_dist,
        "risk": risk,
        "rsi_1h": rsi_1h,
        "rsi_4h": rsi_4h,
        "advice": advice,
        "levels": levels
    }

def format_message(results):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    lines = [f"💼 **倉位建議 [OKX雲端]** | {now}", ""]
    
    for r in results:
        pnl_emoji = "🟢" if r["pnl_pct"] >= 0 else "🔴"
        
        lines.append(f"**{r['name']}** {pnl_emoji}{r['pnl_pct']:+.1f}% | {r['risk']}")
        lines.append(f"現價 ${r['price']:,.2f} | 均價 ${r['entry']:,.2f} | 清算 ${r['liq']:,.0f} ({r['liq_dist']:.0f}%)")
        lines.append(f"RSI → 1H: {r['rsi_1h']:.0f} | 4H: {r['rsi_4h']:.0f}")
        
        for tf in ["1H", "4H", "1D"]:
            lv = r["levels"].get(tf, {})
            bull = lv.get("bull_ob")
            bear = lv.get("bear_ob")
            parts = []
            if bull:
                parts.append(f"🟢${bull['bottom']:,.0f}-${bull['top']:,.0f}")
            if bear:
                parts.append(f"🔴${bear['bottom']:,.0f}-${bear['top']:,.0f}")
            if parts:
                lines.append(f"  [{tf}] {' | '.join(parts)}")
        
        lines.append("")
        for a in r["advice"]:
            lines.append(f"  {a}")
        lines.append("")
    
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
    print("=== Position Advisor Start ===")
    
    prices = {}
    for symbol in set(p["symbol"] for p in POSITIONS):
        prices[symbol] = get_price(symbol)
        print(f"{symbol}: ${prices[symbol]:,.2f}")
    
    results = []
    for pos in POSITIONS:
        price = prices.get(pos["symbol"], 0)
        if price > 0:
            print(f"分析 {pos['name']}...")
            levels = analyze_levels(pos["symbol"])
            result = get_action_advice(pos, price, levels)
            results.append(result)
    
    if results:
        message = format_message(results)
        print("\n" + message)
        send_discord(message)

if __name__ == "__main__":
    main()
