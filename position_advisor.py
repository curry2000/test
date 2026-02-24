"""
倉位監控與建議系統
監控多個倉位的風險狀態，提供加倉/減倉建議
"""
import os
import numpy as np
from datetime import datetime

# 使用共用模組
from config import (
    POSITIONS,
    POSITION_ALERT_LEVELS,
    TW_TIMEZONE
)
from exchange_api import get_price, get_klines
from notify import send_discord_message, DISCORD_WEBHOOK_URL
from ob_engine import find_order_blocks_v2, filter_and_rank_obs, score_ob


def calc_rsi(klines):
    """計算 RSI"""
    if len(klines) < 15:
        return 50
    closes = [k["close"] for k in klines]
    gains, losses = [], []
    for i in range(1, min(15, len(closes))):
        diff = closes[i] - closes[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses) if sum(losses) > 0 else 0.001
    return 100 - (100 / (1 + avg_gain / avg_loss))


def analyze_levels(symbol):
    """分析多時間週期的支撐/壓力 (V2: 含失效過濾)"""
    result = {}
    for interval, label, swing in [("1h","1H",3), ("4h","4H",3), ("1d","1D",3)]:
        klines = get_klines(symbol, interval if "h" in interval else "1D", 100)
        if not klines:
            continue
        
        current = klines[-1]["close"]
        rsi = calc_rsi(klines)
        
        # V2 OB 偵測
        raw_obs = find_order_blocks_v2(klines, swing)
        bull_obs, bear_obs = filter_and_rank_obs(raw_obs, current, tf=label, max_distance_pct=5.0)
        
        recent = klines[-24:] if len(klines) >= 24 else klines
        support = min(k["low"] for k in recent)
        resistance = max(k["high"] for k in recent)
        
        result[label] = {
            "rsi": rsi,
            "support": support,
            "resistance": resistance,
            "bull_ob": bull_obs[0] if bull_obs else None,
            "bear_ob": bear_obs[0] if bear_obs else None
        }
    return result


