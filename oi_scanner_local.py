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

def get_market_cap(symbol):
    base = symbol.replace("USDT", "").lower()
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={base}&vs_currencies=usd&include_market_cap=true"
        r = requests.get(url, timeout=5)
        data = r.json()
        if base in data and "usd_market_cap" in data[base]:
            return data[base]["usd_market_cap"]
    except:
        pass
    
    coin_map = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "binancecoin",
        "xrp": "ripple", "doge": "dogecoin", "ada": "cardano", "avax": "avalanche-2",
        "shib": "shiba-inu", "link": "chainlink", "dot": "polkadot", "matic": "matic-network"
    }
    if base in coin_map:
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_map[base]}&vs_currencies=usd&include_market_cap=true"
            r = requests.get(url, timeout=5)
            data = r.json()
            cg_id = coin_map[base]
            if cg_id in data and "usd_market_cap" in data[cg_id]:
                return data[cg_id]["usd_market_cap"]
        except:
            pass
    return None

def detect_early_momentum(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=5m&limit=13"
        r = requests.get(url, timeout=5)
        data = r.json()
        if not isinstance(data, list) or len(data) < 13:
            return None
        
        volumes = [float(k[7]) for k in data[:-1]]
        avg_vol = sum(volumes) / len(volumes)
        
        latest = data[-1]
        prev = data[-2]
        latest_vol = float(latest[7])
        latest_close = float(latest[4])
        prev_close = float(prev[4])
        
        price_change_5m = (latest_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 0
        
        if abs(price_change_5m) >= 1.5 and vol_ratio >= 2.5:
            return {
                "price_change_5m": price_change_5m,
                "vol_ratio": vol_ratio,
                "direction": "LONG" if price_change_5m > 0 else "SHORT"
            }
    except:
        pass
    return None

def get_direction_signal(oi_change, price_change_1h):
    if oi_change > 5 and price_change_1h > 3:
        return "LONG", "新多進場，趨勢向上"
    elif oi_change > 5 and price_change_1h < -3:
        return "SHORT", "新空進場，趨勢向下"
    elif oi_change < -5 and price_change_1h > 3:
        return "WAIT", "軋空反彈，動能不足"
    elif oi_change < -5 and price_change_1h < -3:
        return "WAIT", "多頭平倉，恐慌拋售"
    elif abs(oi_change) > 8 and abs(price_change_1h) < 2:
        return "PENDING", "多空對峙，即將變盤"
    else:
        return "NONE", ""

def signal_emoji(signal):
    return {"LONG": "🟢 追多", "SHORT": "🔴 追空", "WAIT": "⚠️ 觀望", "PENDING": "⏳ 蓄勢", "EARLY_LONG": "⚡ 早期做多", "EARLY_SHORT": "⚡ 早期做空", "NONE": "⚪ 無訊號"}.get(signal, signal)

def format_message(alerts, scanned):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    if not alerts:
        return None
    
    early_count = len([a for a in alerts if a.get("early_warning")])
    oi_count = len(alerts) - early_count
    
    lines = [f"🔍 **OI 異動掃描** [BN本地] | {now}", f"掃描 {scanned} 幣種 | 早期⚡{early_count} OI📊{oi_count}", ""]
    
    for a in alerts[:10]:
        surge = "🔥" if a.get("aggressive") else ("⚡" if a.get("momentum_surge") or a.get("early_warning") else "")
        
        lines.append(f"**{a['symbol']}** ${a['price']:,.4g} {surge}")
        
        if a.get("early_warning"):
            price_5m = a.get("price_change_5m", 0)
            vol_ratio = a.get("vol_ratio", 0)
            p_dir = "📈" if price_5m > 0 else "📉"
            lines.append(f"• 5分鐘: {p_dir} {price_5m:+.1f}% | 成交量 {vol_ratio:.1f}x 爆量")
            lines.append(f"• 24H: {a['change_24h']:+.1f}%")
        else:
            oi_dir = "📈" if a.get("oi_change", 0) > 0 else "📉"
            price_dir = "📈" if a.get("price_change_1h", 0) > 0 else "📉"
            if a.get("oi_change"):
                oi_line = f"• OI: {oi_dir} {a['oi_change']:+.1f}% ({format_number(a.get('oi', 0))})"
                mc = get_market_cap(a['symbol'] + "USDT")
                if mc and mc > 0:
                    oi_mc_ratio = a.get('oi', 0) / mc * 100
                    oi_line += f" | OI/MC: {oi_mc_ratio:.1f}%"
                lines.append(oi_line)
            lines.append(f"• 價格 1H: {price_dir} {a.get('price_change_1h', 0):+.1f}% | 24H: {a['change_24h']:+.1f}%")
        
        reason = "積極信號！" if a.get("aggressive") else ("動能加速！" if a.get("momentum_surge") else a['reason'])
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
            
            price_1h = abs(a.get("price_change_1h", 0))
            aggressive = oi_change > 10 or price_1h > 5 or (oi_change > 8 and price_1h > 4)
            
            base_signal = signal.replace("EARLY_", "")
            
            prev_base = prev_signal.replace("EARLY_", "") if prev_signal else ""
            is_early = a.get("early_warning", False)
            
            if is_early and base_signal in ["LONG", "SHORT"]:
                a["early_warning"] = True
                filtered.append(a)
                new_notified[symbol] = {"signal": base_signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
                print(f"⚡ {symbol} 早期預警: 5m {a.get('price_change_5m', 0):+.1f}%, Vol {a.get('vol_ratio', 0):.1f}x")
            elif aggressive and base_signal in ["LONG", "SHORT"]:
                a["aggressive"] = True
                filtered.append(a)
                new_notified[symbol] = {"signal": base_signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
                print(f"🔥 {symbol} 積極信號突破冷卻: OI {oi_change:.1f}%, 1H {price_1h:.1f}%")
            elif time_diff > 3600:
                if base_signal == prev_base:
                    filtered.append(a)
                    new_notified[symbol] = {"signal": signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
                else:
                    new_notified[symbol] = {"signal": signal, "oi_change": oi_change, "change_24h": change_24h, "ts": now.isoformat()}
            elif momentum_surge and base_signal == prev_base:
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
    
    high_vol_coins = sorted(tickers, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]
    early_alerts = []
    
    print("掃描早期動能信號...")
    for t in high_vol_coins[:30]:
        symbol = t["symbol"]
        base = symbol.replace("USDT", "")
        momentum = detect_early_momentum(symbol)
        if momentum:
            early_alerts.append({
                "symbol": base,
                "price": float(t["lastPrice"]),
                "oi": 0,
                "oi_change": 0,
                "price_change_1h": 0,
                "price_change_5m": momentum["price_change_5m"],
                "vol_ratio": momentum["vol_ratio"],
                "change_24h": float(t["priceChangePercent"]),
                "signal": f"EARLY_{momentum['direction']}",
                "reason": f"5分鐘爆量 {momentum['vol_ratio']:.1f}x",
                "early_warning": True
            })
            print(f"⚡ [早期] {base}: 5m {momentum['price_change_5m']:+.1f}%, Vol {momentum['vol_ratio']:.1f}x")
    
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
        
        if signal in ["LONG", "SHORT"]:
            alerts.append({
                "symbol": base,
                "price": coin["price"],
                "oi": oi_usd,
                "oi_change": oi_change,
                "price_change_1h": price_change_1h,
                "change_24h": coin["change_24h"],
                "signal": signal,
                "reason": reason
            })
        elif signal in ["WAIT", "PENDING"] and abs(oi_change) > 8:
            alerts.append({
                "symbol": base,
                "price": coin["price"],
                "oi": oi_usd,
                "oi_change": oi_change,
                "price_change_1h": price_change_1h,
                "change_24h": coin["change_24h"],
                "signal": signal,
                "reason": reason
            })
            print(f"🚨 {base}: 24H {coin['change_24h']:+.1f}%, 1H {price_change_1h:+.1f}%, OI {oi_change:+.1f}%")
    
    for base, data in prev_state.items():
        if base not in current_state:
            current_state[base] = data
    
    save_json(STATE_FILE, current_state)
    
    all_alerts = early_alerts + alerts
    all_alerts.sort(key=lambda x: abs(x.get("price_change_5m", 0)) + abs(x.get("oi_change", 0)), reverse=True)
    
    log_signals([a for a in all_alerts if not a.get("early_warning")])
    print(f"偵測到 {len(all_alerts)} 個訊號 (早期:{len(early_alerts)}, OI:{len(alerts)})")
    
    filtered_alerts = filter_new_or_consistent(all_alerts)
    print(f"過濾後 {len(filtered_alerts)} 個需通知（新訊號或方向一致）")
    
    if filtered_alerts:
        message = format_message(filtered_alerts, len(tickers))
        print("\n" + message)
        send_discord(message)
    else:
        print(f"掃描 {len(tickers)} 幣種，無新訊號或方向已改變")

if __name__ == "__main__":
    main()
