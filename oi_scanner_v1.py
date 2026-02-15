import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = "oi_state.json"
SIGNAL_LOG = "signal_log.json"
NOTIFIED_FILE = "oi_notified.json"

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

def format_number(n):
    if n >= 1e9: return f"{n/1e9:.1f}B"
    elif n >= 1e6: return f"{n/1e6:.1f}M"
    elif n >= 1e3: return f"{n/1e3:.1f}K"
    return f"{n:.0f}"

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

def get_oi_change_1h(symbol):
    try:
        url = f"https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history?instId={symbol}-USDT-SWAP&period=1H"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and len(data.get("data", [])) >= 2:
            sorted_data = sorted(data["data"], key=lambda x: int(x[0]))
            old_oi = float(sorted_data[-2][3])
            new_oi = float(sorted_data[-1][3])
            change = (new_oi - old_oi) / old_oi * 100 if old_oi > 0 else 0
            return change, new_oi
    except:
        pass
    return 0, 0

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

MC_CACHE = {}

def get_market_cap(symbol):
    base = symbol.replace("-USDT-SWAP", "").replace("USDT", "").lower()
    
    if base in MC_CACHE:
        return MC_CACHE[base]
    
    coin_map = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "bnb": "binancecoin",
        "xrp": "ripple", "doge": "dogecoin", "ada": "cardano", "avax": "avalanche-2",
        "shib": "shiba-inu", "link": "chainlink", "dot": "polkadot", "matic": "matic-network",
        "sui": "sui", "apt": "aptos", "arb": "arbitrum", "op": "optimism"
    }
    
    cg_id = coin_map.get(base, base)
    
    try:
        import time
        time.sleep(0.5)
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd&include_market_cap=true"
        r = requests.get(url, timeout=5)
        data = r.json()
        if cg_id in data and "usd_market_cap" in data[cg_id]:
            mc = data[cg_id]["usd_market_cap"]
            MC_CACHE[base] = mc
            return mc
    except:
        pass
    
    MC_CACHE[base] = None
    return None

def detect_early_momentum(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}-USDT-SWAP&bar=5m&limit=13"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") != "0" or len(data.get("data", [])) < 13:
            return None
        
        sorted_data = sorted(data["data"], key=lambda x: int(x[0]))
        volumes = [float(k[5]) for k in sorted_data[:-1]]
        avg_vol = sum(volumes) / len(volumes)
        
        latest = sorted_data[-1]
        prev = sorted_data[-2]
        latest_vol = float(latest[5])
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

def get_market_phase(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}-USDT-SWAP&bar=1H&limit=26"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") != "0" or len(data.get("data", [])) < 26:
            return None
        
        sorted_data = sorted(data["data"], key=lambda x: int(x[0]))
        closes = [float(k[4]) for k in sorted_data]
        current_price = closes[-1]
        
        ma7 = sum(closes[-7:]) / 7
        ma25 = sum(closes[-25:]) / 25
        
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            diff = closes[i] - closes[i-1]
            gains.append(diff if diff > 0 else 0)
            losses.append(-diff if diff < 0 else 0)
        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0.0001
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        ma_distance = (current_price - ma25) / ma25 * 100 if ma25 > 0 else 0
        
        high_24h = max(closes[-24:])
        low_24h = min(closes[-24:])
        price_range = high_24h - low_24h
        price_position = (current_price - low_24h) / price_range * 100 if price_range > 0 else 50
        
        return {"rsi": rsi, "ma_distance": ma_distance, "price_position": price_position}
    except:
        pass
    return None

def get_phase_label(phase_data, signal):
    if not phase_data:
        return ""
    rsi, ma_dist, pos = phase_data["rsi"], phase_data["ma_distance"], phase_data["price_position"]
    if signal == "LONG":
        if rsi > 75 or ma_dist > 15 or pos > 90:
            return "⚠️高位追高"
        elif rsi > 65 or ma_dist > 8 or pos > 75:
            return "🔥行情中段"
        else:
            return "🌱啟動初期"
    elif signal == "SHORT":
        if rsi < 25 or ma_dist < -15 or pos < 10:
            return "⚠️低位追空"
        elif rsi < 35 or ma_dist < -8 or pos < 25:
            return "🔥行情中段"
        else:
            return "🌱啟動初期"
    return ""

def get_1h_volume_ratio_okx(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}-USDT-SWAP&bar=1H&limit=24"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            vols = [float(k[5]) for k in reversed(data["data"])]
            if len(vols) >= 6:
                avg_vol = sum(vols[:-1]) / len(vols[:-1])
                return vols[-1] / avg_vol if avg_vol > 0 else 1
    except:
        pass
    return 1