def get_action_advice(pos, price, levels):
    """根據倉位狀態和技術分析給出建議"""
    entry = pos["entry"]
    liq = pos["liquidation"]
    pnl_pct = (price - entry) / entry * 100
    liq_dist = (price - liq) / price * 100
    
    leverage = pos.get("leverage", 20)
    margin = pos.get("margin", 0)
    quantity = pos.get("quantity", 0)
    margin_coin = pos.get("margin_coin", 0)
    margin_unit = pos.get("margin_unit", "USDT")
    
    if margin_coin > 0:
        # 幣本位：保證金是幣，PnL 也是幣
        unrealized_coin = quantity * (price - entry) / price if pos["direction"] == "LONG" else quantity * (entry - price) / price
        pnl_vs_margin = abs(unrealized_coin) / margin_coin
        margin_usd = margin_coin * price
        unrealized_pnl = unrealized_coin * price
    elif quantity > 0 and margin > 0:
        # U本位：用真實持倉量和保證金計算
        unrealized_pnl = quantity * (price - entry) if pos["direction"] == "LONG" else quantity * (entry - price)
        pnl_vs_margin = abs(unrealized_pnl) / margin
    elif margin > 0:
        position_value = margin * leverage
        unrealized_pnl = position_value * pnl_pct / 100
        pnl_vs_margin = abs(unrealized_pnl) / margin
    else:
        pnl_vs_margin = abs(pnl_pct) * leverage / 100  # fallback
    
    # 風險評級
    if liq_dist < POSITION_ALERT_LEVELS["danger"] or (pnl_vs_margin > 5 and leverage >= 20):
        risk = "🔴高風險"
    elif liq_dist < POSITION_ALERT_LEVELS["caution"] or (pnl_vs_margin > 3 and leverage >= 20):
        risk = "🟡中風險"
    else:
        risk = "🟢低風險"
    
    # 額外標註真實槓桿風險
    if pnl_vs_margin > 5:
        risk += f" ⚠️虧損={pnl_vs_margin:.1f}x保證金"
    
    advice = []
    
    rsi_4h = levels.get("4H", {}).get("rsi", 50)
    rsi_1h = levels.get("1H", {}).get("rsi", 50)
    
    bull_1h = levels.get("1H", {}).get("bull_ob")
    bull_4h = levels.get("4H", {}).get("bull_ob")
    bear_1h = levels.get("1H", {}).get("bear_ob")
    bear_4h = levels.get("4H", {}).get("bear_ob")
    
    # 止損參考
    stop_zone = None
    if bull_4h:
        stop_zone = bull_4h["bottom"]
    elif bull_1h:
        stop_zone = bull_1h["bottom"]
    
    # 虧損較大的情況
    if pnl_pct < -15 and pos.get("leverage", 20) >= 30:
        advice.append("⚠️ 虧損大+高槓桿，不建議再加倉")
        advice.append("💡 等反彈到壓力區考慮減倉降風險")
        
        if bear_1h:
            dist = abs(price - bear_1h["bottom"]) / price * 100
            advice.append(f"🎯 減倉目標: ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f} ({dist:.1f}%)")
        if bear_4h:
            advice.append(f"🎯 4H減倉目標: ${bear_4h['bottom']:,.0f}-${bear_4h['top']:,.0f}")
        
        if rsi_4h < 25:
            advice.append("📊 4H RSI超賣，可能短線反彈，可等反彈後減倉")
        
        if stop_zone:
            advice.append(f"🛑 止損參考: 跌破 ${stop_zone:,.0f}")
        
        advice.append("💡 虧損較大，嚴格控制風險")
    
    # 正常情況
    else:
        add_zone = None
        if bull_4h:
            mid = (bull_4h["top"] + bull_4h["bottom"]) / 2
            dist = (price - mid) / price * 100
            if pnl_pct < 0:  # 只在虧損時建議補倉
                if dist < 3:
                    add_zone = bull_4h
                    advice.append(f"📍 接近4H OB支撐 ${bull_4h['bottom']:,.0f}-${bull_4h['top']:,.0f}，可小量補倉")
                elif dist < 5:
                    add_zone = bull_4h
                    advice.append(f"👀 4H OB支撐在 ${bull_4h['bottom']:,.0f}-${bull_4h['top']:,.0f}，等回調到此區再補")
            else:
                advice.append(f"📍 4H OB支撐 ${bull_4h['bottom']:,.0f}-${bull_4h['top']:,.0f}（回調防守位）")
        
        if bull_1h and not add_zone:
            mid = (bull_1h["top"] + bull_1h["bottom"]) / 2
            dist = (price - mid) / price * 100
            if dist < 2 and pnl_pct < 0:
                advice.append(f"📍 接近1H OB支撐 ${bull_1h['bottom']:,.0f}-${bull_1h['top']:,.0f}，可小量補倉")
        
        if stop_zone:
            advice.append(f"🛑 止損參考: 跌破 ${stop_zone:,.0f} (4H OB破)")
        
        if bear_1h:
            dist = abs(price - bear_1h["bottom"]) / price * 100
            if dist < 2:
                advice.append(f"⚠️ 接近1H壓力 ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f}，考慮部分減倉鎖利")
            else:
                advice.append(f"🎯 上方壓力: ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f}")
        
        if bear_4h:
            advice.append(f"🎯 4H壓力: ${bear_4h['bottom']:,.0f}-${bear_4h['top']:,.0f}")
        
        if rsi_4h < 25:
            advice.append("📊 4H RSI超賣，可能反彈")
        elif rsi_4h > 75:
            advice.append("📊 4H RSI超買，小心回調")
        
        if rsi_1h < 30:
            advice.append("📊 1H RSI超賣，短線可能反彈")
        elif rsi_1h > 70:
            advice.append("📊 1H RSI超買，短線注意回調")
        
        if pnl_pct > 5:
            advice.append("💰 盈利中，可設追蹤止盈保護利潤")
            if bear_1h:
                advice.append(f"🎯 止盈目標: ${bear_1h['bottom']:,.0f}-${bear_1h['top']:,.0f}")
        elif pnl_pct > 0:
            advice.append("💡 小幅盈利，持有觀察")
        elif pnl_pct > -3:
            advice.append("💡 接近回本，耐心持有")
        elif pnl_pct > -10:
            advice.append("💡 虧損可控，等待反彈")
    
    return {
        "name": pos["name"],
        "price": price,
        "entry": entry,
        "pnl_pct": pnl_pct,
        "liq": liq,
        "liq_dist": liq_dist,
        "risk": risk,
        "rsi_1h": rsi_1h,
        "rsi_4h": rsi_4h,
        "advice": advice,
        "levels": levels
    }


