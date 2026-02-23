"""
OB V2 回測 — 驗證優化後的 Order Block 邏輯
對比 V1 (現有) vs V2 (優化後) 的勝率和盈虧

改動:
1. OB 失效機制 — 收盤穿破即失效
2. 去重冷卻 — 同 OB 4hr 內不重複觸發
3. 方向衝突過濾 — 同幣種不同時多空
4. 入場用 OB mid，不是現價
5. 品質評分重構
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from collections import defaultdict
from exchange_api import get_klines

# ─── RSI ───
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_g = np.mean(gains[:period])
    avg_l = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100
    return 100 - (100 / (1 + avg_g / avg_l))

# ─── V1: 現有 OB 偵測 (原版) ───
def find_obs_v1(klines, swing_length=3):
    if len(klines) < swing_length * 2 + 5:
        return []
    obs = []
    avg_vol = np.mean([k["volume"] for k in klines[-50:]]) if len(klines) >= 50 else np.mean([k["volume"] for k in klines])
    
    for i in range(swing_length, len(klines) - swing_length - 1):
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and \
                        all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and \
                       all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        vol_ratio = klines[i]["volume"] / avg_vol if avg_vol > 0 else 1
        
        if is_swing_high and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] > klines[i-j]["open"]:
                    obs.append({
                        "type": "bearish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                        "vol_ratio": vol_ratio, "index": i
                    })
                    break
        
        if is_swing_low and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] < klines[i-j]["open"]:
                    obs.append({
                        "type": "bullish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                        "vol_ratio": vol_ratio, "index": i
                    })
                    break
    return obs

# ─── V2: 優化 OB 偵測 ───
def find_obs_v2(klines, swing_length=3):
    """
    改動:
    - 加入失效檢查: OB 被收盤價穿破即失效
    - 追蹤被測試次數
    - 記錄 OB 產生的 index 用於計算 age
    """
    if len(klines) < swing_length * 2 + 5:
        return []
    obs = []
    avg_vol = np.mean([k["volume"] for k in klines[-50:]]) if len(klines) >= 50 else np.mean([k["volume"] for k in klines])
    
    for i in range(swing_length, len(klines) - swing_length - 1):
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and \
                        all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and \
                       all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        vol_ratio = klines[i]["volume"] / avg_vol if avg_vol > 0 else 1
        
        if is_swing_high and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] > klines[i-j]["open"]:
                    ob_top = klines[i-j]["high"]
                    ob_bottom = klines[i-j]["low"]
                    
                    # ✅ 失效檢查: 後續收盤價突破 OB top = 失效
                    invalidated = False
                    test_count = 0
                    for k in range(i+1, len(klines)):
                        if klines[k]["close"] > ob_top:
                            invalidated = True
                            break
                        # 測試次數: 價格觸及但未穿破
                        if klines[k]["high"] >= ob_bottom:
                            test_count += 1
                    
                    if not invalidated and test_count <= 3:
                        obs.append({
                            "type": "bearish", "top": ob_top, "bottom": ob_bottom,
                            "vol_ratio": vol_ratio, "index": i, "tests": test_count,
                            "age": len(klines) - 1 - i
                        })
                    break
        
        if is_swing_low and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] < klines[i-j]["open"]:
                    ob_top = klines[i-j]["high"]
                    ob_bottom = klines[i-j]["low"]
                    
                    # ✅ 失效檢查: 後續收盤價跌破 OB bottom = 失效
                    invalidated = False
                    test_count = 0
                    for k in range(i+1, len(klines)):
                        if klines[k]["close"] < ob_bottom:
                            invalidated = True
                            break
                        if klines[k]["low"] <= ob_top:
                            test_count += 1
                    
                    if not invalidated and test_count <= 3:
                        obs.append({
                            "type": "bullish", "top": ob_top, "bottom": ob_bottom,
                            "vol_ratio": vol_ratio, "index": i, "tests": test_count,
                            "age": len(klines) - 1 - i
                        })
                    break
    return obs

# ─── V2 品質評分 ───
TF_WEIGHT = {"4H": 70, "1H": 55, "15M": 40}

def score_ob_v2(ob, tf):
    base = TF_WEIGHT.get(tf, 50)
    if ob["vol_ratio"] > 1.5:
        base += 15
    elif ob["vol_ratio"] > 1.2:
        base += 8
    base -= ob.get("tests", 0) * 5
    age = ob.get("age", 0)
    if tf == "4H" and age > 12:      # 48h+
        base -= 10
    elif tf == "1H" and age > 48:    # 48h+
        base -= 10
    elif tf == "15M" and age > 96:   # 24h+
        base -= 15
    return max(0, base)

# ─── 回測引擎 ───
def backtest_version(klines_dict, version="v1", max_distance_pct=3.0):
    """
    用滑動窗口模擬即時信號產生 + 追蹤結果
    klines_dict: {"15M": [...], "1H": [...], "4H": [...]}
    """
    # 用 1H K線作為主時間軸 tick
    klines_1h = klines_dict.get("1H", [])
    if len(klines_1h) < 50:
        return []
    
    trades = []
    cooldown = {}  # v2 冷卻追蹤: key=(type, round(mid)) -> last_trigger_idx
    
    for tick in range(60, len(klines_1h) - 6):  # 留 6 根做 outcome
        price = klines_1h[tick]["close"]
        window = klines_1h[:tick+1]
        
        # 找 OB
        if version == "v1":
            obs = find_obs_v1(window, swing_length=3)
        else:
            obs = find_obs_v2(window, swing_length=3)
        
        if not obs:
            continue
        
        # 分多空
        bullish = [ob for ob in obs if ob["type"] == "bullish"]
        bearish = [ob for ob in obs if ob["type"] == "bearish"]
        
        # 按距離排序
        for ob in bullish:
            mid = (ob["top"] + ob["bottom"]) / 2
            ob["distance"] = (price - mid) / price * 100
        for ob in bearish:
            mid = (ob["top"] + ob["bottom"]) / 2
            ob["distance"] = (mid - price) / price * 100
        
        bullish = sorted([ob for ob in bullish if 0 < ob["distance"] < max_distance_pct], key=lambda x: x["distance"])
        bearish = sorted([ob for ob in bearish if 0 < ob["distance"] < max_distance_pct], key=lambda x: abs(x["distance"]))
        
        signals = []
        
        if version == "v1":
            # V1: 直接取最近的，入場=現價，可同時多空
            if bullish:
                ob = bullish[0]
                signals.append({"dir": "LONG", "entry": price, "ob": ob})
            if bearish:
                ob = bearish[0]
                signals.append({"dir": "SHORT", "entry": price, "ob": ob})
        else:
            # V2 改動:
            # - 入場用 OB mid (只有現價在 OB ±1.5% 才觸發)
            # - 冷卻去重
            # - 方向衝突: 只取最高分
            candidates = []
            
            for ob in bullish[:2]:
                mid = (ob["top"] + ob["bottom"]) / 2
                proximity = abs(price - ob["top"]) / price * 100
                if proximity < 1.5:  # 現價接近 OB 頂部才觸發做多
                    key = ("bullish", round(mid / 100) * 100)
                    if key in cooldown and tick - cooldown[key] < 4:
                        continue
                    score = score_ob_v2(ob, "1H")
                    candidates.append({"dir": "LONG", "entry": mid, "ob": ob, "score": score, "key": key})
            
            for ob in bearish[:2]:
                mid = (ob["top"] + ob["bottom"]) / 2
                proximity = abs(price - ob["bottom"]) / price * 100
                if proximity < 1.5:
                    key = ("bearish", round(mid / 100) * 100)
                    if key in cooldown and tick - cooldown[key] < 4:
                        continue
                    score = score_ob_v2(ob, "1H")
                    candidates.append({"dir": "SHORT", "entry": mid, "ob": ob, "score": score, "key": key})
            
            if candidates:
                best = max(candidates, key=lambda x: x["score"])
                signals.append(best)
                cooldown[best["key"]] = tick
        
        # 計算 outcome
        for sig in signals:
            entry = sig["entry"]
            ob = sig["ob"]
            ob_range = ob["top"] - ob["bottom"]
            
            if sig["dir"] == "LONG":
                sl = ob["bottom"] - ob_range * 0.3
                tp1 = entry + (entry - sl) * 1.5
                tp2 = entry + (entry - sl) * 2.5
            else:
                sl = ob["top"] + ob_range * 0.3
                tp1 = entry - (sl - entry) * 1.5
                tp2 = entry - (sl - entry) * 2.5
            
            # 追蹤未來 6 根 1H
            outcomes = {}
            hit_sl = False
            hit_tp1 = False
            for h in range(1, min(7, len(klines_1h) - tick)):
                future = klines_1h[tick + h]
                pnl_pct = ((future["close"] - entry) / entry * 100) if sig["dir"] == "LONG" else ((entry - future["close"]) / entry * 100)
                outcomes[f"{h}h"] = round(pnl_pct, 3)
                
                if sig["dir"] == "LONG":
                    if future["low"] <= sl: hit_sl = True
                    if future["high"] >= tp1: hit_tp1 = True
                else:
                    if future["high"] >= sl: hit_sl = True
                    if future["low"] <= tp1: hit_tp1 = True
            
            trades.append({
                "tick": tick,
                "dir": sig["dir"],
                "entry": round(entry, 2),
                "ob_zone": f"{ob['bottom']:.0f}-{ob['top']:.0f}",
                "vol_ratio": round(ob["vol_ratio"], 2),
                "outcomes": outcomes,
                "hit_sl": hit_sl,
                "hit_tp1": hit_tp1,
                "version": version
            })
    
    return trades

def print_stats(trades, label):
    if not trades:
        print(f"\n{'='*50}")
        print(f"  {label}: 沒有交易")
        return
    
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  總信號數: {len(trades)}")
    
    longs = [t for t in trades if t["dir"] == "LONG"]
    shorts = [t for t in trades if t["dir"] == "SHORT"]
    print(f"  LONG: {len(longs)} | SHORT: {len(shorts)}")
    
    # 各時間點勝率
    for h in ["1h", "2h", "4h", "6h"]:
        wins = sum(1 for t in trades if t["outcomes"].get(h, 0) > 0)
        total = sum(1 for t in trades if h in t["outcomes"])
        if total > 0:
            avg_pnl = np.mean([t["outcomes"][h] for t in trades if h in t["outcomes"]])
            print(f"  {h}: 勝率 {wins}/{total} = {wins/total*100:.1f}% | 平均 PnL {avg_pnl:+.2f}%")
    
    # SL/TP1 hit rate
    sl_hits = sum(1 for t in trades if t["hit_sl"])
    tp_hits = sum(1 for t in trades if t["hit_tp1"])
    print(f"  6h 內觸 SL: {sl_hits}/{len(trades)} ({sl_hits/len(trades)*100:.1f}%)")
    print(f"  6h 內觸 TP1: {tp_hits}/{len(trades)} ({tp_hits/len(trades)*100:.1f}%)")
    
    # 多空分開
    for label2, subset in [("LONG", longs), ("SHORT", shorts)]:
        if not subset:
            continue
        wins_2h = sum(1 for t in subset if t["outcomes"].get("2h", 0) > 0)
        total_2h = sum(1 for t in subset if "2h" in t["outcomes"])
        avg_2h = np.mean([t["outcomes"]["2h"] for t in subset if "2h" in t["outcomes"]]) if total_2h > 0 else 0
        print(f"  {label2} 2h: {wins_2h}/{total_2h} = {wins_2h/total_2h*100:.1f}% | avg {avg_2h:+.2f}%")

def main():
    for symbol in ["BTC", "ETH"]:
        print(f"\n🔍 拉取 {symbol} K 線數據...")
        
        klines_1h = get_klines(f"{symbol}USDT", "1h", 500)
        
        if not klines_1h:
            print(f"  ❌ 無法取得 {symbol} K 線")
            continue
        
        print(f"  ✅ 1H: {len(klines_1h)} 根")
        
        klines_dict = {"1H": klines_1h}
        
        # V1 回測
        trades_v1 = backtest_version(klines_dict, version="v1")
        print_stats(trades_v1, f"{symbol} V1 (現有)")
        
        # V2 回測
        trades_v2 = backtest_version(klines_dict, version="v2")
        print_stats(trades_v2, f"{symbol} V2 (優化)")
        
        # 對比
        if trades_v1 and trades_v2:
            v1_2h = np.mean([t["outcomes"].get("2h", 0) for t in trades_v1])
            v2_2h = np.mean([t["outcomes"].get("2h", 0) for t in trades_v2])
            print(f"\n  📊 {symbol} 2h 平均 PnL: V1 {v1_2h:+.3f}% → V2 {v2_2h:+.3f}%")
            
            v1_signals = len(trades_v1)
            v2_signals = len(trades_v2)
            print(f"  📉 信號量: V1 {v1_signals} → V2 {v2_signals} (減少 {(1-v2_signals/v1_signals)*100:.0f}%)")

if __name__ == "__main__":
    main()
