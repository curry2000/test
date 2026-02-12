#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path("/tmp/ob_large_state.json")

OB_PARAMS = {
    "swing_length": 3,
    "max_extend_bars": 100,
    "alert_distance_pct": 2.0,
    "min_volume_mult": 0.7,
}

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["1h", "4h", "1d"]

@dataclass
class OrderBlock:
    symbol: str
    timeframe: str
    ob_type: str
    high: float
    low: float
    body_high: float
    body_low: float
    volume: float
    formed_time: str
    formed_idx: int
    mitigation_pct: float = 0.0
    is_valid: bool = True
    touch_count: int = 0

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ob_type": self.ob_type,
            "high": self.high,
            "low": self.low,
            "body_high": self.body_high,
            "body_low": self.body_low,
            "volume": self.volume,
            "formed_time": self.formed_time,
            "formed_idx": self.formed_idx,
            "mitigation_pct": self.mitigation_pct,
            "is_valid": self.is_valid,
            "touch_count": self.touch_count
        }

def get_klines(symbol: str, interval: str, limit: int = 150) -> List[Dict]:
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
    except Exception as e:
        print(f"Bybit error: {e}")
    
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
    except Exception as e:
        print(f"OKX error: {e}")
    
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
    
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": f"{symbol}-USDT-SWAP"},
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0]["last"])
    except:
        pass
    
    return 0

def find_swing_highs(klines: List[Dict], length: int) -> List[int]:
    highs = [k["high"] for k in klines]
    swing_highs = []
    
    for i in range(length, len(highs) - length):
        is_swing = True
        for j in range(1, length + 1):
            if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_highs.append(i)
    
    return swing_highs

def find_swing_lows(klines: List[Dict], length: int) -> List[int]:
    lows = [k["low"] for k in klines]
    swing_lows = []
    
    for i in range(length, len(lows) - length):
        is_swing = True
        for j in range(1, length + 1):
            if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                is_swing = False
                break
        if is_swing:
            swing_lows.append(i)
    
    return swing_lows

def detect_structure_break(klines: List[Dict], swing_idx: int, direction: str) -> Optional[int]:
    if direction == "bullish":
        swing_high_before = max(k["high"] for k in klines[max(0, swing_idx-10):swing_idx])
        for i in range(swing_idx + 1, min(len(klines), swing_idx + 20)):
            if klines[i]["close"] > swing_high_before:
                return i
    else:
        swing_low_before = min(k["low"] for k in klines[max(0, swing_idx-10):swing_idx])
        for i in range(swing_idx + 1, min(len(klines), swing_idx + 20)):
            if klines[i]["close"] < swing_low_before:
                return i
    return None

def find_order_blocks(klines: List[Dict], symbol: str, timeframe: str) -> List[OrderBlock]:
    order_blocks = []
    length = OB_PARAMS["swing_length"]
    avg_volume = sum(k["volume"] for k in klines) / len(klines)
    
    swing_lows = find_swing_lows(klines, length)
    for sl_idx in swing_lows:
        break_idx = detect_structure_break(klines, sl_idx, "bullish")
        if break_idx:
            for i in range(break_idx - 1, max(sl_idx - 5, 0), -1):
                k = klines[i]
                if k["close"] < k["open"]:
                    body_high = k["open"]
                    body_low = k["close"]
                    
                    if k["volume"] >= avg_volume * OB_PARAMS["min_volume_mult"]:
                        ob = OrderBlock(
                            symbol=symbol,
                            timeframe=timeframe,
                            ob_type="bullish",
                            high=k["high"],
                            low=k["low"],
                            body_high=body_high,
                            body_low=body_low,
                            volume=k["volume"],
                            formed_time=k["time"],
                            formed_idx=i
                        )
                        order_blocks.append(ob)
                    break
    
    swing_highs = find_swing_highs(klines, length)
    for sh_idx in swing_highs:
        break_idx = detect_structure_break(klines, sh_idx, "bearish")
        if break_idx:
            for i in range(break_idx - 1, max(sh_idx - 5, 0), -1):
                k = klines[i]
                if k["close"] > k["open"]:
                    body_high = k["close"]
                    body_low = k["open"]
                    
                    if k["volume"] >= avg_volume * OB_PARAMS["min_volume_mult"]:
                        ob = OrderBlock(
                            symbol=symbol,
                            timeframe=timeframe,
                            ob_type="bearish",
                            high=k["high"],
                            low=k["low"],
                            body_high=body_high,
                            body_low=body_low,
                            volume=k["volume"],
                            formed_time=k["time"],
                            formed_idx=i
                        )
                        order_blocks.append(ob)
                    break
    
    return order_blocks

def update_ob_mitigation(ob: OrderBlock, klines: List[Dict]) -> OrderBlock:
    ob_range = ob.high - ob.low
    if ob_range == 0:
        return ob
    
    for i in range(ob.formed_idx + 1, len(klines)):
        k = klines[i]
        
        if ob.ob_type == "bullish":
            if k["low"] < ob.high:
                penetration = ob.high - k["low"]
                mitigation = min(100, (penetration / ob_range) * 100)
                ob.mitigation_pct = max(ob.mitigation_pct, mitigation)
                ob.touch_count += 1
                
                if k["close"] < ob.low:
                    ob.is_valid = False
                    ob.mitigation_pct = 100
        else:
            if k["high"] > ob.low:
                penetration = k["high"] - ob.low
                mitigation = min(100, (penetration / ob_range) * 100)
                ob.mitigation_pct = max(ob.mitigation_pct, mitigation)
                ob.touch_count += 1
                
                if k["close"] > ob.high:
                    ob.is_valid = False
                    ob.mitigation_pct = 100
    
    return ob

