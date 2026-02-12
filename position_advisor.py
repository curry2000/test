import requests
import os
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

POSITIONS = [
    {"name": "BTC 幣本位", "symbol": "BTCUSDT", "entry": 75225, "liquidation": 40336, "strategy": "ADD", "levels": [63000, 59800, 57000]},
    {"name": "BTC U本位", "symbol": "BTCUSDT", "entry": 86265, "liquidation": 45667, "strategy": "REDUCE", "levels": [72000, 76000, 80000]},
    {"name": "ETH 幣本位", "symbol": "ETHUSDT", "entry": 2253.98, "liquidation": 1234, "strategy": "ADD", "levels": [1800, 1650, 1500]}
]

def get_price(symbol):
    base = symbol.replace("USDT", "")
    
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={base}-USDT-SWAP"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0]["last"])
    except:
        pass
    
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("price"):
            return float(data["price"])
    except:
        pass
    
    return 0

def analyze_position(pos, current_price):
    if current_price <= 0:
        return None
    
    entry = pos["entry"]
    pnl_pct = ((current_price - entry) / entry) * 100
    liq = pos["liquidation"]
    liq_distance = ((current_price - liq) / current_price) * 100
    
    if pos["strategy"] == "ADD":
        action_levels = [l for l in pos["levels"] if current_price > l]
        next_level = min(action_levels) if action_levels else None
        action = "補倉"
    else:
        action_levels = [l for l in pos["levels"] if current_price < l]
        next_level = max(action_levels) if action_levels else None
        action = "減倉"
    
    if liq_distance < 20:
        risk = "🔴高風險"
    elif liq_distance < 35:
        risk = "🟡中風險"
    else:
        risk = "🟢低風險"
    
    return {
        "name": pos["name"], "price": current_price, "entry": entry,
        "pnl_pct": pnl_pct, "liq": liq, "liq_distance": liq_distance,
        "strategy": pos["strategy"], "action": action, "next_level": next_level,
        "levels": pos["levels"], "risk": risk
    }

def format_message(results):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    lines = [f"💼 **倉位建議** | {now}", ""]
    
    for r in results:
        pnl_emoji = "🟢" if r["pnl_pct"] >= 0 else "🔴"
        strategy_text = "補倉" if r["strategy"] == "ADD" else "減倉"
        levels_text = " / ".join([f"${l:,}" for l in r["levels"]])
        
        lines.append(f"**{r['name']}**")
        lines.append(f"現價 ${r['price']:,.2f} | 入場 ${r['entry']:,.2f} | {pnl_emoji}{r['pnl_pct']:+.1f}%")
        lines.append(f"清算 ${r['liq']:,.0f} (距離 {r['liq_distance']:.1f}%) | {r['risk']}")
        lines.append(f"📋 {strategy_text}點位: {levels_text}")
        
        if r["next_level"]:
            lines.append(f"⏭️ 下一動作: 到 ${r['next_level']:,} 時{strategy_text}")
        
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
            result = analyze_position(pos, price)
            if result:
                results.append(result)
    
    if results:
        message = format_message(results)
        print("\n" + message)
        send_discord(message)

if __name__ == "__main__":
    main()
