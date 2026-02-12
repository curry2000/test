#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime
from typing import List, Dict, Tuple
from pathlib import Path

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path("/tmp/key_levels_state.json")

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "4h", "1d"]

ATR_PERIOD = 14
SWING_LENGTH = 5
FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

def get_klines(symbol: str, interval: str, limit: int = 100) -> List[Dict]:
    try:
        interval_map = {"15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "interval": interval_map.get(interval, "60"),
                "limit": limit
            },
            timeout=15
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            klines = []
            for k in reversed(data["result"]["list"]):
                klines.append({
                    "time": datetime.fromtimestamp(int(k[0])/1000).strftime("%Y-%m-%d %H:%M"),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                })
            return klines
    except:
        pass
    
    try:
        interval_map = {"15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={
                "instId": f"{symbol}-USDT-SWAP",
                "bar": interval_map.get(interval, "1H"),
                "limit": str(limit)
            },
            timeout=15
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            klines = []
            for k in reversed(data["data"]):
                klines.append({
                    "time": datetime.fromtimestamp(int(k[0])/1000).strftime("%Y-%m-%d %H:%M"),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                })
            return klines
    except:
        pass
    
    return []

def get_current_price(symbol: str) -> float:
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            return float(data["result"]["list"][0]["lastPrice"])
    except:
        pass
    return 0

