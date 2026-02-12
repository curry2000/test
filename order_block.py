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
    "swing_length": 3,
    "max_extend_bars": 300,
    "alert_distance_pct": 2.0,
    "min_volume_mult": 0.5,
    "show_all": True,
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

def get_klines(symbol: str, interval: str, limit: int = 300) -> List[Dict]:
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
    except:
        pass
    
    try:
        interval_map = {"15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={
                "instId": f"{symbol}-USDT-SWAP",
                "bar": interval_map.get(interval, "15m"),
                "limit": str(min(limit, 100))
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

def detect_structure_break(klines: List[Dict], swing_idx: int, direction: str, lookback: int = 15) -> Optional[int]:
    if direction == "bullish":
        ref_highs = [k["high"] for k in klines[max(0, swing_idx-lookback):swing_idx]]
        if not ref_highs:
            return None
        swing_high_before = max(ref_highs)
        for i in range(swing_idx + 1, min(len(klines), swing_idx + 30)):
            if klines[i]["close"] > swing_high_before:
                return i
    else:
        ref_lows = [k["low"] for k in klines[max(0, swing_idx-lookback):swing_idx]]
        if not ref_lows:
            return None
        swing_low_before = min(ref_lows)
        for i in range(swing_idx + 1, min(len(klines), swing_idx + 30)):
            if klines[i]["close"] < swing_low_before:
                return i
    return None

def find_order_blocks(klines: List[Dict], symbol: str, timeframe: str) -> List[OrderBlock]:
    order_blocks = []
    length = OB_PARAMS["swing_length"]
    avg_volume = sum(k["volume"] for k in klines) / len(klines) if klines else 1
    
    swing_lows = find_swing_lows(klines, length)
    for sl_idx in swing_lows:
        break_idx = detect_structure_break(klines, sl_idx, "bullish")
        if break_idx:
            for i in range(break_idx - 1, max(sl_idx - 8, 0), -1):
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
            for i in range(break_idx - 1, max(sh_idx - 8, 0), -1):
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

def filter_recent_obs(order_blocks: List[OrderBlock], klines: List[Dict], max_bars: int = 300) -> List[OrderBlock]:
    current_idx = len(klines) - 1
    valid_obs = []
    
    for ob in order_blocks:
        if current_idx - ob.formed_idx <= max_bars:
            ob = update_ob_mitigation(ob, klines)
            if ob.is_valid:
                valid_obs.append(ob)
    
    return valid_obs

def merge_nearby_obs(obs: List[OrderBlock], threshold_pct: float = 1.0) -> List[OrderBlock]:
    if not obs:
        return []
    
    sorted_obs = sorted(obs, key=lambda x: x.body_low)
    merged = []
    current = sorted_obs[0]
    
    for ob in sorted_obs[1:]:
        if abs(ob.body_low - current.body_high) / current.body_low < threshold_pct / 100:
            current = OrderBlock(
                symbol=current.symbol,
                timeframe=current.timeframe,
                ob_type=current.ob_type,
                high=max(current.high, ob.high),
                low=min(current.low, ob.low),
                body_high=max(current.body_high, ob.body_high),
                body_low=min(current.body_low, ob.body_low),
                volume=current.volume + ob.volume,
                formed_time=current.formed_time,
                formed_idx=min(current.formed_idx, ob.formed_idx),
                mitigation_pct=min(current.mitigation_pct, ob.mitigation_pct),
                is_valid=True,
                touch_count=current.touch_count + ob.touch_count
            )
        else:
            merged.append(current)
            current = ob
    merged.append(current)
    
    return merged

def load_state() -> Dict:
    return {"alerted_obs": [], "last_check": None}

def save_state(state: Dict):
    pass

def send_discord_alert(message: str):
    if not DISCORD_WEBHOOK_URL:
        print(f"[NO WEBHOOK] {message}")
        return
    try:
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            requests.post(DISCORD_WEBHOOK_URL, json={
                "content": chunk,
                "username": "📊 OB 訂單塊"
            }, timeout=10)
    except Exception as e:
        print(f"Webhook error: {e}")

def run_ob_analysis():
    state = load_state()
    all_obs = {}
    all_signals = []
    
    for symbol in SYMBOLS:
        current_price = get_current_price(symbol)
        if current_price == 0:
            continue
        
        for tf in TIMEFRAMES:
            klines = get_klines(symbol, tf, 300)
            if not klines:
                continue
            
            obs = find_order_blocks(klines, symbol, tf)
            valid_obs = filter_recent_obs(obs, klines, OB_PARAMS["max_extend_bars"])
            
            bullish_obs = merge_nearby_obs([ob for ob in valid_obs if ob.ob_type == "bullish"])
            bearish_obs = merge_nearby_obs([ob for ob in valid_obs if ob.ob_type == "bearish"])
            
            key = f"{symbol}_{tf}"
            all_obs[key] = bullish_obs + bearish_obs
            
            alert_pct = OB_PARAMS["alert_distance_pct"] / 100
            for ob in bullish_obs + bearish_obs:
                if ob.ob_type == "bullish":
                    distance = (current_price - ob.body_high) / current_price
                else:
                    distance = (ob.body_low - current_price) / current_price
                
                if -alert_pct <= distance <= alert_pct:
                    sig_key = f"{symbol}_{tf}_{ob.body_low:.0f}"
                    if sig_key not in state["alerted_obs"]:
                        all_signals.append({
                            "symbol": symbol,
                            "timeframe": tf,
                            "ob_type": ob.ob_type,
                            "entry_low": ob.body_low,
                            "entry_high": ob.body_high,
                            "stop_loss": ob.low * 0.995 if ob.ob_type == "bullish" else ob.high * 1.005,
                            "strength": 100 - ob.mitigation_pct,
                            "price": current_price
                        })
                        state["alerted_obs"].append(sig_key)
    
    lines = ["📊 **OB 訂單塊分析**", ""]
    
    for symbol in SYMBOLS:
        price = get_current_price(symbol)
        if price == 0:
            continue
        
        lines.append(f"**{symbol}** ${price:,.2f}")
        lines.append("")
        
        for tf in TIMEFRAMES:
            key = f"{symbol}_{tf}"
            obs = all_obs.get(key, [])
            
            bullish = sorted([ob for ob in obs if ob.ob_type == "bullish"], key=lambda x: x.body_high, reverse=True)
            bearish = sorted([ob for ob in obs if ob.ob_type == "bearish"], key=lambda x: x.body_low)
            
            if bullish or bearish:
                lines.append(f"📈 **{tf}**")
                
                if bearish:
                    lines.append("🔴 壓力區:")
                    for ob in bearish[:4]:
                        strength = 100 - ob.mitigation_pct
                        dist = (ob.body_low - price) / price * 100
                        lines.append(f"   ${ob.body_low:,.0f}-${ob.body_high:,.0f} ({dist:+.1f}%) 強度:{strength:.0f}%")
                
                if bullish:
                    lines.append("🟢 支撐區:")
                    for ob in bullish[:4]:
                        strength = 100 - ob.mitigation_pct
                        dist = (price - ob.body_high) / price * 100
                        lines.append(f"   ${ob.body_low:,.0f}-${ob.body_high:,.0f} ({dist:+.1f}%) 強度:{strength:.0f}%")
                
                lines.append("")
        
        lines.append("---")
    
    if all_signals:
        lines.append("")
        lines.append("🔔 **接近 OB 信號**")
        lines.append("")
        for sig in all_signals:
            action = "考慮做多 📈" if sig["ob_type"] == "bullish" else "考慮做空 📉"
            lines.append(f"{action} {sig['symbol']} ({sig['timeframe']})")
            lines.append(f"入場區: ${sig['entry_low']:,.0f} - ${sig['entry_high']:,.0f}")
            lines.append(f"止損: ${sig['stop_loss']:,.0f}")
            lines.append(f"OB強度: {sig['strength']:.0f}%")
            lines.append("")
    
    lines.append(f"⏰ {datetime.now().strftime('%H:%M')}")
    
    message = "\n".join(lines)
    send_discord_alert(message)
    print(message)
    
    save_state(state)
    
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "order_blocks": {k: [ob.to_dict() for ob in v] for k, v in all_obs.items()}
    }
    with open(Path(__file__).parent / "ob_report.json", "w") as f:
        json.dump(report_data, f, indent=2)
    
    return all_obs, all_signals

if __name__ == "__main__":
    run_ob_analysis()
