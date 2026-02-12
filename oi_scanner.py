import requests
import os
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

def get_all_tickers():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        r = requests.get(url, timeout=15)
        return r.json()
    except:
        return []

def get_all_oi():
    url = "https://fapi.binance.com/fapi/v1/openInterest"
    try:
        symbols = get_top_symbols()
        oi_map = {}
        for symbol in symbols:
            try:
                r = requests.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}", timeout=5)
                data = r.json()
                oi_map[symbol] = float(data.get("openInterest", 0))
            except:
                pass
        return oi_map
    except:
        return {}

def get_top_symbols():
    tickers = get_all_tickers()
    usdt_tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt_tickers.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    return [t["symbol"] for t in usdt_tickers[:100]]

def get_oi_history_batch(symbols, period="5m"):
    results = {}
    for symbol in symbols:
        try:
            url = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period={period}&limit=2"
            r = requests.get(url, timeout=5)
            data = r.json()
            if isinstance(data, list) and len(data) >= 2:
                old_oi = float(data[0].get("sumOpenInterestValue", 0))
                new_oi = float(data[-1].get("sumOpenInterestValue", 0))
                results[symbol] = {"old": old_oi, "new": new_oi}
        except:
            pass
    return results

def get_price_history_batch(symbols, interval="5m"):
    results = {}
    for symbol in symbols:
        try:
            url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit=2"
            r = requests.get(url, timeout=5)
            data = r.json()
            if len(data) >= 2:
                old_close = float(data[0][4])
                new_close = float(data[-1][4])
                results[symbol] = {"old": old_close, "new": new_close}
        except:
            pass
    return results

def get_market_caps():
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        mc_map = {}
        for coin in data:
            symbol = coin.get("symbol", "").upper()
            mc = coin.get("market_cap", 0)
            if mc:
                mc_map[symbol] = mc
        return mc_map
    except:
        return {}

def format_number(n):
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    elif n >= 1e6:
        return f"{n/1e6:.2f}M"
    elif n >= 1e3:
        return f"{n/1e3:.2f}K"
    return f"{n:.2f}"

def send_discord_alert(alerts):
    if not DISCORD_WEBHOOK:
        print("WARNING: No DISCORD_WEBHOOK_URL set!")
        return
    if not alerts:
        print("No alerts to send")
        return
    
    print(f"Sending {len(alerts)} alerts to Discord...")
    
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M")
    
    embeds = []
    for a in alerts[:5]:
        if a["oi_change"] > 0 and a["price_change"] > 0:
            direction = "🟢 多方進場"
            color = 0x00ff00
        elif a["oi_change"] > 0 and a["price_change"] < 0:
            direction = "🔴 空方進場"
            color = 0xff0000
        else:
            direction = "⚪ OI減少"
            color = 0x808080
        
        embed = {
            "title": f"🚨 {a['symbol']} OI 異動",
            "color": color,
            "fields": [
                {"name": "📊 5M OI變動", "value": f"{a['oi_change']:+.2f}%", "inline": True},
                {"name": "💰 5M價格變動", "value": f"{a['price_change']:+.2f}%", "inline": True},
                {"name": "📈 24H變動", "value": f"{a['change_24h']:+.2f}%", "inline": True},
                {"name": "🎯 現價", "value": f"${a['price']:.6g}", "inline": True},
                {"name": "📦 OI金額", "value": f"${format_number(a['oi_value'])}", "inline": True},
                {"name": "⚖️ OI/市值", "value": f"{a['oi_mc_ratio']:.1f}%" if a['oi_mc_ratio'] else "N/A", "inline": True},
            ],
            "footer": {"text": f"{direction} | 交易量排名 Top 100"}
        }
        embeds.append(embed)
    
    payload = {
        "content": f"**🔍 OI 異動掃描 | {now}**\n偵測到 {len(alerts)} 個訊號（掃描前100大交易量幣種）：",
        "embeds": embeds
    }
    
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Discord error: {e}")

def main():
    print("=== OI Scanner Start ===")
    
    print("Getting top 100 symbols by volume...")
    tickers = get_all_tickers()
    usdt_tickers = [t for t in tickers if t["symbol"].endswith("USDT")]
    usdt_tickers.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
    top_symbols = usdt_tickers[:100]
    
    ticker_map = {t["symbol"]: t for t in top_symbols}
    symbols = [t["symbol"] for t in top_symbols]
    print(f"Scanning {len(symbols)} symbols")
    
    print("Getting market caps...")
    market_caps = get_market_caps()
    
    print("Getting OI history...")
    oi_data = get_oi_history_batch(symbols)
    
    print("Getting price history...")
    price_data = get_price_history_batch(symbols)
    
    alerts = []
    
    for symbol in symbols:
        if symbol not in oi_data or symbol not in price_data:
            continue
        
        oi = oi_data[symbol]
        price = price_data[symbol]
        ticker = ticker_map[symbol]
        
        if oi["old"] == 0 or price["old"] == 0:
            continue
        
        oi_change = ((oi["new"] - oi["old"]) / oi["old"]) * 100
        price_change = ((price["new"] - price["old"]) / price["old"]) * 100
        
        base = symbol.replace("USDT", "")
        mc = market_caps.get(base, 0)
        oi_mc_ratio = (oi["new"] / mc * 100) if mc > 0 else 0
        
        is_alert = False
        
        if abs(oi_change) >= 2 and abs(price_change) >= 1.5:
            is_alert = True
        
        if abs(oi_change) >= 3 and oi_mc_ratio >= 10:
            is_alert = True
        
        if abs(oi_change) >= 4:
            is_alert = True
        
        if is_alert:
            alerts.append({
                "symbol": symbol,
                "oi_change": oi_change,
                "price_change": price_change,
                "change_24h": float(ticker.get("priceChangePercent", 0)),
                "price": float(ticker.get("lastPrice", 0)),
                "oi_value": oi["new"],
                "oi_mc_ratio": oi_mc_ratio,
            })
            print(f"🚨 {symbol}: OI {oi_change:+.1f}% | Price {price_change:+.1f}% | OI/MC {oi_mc_ratio:.1f}%")
    
    print(f"\nFound {len(alerts)} alerts")
    
    if alerts:
        alerts.sort(key=lambda x: abs(x["oi_change"]), reverse=True)
        send_discord_alert(alerts)
    else:
        print("No significant OI movements detected")
        if DISCORD_WEBHOOK:
            tw_tz = timezone(timedelta(hours=8))
            now = datetime.now(tw_tz).strftime("%H:%M")
            payload = {
                "content": f"✅ **OI 掃描完成** | {now}\n掃描 {len(symbols)} 個幣種，目前無顯著異動"
            }
            try:
                r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
                print(f"Status sent: {r.status_code}")
            except Exception as e:
                print(f"Status error: {e}")

if __name__ == "__main__":
    main()
