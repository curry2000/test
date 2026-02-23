"""
OB Engine V2 — 共用 Order Block 偵測與評分
供 monitor.py 和 position_advisor.py 使用

改動:
1. OB 失效機制 — 收盤穿破即失效
2. 被測試次數追蹤 (>3 次降級)
3. 品質評分 (時間週期權重 + 成交量 + age 衰減)
4. 方向衝突過濾 — 同幣種只取最高分方向
5. 冷卻去重 — 同 OB 不重複觸發
"""
import numpy as np
from datetime import datetime

# ─── 品質評分權重 ───
TF_WEIGHT = {"4H": 70, "1H": 55, "15M": 40, "1D": 80}
# age 上限 (超過即失效，單位: K 線根數)
AGE_LIMIT = {"4H": 42, "1H": 72, "15M": 96, "1D": 30}
# age 衰減門檻
AGE_DECAY = {"4H": 12, "1H": 48, "15M": 72, "1D": 14}


def find_order_blocks_v2(klines, swing_length=3):
    """
    偵測 Order Block，含失效過濾和測試次數追蹤
    
    Returns: list of OB dicts with keys:
        type, top, bottom, vol_ratio, index, tests, age, fvg
    """
    if len(klines) < swing_length * 2 + 5:
        return []
    
    obs = []
    avg_vol = np.mean([k["volume"] for k in klines[-50:]]) if len(klines) >= 50 else np.mean([k["volume"] for k in klines])
    if avg_vol == 0:
        avg_vol = 1
    
    for i in range(swing_length, len(klines) - swing_length - 1):
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        
        is_swing_high = all(highs[i] > highs[i-j] for j in range(1, swing_length+1)) and \
                        all(highs[i] > highs[i+j] for j in range(1, swing_length+1))
        is_swing_low = all(lows[i] < lows[i-j] for j in range(1, swing_length+1)) and \
                       all(lows[i] < lows[i+j] for j in range(1, swing_length+1))
        
        vol_ratio = klines[i]["volume"] / avg_vol if avg_vol > 0 else 1
        
        # ─── Bearish OB (Swing High) ───
        if is_swing_high and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] > klines[i-j]["open"]:
                    ob_top = klines[i-j]["high"]
                    ob_bottom = klines[i-j]["low"]
                    
                    # 失效檢查: 後續收盤價突破 OB top
                    invalidated = False
                    test_count = 0
                    for k in range(i+1, len(klines)):
                        if klines[k]["close"] > ob_top:
                            invalidated = True
                            break
                        if klines[k]["high"] >= ob_bottom:
                            test_count += 1
                    
                    if not invalidated and test_count <= 3:
                        has_fvg = _check_fvg(klines, i, "bearish")
                        obs.append({
                            "type": "bearish",
                            "top": ob_top,
                            "bottom": ob_bottom,
                            "vol_ratio": vol_ratio,
                            "index": i,
                            "tests": test_count,
                            "age": len(klines) - 1 - i,
                            "fvg": has_fvg
                        })
                    break
        
        # ─── Bullish OB (Swing Low) ───
        if is_swing_low and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] < klines[i-j]["open"]:
                    ob_top = klines[i-j]["high"]
                    ob_bottom = klines[i-j]["low"]
                    
                    # 失效檢查: 後續收盤價跌破 OB bottom
                    invalidated = False
                    test_count = 0
                    for k in range(i+1, len(klines)):
                        if klines[k]["close"] < ob_bottom:
                            invalidated = True
                            break
                        if klines[k]["low"] <= ob_top:
                            test_count += 1
                    
                    if not invalidated and test_count <= 3:
                        has_fvg = _check_fvg(klines, i, "bullish")
                        obs.append({
                            "type": "bullish",
                            "top": ob_top,
                            "bottom": ob_bottom,
                            "vol_ratio": vol_ratio,
                            "index": i,
                            "tests": test_count,
                            "age": len(klines) - 1 - i,
                            "fvg": has_fvg
                        })
                    break
    
    return obs


def _check_fvg(klines, index, direction):
    """檢查 OB 附近有沒有 FVG"""
    if index < 2 or index >= len(klines) - 1:
        return None
    
    prev = klines[index - 1]
    curr = klines[index]
    nxt = klines[index + 1]
    
    if direction == "bullish":
        gap_top = prev["low"]
        gap_bottom = nxt["high"]
        if gap_bottom < gap_top:
            return {"top": gap_top, "bottom": gap_bottom}
    else:
        gap_top = nxt["low"]
        gap_bottom = prev["high"]
        if gap_top > gap_bottom:
            return {"top": gap_top, "bottom": gap_bottom}
    return None