def calculate_atr(klines: List[Dict], period: int = 14) -> float:
    if len(klines) < period + 1:
        return 0
    
    trs = []
    for i in range(1, len(klines)):
        high = klines[i]["high"]
        low = klines[i]["low"]
        prev_close = klines[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    
    return sum(trs[-period:]) / period

def find_swing_highs(klines: List[Dict], length: int) -> List[Tuple[int, float, str]]:
    highs = [k["high"] for k in klines]
    swing_highs = []
    
    for i in range(length, len(highs) - length):
        is_swing = True
        for j in range(1, length + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_highs.append((i, highs[i], klines[i]["time"]))
    
    return swing_highs

def find_swing_lows(klines: List[Dict], length: int) -> List[Tuple[int, float, str]]:
    lows = [k["low"] for k in klines]
    swing_lows = []
    
    for i in range(length, len(lows) - length):
        is_swing = True
        for j in range(1, length + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_lows.append((i, lows[i], klines[i]["time"]))
    
    return swing_lows

def calculate_fib_levels(high: float, low: float, trend: str) -> Dict[str, float]:
    diff = high - low
    levels = {}
    
    if trend == "up":
        for fib in FIB_LEVELS:
            levels[f"{fib*100:.1f}%"] = high - (diff * fib)
    else:
        for fib in FIB_LEVELS:
            levels[f"{fib*100:.1f}%"] = low + (diff * fib)
    
    return levels

def get_psychological_levels(price: float, symbol: str) -> List[float]:
    if symbol == "BTC":
        base = 1000
        levels = []
        start = int(price / base) * base - (base * 5)
        for i in range(12):
            levels.append(start + (i * base))
        return [l for l in levels if abs(l - price) / price < 0.15]
    else:
        base = 50
        levels = []
        start = int(price / base) * base - (base * 5)
        for i in range(12):
            levels.append(start + (i * base))
        return [l for l in levels if abs(l - price) / price < 0.15]

def analyze_key_levels(symbol: str) -> Dict:
    price = get_current_price(symbol)
    if price == 0:
        return {}
    
    all_supports = []
    all_resistances = []
    
    tf_weights = {"1d": 3, "4h": 2, "1h": 1}
    
    for tf in TIMEFRAMES:
        klines = get_klines(symbol, tf, 100)
        if not klines:
            continue
        
        weight = tf_weights.get(tf, 1)
        atr = calculate_atr(klines, ATR_PERIOD)
        
        swing_highs = find_swing_highs(klines, SWING_LENGTH)
        swing_lows = find_swing_lows(klines, SWING_LENGTH)
        
        for idx, level, time in swing_highs[-5:]:
            if level > price:
                all_resistances.append({
                    "price": level,
                    "type": "Swing High",
                    "tf": tf,
                    "weight": weight,
                    "time": time
                })
            else:
                all_supports.append({
                    "price": level,
                    "type": "Swing High",
                    "tf": tf,
                    "weight": weight,
                    "time": time
                })
        
        for idx, level, time in swing_lows[-5:]:
            if level < price:
                all_supports.append({
                    "price": level,
                    "type": "Swing Low",
                    "tf": tf,
                    "weight": weight,
                    "time": time
                })
            else:
                all_resistances.append({
                    "price": level,
                    "type": "Swing Low",
                    "tf": tf,
                    "weight": weight,
                    "time": time
                })
        
        if swing_highs and swing_lows:
            recent_high = max(h[1] for h in swing_highs[-3:])
            recent_low = min(l[1] for l in swing_lows[-3:])
            
            if price > (recent_high + recent_low) / 2:
                fibs = calculate_fib_levels(recent_high, recent_low, "up")
                for name, level in fibs.items():
                    if level < price:
                        all_supports.append({
                            "price": level,
                            "type": f"Fib {name}",
                            "tf": tf,
                            "weight": weight * 0.8,
                            "time": ""
                        })
            else:
                fibs = calculate_fib_levels(recent_high, recent_low, "down")
                for name, level in fibs.items():
                    if level > price:
                        all_resistances.append({
                            "price": level,
                            "type": f"Fib {name}",
                            "tf": tf,
                            "weight": weight * 0.8,
                            "time": ""
                        })
        
        if tf == "1d" and atr > 0:
            all_supports.append({
                "price": price - atr * 1.5,
                "type": "ATR 1.5x",
                "tf": tf,
                "weight": weight * 0.7,
                "time": ""
            })
            all_supports.append({
                "price": price - atr * 2,
                "type": "ATR 2x",
                "tf": tf,
                "weight": weight * 0.7,
                "time": ""
            })
            all_resistances.append({
                "price": price + atr * 1.5,
                "type": "ATR 1.5x",
                "tf": tf,
                "weight": weight * 0.7,
                "time": ""
            })
            all_resistances.append({
                "price": price + atr * 2,
                "type": "ATR 2x",
                "tf": tf,
                "weight": weight * 0.7,
                "time": ""
            })
    
    psych_levels = get_psychological_levels(price, symbol)
    for level in psych_levels:
        entry = {
            "price": level,
            "type": "Round",
            "tf": "-",
            "weight": 1.5,
            "time": ""
        }
        if level > price:
            all_resistances.append(entry)
        else:
            all_supports.append(entry)
    
    def cluster_levels(levels: List[Dict], threshold_pct: float = 0.5) -> List[Dict]:
        if not levels:
            return []
        
        sorted_levels = sorted(levels, key=lambda x: x["price"])
        clusters = []
        current_cluster = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            if abs(level["price"] - current_cluster[-1]["price"]) / current_cluster[-1]["price"] < threshold_pct / 100:
                current_cluster.append(level)
            else:
                clusters.append(current_cluster)
                current_cluster = [level]
        clusters.append(current_cluster)
        
        result = []
        for cluster in clusters:
            avg_price = sum(l["price"] for l in cluster) / len(cluster)
            total_weight = sum(l["weight"] for l in cluster)
            types = list(set(l["type"] for l in cluster))
            tfs = list(set(l["tf"] for l in cluster if l["tf"] != "-"))
            
            result.append({
                "price": avg_price,
                "weight": total_weight,
                "types": types,
                "tfs": tfs,
                "count": len(cluster)
            })
        
        return sorted(result, key=lambda x: x["weight"], reverse=True)
    
    clustered_supports = cluster_levels(all_supports)
    clustered_resistances = cluster_levels(all_resistances)
    
    return {
        "symbol": symbol,
        "price": price,
        "supports": clustered_supports[:6],
        "resistances": clustered_resistances[:6]
    }

def load_state() -> Dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"alerted": [], "last_check": None}

def save_state(state: Dict):
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def send_discord_alert(message: str):
    if not DISCORD_WEBHOOK_URL:
        print(f"[NO WEBHOOK] {message}")
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={
            "content": message,
            "username": "📍 Key Levels"
        }, timeout=10)
    except Exception as e:
        print(f"Webhook error: {e}")

def get_strength_emoji(weight: float) -> str:
    if weight >= 5:
        return "⭐⭐⭐"
    elif weight >= 3:
        return "⭐⭐"
    elif weight >= 1.5:
        return "⭐"
    else:
        return "·"

def format_report(results: List[Dict]) -> str:
    lines = [
        "📍 **關鍵支撐壓力位 (1H/4H/1D)**",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ""
    ]
    
    for data in results:
        symbol = data["symbol"]
        price = data["price"]
        
        lines.append(f"**{symbol}** ${price:,.2f}")
        lines.append("")
        
        if data["resistances"]:
            lines.append("🔴 **Resistance (壓力)**")
            for r in data["resistances"][:5]:
                dist = (r["price"] - price) / price * 100
                emoji = get_strength_emoji(r["weight"])
                tfs = "/".join(r["tfs"]) if r["tfs"] else "-"
                types = "+".join(r["types"][:2])
                lines.append(f"{emoji} ${r['price']:,.0f} (+{dist:.1f}%) [{tfs}] {types}")
            lines.append("")
        
        if data["supports"]:
            lines.append("🟢 **Support (支撐)**")
            for s in data["supports"][:5]:
                dist = (price - s["price"]) / price * 100
                emoji = get_strength_emoji(s["weight"])
                tfs = "/".join(s["tfs"]) if s["tfs"] else "-"
                types = "+".join(s["types"][:2])
                lines.append(f"{emoji} ${s['price']:,.0f} (-{dist:.1f}%) [{tfs}] {types}")
            lines.append("")
        
        lines.append("---")
    
    lines.append("")
    lines.append("⭐⭐⭐ = 多時框+多指標確認")
    lines.append("⭐⭐ = 中強度 | ⭐ = 單一確認")
    
    return "\n".join(lines)

def check_price_alerts(results: List[Dict], state: Dict) -> List[str]:
    alerts = []
    alert_threshold = 0.015
    
    for data in results:
        symbol = data["symbol"]
        price = data["price"]
        
        for r in data["resistances"][:3]:
            dist = (r["price"] - price) / price
            if dist <= alert_threshold and r["weight"] >= 2:
                key = f"{symbol}_res_{r['price']:.0f}"
                if key not in state["alerted"]:
                    alerts.append(f"⚠️ {symbol} 接近壓力 ${r['price']:,.0f} (距離 {dist*100:.1f}%)")
                    state["alerted"].append(key)
        
        for s in data["supports"][:3]:
            dist = (price - s["price"]) / price
            if dist <= alert_threshold and s["weight"] >= 2:
                key = f"{symbol}_sup_{s['price']:.0f}"
                if key not in state["alerted"]:
                    alerts.append(f"⚠️ {symbol} 接近支撐 ${s['price']:,.0f} (距離 {dist*100:.1f}%)")
                    state["alerted"].append(key)
    
    return alerts

def main():
    print("📍 關鍵支撐壓力位分析")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    state = load_state()
    results = []
    
    for symbol in SYMBOLS:
        print(f"\n分析 {symbol}...")
        data = analyze_key_levels(symbol)
        if data:
            results.append(data)
            
            print(f"  價格: ${data['price']:,.2f}")
            print(f"  支撐位: {len(data['supports'])} 個")
            print(f"  壓力位: {len(data['resistances'])} 個")
    
    if results:
        report = format_report(results)
        print("\n" + report)
        send_discord_alert(report)
        
        alerts = check_price_alerts(results, state)
        if alerts:
            alert_msg = "🔔 **接近關鍵價位！**\n\n" + "\n".join(alerts)
            send_discord_alert(alert_msg)
    
    save_state(state)
    
    with open(Path(__file__).parent / "key_levels_report.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print("\n✅ 完成")

if __name__ == "__main__":
    main()
