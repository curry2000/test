import requests
import os
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

POSITIONS = [
    {
        "name": "BTC 幣本位",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "entry": 75225,
        "size": 0.9046,
        "liquidation": 40336,
        "strategy": "ADD",
        "levels": [63000, 59800, 57000]
    },
    {
        "name": "BTC U本位",
        "symbol": "BTCUSDT",
        "side": "LONG",
        "entry": 86265,
        "size": 1.109,
        "liquidation": 45667,
        "strategy": "REDUCE",
        "levels": [72000, 76000, 80000]
    },
    {
        "name": "ETH 幣本位",
        "symbol": "ETHUSDT",
        "side": "LONG",
        "entry": 2253.98,
        "size": 15.45,
        "liquidation": 1234,
        "strategy": "ADD",
        "levels": [1800, 1650, 1500]
    }
]

def get_price(symbol):
    urls = [
        f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}",
        f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}",
        f"https://www.okx.com/api/v5/market/ticker?instId={symbol.replace('USDT', '-USDT-SWAP')}"
    ]
    
    for i, url in enumerate(urls):
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            if i == 0:
                price = float(data["result"]["list"][0]["lastPrice"])
            elif i == 1:
                price = float(data["price"])
            else:
                price = float(data["data"][0]["last"])
            if price > 0:
                return price
        except:
            continue
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
        action = "補倉" if next_level else "觀望"
    else:
        action_levels = [l for l in pos["levels"] if current_price < l]
        next_level = max(action_levels) if action_levels else None
        action = "減倉" if next_level else "觀望"
    
    if liq_distance < 20:
        risk = "🔴 高風險"
        risk_color = 0xff0000
    elif liq_distance < 35:
        risk = "🟡 中風險"
        risk_color = 0xffaa00
    else:
        risk = "🟢 低風險"
        risk_color = 0x00ff00
    
    return {
        "name": pos["name"],
        "symbol": pos["symbol"],
        "current_price": current_price,
        "entry": entry,
        "pnl_pct": pnl_pct,
        "liq": liq,
        "liq_distance": liq_distance,
        "strategy": pos["strategy"],
        "action": action,
        "next_level": next_level,
        "levels": pos["levels"],
        "risk": risk,
        "risk_color": risk_color
    }

def send_discord(results):
    if not DISCORD_WEBHOOK or not results:
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
            fields.append({
                "name": "⏭️ 下一動作",
                "value": f"價格到 ${r['next_level']:,} 時{strategy_text}",
                "inline": False
            })
        
        embed = {
            "title": f"📊 {r['name']}",
            "color": r["risk_color"],
            "fields": fields
        }
        embeds.append(embed)
    
    payload = {
        "content": f"**💼 倉位建議報告 | {now}**",
        "embeds": embeds
    }
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Discord error: {e}")

def main():
    print("=== Position Advisor Start ===")
    
    prices = {}
    for symbol in set(p["symbol"] for p in POSITIONS):
        price = get_price(symbol)
        prices[symbol] = price
        print(f"{symbol}: ${price:,.2f}")
    
    results = []
    for pos in POSITIONS:
        price = prices.get(pos["symbol"], 0)
        if price > 0:
            result = analyze_position(pos, price)
            if result:
                results.append(result)
                print(f"\n{pos['name']}: PnL {result['pnl_pct']:+.2f}%, Risk: {result['risk']}")
    
    if results:
        send_discord(results)

if __name__ == "__main__":
    main()
