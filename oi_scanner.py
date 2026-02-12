import requests
import os
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

def get_all_tickers():
    print("Fetching tickers...")
    
    print("  [1] Trying OKX...")
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            tickers = []
            for t in data["data"]:
                if "-USDT-SWAP" in t["instId"]:
                    symbol = t["instId"].replace("-USDT-SWAP", "") + "USDT"
                    open_price = float(t.get("open24h", 0))
                    tickers.append({
                        "symbol": symbol,
                        "lastPrice": float(t["last"]),
                        "priceChangePercent": (float(t["last"]) / open_price * 100 - 100) if open_price > 0 else 0,
                        "quoteVolume": float(t.get("volCcy24h", 0))
                    })
            print(f"  ✓ OKX: {len(tickers)} tickers")
            return tickers
        print(f"  ✗ OKX: {data.get('msg', 'error')}")
    except Exception as e:
        print(f"  ✗ OKX: {e}")
    
    print("  [2] Trying Binance Spot...")
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list):
            tickers = [{"symbol": t["symbol"], "lastPrice": float(t["lastPrice"]), 
                       "priceChangePercent": float(t["priceChangePercent"]),
                       "quoteVolume": float(t["quoteVolume"])} 
                      for t in data if t["symbol"].endswith("USDT")]
            print(f"  ✓ Binance Spot: {len(tickers)} tickers")
            return tickers
    except Exception as e:
        print(f"  ✗ Binance Spot: {e}")
    
    return []

def get_oi_and_price_data(symbols):
    print(f"Fetching OI & price for {len(symbols)} symbols...")
    results = {}
    
    for symbol in symbols[:50]:
        base = symbol.replace("USDT", "")
        
        try:
            okx_symbol = f"{base}-USDT-SWAP"
            
            oi_url = f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={okx_symbol}"
            r = requests.get(oi_url, timeout=10)
            data = r.json()
            
            current_oi = 0
            if data.get("code") == "0" and data.get("data"):
                current_oi = float(data["data"][0].get("oiCcy", 0))
            
            price_url = f"https://www.okx.com/api/v5/market/candles?instId={okx_symbol}&bar=1H&limit=2"
            r2 = requests.get(price_url, timeout=10)
            data2 = r2.json()
            
            if data2.get("code") == "0" and data2.get("data") and len(data2["data"]) >= 2:
                sorted_candles = sorted(data2["data"], key=lambda x: int(x[0]))
                old_price = float(sorted_candles[-2][4])
                new_price = float(sorted_candles[-1][4])
                
                if current_oi > 0 and old_price > 0:
                    results[symbol] = {
                        "oi": current_oi,
                        "old_price": old_price,
                        "new_price": new_price,
                        "price_change": (new_price - old_price) / old_price * 100
                    }
        except:
            pass
    
    print(f"  Got data for {len(results)} symbols")
    return results

def get_market_caps():
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1"
        r = requests.get(url, timeout=15)
        data = r.json()
        return {coin["symbol"].upper(): coin.get("market_cap", 0) for coin in data if coin.get("market_cap")}
    except:
        return {}

def format_number(n):
    if n >= 1e9: return f"{n/1e9:.2f}B"
    elif n >= 1e6: return f"{n/1e6:.2f}M"
    elif n >= 1e3: return f"{n/1e3:.2f}K"
    return f"{n:.2f}"

def send_discord_alert(alerts, scanned_count):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M")
    
    if not DISCORD_WEBHOOK:
        print("No DISCORD_WEBHOOK")
        return
    
    if not alerts:
        payload = {"content": f"✅ **OI 掃描完成** | {now}\n掃描 {scanned_count} 個幣種，目前無顯著異動"}
        try:
            r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
            print(f"Status sent: {r.status_code}")
        except Exception as e:
            print(f"Error: {e}")
        return
    
    embeds = []
    for a in alerts[:5]:
        if a["price_change"] > 0:
            direction, color = "🟢 多方進場", 0x00ff00
        else:
            direction, color = "🔴 空方進場", 0xff0000
        
        embeds.append({
            "title": f"🚨 {a['symbol']} OI 異動",
            "color": color,
            "fields": [
                {"name": "💰 現價", "value": f"${a['new_price']:,.4f}", "inline": True},
                {"name": "📈 1H價格", "value": f"{a['price_change']:+.2f}%", "inline": True},
                {"name": "📦 OI", "value": f"{format_number(a['oi'])}", "inline": True},
            ],
            "footer": {"text": f"{direction} | {now}"}
        })
    
    payload = {"content": f"**🔍 OI 異動掃描 | {now}**\n偵測到 {len(alerts)} 個訊號：", "embeds": embeds}
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"Alert sent: {r.status_code}")
    except Exception as e:
        print(f"Discord error: {e}")

def main():
    print("=== OI Scanner Start ===")
    
    tickers = get_all_tickers()
    if not tickers:
        print("❌ No tickers")
        return
    
    tickers.sort(key=lambda x: x.get("quoteVolume", 0), reverse=True)
    top_symbols = [t["symbol"] for t in tickers[:50]]
    ticker_map = {t["symbol"]: t for t in tickers}
    
    print(f"Top symbols: {top_symbols[:5]}...")
    
    data = get_oi_and_price_data(top_symbols)
    market_caps = get_market_caps()
    
    alerts = []
    for symbol, d in data.items():
        price_change = d["price_change"]
        
        is_alert = False
        if abs(price_change) >= 3:
            is_alert = True
        if abs(price_change) >= 5:
            is_alert = True
        
        if is_alert:
            alerts.append({
                "symbol": symbol,
                "oi": d["oi"],
                "old_price": d["old_price"],
                "new_price": d["new_price"],
                "price_change": price_change,
                "change_24h": ticker_map.get(symbol, {}).get("priceChangePercent", 0)
            })
            print(f"🚨 {symbol}: Price {price_change:+.1f}%")
    
    alerts.sort(key=lambda x: abs(x["price_change"]), reverse=True)
    print(f"\nFound {len(alerts)} alerts")
    send_discord_alert(alerts, len(data))

if __name__ == "__main__":
    main()
