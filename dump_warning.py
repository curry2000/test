"""
暴跌預警系統
偵測高位背離、假突破、量能枯竭等預警信號
"""
import os
import json
import time
from datetime import datetime

# 使用共用模組
from config import (
    DUMP_WARNING_STATE_FILE,
    TW_TIMEZONE
)
from exchange_api import get_klines, get_all_tickers
from notify import send_discord_message


def load_state():
    """載入狀態"""
    try:
        with open(DUMP_WARNING_STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    """儲存狀態"""
    os.makedirs(os.path.dirname(DUMP_WARNING_STATE_FILE), exist_ok=True)
    with open(DUMP_WARNING_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def calc_rsi_series(closes, period=14):
    """計算 RSI 序列"""
    if len(closes) < period+1:
        return [50]*len(closes)
    
    rsis = [50]*period
    gains, losses = [], []
    
    for i in range(1, period+1):
        d = closes[i]-closes[i-1]
        gains.append(d if d>0 else 0)
        losses.append(-d if d<0 else 0)
    
    ag = sum(gains)/period
    al = sum(losses)/period
    
    for i in range(period, len(closes)):
        d = closes[i]-closes[i-1]
        g = d if d>0 else 0
        l = -d if d<0 else 0
        ag = (ag*(period-1)+g)/period
        al = (al*(period-1)+l)/period
        rsis.append(100 if al==0 else 100-(100/(1+ag/al)))
    
    return rsis


def get_top_coins(limit=50):
    """取得交易量前 N 名的幣種"""
    try:
        tickers = get_all_tickers()
        if not tickers:
            return []
        
        # 按交易量排序
        tickers.sort(key=lambda x: x.get("volume_24h", 0), reverse=True)
        
        return [t["symbol"] for t in tickers[:limit]]
    except:
        return []


def scan_coin(symbol, candles_1h_map=None):
    """掃描單個幣種的下跌預警信號"""
    # 取得 5 分鐘 K 線
    klines = get_klines(symbol, "5m", 60)
    if not klines or len(klines) < 40:
        return None
    
    # 轉換格式
    c5 = [{"t": k["open_time"], "o": k["open"], "h": k["high"],
           "l": k["low"], "c": k["close"], "v": k["volume"]} for k in klines]

    closes = [c["c"] for c in c5]
    highs = [c["h"] for c in c5]
    volumes = [c["v"] for c in c5]
    rsis = calc_rsi_series(closes)

    i = len(c5) - 1
    rsi_now = rsis[i]
    price_now = closes[i]

    # 過濾：只看 RSI > 65 的（高位）
    if rsi_now < 65:
        return None

    score = 0
    signals = []
    lb = min(36, i)

    # 檢查 RSI 背離
    w_rsi = rsis[max(0,i-lb):i+1]
    w_high = highs[max(0,i-lb):i+1]

    if len(w_rsi) > 6:
        rsi_peak_val = max(w_rsi)
        rsi_peak_idx = w_rsi.index(rsi_peak_val)
        price_peak_idx = w_high.index(max(w_high))

        if price_peak_idx > rsi_peak_idx + 3 and rsi_peak_val - w_rsi[price_peak_idx] > 8:
            div = rsi_peak_val - w_rsi[price_peak_idx]
            if div > 15:
                score += 40
                signals.append(f"RSI強背離(差{div:.0f})")
            else:
                score += 25
                signals.append(f"RSI背離(差{div:.0f})")

    # 檢查假突破（長上影線）
    for c in c5[-7:]:
        wick = (c["h"] - max(c["o"],c["c"])) / c["o"] * 100
        body = abs(c["c"]-c["o"])/c["o"]*100
        if wick > 3 and body < 1:
            score += 30
            signals.append(f"假突破(影{wick:.1f}%)")
            break
        elif wick > 2 and c["c"] < c["o"]:
            score += 20
            signals.append(f"沖高回落(影{wick:.1f}%)")
            break

    # 檢查量能枯竭
    if i >= 12:
        first = sum(volumes[i-12:i-6])/6
        second = sum(volumes[i-6:i+1])/7
        if first > 0:
            ratio = second/first
            if ratio < 0.35:
                score += 25
                signals.append(f"量枯竭({ratio:.2f}x)")
            elif ratio < 0.5:
                score += 15
                signals.append(f"量萎縮({ratio:.2f}x)")

    # 檢查連續紅 K
    red_count = sum(1 for j in range(max(0,i-4),i+1) if c5[j]["c"] < c5[j]["o"])
    if red_count >= 4:
        score += 25
        signals.append(f"連{red_count}紅K")
    elif red_count >= 3:
        drop = (c5[i-2]["o"]-closes[i])/c5[i-2]["o"]*100
        if drop > 2:
            score += 15
            signals.append(f"連3紅跌{drop:.1f}%")

    # RSI 極高
    if rsi_now > 85:
        score += 15
        signals.append(f"RSI極高{rsi_now:.0f}")
    elif rsi_now > 75:
        score += 8

    # 高位盤整
    if i >= 24:
        rng_h = max(closes[i-24:i+1])
        rng_l = min(closes[i-24:i+1])
        if rng_h > 0 and (rng_h-rng_l)/rng_h*100 < 3 and rsi_now > 70:
            score += 15
            signals.append("高位盤整")

    # 1H RSI 檢查
    c1h = candles_1h_map.get(symbol) if candles_1h_map else None
    if not c1h:
        klines_1h = get_klines(symbol, "1h", 30)
        if klines_1h:
            c1h = [{"c": k["close"]} for k in klines_1h]
    
    if c1h and len(c1h) > 15:
        rsi_1h = calc_rsi_series([c["c"] for c in c1h])
        if len(rsi_1h) >= 3:
            r1h = rsi_1h[-1]
            r1h_p = rsi_1h[-3]
            if r1h < r1h_p - 5 and r1h > 55:
                score += 20
                signals.append(f"1H RSI轉弱({r1h_p:.0f}→{r1h:.0f})")
            elif r1h > 80:
                score += 10
                signals.append(f"1H超買{r1h:.0f}")

    # 評級
    if score >= 55 and len(signals) >= 2:
        name = symbol.replace("USDT", "")
        grade = ""
        emoji = ""
        if score >= 75:
            grade = "高危"
            emoji = "🔴"
        elif score >= 60:
            grade = "警戒"
            emoji = "🟡"
        else:
            grade = "注意"
            emoji = "⚠️"

        return {
            "symbol": name,
            "price": price_now,
            "rsi": rsi_now,
            "score": score,
            "grade": grade,
            "emoji": emoji,
            "signals": signals
        }

    return None


def get_btc_trend():
    """判斷 BTC 大盤趨勢 (4H RSI)"""
    try:
        klines = get_klines("BTC", "4h", 20)
        if not klines or len(klines) < 15:
            return "neutral", 50
        closes = [k["close"] for k in klines]
        rsis = calc_rsi_series(closes)
        rsi = rsis[-1] if rsis else 50
        if rsi > 55:
            return "bullish", rsi
        elif rsi < 45:
            return "bearish", rsi
        return "neutral", rsi
    except:
        return "neutral", 50


def main():
    """主程序"""
    now = datetime.now(TW_TIMEZONE)
    state = load_state()

    # 判斷大盤趨勢
    btc_trend, btc_rsi = get_btc_trend()
    print(f"BTC trend: {btc_trend} (4H RSI: {btc_rsi:.0f})")

    # 取得交易量前 80 的幣種
    coins = get_top_coins(80)
    if not coins:
        print("Failed to get coin list")
        return

    print(f"Scanning {len(coins)} coins for dump warnings...")

    # 取得所有幣種的 24H 價格變化
    try:
        all_tickers = get_all_tickers()
        price_changes = {}
        for t in all_tickers:
            price_changes[t["symbol"]] = t.get("price_change_pct", 0)
    except:
        price_changes = {}

    # 預篩選：優先掃描 24H 漲幅 > 10% 的幣種
    candidates = []
    for sym in coins:
        chg = price_changes.get(sym, 0)
        if chg > 10:
            candidates.append(sym)

    if not candidates:
        candidates = coins[:20]

    print(f"  Pre-filter: {len(candidates)} coins with 24H change > 10%")

    # 掃描每個幣種
    dump_alerts = []
    momentum_alerts = []
    
    for sym in candidates:
        try:
            result = scan_coin(sym)
            if result:
                key = f"{result['symbol']}_dump"
                last = state.get(key, "")
                
                # 檢查冷卻時間（1小時）
                if last:
                    try:
                        lt = datetime.fromisoformat(last)
                        if (now - lt).total_seconds() < 3600:
                            print(f"  {result['symbol']}: 1H內已通知，跳過")
                            continue
                    except:
                        pass

                # 根據大盤趨勢分類
                chg_24h = price_changes.get(sym, 0)
                if btc_trend == "bullish" and chg_24h > 10:
                    # 大盤漲 + 幣漲超過 10% = 強勢回調候選
                    result["momentum"] = True
                    result["change_24h"] = chg_24h
                    momentum_alerts.append(result)
                else:
                    result["momentum"] = False
                    dump_alerts.append(result)
                
                state[key] = now.isoformat()
                tag = "📈" if result["momentum"] else result["emoji"]
                print(f"  {tag} {result['symbol']} ${result['price']:.4f} 分{result['score']} {result['grade']} | {', '.join(result['signals'])}")
            
            time.sleep(0.1)  # Rate limit
        except Exception as e:
            print(f"  {sym} error: {e}")

    # 發送下跌預警（大盤弱勢或中性時）
    if dump_alerts:
        dump_alerts.sort(key=lambda x: x["score"], reverse=True)
        lines = [f"⚠️ **下跌預警** | {now.strftime('%m/%d %H:%M')}\n"]
        for a in dump_alerts[:8]:
            sig_text = " + ".join(a["signals"][:3])
            lines.append(
                f"{a['emoji']} **{a['symbol']}** ${a['price']:,.4f} | "
                f"分數 {a['score']} ({a['grade']}) | RSI {a['rsi']:.0f}\n"
                f"  → {sig_text}"
            )
        lines.append("\n💡 預警≠做空信號，建議：有多單先收利潤/移止損")
        msg = "\n".join(lines)
        print(f"\n{msg}")
        send_discord_message(msg)

    # 發送強勢回調候選（大盤上漲時）
    if momentum_alerts:
        momentum_alerts.sort(key=lambda x: x["score"], reverse=True)
        lines = [f"📈 **強勢回調候選** | {now.strftime('%m/%d %H:%M')} | BTC 4H RSI {btc_rsi:.0f}\n"]
        for a in momentum_alerts[:8]:
            sig_text = " + ".join(a["signals"][:3])
            lines.append(
                f"🔥 **{a['symbol']}** ${a['price']:,.4f} | "
                f"24H +{a.get('change_24h', 0):.0f}% | RSI {a['rsi']:.0f}\n"
                f"  → {sig_text}\n"
                f"  💡 強勢幣短暫修正，觀察是否回調做多"
            )
        lines.append(f"\n⚡ 大盤偏多(RSI {btc_rsi:.0f})，這些幣的「弱勢信號」可能是回調買點")
        msg = "\n".join(lines)
        print(f"\n{msg}")
        send_discord_message(msg)

    if not dump_alerts and not momentum_alerts:
        print("No alerts")

    save_state(state)


if __name__ == "__main__":
    main()