def get_signal_strength(oi_change, vol_ratio, rsi, signal, price_change_1h):
    score = 0
    tags = []
    
    if vol_ratio >= 2:
        score += 30
        tags.append(f"📊Vol {vol_ratio:.1f}x")
    elif vol_ratio >= 1.5:
        score += 20
        tags.append(f"📊Vol {vol_ratio:.1f}x")
    
    if signal == "LONG" and rsi >= 60:
        score += 25
        tags.append(f"💪RSI {rsi:.0f}")
    elif signal == "SHORT" and rsi <= 40:
        score += 25
        tags.append(f"💪RSI {rsi:.0f}")
    
    oi = abs(oi_change)
    if oi >= 15:
        score += 25
        tags.append(f"🔥OI {oi:.0f}%")
    elif oi >= 10:
        score += 15
        tags.append(f"📈OI {oi:.0f}%")
    elif oi >= 7:
        score += 10
    
    p = abs(price_change_1h)
    if p >= 5:
        score += 20
        tags.append(f"🚀1H {price_change_1h:+.1f}%")
    elif p >= 3:
        score += 10
    
    if score >= 60:
        grade = "🔥🔥🔥 S級"
    elif score >= 40:
        grade = "🔥🔥 A級"
    elif score >= 25:
        grade = "🔥 B級"
    else:
        grade = "C級"
    
    return {"score": score, "grade": grade, "tags": tags}

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

