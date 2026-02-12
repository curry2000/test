import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = "oi_state.json"
SIGNAL_LOG = "signal_log.json"

def load_json(filepath):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return {} if "state" in filepath else []

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Save error: {e}")

def get_okx_oi_data():
    results = []
    
    try:
        url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") != "0":
            return results
        
        swap_data = {}
        for t in data["data"]:
            if "-USDT-SWAP" in t["instId"]:
                base = t["instId"].replace("-USDT-SWAP", "")
                open_price = float(t.get("open24h", 0))
                swap_data[base] = {
                    "price": float(t["last"]),
                    "change_24h": (float(t["last"]) / open_price * 100 - 100) if open_price > 0 else 0,
                    "volume": float(t.get("volCcy24h", 0))
                }
    except Exception as e:
        print(f"Ticker error: {e}")
        return results
    
    try:
        url = "https://www.okx.com/api/v5/public/open-interest?instType=SWAP"
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("code") != "0":
            return results
        
        for item in data["data"]:
            if "-USDT-SWAP" in item["instId"]:
                base = item["instId"].replace("-USDT-SWAP", "")
                if base in swap_data:
                    oi_usd = float(item.get("oiCcy", 0)) * swap_data[base]["price"]
                    results.append({
                        "symbol": base,
                        "price": swap_data[base]["price"],
                        "change_24h": swap_data[base]["change_24h"],
                        "volume": swap_data[base]["volume"],
                        "oi": oi_usd
                    })
    except Exception as e:
        print(f"OI error: {e}")
    
    return results

def get_price_change_1h(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}-USDT-SWAP&bar=1H&limit=2"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and len(data.get("data", [])) >= 2:
            sorted_data = sorted(data["data"], key=lambda x: int(x[0]))
            old_price = float(sorted_data[-2][4])
            new_price = float(sorted_data[-1][4])
            return (new_price - old_price) / old_price * 100 if old_price > 0 else 0
    except:
        pass
    return 0

def get_direction_signal(oi_change, price_change_1h):
    if oi_change > 3 and price_change_1h > 1.5:
        return "LONG", "新多進場，趨勢向上"
    elif oi_change > 3 and price_change_1h < -1.5:
        return "SHORT", "新空進場，趨勢向下"
    elif oi_change < -3 and price_change_1h > 1.5:
        return "WAIT", "軋空反彈，動能不足"
    elif oi_change < -3 and price_change_1h < -1.5:
        return "WAIT", "多頭平倉，恐慌拋售"
    elif abs(oi_change) > 5 and abs(price_change_1h) < 1:
        return "PENDING", "多空對峙，即將變盤"
    else:
        return "NONE", ""

def signal_emoji(signal):
    return {"LONG": "🟢 追多", "SHORT": "🔴 追空", "WAIT": "⚠️ 觀望", "PENDING": "⏳ 蓄勢", "NONE": "⚪ 無訊號"}.get(signal, signal)

def format_message(alerts, scanned):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    if not alerts:
        return f"✅ **OI 掃描** | {now}\n掃描 {scanned} 幣種，無顯著異動"
    
    lines = [f"🔍 **OI 異動掃描** | {now}", f"掃描 {scanned} 幣種，發現 {len(alerts)} 個異動", ""]
    
    for a in alerts[:10]:
        oi_dir = "📈" if a["oi_change"] > 0 else "📉"
        price_dir = "📈" if a["price_change_1h"] > 0 else "📉"
        
        lines.append(f"**{a['symbol']}** ${a['price']:,.4g}")
        lines.append(f"• OI: {oi_dir} {a['oi_change']:+.1f}% | 價格1H: {price_dir} {a['price_change_1h']:+.1f}%")
        lines.append(f"• 訊號: {signal_emoji(a['signal'])} — {a['reason']}")
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

def log_signals(alerts):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    timestamp = now.isoformat()
    
    logs = load_json(SIGNAL_LOG)
    if not isinstance(logs, list):
        logs = []
    
    for a in alerts:
        if a["signal"] in ["LONG", "SHORT"]:
            logs.append({
                "ts": timestamp,
                "symbol": a["symbol"],
                "signal": a["signal"],
                "entry_price": a["price"],
                "oi_change": round(a["oi_change"], 2),
                "price_change_1h": round(a["price_change_1h"], 2),
                "checked": False
            })
    
    cutoff = now - timedelta(days=7)
    logs = [l for l in logs if datetime.fromisoformat(l["ts"]) > cutoff]
    
    save_json(SIGNAL_LOG, logs)
    print(f"已記錄 {len([a for a in alerts if a['signal'] in ['LONG', 'SHORT']])} 個訊號")

def main():
    print("=== OI Scanner Start ===")
    
    prev_state = load_json(STATE_FILE)
    current_data = get_okx_oi_data()
    
    if not current_data:
        print("No data")
        return
    
    print(f"獲取 {len(current_data)} 個幣種")
    
    current_state = {}
    alerts = []
    
    top_by_oi = sorted(current_data, key=lambda x: x["oi"], reverse=True)[:100]
    
    for coin in top_by_oi:
        symbol = coin["symbol"]
        current_state[symbol] = {"oi": coin["oi"], "price": coin["price"]}
        
        if symbol in prev_state:
            prev_oi = prev_state[symbol].get("oi", coin["oi"])
            oi_change = (coin["oi"] - prev_oi) / prev_oi * 100 if prev_oi > 0 else 0
        else:
            oi_change = 0
        
        price_change_1h = get_price_change_1h(symbol)
        
        signal, reason = get_direction_signal(oi_change, price_change_1h)
        
        if abs(oi_change) >= 3 or abs(price_change_1h) >= 3:
            alerts.append({
                "symbol": symbol,
                "price": coin["price"],
                "oi": coin["oi"],
                "oi_change": oi_change,
                "price_change_1h": price_change_1h,
                "signal": signal,
                "reason": reason
            })
            print(f"🚨 {symbol}: OI {oi_change:+.1f}%, 價格1H {price_change_1h:+.1f}% → {signal_emoji(signal)}")
    
    save_json(STATE_FILE, current_state)
    
    alerts.sort(key=lambda x: abs(x["oi_change"]), reverse=True)
    
    log_signals(alerts)
    
    actionable = [a for a in alerts if a["signal"] in ["LONG", "SHORT", "PENDING"]]
    
    if actionable:
        message = format_message(actionable, len(top_by_oi))
        print("\n" + message)
        send_discord(message)
    else:
        print(f"\n掃描 {len(top_by_oi)} 幣種，無明確多空訊號")

if __name__ == "__main__":
    main()
