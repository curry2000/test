import requests
import os
import json
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = os.path.expanduser("~/.openclaw/oi_state_local.json")
SIGNAL_LOG = os.path.expanduser("~/.openclaw/oi_signals_local.json")
NOTIFIED_FILE = os.path.expanduser("~/.openclaw/oi_notified_local.json")

def load_json(filepath):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return {} if "state" in filepath else []

def save_json(filepath, data):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Save error: {e}")

def format_number(n):
    if n >= 1e9: return f"{n/1e9:.1f}B"
    elif n >= 1e6: return f"{n/1e6:.1f}M"
    elif n >= 1e3: return f"{n/1e3:.1f}K"
    return f"{n:.0f}"

def get_all_tickers():
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return [t for t in r.json() if t["symbol"].endswith("USDT")]
    except Exception as e:
        print(f"Ticker error: {e}")
    return []

def get_oi_for_symbol(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return symbol, float(r.json().get("openInterest", 0))
    except:
        pass
    return symbol, 0

def get_price_change_1h(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=2"
        r = requests.get(url, timeout=5)
        data = r.json()
        if isinstance(data, list) and len(data) >= 2:
            old_close = float(data[-2][4])
            new_close = float(data[-1][4])
            return (new_close - old_close) / old_close * 100 if old_close > 0 else 0
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
        return None
    
    lines = [f"🔍 **OI 異動掃描** [BN本地] | {now}", f"掃描 {scanned} 幣種，發現 {len(alerts)} 個異動", ""]
    
    for a in alerts[:10]:
        oi_dir = "📈" if a.get("oi_change", 0) > 0 else "📉"
        price_dir = "📈" if a["price_change_1h"] > 0 else "📉"
        surge = "⚡" if a.get("momentum_surge") else ""
        
        lines.append(f"**{a['symbol']}** ${a['price']:,.4g} {surge}")
        if a.get("oi_change"):
            lines.append(f"• OI: {oi_dir} {a['oi_change']:+.1f}% ({format_number(a.get('oi', 0))})")
        lines.append(f"• 價格 1H: {price_dir} {a['price_change_1h']:+.1f}% | 24H: {a['change_24h']:+.1f}%")
        reason = "動能加速！" if a.get("momentum_surge") else a['reason']
        lines.append(f"• 訊號: {signal_emoji(a['signal'])} — {reason}")
        lines.append("")
    
    return "\n".join(lines)

def send_discord(message):
    if not DISCORD_WEBHOOK or not message:
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
                "oi_change": a.get("oi_change", 0),
                "price_change_1h": a["price_change_1h"],
                "source": "binance"
            })
    
    cutoff = now - timedelta(days=7)
    logs = [l for l in logs if datetime.fromisoformat(l["ts"]) > cutoff]
    
    save_json(SIGNAL_LOG, logs)

