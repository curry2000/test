"""
回測 monitor.py 的 OB 進場信號準確度
用歷史 K 線找 OB → 模擬進場 → 看後續是否達到 TP1/TP2/TP3 或 SL
"""
import requests
import numpy as np
from datetime import datetime, timezone, timedelta
from collections import defaultdict

def get_klines(symbol, interval, limit):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=15)
        data = r.json()
        if isinstance(data, list):
            return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5]),"time":int(k[0])} for k in data]
    except:
        pass
    return []

def calculate_rsi(klines, period=14):
    if len(klines) < period + 1:
        return 50
    closes = [k["close"] for k in klines]
    gains, losses = [], []
    for i in range(len(closes)-period, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses) if sum(losses) > 0 else 0.001
    return 100 - (100 / (1 + avg_gain / avg_loss))

def find_order_blocks(klines, swing_length=3):
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
        rsi_at_ob = calculate_rsi(klines[:i+1])
        
        if is_swing_high and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] > klines[i-j]["open"]:
                    obs.append({"type": "bearish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                               "vol_ratio": vol_ratio, "rsi": rsi_at_ob, "index": i})
                    break
        
        if is_swing_low and vol_ratio > 0.5:
            for j in range(1, min(5, i+1)):
                if klines[i-j]["close"] < klines[i-j]["open"]:
                    obs.append({"type": "bullish", "top": klines[i-j]["high"], "bottom": klines[i-j]["low"],
                               "vol_ratio": vol_ratio, "rsi": rsi_at_ob, "index": i})
                    break
    return obs

def get_confidence(ob):
    high_vol = ob.get("vol_ratio", 1) > 1.2
    rsi = ob.get("rsi", 50)
    vol_ratio = ob.get("vol_ratio", 1)
    
    if ob["type"] == "bearish":
        if rsi > 65: base = 75
        elif high_vol: base = 40
        else: base = 65
    else:
        if rsi < 35: base = 37
        elif high_vol: base = 45
        else: base = 35
    
    if vol_ratio > 2.0: base += 8
    elif vol_ratio > 1.5: base += 5
    return min(base, 95)

def backtest_symbol(symbol, tf_interval, tf_label, lookback=500, swing=3):
    """
    用歷史數據回測 OB 信號
    找到 OB 後，用之後的 K 線模擬：
    - 做多：價格回到 OB 中間 → 進場，SL = OB bottom - 0.1%, TP 用 R 倍數
    - 做空：價格回到 OB 中間 → 進場，SL = OB top + 0.1%, TP 用 R 倍數
    """
    print(f"\n=== {symbol} {tf_label} (swing={swing}) ===")
    klines = get_klines(symbol, tf_interval, lookback)
    if not klines:
        print("No data")
        return []
    
    print(f"取得 {len(klines)} 根 K 線")
    
    # Find all OBs using first 80% of data, test on remaining
    split = int(len(klines) * 0.6)
    trades = []
    
    # Sliding window: find OBs and test forward
    for start in range(50, len(klines) - 30, 5):
        window = klines[max(0, start-100):start]
        obs = find_order_blocks(window, swing)
        current_price = klines[start]["close"]
        
        for ob in obs[-3:]:  # Only recent OBs
            mid = (ob["top"] + ob["bottom"]) / 2
            conf = get_confidence(ob)
            
            if ob["type"] == "bullish":
                # Check if price touches OB zone in future
                sl = ob["bottom"] * 0.999
                risk = mid - sl
                if risk <= 0: continue
                tp1 = mid + risk * 1.5
                tp2 = mid + risk * 2.5
                tp3 = mid + risk * 4.0
                
                entered = False
                for k in klines[start:start+30]:
                    if not entered:
                        if k["low"] <= mid:
                            entered = True
                            entry_price = mid
                            # Now check outcome from this candle onward
                            hit_sl = False
                            hit_tp1 = False
                            hit_tp2 = False
                            hit_tp3 = False
                            max_pnl = 0
                            
                            for fk in klines[klines.index(k):min(klines.index(k)+20, len(klines))]:
                                pnl_pct = (fk["high"] - entry_price) / entry_price * 100
                                max_pnl = max(max_pnl, pnl_pct)
                                
                                if fk["low"] <= sl:
                                    hit_sl = True
                                    break
                                if fk["high"] >= tp3:
                                    hit_tp3 = True
                                    break
                                if fk["high"] >= tp2:
                                    hit_tp2 = True
                                if fk["high"] >= tp1:
                                    hit_tp1 = True
                            
                            # Calculate PnL (40/30/30 split)
                            if hit_tp3:
                                pnl_r = 4.0
                                result = "TP3"
                            elif hit_tp2:
                                pnl_r = (1.5*0.4 + 2.5*0.3 + max_pnl/100*entry_price/risk*0.3) if risk > 0 else 0
                                result = "TP2"
                            elif hit_tp1:
                                pnl_r = (1.5*0.4 + max_pnl/100*entry_price/risk*0.6) if risk > 0 else 0
                                result = "TP1"
                            elif hit_sl:
                                pnl_r = -1.0
                                result = "SL"
                            else:
                                # Time exit
                                last_price = klines[min(klines.index(k)+19, len(klines)-1)]["close"]
                                pnl_r = (last_price - entry_price) / risk if risk > 0 else 0
                                result = "TIME"
                            
                            trades.append({
                                "symbol": symbol, "tf": tf_label, "direction": "LONG",
                                "confidence": conf, "vol_ratio": ob["vol_ratio"],
                                "rsi": ob["rsi"], "result": result, "pnl_r": pnl_r,
                                "max_pnl_pct": max_pnl
                            })
                            break
            
            elif ob["type"] == "bearish":
                sl = ob["top"] * 1.001
                risk = sl - mid
                if risk <= 0: continue
                tp1 = mid - risk * 1.5
                tp2 = mid - risk * 2.5
                tp3 = mid - risk * 4.0
                
                entered = False
                for k in klines[start:start+30]:
                    if not entered:
                        if k["high"] >= mid:
                            entered = True
                            entry_price = mid
                            hit_sl = False
                            hit_tp1 = False
                            hit_tp2 = False
                            hit_tp3 = False
                            max_pnl = 0
                            
                            for fk in klines[klines.index(k):min(klines.index(k)+20, len(klines))]:
                                pnl_pct = (entry_price - fk["low"]) / entry_price * 100
                                max_pnl = max(max_pnl, pnl_pct)
                                
                                if fk["high"] >= sl:
                                    hit_sl = True
                                    break
                                if fk["low"] <= tp3:
                                    hit_tp3 = True
                                    break
                                if fk["low"] <= tp2:
                                    hit_tp2 = True
                                if fk["low"] <= tp1:
                                    hit_tp1 = True
                            
                            if hit_tp3:
                                pnl_r = 4.0
                                result = "TP3"
                            elif hit_tp2:
                                pnl_r = (1.5*0.4 + 2.5*0.3 + max_pnl/100*entry_price/risk*0.3) if risk > 0 else 0
                                result = "TP2"
                            elif hit_tp1:
                                pnl_r = (1.5*0.4 + max_pnl/100*entry_price/risk*0.6) if risk > 0 else 0
                                result = "TP1"
                            elif hit_sl:
                                pnl_r = -1.0
                                result = "SL"
                            else:
                                last_price = klines[min(klines.index(k)+19, len(klines)-1)]["close"]
                                pnl_r = (entry_price - last_price) / risk if risk > 0 else 0
                                result = "TIME"
                            
                            trades.append({
                                "symbol": symbol, "tf": tf_label, "direction": "SHORT",
                                "confidence": conf, "vol_ratio": ob["vol_ratio"],
                                "rsi": ob["rsi"], "result": result, "pnl_r": pnl_r,
                                "max_pnl_pct": max_pnl
                            })
                            break
    
    return trades

def print_stats(trades, label=""):
    if not trades:
        print(f"{label}: 無交易")
        return
    
    wins = [t for t in trades if t["pnl_r"] > 0]
    losses = [t for t in trades if t["pnl_r"] <= 0]
    wr = len(wins)/len(trades)*100
    total_r = sum(t["pnl_r"] for t in trades)
    avg_r = total_r / len(trades)
    
    by_result = defaultdict(int)
    for t in trades:
        by_result[t["result"]] += 1
    
    print(f"\n{label} ({len(trades)} 筆)")
    print(f"  勝率: {wr:.1f}% ({len(wins)}W/{len(losses)}L)")
    print(f"  總 R: {total_r:+.1f}R | 平均: {avg_r:+.2f}R")
    print(f"  結果: {dict(by_result)}")
    
    # By direction
    for d in ["LONG", "SHORT"]:
        dt = [t for t in trades if t["direction"] == d]
        if dt:
            dw = len([t for t in dt if t["pnl_r"] > 0])
            print(f"  {d}: {dw}/{len(dt)} = {dw/len(dt)*100:.0f}% | R={sum(t['pnl_r'] for t in dt):+.1f}")
    
    # By confidence bucket
    for lo, hi, label_c in [(0,40,"低信心<40"),(40,60,"中信心40-60"),(60,100,"高信心≥60")]:
        ct = [t for t in trades if lo <= t["confidence"] < hi]
        if ct:
            cw = len([t for t in ct if t["pnl_r"] > 0])
            print(f"  {label_c}: {cw}/{len(ct)} = {cw/len(ct)*100:.0f}% | R={sum(t['pnl_r'] for t in ct):+.1f}")

def main():
    all_trades = []
    
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        for interval, label, lookback, swing in [
            ("15m", "15M", 500, 2),
            ("1h", "1H", 500, 3),
            ("4h", "4H", 500, 3),
        ]:
            trades = backtest_symbol(symbol, interval, label, lookback, swing)
            all_trades.extend(trades)
            print_stats(trades, f"{symbol} {label}")
    
    print("\n" + "="*50)
    print_stats(all_trades, "📊 全部合計")
    
    # By timeframe
    for tf in ["15M", "1H", "4H"]:
        tf_trades = [t for t in all_trades if t["tf"] == tf]
        print_stats(tf_trades, f"  {tf}")

if __name__ == "__main__":
    main()
