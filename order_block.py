#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path("/tmp/ob_state.json")

OB_PARAMS = {
    "swing_length": 4,
    "min_body_pct": 0.3,
    "max_extend_bars": 150,
    "invalidate_pct": 100,
    "alert_distance_pct": 1.0,
    "min_volume_mult": 0.8,
}

SYMBOLS = ["BTC", "ETH"]
TIMEFRAMES = ["15m", "30m"]

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

def get_klines(symbol: str, interval: str, limit: int = 200) -> List[Dict]:
    try:
        interval_map = {"15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "interval": interval_map.get(interval, "15"),
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
                "bar": interval_map.get(interval, "15m"),
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
    
    try:
        coin_id = "bitcoin" if symbol == "BTC" else "ethereum" if symbol == "ETH" else symbol.lower()
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=10
        )
        data = r.json()
        if coin_id in data:
            return float(data[coin_id]["usd"])
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

def filter_recent_obs(order_blocks: List[OrderBlock], klines: List[Dict], max_bars: int = 150) -> List[OrderBlock]:
    current_idx = len(klines) - 1
    valid_obs = []
    
    for ob in order_blocks:
        if current_idx - ob.formed_idx <= max_bars:
            ob = update_ob_mitigation(ob, klines)
            if ob.is_valid:
                valid_obs.append(ob)
    
    valid_obs.sort(key=lambda x: x.high, reverse=True)
    return valid_obs

def check_ob_signals(symbol: str, timeframe: str, current_price: float, order_blocks: List[OrderBlock]) -> List[Dict]:
    signals = []
    alert_pct = OB_PARAMS["alert_distance_pct"] / 100
    
    for ob in order_blocks:
        if not ob.is_valid:
            continue
        
        if ob.ob_type == "bullish":
            distance = (current_price - ob.body_high) / current_price
            if -alert_pct <= distance <= alert_pct:
                signals.append({
                    "type": "BULLISH_OB",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "action": "📈",
                    "entry_zone": f"${ob.body_low:,.0f}-${ob.body_high:,.0f}",
                    "stop_loss": f"${ob.low * 0.995:,.0f}",
                    "ob_strength": f"{100 - ob.mitigation_pct:.0f}%",
                    "volume": ob.volume,
                    "formed": ob.formed_time
                })
        else:
            distance = (ob.body_low - current_price) / current_price
            if -alert_pct <= distance <= alert_pct:
                signals.append({
                    "type": "BEARISH_OB",
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "action": "📉",
                    "entry_zone": f"${ob.body_low:,.0f}-${ob.body_high:,.0f}",
                    "stop_loss": f"${ob.high * 1.005:,.0f}",
                    "ob_strength": f"{100 - ob.mitigation_pct:.0f}%",
                    "volume": ob.volume,
                    "formed": ob.formed_time
                })
    
    return signals

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
            "username": "📊 OB"
        }, timeout=10)
    except Exception as e:
        print(f"Webhook error: {e}")

def format_ob_report(all_obs: Dict, signals: List[Dict]) -> str:
    lines = [
        "=" * 50,
        "📊 **OB Analysis**",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 50,
    ]
    
    for symbol in SYMBOLS:
        price = get_current_price(symbol)
        lines.append(f"\n**{symbol}** ${price:,.2f}")
        
        for tf in TIMEFRAMES:
            key = f"{symbol}_{tf}"
            obs = all_obs.get(key, [])
            
            bullish = [ob for ob in obs if ob.ob_type == "bullish" and ob.is_valid]
            bearish = [ob for ob in obs if ob.ob_type == "bearish" and ob.is_valid]
            
            lines.append(f"\n  {tf}:")
            
            if bullish:
                lines.append(f"    🟢 S:")
                for ob in bullish[:3]:
                    strength = 100 - ob.mitigation_pct
                    lines.append(f"       ${ob.body_low:,.0f}-${ob.body_high:,.0f} [{strength:.0f}%]")
            
            if bearish:
                lines.append(f"    🔴 R:")
                for ob in bearish[:3]:
                    strength = 100 - ob.mitigation_pct
                    lines.append(f"       ${ob.body_low:,.0f}-${ob.body_high:,.0f} [{strength:.0f}%]")
    
    if signals:
        lines.append("\n" + "=" * 50)
        lines.append("🔔 **Signal**")
        for sig in signals:
            lines.append(f"\n{sig['action']} {sig['symbol']} ({sig['timeframe']})")
            lines.append(f"   {sig['entry_zone']}")
            lines.append(f"   SL: {sig['stop_loss']}")
            lines.append(f"   {sig['ob_strength']}")
    
    return "\n".join(lines)

def run_ob_analysis():
    state = load_state()
    all_obs = {}
    all_signals = []
    
    print("Analyzing...")
    
    for symbol in SYMBOLS:
        current_price = get_current_price(symbol)
        print(f"\n{symbol}: ${current_price:,.2f}")
        
        for tf in TIMEFRAMES:
            print(f"  {tf}...")
            klines = get_klines(symbol, tf, 200)
            
            if not klines:
                continue
            
            obs = find_order_blocks(klines, symbol, tf)
            valid_obs = filter_recent_obs(obs, klines, OB_PARAMS["max_extend_bars"])
            
            key = f"{symbol}_{tf}"
            all_obs[key] = valid_obs
            
            signals = check_ob_signals(symbol, tf, current_price, valid_obs)
            
            for sig in signals:
                sig_key = f"{sig['symbol']}_{sig['timeframe']}_{sig['entry_zone']}"
                if sig_key not in state["alerted_obs"]:
                    all_signals.append(sig)
                    state["alerted_obs"].append(sig_key)
            
            print(f"    {len(valid_obs)} OB")
    
    report = format_ob_report(all_obs, all_signals)
    print(report)
    
    if all_signals:
        alert_msg = "🔔 **OB Signal**\n\n"
        for sig in all_signals:
            alert_msg += f"**{sig['action']}** {sig['symbol']} ({sig['timeframe']})\n"
            alert_msg += f"{sig['entry_zone']}\n"
            alert_msg += f"SL: {sig['stop_loss']}\n"
            alert_msg += f"{sig['ob_strength']}\n\n"
        alert_msg += f"⏰ {datetime.now().strftime('%H:%M')}"
        send_discord_alert(alert_msg)
    
    save_state(state)
    
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "order_blocks": {k: [ob.to_dict() for ob in v] for k, v in all_obs.items()},
        "signals": all_signals
    }
    with open(Path(__file__).parent / "ob_report.json", "w") as f:
        json.dump(report_data, f, indent=2)
    
    return all_obs, all_signals

if __name__ == "__main__":
    run_ob_analysis()
