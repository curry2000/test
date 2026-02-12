import requests
import os
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

def get_all_tickers():
    tickers = []
    seen = set()
    
    print("  [1] Binance Futures...")
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list):
            for t in data:
                if t["symbol"].endswith("USDT"):
                    tickers.append({
                        "symbol": t["symbol"],
                        "price": float(t["lastPrice"]),
                        "change_24h": float(t["priceChangePercent"]),
                        "volume": float(t["quoteVolume"]),
                        "source": "BN"
                    })
                    seen.add(t["symbol"])
            print(f"  ✓ Binance: {len(tickers)} 個")
    except Exception as e:
        print(f"  ✗ Binance: {e}")
    
    print("  [2] OKX SWAP...")
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            count = 0
            for t in data["data"]:
                if "-USDT-SWAP" in t["instId"]:
                    symbol = t["instId"].replace("-USDT-SWAP", "") + "USDT"
                    if symbol not in seen:
                        open_price = float(t.get("open24h", 0))
                        tickers.append({
                            "symbol": symbol,
                            "price": float(t["last"]),
                            "change_24h": (float(t["last"]) / open_price * 100 - 100) if open_price > 0 else 0,
                            "volume": float(t.get("volCcy24h", 0)),
                            "source": "OKX"
                        })
                        count += 1
            print(f"  ✓ OKX: +{count} 個")
    except Exception as e:
        print(f"  ✗ OKX: {e}")
    
    return tickers

def get_price_change_1h(symbol):
    base = symbol.replace("USDT", "")
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={base}-USDT-SWAP&bar=1H&limit=2"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and data.get("data") and len(data["data"]) >= 2:
            sorted_data = sorted(data["data"], key=lambda x: int(x[0]))
            old_price = float(sorted_data[-2][4])
            new_price = float(sorted_data[-1][4])
            return (new_price - old_price) / old_price * 100 if old_price > 0 else 0
    except:
        pass
    return 0

def format_number(n):
    if n >= 1e9: return f"{n/1e9:.1f}B"
    elif n >= 1e6: return f"{n/1e6:.1f}M"
    elif n >= 1e3: return f"{n/1e3:.1f}K"
    return f"{n:.0f}"

def format_message(alerts, scanned):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    if not alerts:
        return f"✅ **價格掃描** | {now}\n掃描 {scanned} 幣種，無 >15% 異動"
    
    lines = [f"🔍 **價格異動** | {now}", f"掃描 {scanned} 幣種，發現 {len(alerts)} 個 >15% 波動", ""]
    
    for a in alerts[:10]:
        direction = "📈" if a["change_24h"] > 0 else "📉"
        src = a.get("source", "")
        lines.append(f"**{a['symbol'].replace('USDT', '')}** ${a['price']:,.4g} | {direction}{a['change_24h']:+.1f}%")
    
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
    print("=== OI Scanner Start ===")
    
    tickers = get_all_tickers()
    if not tickers:
        print("No tickers")
        return
    
    print(f"總共 {len(tickers)} 個幣種")
    
    alerts = []
    for t in tickers:
        if abs(t["change_24h"]) >= 15:
            alerts.append(t)
            src = t.get("source", "?")
            print(f"🚨 [{src}] {t['symbol']}: 24H {t['change_24h']:+.1f}%")
    
    alerts.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    
    message = format_message(alerts, len(tickers))
    print("\n" + message)
    send_discord(message)

if __name__ == "__main__":
    main()