def score_ob(ob, tf="1H"):
    """
    OB 品質評分
    base = 時間週期權重
    + volume bonus
    + fvg bonus
    - test penalty
    - age decay
    """
    base = TF_WEIGHT.get(tf, 50)
    
    # Volume bonus
    if ob["vol_ratio"] > 1.5:
        base += 15
    elif ob["vol_ratio"] > 1.2:
        base += 8
    
    # FVG bonus
    if ob.get("fvg"):
        base += 10
    
    # Test penalty
    base -= ob.get("tests", 0) * 5
    
    # Age decay
    age = ob.get("age", 0)
    decay_threshold = AGE_DECAY.get(tf, 48)
    if age > decay_threshold:
        base -= 10
    
    return max(0, base)


def filter_and_rank_obs(obs, current_price, tf="1H", max_distance_pct=5.0):
    """
    過濾 + 排序 OB，加入距離和評分
    
    Returns: (bullish_obs, bearish_obs) 各自按品質排序
    """
    for ob in obs:
        mid = (ob["top"] + ob["bottom"]) / 2
        ob["mid"] = mid
        ob["score"] = score_ob(ob, tf)
        if ob["type"] == "bullish":
            ob["distance"] = (current_price - mid) / current_price * 100
        else:
            ob["distance"] = (mid - current_price) / current_price * 100
    
    # 過濾: 距離限制 + age 限制
    age_limit = AGE_LIMIT.get(tf, 72)
    
    bullish = [ob for ob in obs 
               if ob["type"] == "bullish" 
               and 0 < ob["distance"] < max_distance_pct
               and ob["age"] < age_limit]
    bearish = [ob for ob in obs 
               if ob["type"] == "bearish" 
               and 0 < ob["distance"] < max_distance_pct
               and ob["age"] < age_limit]
    
    # 按 score 排序 (高分優先)
    bullish.sort(key=lambda x: x["score"], reverse=True)
    bearish.sort(key=lambda x: x["score"], reverse=True)
    
    # 去重: 相近價位只保留最高分
    bullish = _dedupe_obs(bullish, current_price)
    bearish = _dedupe_obs(bearish, current_price)
    
    return bullish[:3], bearish[:3]


def _dedupe_obs(obs_list, current_price, min_gap_pct=1.5):
    """相近價位去重"""
    if not obs_list:
        return []
    result = [obs_list[0]]
    for ob in obs_list[1:]:
        too_close = False
        for existing in result:
            gap = abs(ob["mid"] - existing["mid"]) / current_price * 100
            if gap < min_gap_pct:
                too_close = True
                break
        if not too_close:
            result.append(ob)
    return result


def resolve_direction_conflict(bullish_obs, bearish_obs):
    """
    方向衝突過濾: 同幣種多空衝突時，取最高分的方向
    Returns: (bullish_obs, bearish_obs) — 其中一個可能被清空
    """
    if not bullish_obs or not bearish_obs:
        return bullish_obs, bearish_obs
    
    best_bull = max(ob["score"] for ob in bullish_obs)
    best_bear = max(ob["score"] for ob in bearish_obs)
    
    if best_bull > best_bear:
        return bullish_obs, []
    elif best_bear > best_bull:
        return [], bearish_obs
    else:
        # 平手: 都保留，讓使用者判斷
        return bullish_obs, bearish_obs


def calc_entry_sl_tp(ob, direction):
    """
    基於 OB 區間計算入場/止損/止盈
    入場 = OB mid
    """
    mid = (ob["top"] + ob["bottom"]) / 2
    ob_range = ob["top"] - ob["bottom"]
    
    if direction == "LONG":
        entry = mid
        sl = ob["bottom"] - ob_range * 0.3
        risk = entry - sl
        tp1 = entry + risk * 1.5
        tp2 = entry + risk * 2.5
        tp3 = entry + risk * 4.0
    else:  # SHORT
        entry = mid
        sl = ob["top"] + ob_range * 0.3
        risk = sl - entry
        tp1 = entry - risk * 1.5
        tp2 = entry - risk * 2.5
        tp3 = entry - risk * 4.0
    
    rr = (abs(tp2 - entry) / risk) if risk > 0 else 0
    
    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk": risk,
        "rr": rr
    }