def format_message(results):
    """格式化輸出訊息"""
    now = datetime.now(TW_TIMEZONE).strftime("%m/%d %H:%M")
    
    lines = [f"💼 **倉位建議 [BN本地]** | {now}", ""]
    
    for r in results:
        pnl_emoji = "🟢" if r["pnl_pct"] >= 0 else "🔴"
        
        lines.append(f"**{r['name']}** {pnl_emoji}{r['pnl_pct']:+.1f}% | {r['risk']}")
        lines.append(f"現價 ${r['price']:,.2f} | 均價 ${r['entry']:,.2f} | 清算 ${r['liq']:,.0f} ({r['liq_dist']:.0f}%)")
        lines.append(f"RSI → 1H: {r['rsi_1h']:.0f} | 4H: {r['rsi_4h']:.0f}")
        
        # 顯示各週期的 OB
        for tf in ["1H", "4H", "1D"]:
            lv = r["levels"].get(tf, {})
            bull = lv.get("bull_ob")
            bear = lv.get("bear_ob")
            parts = []
            if bull:
                parts.append(f"🟢${bull['bottom']:,.0f}-${bull['top']:,.0f}")
            if bear:
                parts.append(f"🔴${bear['bottom']:,.0f}-${bear['top']:,.0f}")
            if parts:
                lines.append(f"  [{tf}] {' | '.join(parts)}")
        
        lines.append("")
        for a in r["advice"]:
            lines.append(f"  {a}")
        lines.append("")
    
    return "\n".join(lines)


def main():
    """主程序"""
    print("=== Position Advisor Start ===")
    
    # 取得所有需要的價格
    prices = {}
    for symbol in set(p["symbol"] for p in POSITIONS):
        price = get_price(symbol)
        if price:
            prices[symbol] = price
            print(f"{symbol}: ${price:,.2f}")
        else:
            print(f"{symbol}: 無法取得價格")
    
    # 分析每個倉位
    results = []
    for pos in POSITIONS:
        price = prices.get(pos["symbol"], 0)
        if price > 0:
            print(f"分析 {pos['name']}...")
            levels = analyze_levels(pos["symbol"])
            result = get_action_advice(pos, price, levels)
            results.append(result)
    
    # 智能通知: 共用 monitor 的 notify_state，波動 >2% 即時，否則 30 分鐘
    import json as _json
    ADVISOR_NOTIFY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "advisor_notify_state.json")
    ADVISOR_INTERVAL = 1800  # 30 分鐘
    ADVISOR_VOL_THRESHOLD = 2.0
    
    try:
        with open(ADVISOR_NOTIFY_FILE) as _f:
            _state = _json.load(_f)
    except:
        _state = {}
    
    _now = datetime.now(TW_TIMEZONE).timestamp()
    _last = _state.get("last_ts", 0)
    _last_prices = _state.get("prices", {})
    _elapsed = _now - _last
    
    _high_vol = False
    for r in results:
        prev = _last_prices.get(r["name"], 0)
        if prev > 0:
            change = abs(r["price"] - prev) / prev * 100
            if change >= ADVISOR_VOL_THRESHOLD:
                _high_vol = True
    
    _should_send = _high_vol or _elapsed >= ADVISOR_INTERVAL
    
    if _should_send:
        _state["last_ts"] = _now
        _state["prices"] = {r["name"]: r["price"] for r in results}
        with open(ADVISOR_NOTIFY_FILE, "w") as _f:
            _json.dump(_state, _f)
    
    if results and _should_send:
        message = format_message(results)
        if _high_vol:
            message = "🚨 波動警報\n\n" + message
        print("\n" + message)
        send_discord_message(message, webhook_url=DISCORD_WEBHOOK_URL)
    elif results:
        print(f"[靜默] 距上次 {_elapsed:.0f}s/{ADVISOR_INTERVAL}s, 無大波動")


if __name__ == "__main__":
    main()