def format_message(alerts, scanned, is_smallcap=False):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    if not alerts:
        return None
    
    early_count = len([a for a in alerts if a.get("early_warning")])
    oi_count = len(alerts) - early_count
    
    title = "🚀 **小幣大波動**" if is_smallcap else "🔍 **OI 異動掃描**"
    lines = [f"{title} | {now}", f"掃描 {scanned} 幣種 | 早期⚡{early_count} OI📊{oi_count}", ""]
    
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
            oi_line = f"• OI: {oi_dir} {a['oi_change']:+.1f}% ({format_number(a['oi'])})"
            mc = get_market_cap(a['symbol'])
            if mc and mc > 0:
                oi_mc_ratio = a.get('oi', 0) / mc * 100
                oi_line += f" | OI/MC: {oi_mc_ratio:.1f}%"
            lines.append(oi_line)
            lines.append(f"• 價格 1H: {price_dir} {a['price_change_1h']:+.1f}% | 24H: {a['change_24h']:+.1f}%")
        
        reason = "積極信號！" if a.get("aggressive") else ("動能加速！" if a.get("momentum_surge") else a['reason'])
        phase = a.get("phase", "")
        rsi = a.get("rsi", 0)
        grade = a.get("strength_grade", "")
        tags = a.get("strength_tags", [])
        
        signal_line = f"• 訊號: {signal_emoji(a['signal'])}"
        if phase:
            signal_line += f" {phase}"
        if grade:
            signal_line += f" | {grade}"
        if rsi:
            signal_line += f" | RSI: {rsi:.0f}"
        lines.append(signal_line)
        
        if tags:
            lines.append(f"• 強度: {' '.join(tags)}")
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
                "oi_change": round(a["oi_change"], 2),
                "oi_change_pct": round(a["oi_change"], 2),
                "price_change_1h": round(a["price_change_1h"], 2),
                "vol_ratio": round(a.get("1h_vol_ratio", 1), 2),
                "rsi": round(a.get("rsi", 50), 1),
                "strength_score": a.get("strength_score", 0),
                "strength_grade": a.get("strength_grade", ""),
                "checked": False
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
    print("=== OI Scanner Start ===")
    
    prev_state = load_json(STATE_FILE)
    current_data = get_okx_oi_data()
    
    if not current_data:
        print("No data")
        return
    
    print(f"獲取 {len(current_data)} 個幣種")
    
    sorted_by_oi = sorted(current_data, key=lambda x: x["oi"], reverse=True)
    top_100 = set(c["symbol"] for c in sorted_by_oi[:100])
    
    early_alerts = []
    print("掃描早期動能信號...")
    for coin in sorted_by_oi[:30]:
        momentum = detect_early_momentum(coin["symbol"])
        if momentum:
            early_alerts.append({
                "symbol": coin["symbol"],
                "price": coin["price"],
                "oi": coin["oi"],
                "oi_change": 0,
                "price_change_1h": 0,
                "price_change_5m": momentum["price_change_5m"],
                "vol_ratio": momentum["vol_ratio"],
                "change_24h": coin["change_24h"],
                "signal": f"EARLY_{momentum['direction']}",
                "reason": f"5分鐘爆量 {momentum['vol_ratio']:.1f}x",
                "early_warning": True
            })
            print(f"⚡ [早期] {coin['symbol']}: 5m {momentum['price_change_5m']:+.1f}%, Vol {momentum['vol_ratio']:.1f}x")
    
    current_state = {}
    top_alerts = []
    smallcap_alerts = []
    
    for coin in current_data:
        symbol = coin["symbol"]
        current_state[symbol] = {"oi": coin["oi"], "price": coin["price"]}
        
        oi_change, oi_usd = get_oi_change_1h(symbol)
        if oi_usd > 0:
            coin["oi"] = oi_usd
        
        is_top = symbol in top_100
        
        if is_top:
            threshold_oi = 5
            threshold_price = 5
        else:
            threshold_oi = 8
            threshold_price = 15
        
        if abs(oi_change) < threshold_oi and abs(coin["change_24h"]) < threshold_price:
            continue
        
        price_change_1h = get_price_change_1h(symbol)
        signal, reason = get_direction_signal(oi_change, price_change_1h)
        
        phase_data = get_market_phase(symbol) if signal in ["LONG", "SHORT"] else None
        phase_label = get_phase_label(phase_data, signal) if phase_data else ""
        rsi_val = phase_data["rsi"] if phase_data else 50
        
        vol_1h = 1
        if signal in ["LONG", "SHORT"]:
            vol_1h = get_1h_volume_ratio_okx(symbol)
        strength = get_signal_strength(oi_change, vol_1h, rsi_val, signal, price_change_1h)
        
        alert = {
            "symbol": symbol,
            "price": coin["price"],
            "oi": coin["oi"],
            "oi_change": oi_change,
            "price_change_1h": price_change_1h,
            "change_24h": coin["change_24h"],
            "signal": signal,
            "reason": reason,
            "phase": phase_label,
            "rsi": rsi_val,
            "1h_vol_ratio": vol_1h,
            "strength_score": strength["score"],
            "strength_grade": strength["grade"],
            "strength_tags": strength["tags"]
        }
        
        if is_top:
            if signal in ["LONG", "SHORT"] or (signal == "PENDING" and abs(oi_change) >= 8):
                top_alerts.append(alert)
                print(f"🚨 [TOP] {symbol}: OI {oi_change:+.1f}%, 1H {price_change_1h:+.1f}% → {signal_emoji(signal)}")
        else:
            if signal in ["LONG", "SHORT"] and abs(oi_change) >= 8:
                smallcap_alerts.append(alert)
                print(f"🚀 [SMALL] {symbol}: OI {oi_change:+.1f}%, 24H {coin['change_24h']:+.1f}% → {signal_emoji(signal)}")
    
    save_json(STATE_FILE, current_state)
    
    top_alerts.sort(key=lambda x: x.get("strength_score", 0), reverse=True)
    smallcap_alerts.sort(key=lambda x: x.get("strength_score", 0), reverse=True)
    
    all_oi_alerts = top_alerts + smallcap_alerts
    log_signals(all_oi_alerts)
    print(f"偵測到 {len(all_oi_alerts)} 個OI訊號, {len(early_alerts)} 個早期訊號")
    
    combined_top = early_alerts + top_alerts
    top_actionable = [a for a in combined_top if a["signal"] in ["LONG", "SHORT", "PENDING", "EARLY_LONG", "EARLY_SHORT"]]
    top_filtered = filter_new_or_consistent(top_actionable)
    if top_filtered:
        msg = format_message(top_filtered, 100, is_smallcap=False)
        print("\n" + msg)
        send_discord(msg)
    
    smallcap_actionable = [a for a in smallcap_alerts if a["signal"] in ["LONG", "SHORT"]]
    smallcap_filtered = filter_new_or_consistent(smallcap_actionable)
    if smallcap_filtered:
        msg = format_message(smallcap_filtered, len(current_data) - 100, is_smallcap=True)
        print("\n" + msg)
        send_discord(msg)
    
    print(f"過濾後通知: Top {len(top_filtered)}, Small {len(smallcap_filtered)}")
    
    if not top_filtered and not smallcap_filtered:
        print(f"掃描 {len(current_data)} 幣種，無新訊號或方向已改變")

if __name__ == "__main__":
    main()