def filter_recent_obs(order_blocks: List[OrderBlock], klines: List[Dict], max_bars: int = 100) -> List[OrderBlock]:
    current_idx = len(klines) - 1
    valid_obs = []
    
    for ob in order_blocks:
        if current_idx - ob.formed_idx <= max_bars:
            ob = update_ob_mitigation(ob, klines)
            if ob.is_valid:
                valid_obs.append(ob)
    
    valid_obs.sort(key=lambda x: x.high, reverse=True)
    return valid_obs

def load_state() -> Dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"alerted_obs": [], "last_check": None}

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
            "username": "📊 OB 大時框"
        }, timeout=10)
    except Exception as e:
        print(f"Webhook error: {e}")

def get_tf_weight(tf: str) -> int:
    weights = {"1d": 3, "4h": 2, "1h": 1}
    return weights.get(tf, 1)

def run_ob_analysis():
    state = load_state()
    all_obs = {}
    
    print(f"🔍 OB 大時框分析 (1h/4h/1d)")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    for symbol in SYMBOLS:
        current_price = get_current_price(symbol)
        print(f"\n**{symbol}** ${current_price:,.2f}")
        
        for tf in TIMEFRAMES:
            klines = get_klines(symbol, tf, 150)
            
            if not klines:
                continue
            
            obs = find_order_blocks(klines, symbol, tf)
            valid_obs = filter_recent_obs(obs, klines, OB_PARAMS["max_extend_bars"])
            
            key = f"{symbol}_{tf}"
            all_obs[key] = valid_obs
            
            bullish = [ob for ob in valid_obs if ob.ob_type == "bullish"]
            bearish = [ob for ob in valid_obs if ob.ob_type == "bearish"]
            
            print(f"\n  📈 {tf}:")
            if bullish:
                print(f"    🟢 Support:")
                for ob in bullish[:3]:
                    strength = 100 - ob.mitigation_pct
                    dist = (current_price - ob.body_high) / current_price * 100
                    print(f"       ${ob.body_low:,.0f}-${ob.body_high:,.0f} [{strength:.0f}%] {dist:+.1f}%")
            if bearish:
                print(f"    🔴 Resistance:")
                for ob in bearish[:3]:
                    strength = 100 - ob.mitigation_pct
                    dist = (ob.body_low - current_price) / current_price * 100
                    print(f"       ${ob.body_low:,.0f}-${ob.body_high:,.0f} [{strength:.0f}%] {dist:+.1f}%")
    
    msg_lines = [
        "📊 **OB 大時框分析 (1H/4H/1D)**",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ""
    ]
    
    for symbol in SYMBOLS:
        price = get_current_price(symbol)
        msg_lines.append(f"**{symbol}** ${price:,.2f}")
        msg_lines.append("")
        
        nearby_supports = []
        nearby_resistances = []
        
        for tf in TIMEFRAMES:
            key = f"{symbol}_{tf}"
            obs = all_obs.get(key, [])
            weight = get_tf_weight(tf)
            
            for ob in obs:
                strength = 100 - ob.mitigation_pct
                if ob.ob_type == "bullish":
                    dist = (price - ob.body_high) / price * 100
                    if -5 <= dist <= 10:
                        nearby_supports.append({
                            "tf": tf,
                            "low": ob.body_low,
                            "high": ob.body_high,
                            "strength": strength,
                            "dist": dist,
                            "weight": weight,
                            "score": strength * weight
                        })
                else:
                    dist = (ob.body_low - price) / price * 100
                    if -5 <= dist <= 10:
                        nearby_resistances.append({
                            "tf": tf,
                            "low": ob.body_low,
                            "high": ob.body_high,
                            "strength": strength,
                            "dist": dist,
                            "weight": weight,
                            "score": strength * weight
                        })
        
        nearby_supports.sort(key=lambda x: x["score"], reverse=True)
        nearby_resistances.sort(key=lambda x: x["score"], reverse=True)
        
        if nearby_supports:
            msg_lines.append("🟢 **Support (可做多)**")
            for s in nearby_supports[:4]:
                emoji = "⭐" if s["score"] >= 150 else "✓" if s["score"] >= 80 else "·"
                msg_lines.append(f"{emoji} ${s['low']:,.0f}-${s['high']:,.0f} ({s['tf']}) [{s['strength']:.0f}%]")
            msg_lines.append("")
        
        if nearby_resistances:
            msg_lines.append("🔴 **Resistance (可做空)**")
            for r in nearby_resistances[:4]:
                emoji = "⭐" if r["score"] >= 150 else "✓" if r["score"] >= 80 else "·"
                msg_lines.append(f"{emoji} ${r['low']:,.0f}-${r['high']:,.0f} ({r['tf']}) [{r['strength']:.0f}%]")
            msg_lines.append("")
        
        msg_lines.append("---")
    
    msg_lines.append("")
    msg_lines.append("⭐ = 高信心 (大時框+高強度)")
    msg_lines.append("✓ = 中信心 | · = 參考")
    
    message = "\n".join(msg_lines)
    send_discord_alert(message)
    print("\n" + "=" * 50)
    print("✅ 已發送 Discord 通知")
    
    save_state(state)
    
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "order_blocks": {k: [ob.to_dict() for ob in v] for k, v in all_obs.items()}
    }
    with open(Path(__file__).parent / "ob_large_report.json", "w") as f:
        json.dump(report_data, f, indent=2)
    
    return all_obs

if __name__ == "__main__":
    run_ob_analysis()
