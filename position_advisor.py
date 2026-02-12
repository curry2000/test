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
    
    print(f"  [1] OKX...")
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={base}-USDT-SWAP"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            price = float(data["data"][0]["last"])
            print(f"  ✓ OKX: ${price:,.2f}")
            return price
        print(f"  ✗ OKX: {data.get('msg', 'error')}")
    except Exception as e:
        print(f"  ✗ OKX: {e}")
    
    print(f"  [2] Binance Spot...")
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("price"):
            price = float(data["price"])
            print(f"  ✓ Binance: ${price:,.2f}")
            return price
    except Exception as e:
        print(f"  ✗ Binance: {e}")
    
    print(f"  [3] CoinGecko...")
    try:
        cg_id = "bitcoin" if base == "BTC" else "ethereum" if base == "ETH" else base.lower()
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get(cg_id, {}).get("usd"):
            price = float(data[cg_id]["usd"])
            print(f"  ✓ CoinGecko: ${price:,.2f}")
            return price
    except Exception as e:
        print(f"  ✗ CoinGecko: {e}")
    
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
        risk, risk_color = "🔴 高風險", 0xff0000
    elif liq_distance < 35:
        risk, risk_color = "🟡 中風險", 0xffaa00
    else:
        risk, risk_color = "🟢 低風險", 0x00ff00
    
    return {
        "name": pos["name"], "current_price": current_price, "entry": entry,
        "pnl_pct": pnl_pct, "liq": liq, "liq_distance": liq_distance,
        "strategy": pos["strategy"], "action": action, "next_level": next_level,
        "levels": pos["levels"], "risk": risk, "risk_color": risk_color
    }

def send_discord(results):
    if not DISCORD_WEBHOOK:
        print("No DISCORD_WEBHOOK")
        return
    if not results:
        print("No results")
        return
    
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M")
    
    embeds = []
    for r in results:
        strategy_text = "補倉" if r["strategy"] == "ADD" else "減倉"
        levels_text = " / ".join([f"${l:,}" for l in r["levels"]])
        pnl_emoji = "🟢" if r["pnl_pct"] >= 0 else "🔴"
        
        fields = [
            {"name": "💰 現價", "value": f"${r['current_price']:,.2f}", "inline": True},
            {"name": "📍 入場價", "value": f"${r['entry']:,.2f}", "inline": True},
            {"name": f"{pnl_emoji} 盈虧", "value": f"{r['pnl_pct']:+.2f}%", "inline": True},
            {"name": "⚠️ 清算價", "value": f"${r['liq']:,.2f}", "inline": True},
            {"name": "📏 清算距離", "value": f"{r['liq_distance']:.1f}%", "inline": True},
            {"name": "🎯 風險", "value": r["risk"], "inline": True},
            {"name": f"📋 策略 ({strategy_text})", "value": levels_text, "inline": False},
        ]
        
        if r["next_level"]:
            fields.append({"name": "⏭️ 下一動作", "value": f"價格到 ${r['next_level']:,} 時{strategy_text}", "inline": False})
        
        embeds.append({"title": f"📊 {r['name']}", "color": r["risk_color"], "fields": fields})
    
    payload = {"content": f"**💼 倉位建議報告 | {now}**", "embeds": embeds}
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Discord error: {e}")

def main():
    print("=== Position Advisor Start ===")
    
    prices = {}
    for symbol in set(p["symbol"] for p in POSITIONS):
        print(f"\n[{symbol}]")
        prices[symbol] = get_price(symbol)
    
    results = []
    for pos in POSITIONS:
        price = prices.get(pos["symbol"], 0)
        if price > 0:
            result = analyze_position(pos, price)
            if result:
                results.append(result)
                print(f"\n{pos['name']}: PnL {result['pnl_pct']:+.2f}%, {result['risk']}")
    
    print(f"\n=== {len(results)} positions analyzed ===")
    send_discord(results)

if __name__ == "__main__":
    main()
