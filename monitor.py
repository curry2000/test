"""
Monitor 系統 - Order Block 和 FVG 監控
偵測關鍵支撐壓力位並發送通知
"""
import os
import json
from datetime import datetime, timedelta
import numpy as np

# 使用共用模組
from config import (
    MONITOR_SIGNALS_FILE,
    OB_STATE_FILE,
    TW_TIMEZONE
)
from exchange_api import get_klines
from notify import send_discord_message

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

CONFIDENCE_TABLE = {
    "rsi_high_bearish": 75,
    "normal_bearish": 65,
    "high_vol_bullish": 45,
    "high_vol_bearish": 40,
    "rsi_low_bullish": 37,
    "normal_bullish": 35,
}

def load_json(filepath):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return []

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    except:
        pass

# 注意：get_klines 已從 exchange_api 導入，此處不需要重新定義
# 如果 exchange_api.get_klines 返回格式不同，在此處轉換

def calculate_rsi(klines, period=14):
    if len(klines) < period + 1:
        return 50
    closes = [k["close"] for k in klines]
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def rsi_emoji(rsi):
    if rsi <= 30: return "🔴"
    elif rsi >= 70: return "🟢"
    return "⚪"

def find_order_blocks(klines, swing_length=3):
    if len(klines) < swing_length * 2 + 5:
        return []
    
    obs = []
    avg_vol = np.mean([k["volume"] for k in klines[-50:]]) if len(klines) >= 50 else np.mean([k["volume"] for k in klines])
    closes = [k["close"] for k in klines]
    
    for i in range(swing_length, len(klines) - swing_length - 1):
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and \
                        all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and \
                       all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        vol_ratio = klines[i]["volume"] / avg_vol if avg_vol > 0 else 1
        rsi_at_ob = calculate_rsi(klines[:i+1])
        
        if is_swing_high and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] > klines[i-j]["open"]:
                    has_fvg = check_fvg(klines, i, "bearish")
                    obs.append({"type": "bearish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                               "vol_ratio": vol_ratio, "rsi": rsi_at_ob, "index": i, "fvg": has_fvg})
                    break
        
        if is_swing_low and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] < klines[i-j]["open"]:
                    has_fvg = check_fvg(klines, i, "bullish")
                    obs.append({"type": "bullish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                               "vol_ratio": vol_ratio, "rsi": rsi_at_ob, "index": i, "fvg": has_fvg})
                    break
    
    return obs

def check_fvg(klines, index, direction):
    if index < 2 or index >= len(klines) - 1:
        return None
    
    prev = klines[index - 1]
    curr = klines[index]
    nxt = klines[index + 1]
    
    if direction == "bullish":
        gap_top = prev["low"]
        gap_bottom = nxt["high"]
        if gap_bottom < gap_top:
            return {"top": gap_top, "bottom": gap_bottom, "filled": False}
    else:
        gap_top = nxt["low"]
        gap_bottom = prev["high"]
        if gap_top > gap_bottom:
            return {"top": gap_top, "bottom": gap_bottom, "filled": False}
    
    return None

def find_standalone_fvgs(klines, current_price):
    fvgs = []
    if len(klines) < 3:
        return fvgs
    
    for i in range(1, len(klines) - 1):
        prev = klines[i - 1]
        curr = klines[i]
        nxt = klines[i + 1]
        
        if nxt["low"] > prev["high"]:
            gap_top = nxt["low"]
            gap_bottom = prev["high"]
            mid = (gap_top + gap_bottom) / 2
            gap_pct = (gap_top - gap_bottom) / current_price * 100
            if gap_pct > 0.3 and current_price > gap_top:
                fvgs.append({"type": "bullish", "top": gap_top, "bottom": gap_bottom, "mid": mid, "gap_pct": gap_pct})
        
        if prev["low"] > nxt["high"]:
            gap_top = prev["low"]
            gap_bottom = nxt["high"]
            mid = (gap_top + gap_bottom) / 2
            gap_pct = (gap_top - gap_bottom) / current_price * 100
            if gap_pct > 0.3 and current_price < gap_bottom:
                fvgs.append({"type": "bearish", "top": gap_top, "bottom": gap_bottom, "mid": mid, "gap_pct": gap_pct})
    
    return fvgs

def get_confidence(ob):
    high_vol = ob.get("vol_ratio", 1) > 1.2
    rsi = ob.get("rsi", 50)
    has_fvg = ob.get("fvg") is not None
    vol_ratio = ob.get("vol_ratio", 1)
    
    if ob["type"] == "bearish":
        if rsi > 65:
            base = CONFIDENCE_TABLE["rsi_high_bearish"]
        elif high_vol:
            base = CONFIDENCE_TABLE["high_vol_bearish"]
        else:
            base = CONFIDENCE_TABLE["normal_bearish"]
    else:
        if rsi < 35:
            base = CONFIDENCE_TABLE["rsi_low_bullish"]
        elif high_vol:
            base = CONFIDENCE_TABLE["high_vol_bullish"]
        else:
            base = CONFIDENCE_TABLE["normal_bullish"]
    
    if has_fvg:
        base += 10
    if vol_ratio > 2.0:
        base += 8
    elif vol_ratio > 1.5:
        base += 5
    
    return min(base, 95)

def check_ob_status(symbol, price, bullish_obs, bearish_obs):
    ob_state = load_json(OB_STATE_FILE)
    if not isinstance(ob_state, dict):
        ob_state = {}

    base = symbol.replace("USDT", "")
    if base not in ob_state:
        ob_state[base] = {}

    alerts = []

    for ob in bullish_obs:
        ob_key = f"bull_{ob['tf']}_{ob['bottom']:.0f}_{ob['top']:.0f}"
        prev = ob_state[base].get(ob_key, {"stage": "watching"})
        stage = prev.get("stage", "watching")

        in_zone = price <= ob["top"] and price >= ob["bottom"]
        above = price > ob["top"]
        below = price < ob["bottom"]

        if stage == "watching" and in_zone:
            alerts.append({
                "type": "TEST", "ob_type": "bullish", "symbol": base, "price": price, "ob": ob,
                "message": f"⚠️ {base} ${price:,.0f} 測試支撐 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "testing"}

        elif stage == "testing" and above:
            alerts.append({
                "type": "DEFEND", "ob_type": "bullish", "symbol": base, "price": price, "ob": ob,
                "message": f"✅ {base} ${price:,.0f} 守住支撐 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "defended"}

        elif stage == "testing" and below:
            alerts.append({
                "type": "BREAK", "ob_type": "bullish", "symbol": base, "price": price, "ob": ob,
                "message": f"❌ {base} ${price:,.0f} 跌破支撐 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "broken"}

        elif stage == "defended" and in_zone:
            ob_state[base][ob_key] = {"stage": "testing"}

        elif stage == "defended" and below:
            alerts.append({
                "type": "BREAK", "ob_type": "bullish", "symbol": base, "price": price, "ob": ob,
                "message": f"❌ {base} ${price:,.0f} 跌破支撐 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "broken"}

        elif stage == "broken" and above:
            alerts.append({
                "type": "RECLAIM", "ob_type": "bullish", "symbol": base, "price": price, "ob": ob,
                "message": f"🔄 {base} ${price:,.0f} 收復支撐 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "defended"}

    for ob in bearish_obs:
        ob_key = f"bear_{ob['tf']}_{ob['bottom']:.0f}_{ob['top']:.0f}"
        prev = ob_state[base].get(ob_key, {"stage": "watching"})
        stage = prev.get("stage", "watching")

        in_zone = price >= ob["bottom"] and price <= ob["top"]
        below = price < ob["bottom"]
        above = price > ob["top"]

        if stage == "watching" and in_zone:
            alerts.append({
                "type": "TEST", "ob_type": "bearish", "symbol": base, "price": price, "ob": ob,
                "message": f"⚠️ {base} ${price:,.0f} 測試阻力 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "testing"}

        elif stage == "testing" and below:
            alerts.append({
                "type": "DEFEND", "ob_type": "bearish", "symbol": base, "price": price, "ob": ob,
                "message": f"✅ {base} ${price:,.0f} 守住阻力 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "defended"}

        elif stage == "testing" and above:
            alerts.append({
                "type": "BREAK", "ob_type": "bearish", "symbol": base, "price": price, "ob": ob,
                "message": f"❌ {base} ${price:,.0f} 突破阻力 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "broken"}

        elif stage == "defended" and in_zone:
            ob_state[base][ob_key] = {"stage": "testing"}

        elif stage == "defended" and above:
            alerts.append({
                "type": "BREAK", "ob_type": "bearish", "symbol": base, "price": price, "ob": ob,
                "message": f"❌ {base} ${price:,.0f} 突破阻力 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "broken"}

        elif stage == "broken" and below:
            alerts.append({
                "type": "RECLAIM", "ob_type": "bearish", "symbol": base, "price": price, "ob": ob,
                "message": f"🔄 {base} ${price:,.0f} 收復阻力 OB [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f}"
            })
            ob_state[base][ob_key] = {"stage": "defended"}

    stale = []
    for k in ob_state[base]:
        if k.startswith("bull_") or k.startswith("bear_"):
            all_keys = [f"bull_{o['tf']}_{o['bottom']:.0f}_{o['top']:.0f}" for o in bullish_obs]
            all_keys += [f"bear_{o['tf']}_{o['bottom']:.0f}_{o['top']:.0f}" for o in bearish_obs]
            if k not in all_keys:
                stale.append(k)
    for k in stale:
        del ob_state[base][k]

    save_json(OB_STATE_FILE, ob_state)
    return alerts

def detect_signals(analysis):
    signals = []
    price = analysis["price"]
    rsi = analysis["rsi"]
    symbol = analysis["symbol"].replace("USDT", "")
    
    for ob in analysis.get("bullish_obs", []):
        if ob["distance"] < 3:
            signals.append({
                "symbol": symbol,
                "signal": "LONG",
                "trigger": "OB",
                "entry_price": price,
                "ob_zone": f"${ob['bottom']:,.0f}-${ob['top']:,.0f}",
                "tf": ob["tf"],
                "confidence": ob["confidence"],
                "rsi_1h": rsi["1h"]
            })
            break
    
    for ob in analysis.get("bearish_obs", []):
        if abs(ob["distance"]) < 3:
            signals.append({
                "symbol": symbol,
                "signal": "SHORT",
                "trigger": "OB",
                "entry_price": price,
                "ob_zone": f"${ob['bottom']:,.0f}-${ob['top']:,.0f}",
                "tf": ob["tf"],
                "confidence": ob["confidence"],
                "rsi_1h": rsi["1h"]
            })
            break
    
    if rsi["1h"] <= 25 and rsi["4h"] <= 35:
        signals.append({
            "symbol": symbol,
            "signal": "LONG",
            "trigger": "RSI",
            "entry_price": price,
            "rsi_1h": rsi["1h"],
            "rsi_4h": rsi["4h"],
            "confidence": 60
        })
    elif rsi["1h"] >= 75 and rsi["4h"] >= 65:
        signals.append({
            "symbol": symbol,
            "signal": "SHORT",
            "trigger": "RSI",
            "entry_price": price,
            "rsi_1h": rsi["1h"],
            "rsi_4h": rsi["4h"],
            "confidence": 60
        })
    
    sup_dist = (price - analysis["support"]) / price * 100
    res_dist = (analysis["resistance"] - price) / price * 100
    
    if sup_dist < 1.5 and rsi["1h"] < 40:
        signals.append({
            "symbol": symbol,
            "signal": "LONG",
            "trigger": "SUPPORT",
            "entry_price": price,
            "level": analysis["support"],
            "rsi_1h": rsi["1h"],
            "confidence": 55
        })
    elif res_dist < 1.5 and rsi["1h"] > 60:
        signals.append({
            "symbol": symbol,
            "signal": "SHORT",
            "trigger": "RESISTANCE",
            "entry_price": price,
            "level": analysis["resistance"],
            "rsi_1h": rsi["1h"],
            "confidence": 55
        })
    
    return signals

def log_signals(signals):
    if not signals:
        return
    
    tw_tz = TW_TIMEZONE
    now = datetime.now(tw_tz)
    timestamp = now.isoformat()
    
    logs = load_json(MONITOR_SIGNALS_FILE)
    if not isinstance(logs, list):
        logs = []
    
    for sig in signals:
        logs.append({
            "ts": timestamp,
            "symbol": sig["symbol"],
            "signal": sig["signal"],
            "trigger": sig["trigger"],
            "entry_price": sig["entry_price"],
            "confidence": sig.get("confidence", 50),
            "rsi_1h": sig.get("rsi_1h", 50)
        })
    
    cutoff = now - timedelta(days=7)
    logs = [l for l in logs if datetime.fromisoformat(l["ts"]) > cutoff]
    
    save_json(MONITOR_SIGNALS_FILE, logs)
    print(f"已記錄 {len(signals)} 個訊號")

def analyze_symbol(symbol):
    klines_15m = get_klines(symbol, "15m", 96)
    klines_30m = get_klines(symbol, "30m", 96)
    klines_1h = get_klines(symbol, "1H", 72)
    klines_4h = get_klines(symbol, "4H", 42)
    
    if not klines_15m and not klines_1h:
        return None
    
    klines_main = klines_15m or klines_1h
    current_price = klines_main[-1]["close"]
    
    rsi_15m = calculate_rsi(klines_15m) if klines_15m else 50
    rsi_30m = calculate_rsi(klines_30m) if klines_30m else 50
    rsi_1h = calculate_rsi(klines_1h) if klines_1h else 50
    rsi_4h = calculate_rsi(klines_4h) if klines_4h else 50
    
    all_obs = []
    all_fvgs = []
    for tf_name, klines, swing in [("15M", klines_15m, 2), ("1H", klines_1h, 3), ("4H", klines_4h, 3)]:
        if not klines:
            continue
        for ob in find_order_blocks(klines, swing)[-5:]:
            ob["tf"] = tf_name
            mid = (ob["top"] + ob["bottom"]) / 2
            ob["distance"] = (current_price - mid) / current_price * 100
            ob["confidence"] = get_confidence(ob)
            all_obs.append(ob)
        
        fvgs = find_standalone_fvgs(klines, current_price)
        for fvg in fvgs[-3:]:
            fvg["tf"] = tf_name
            mid = (fvg["top"] + fvg["bottom"]) / 2
            fvg["distance"] = (current_price - mid) / current_price * 100
            all_fvgs.append(fvg)
    
    bullish_obs = sorted([ob for ob in all_obs if ob["type"] == "bullish" and current_price > ob["top"]],
                        key=lambda x: x["distance"])[:3]
    bearish_obs = sorted([ob for ob in all_obs if ob["type"] == "bearish" and current_price < ob["bottom"]],
                        key=lambda x: abs(x["distance"]))[:3]
    
    def dedupe_obs(obs_list, min_gap_pct=1.5):
        if not obs_list:
            return []
        result = [obs_list[0]]
        for ob in obs_list[1:]:
            last_mid = (result[-1]["top"] + result[-1]["bottom"]) / 2
            this_mid = (ob["top"] + ob["bottom"]) / 2
            gap = abs(this_mid - last_mid) / current_price * 100
            if gap >= min_gap_pct:
                result.append(ob)
        return result
    
    bullish_obs = dedupe_obs(bullish_obs)
    bearish_obs = dedupe_obs(bearish_obs)
    
    bullish_fvgs = sorted([f for f in all_fvgs if f["type"] == "bullish"], key=lambda x: x["distance"])[:2]
    bearish_fvgs = sorted([f for f in all_fvgs if f["type"] == "bearish"], key=lambda x: abs(x["distance"]))[:2]
    
    highs = [k["high"] for k in klines_1h] if klines_1h else [current_price]
    lows = [k["low"] for k in klines_1h] if klines_1h else [current_price]
    support = min(lows[-24:]) if len(lows) >= 24 else min(lows)
    resistance = max(highs[-24:]) if len(highs) >= 24 else max(highs)
    
    return {
        "symbol": symbol,
        "price": current_price,
        "rsi": {"15m": rsi_15m, "30m": rsi_30m, "1h": rsi_1h, "4h": rsi_4h},
        "support": support,
        "resistance": resistance,
        "bullish_obs": bullish_obs,
        "bearish_obs": bearish_obs,
        "bullish_fvgs": bullish_fvgs,
        "bearish_fvgs": bearish_fvgs
    }

def format_message(analyses):
    tw_tz = TW_TIMEZONE
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    tag = os.environ.get("SOURCE_TAG", "OKX雲端")
    lines = [f"📊 **技術分析 [{tag}]** | {now}", ""]
    
    for a in analyses:
        base = a["symbol"].replace("USDT", "")
        rsi = a["rsi"]
        
        lines.append(f"**{base}: ${a['price']:,.2f}**")
        lines.append(f"RSI → 15分:{rsi_emoji(rsi['15m'])}{rsi['15m']:.0f} | 30分:{rsi_emoji(rsi['30m'])}{rsi['30m']:.0f} | 1時:{rsi_emoji(rsi['1h'])}{rsi['1h']:.0f} | 4時:{rsi_emoji(rsi['4h'])}{rsi['4h']:.0f}")
        
        sup_dist = (a["price"] - a["support"]) / a["price"] * 100
        res_dist = (a["resistance"] - a["price"]) / a["price"] * 100
        lines.append(f"📍 支撐 ${a['support']:,.0f} ({sup_dist:.1f}%) | 阻力 ${a['resistance']:,.0f} ({res_dist:.1f}%)")
        
        if a["bullish_obs"]:
            for ob in a["bullish_obs"][:2]:
                mid = (ob['top'] + ob['bottom']) / 2
                ob_range = ob['top'] - ob['bottom']
                entry = mid
                sl = ob['bottom'] - ob_range * 0.3
                risk = entry - sl
                tp1 = entry + risk * 1.5
                tp2 = entry + risk * 2.5
                tp3 = entry + risk * 4.0
                rr = (tp2 - entry) / risk if risk > 0 else 0
                vol_tag = f" 📊{ob['vol_ratio']:.1f}x" if ob.get('vol_ratio', 0) > 1.2 else ""
                fvg_tag = " ⚡FVG" if ob.get('fvg') else ""
                lines.append(f"🟢 [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f} (中:{mid:,.0f}) | 📈做多 {ob['confidence']}%{vol_tag}{fvg_tag}")
                lines.append(f"  📍 入場 ${entry:,.0f} | SL ${sl:,.0f}")
                lines.append(f"  🎯 TP1 ${tp1:,.0f}(40%) → TP2 ${tp2:,.0f}(30%) → TP3 ${tp3:,.0f}(30%)")
                lines.append(f"  📐 盈虧比 {rr:.1f}R")
        
        if a["bearish_obs"]:
            for ob in a["bearish_obs"][:2]:
                mid = (ob['top'] + ob['bottom']) / 2
                ob_range = ob['top'] - ob['bottom']
                entry = mid
                sl = ob['top'] + ob_range * 0.3
                risk = sl - entry
                tp1 = entry - risk * 1.5
                tp2 = entry - risk * 2.5
                tp3 = entry - risk * 4.0
                rr = (entry - tp2) / risk if risk > 0 else 0
                vol_tag = f" 📊{ob['vol_ratio']:.1f}x" if ob.get('vol_ratio', 0) > 1.2 else ""
                fvg_tag = " ⚡FVG" if ob.get('fvg') else ""
                lines.append(f"🔴 [{ob['tf']}] ${ob['bottom']:,.0f}-${ob['top']:,.0f} (中:{mid:,.0f}) | 📉做空 {ob['confidence']}%{vol_tag}{fvg_tag}")
                lines.append(f"  📍 入場 ${entry:,.0f} | SL ${sl:,.0f}")
                lines.append(f"  🎯 TP1 ${tp1:,.0f}(40%) → TP2 ${tp2:,.0f}(30%) → TP3 ${tp3:,.0f}(30%)")
                lines.append(f"  📐 盈虧比 {rr:.1f}R")
        
        if a.get("bullish_fvgs") or a.get("bearish_fvgs"):
            for fvg in a.get("bullish_fvgs", [])[:1]:
                lines.append(f"⚡ [{fvg['tf']}] 多方缺口 ${fvg['bottom']:,.0f}-${fvg['top']:,.0f} ({fvg['gap_pct']:.1f}%)")
            for fvg in a.get("bearish_fvgs", [])[:1]:
                lines.append(f"⚡ [{fvg['tf']}] 空方缺口 ${fvg['bottom']:,.0f}-${fvg['top']:,.0f} ({fvg['gap_pct']:.1f}%)")
        
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("🔴<30超賣 | ⚪中性 | 🟢>70超買")
    lines.append("信心%=30天回測勝率")
    
    return "\n".join(lines)

def send_discord(message):
    """發送 Discord 訊息（使用共用 notify 模組）"""
    success = send_discord_message(message)
    if success:
        print("Discord: 200 OK")
    else:
        print("Discord: Send failed")

def main():
    print("=== Crypto Monitor Start ===")
    
    analyses = []
    all_signals = []
    ob_alerts = []
    
    for symbol in SYMBOLS:
        print(f"Analyzing {symbol}...")
        result = analyze_symbol(symbol)
        if result:
            analyses.append(result)
            signals = detect_signals(result)
            all_signals.extend(signals)
            
            ob_status = check_ob_status(
                symbol, 
                result["price"], 
                result["bullish_obs"], 
                result["bearish_obs"]
            )
            ob_alerts.extend(ob_status)
            
            print(f"  OK: ${result['price']:,.2f}, {len(signals)} 訊號, {len(ob_status)} OB狀態")
    
    log_signals(all_signals)
    
    if analyses:
        message = format_message(analyses)
        print("\n" + message)
        send_discord(message)
    
    if ob_alerts:
        tw_tz = TW_TIMEZONE
        now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
        ob_tag = os.environ.get("SOURCE_TAG", "OKX雲端")
        ob_lines = [f"🎯 **OB 狀態更新 [{ob_tag}]** | {now}", ""]
        for alert in ob_alerts:
            ob_lines.append(alert["message"])
        ob_message = "\n".join(ob_lines)
        print("\n" + ob_message)
        send_discord(ob_message)
    
    if not analyses:
        print("No data")

if __name__ == "__main__":
    main()