def filter_new_or_consistent(alerts):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    
    notified = load_json(NOTIFIED_FILE)
    if not isinstance(notified, dict):
        notified = {}
    
    filtered = []
    new_notified = {}
    
    for a in alerts:
        symbol = a["symbol"]
        signal = a["signal"]
        oi_change = abs(a.get("oi_change", 0))
        change_24h = abs(a.get("change_24h", 0))
        
        if symbol in notified:
            prev = notified[symbol]
            prev_signal = prev.get("signal")
            prev_oi = prev.get("oi_change", 0)
            prev_24h = prev.get("change_24h", 0)
            prev_time = datetime.fromisoformat(prev.get("ts", "2000-01-01T00:00:00"))
            time_diff = (now - prev_time).total_seconds()
            
            oi_increased = oi_change > prev_oi * 1.5 or (oi_change - prev_oi) > 5
            trend_accelerated = change_24h > prev_24h + 3
            momentum_surge = oi_increased or trend_accelerated
            
            if time_diff > 1800:
                if signal == prev_signal:
                    filtered.append(a)
                    new_notified[symbol] = {"signal": signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
                else:
                    new_notified[symbol] = {"signal": signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
            elif momentum_surge and signal == prev_signal:
                a["momentum_surge"] = True
                filtered.append(a)
                new_notified[symbol] = {"signal": signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
                print(f"⚡ {symbol} 動能加速: OI {prev_oi:.1f}%→{oi_change:.1f}%, 24H {prev_24h:.1f}%→{change_24h:.1f}%")
            else:
                new_notified[symbol] = prev
        else:
            filtered.append(a)
            new_notified[symbol] = {"signal": signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
    
    for sym, data in notified.items():
        if sym not in new_notified:
            prev_time = datetime.fromisoformat(data.get("ts", "2000-01-01T00:00:00"))
            if (now - prev_time).total_seconds() < 86400:
                new_notified[sym] = data
    
    save_json(NOTIFIED_FILE, new_notified)
    return filtered

def main():
    print("=== OI Scanner (Binance Local) ===")
    
    tickers = get_all_tickers()
    if not tickers:
        print("No tickers")
        return
    
    print(f"獲取 {len(tickers)} 個幣種")
    
    prev_state = load_json(STATE_FILE)
    
    candidates = []
    for t in tickers:
        symbol = t["symbol"]
        price = float(t["lastPrice"])
        change_24h = float(t["priceChangePercent"])
        volume = float(t["quoteVolume"])
        
        if volume < 1000000:
            continue
        
        if abs(change_24h) >= 10:
            candidates.append({
                "symbol": symbol.replace("USDT", ""),
                "full_symbol": symbol,
                "price": price,
                "change_24h": change_24h,
                "volume": volume
            })
    
    print(f"篩選出 {len(candidates)} 個候選幣種 (24H變動>10%)")
    
    alerts = []
    current_state = {}
    
    for coin in candidates[:50]:
        symbol = coin["full_symbol"]
        base = coin["symbol"]
        
        _, oi = get_oi_for_symbol(symbol)
        if oi == 0:
            continue
        
        oi_usd = oi * coin["price"]
        current_state[base] = {"oi": oi_usd, "price": coin["price"]}
        
        oi_change = 0
        if base in prev_state:
            prev_oi = prev_state[base].get("oi", oi_usd)
            if prev_oi > 0:
                oi_change = (oi_usd - prev_oi) / prev_oi * 100
        
        price_change_1h = get_price_change_1h(symbol)
        signal, reason = get_direction_signal(oi_change, price_change_1h)
        
        if signal != "NONE" or abs(coin["change_24h"]) >= 15:
            alerts.append({
                "symbol": base,
                "price": coin["price"],
                "oi": oi_usd,
                "oi_change": oi_change,
                "price_change_1h": price_change_1h,
                "change_24h": coin["change_24h"],
                "signal": signal if signal != "NONE" else ("LONG" if coin["change_24h"] > 0 else "SHORT"),
                "reason": reason if reason else ("24H大漲" if coin["change_24h"] > 0 else "24H大跌")
            })
            print(f"🚨 {base}: 24H {coin['change_24h']:+.1f}%, 1H {price_change_1h:+.1f}%, OI {oi_change:+.1f}%")
    
    for base, data in prev_state.items():
        if base not in current_state:
            current_state[base] = data
    
    save_json(STATE_FILE, current_state)
    
    alerts.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    
    log_signals(alerts)
    print(f"偵測到 {len(alerts)} 個訊號")
    
    filtered_alerts = filter_new_or_consistent(alerts)
    print(f"過濾後 {len(filtered_alerts)} 個需通知（新訊號或方向一致）")
    
    if filtered_alerts:
        message = format_message(filtered_alerts, len(tickers))
        print("\n" + message)
        send_discord(message)
    else:
        print(f"掃描 {len(tickers)} 幣種，無新訊號或方向已改變")

if __name__ == "__main__":
    main()
