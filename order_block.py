#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

OB_PARAMS = {
    "swing_length": 3,
    "max_extend_bars": 300,
    "alert_distance_pct": 2.0,
    "min_volume_mult": 0.5,
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
        print(f"Klines error: {e}")
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
    except Exception as e:
        print(f"Price error: {e}")
    return 0

def find_swing_highs(klines: List[Dict], length: int) -> List[int]:
    highs = [k["high"] for k in klines]
    swings = []
    for i in range(length, len(highs) - length):
        if all(highs[i] > highs[i-j] and highs[i] > highs[i+j] for j in range(1, length+1)):
            swings.append(i)
    return swings

def find_swing_lows(klines: List[Dict], length: int) -> List[int]:
    lows = [k["low"] for k in klines]
    swings = []
    for i in range(length, len(lows) - length):
        if all(lows[i] < lows[i-j] and lows[i] < lows[i+j] for j in range(1, length+1)):
            swings.append(i)
    return swings

def find_order_blocks(klines: List[Dict], symbol: str, timeframe: str) -> List[OrderBlock]:
    obs = []
    length = OB_PARAMS["swing_length"]
    if len(klines) < length * 2 + 1:
        return obs
    
    avg_volume = sum(k["volume"] for k in klines) / len(klines) if klines else 1
    swing_lows = find_swing_lows(klines, length)
    swing_highs = find_swing_highs(klines, length)
    
    for sl_idx in swing_lows:
        if sl_idx < 15:
            continue
        ref_high = max(k["high"] for k in klines[sl_idx-15:sl_idx])
        for i in range(sl_idx+1, min(len(klines), sl_idx+30)):
            if klines[i]["close"] > ref_high:
                for j in range(i-1, max(sl_idx-8, 0), -1):
                    k = klines[j]
                    if k["close"] < k["open"] and k["volume"] >= avg_volume * OB_PARAMS["min_volume_mult"]:
                        obs.append(OrderBlock(
                            symbol=symbol, timeframe=timeframe, ob_type="bullish",
                            high=k["high"], low=k["low"], body_high=k["open"], body_low=k["close"],
                            volume=k["volume"], formed_time=k["time"], formed_idx=j
                        ))
                        break
                break
    
    for sh_idx in swing_highs:
        if sh_idx < 15:
            continue
        ref_low = min(k["low"] for k in klines[sh_idx-15:sh_idx])
        for i in range(sh_idx+1, min(len(klines), sh_idx+30)):
            if klines[i]["close"] < ref_low:
                for j in range(i-1, max(sh_idx-8, 0), -1):
                    k = klines[j]
                    if k["close"] > k["open"] and k["volume"] >= avg_volume * OB_PARAMS["min_volume_mult"]:
                        obs.append(OrderBlock(
                            symbol=symbol, timeframe=timeframe, ob_type="bearish",
                            high=k["high"], low=k["low"], body_high=k["close"], body_low=k["open"],
                            volume=k["volume"], formed_time=k["time"], formed_idx=j
                        ))
                        break
                break
    
    return obs

def filter_valid_obs(obs: List[OrderBlock], klines: List[Dict]) -> List[OrderBlock]:
    valid = []
    current_idx = len(klines) - 1
    
    for ob in obs:
        if current_idx - ob.formed_idx > OB_PARAMS["max_extend_bars"]:
            continue
        
        is_valid = True
        for i in range(ob.formed_idx + 1, len(klines)):
            k = klines[i]
            if ob.ob_type == "bullish" and k["close"] < ob.low:
                is_valid = False
                break
            if ob.ob_type == "bearish" and k["close"] > ob.high:
                is_valid = False
                break
        
        if is_valid:
            ob_range = ob.high - ob.low
            if ob_range > 0:
                for i in range(ob.formed_idx + 1, len(klines)):
                    k = klines[i]
                    if ob.ob_type == "bullish" and k["low"] < ob.high:
                        penetration = ob.high - k["low"]
                        ob.mitigation_pct = max(ob.mitigation_pct, min(100, (penetration / ob_range) * 100))
                    elif ob.ob_type == "bearish" and k["high"] > ob.low:
                        penetration = k["high"] - ob.low
                        ob.mitigation_pct = max(ob.mitigation_pct, min(100, (penetration / ob_range) * 100))
            valid.append(ob)
    
    return valid

def send_discord(message: str):
    print(message)
    if not DISCORD_WEBHOOK_URL:
        print("[NO WEBHOOK URL]")
        return
    try:
        for i in range(0, len(message), 1900):
            chunk = message[i:i+1900]
            r = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk, "username": "📊 OB 訂單塊"}, timeout=10)
            print(f"Webhook response: {r.status_code}")
    except Exception as e:
        print(f"Webhook error: {e}")

def run_ob_analysis():
    print("Starting OB analysis...")
    all_obs = {}
    
    for symbol in SYMBOLS:
        price = get_current_price(symbol)
        print(f"{symbol}: ${price:,.2f}")
        if price == 0:
            continue
        
        for tf in TIMEFRAMES:
            klines = get_klines(symbol, tf, 200)
            print(f"  {tf}: {len(klines)} klines")
            if not klines:
                continue
            
            obs = find_order_blocks(klines, symbol, tf)
            print(f"  Found {len(obs)} raw OBs")
            
            valid_obs = filter_valid_obs(obs, klines)
            print(f"  Valid: {len(valid_obs)} OBs")
            
            all_obs[f"{symbol}_{tf}"] = valid_obs
    
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
            
            lines.append(f"📈 **{tf}**")
            
            if bearish:
                lines.append("🔴 壓力區:")
                for ob in bearish[:4]:
                    strength = 100 - ob.mitigation_pct
                    dist = (ob.body_low - price) / price * 100
                    lines.append(f"   ${ob.body_low:,.0f}-${ob.body_high:,.0f} ({dist:+.1f}%) 強度:{strength:.0f}%")
            else:
                lines.append("🔴 壓力區: 無")
            
            if bullish:
                lines.append("🟢 支撐區:")
                for ob in bullish[:4]:
                    strength = 100 - ob.mitigation_pct
                    dist = (price - ob.body_high) / price * 100
                    lines.append(f"   ${ob.body_low:,.0f}-${ob.body_high:,.0f} ({dist:+.1f}%) 強度:{strength:.0f}%")
            else:
                lines.append("🟢 支撐區: 無")
            
            lines.append("")
        
        lines.append("---")
    
    lines.append(f"⏰ {datetime.now().strftime('%H:%M')}")
    
    message = "\n".join(lines)
    send_discord(message)

if __name__ == "__main__":
    run_ob_analysis()
