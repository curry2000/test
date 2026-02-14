import requests
import json
import os
from datetime import datetime, timezone, timedelta

STATE_FILE = os.path.expanduser("~/.openclaw/paper_state.json")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

CONFIG = {
    "capital": 10000,
    "leverage": 5,
    "position_pct": 10,
    "max_positions": 10,
    "sl_pct": 10,
    "tp1_pct": 5,
    "tp2_pct": 10,
    "time_exit_hours": 6
}

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"positions": [], "closed": [], "capital": CONFIG["capital"]}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_price(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}USDT"
        r = requests.get(url, timeout=5)
        return float(r.json()["price"])
    except:
        return None

def get_dynamic_tp(strength_grade="", vol_ratio=1.0):
    if "S" in strength_grade:
        tp1, tp2, sl = 3, 7, 7
    elif "A" in strength_grade:
        tp1, tp2, sl = 2, 4, 8
    elif "B" in strength_grade:
        tp1, tp2, sl = 3, 5, 9
    else:
        tp1, tp2, sl = 5, 10, 10
    
    if vol_ratio >= 3:
        tp1 *= 1.5
        tp2 *= 1.8
    elif vol_ratio >= 2:
        tp1 *= 1.3
        tp2 *= 1.5
    elif vol_ratio >= 1.5:
        tp1 *= 1.1
        tp2 *= 1.2
    
    return round(tp1, 1), round(tp2, 1), sl

def should_open_position(signal, phase, rsi, strength_grade="", vol_ratio=0):
    if signal == "LONG":
        if rsi >= 80 and "⚠️" in phase:
            return False, f"RSI {rsi:.0f} 極端超買+高位，跳過"
        if rsi >= 60:
            return True, f"RSI {rsi:.0f} 強勢追多"
        if "🌱" in phase:
            return True, "啟動初期"
        return True, "符合條件"
    
    elif signal == "SHORT":
        if rsi <= 40:
            return True, f"RSI {rsi:.0f} 弱勢追空"
        return False, f"RSI {rsi:.0f} 未進入弱勢區，不做空"
    
    return True, "符合條件"

def open_position(state, symbol, signal, entry_price, phase, rsi, strength_grade="", vol_ratio=0):
    if len(state["positions"]) >= CONFIG["max_positions"]:
        return None, "已達最大持倉數"
    
    for p in state["positions"]:
        if p["symbol"] == symbol:
            return None, "已有持倉"
    
    should_open, reason = should_open_position(signal, phase, rsi, strength_grade, vol_ratio)
    if not should_open:
        return None, f"不開倉: {reason}"
    
    position_size = state["capital"] * CONFIG["position_pct"] / 100 * CONFIG["leverage"]
    
    tp1_pct, tp2_pct, sl_pct = get_dynamic_tp(strength_grade, vol_ratio)
    
    if signal == "LONG":
        sl = entry_price * (1 - sl_pct / 100)
        tp1 = entry_price * (1 + tp1_pct / 100)
        tp2 = entry_price * (1 + tp2_pct / 100)
    else:
        sl = entry_price * (1 + sl_pct / 100)
        tp1 = entry_price * (1 - tp1_pct / 100)
        tp2 = entry_price * (1 - tp2_pct / 100)
    
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    
    position = {
        "symbol": symbol,
        "direction": signal,
        "entry_price": entry_price,
        "size": position_size,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp1_hit": False,
        "entry_time": now.isoformat(),
        "phase": phase,
        "rsi": rsi
    }
    
    state["positions"].append(position)
    save_state(state)
    
    return position, reason

def check_positions(state):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    
    closed = []
    remaining = []
    
    for pos in state["positions"]:
        symbol = pos["symbol"]
        current_price = get_price(symbol)
        
        if not current_price:
            remaining.append(pos)
            continue
        
        entry_time = datetime.fromisoformat(pos["entry_time"])
        hours_held = (now - entry_time).total_seconds() / 3600
        
        exit_reason = None
        exit_price = current_price
        
        tp2_hit = pos.get("tp2_hit", False)
        trailing_sl = pos.get("trailing_sl", 0)
        remaining_pct = pos.get("remaining_pct", 100)
        
        if pos["direction"] == "LONG":
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
            
            if tp2_hit:
                if trailing_sl > 0 and current_price <= trailing_sl:
                    exit_reason = "TRAIL"
                else:
                    new_trail = current_price * 0.95
                    if new_trail > trailing_sl:
                        pos["trailing_sl"] = new_trail
            elif current_price <= pos["sl"]:
                exit_reason = "SL"
            elif current_price >= pos["tp2"] and not tp2_hit:
                pos["tp2_hit"] = True
                pos["trailing_sl"] = current_price * 0.95
                tp2_pnl = pnl_pct
                tp2_usd = pos["size"] * 0.7 * tp2_pnl / 100
                state["capital"] += tp2_usd
                pos["size"] = pos["size"] * 0.3
                pos["remaining_pct"] = 30
                closed.append({
                    "symbol": symbol, "direction": pos["direction"],
                    "entry": pos["entry_price"], "exit": exit_price,
                    "pnl_pct": tp2_pnl, "pnl_usd": tp2_usd,
                    "reason": "TP2(70%平)", "phase": pos["phase"],
                    "closed_at": now.isoformat()
                })
                state["closed"].append(closed[-1])
            elif current_price >= pos["tp1"] and not pos.get("tp1_hit"):
                pos["tp1_hit"] = True
                pos["sl"] = pos["entry_price"]
        else:
            pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100
            
            if tp2_hit:
                if trailing_sl > 0 and current_price >= trailing_sl:
                    exit_reason = "TRAIL"
                else:
                    new_trail = current_price * 1.05
                    if trailing_sl == 0 or new_trail < trailing_sl:
                        pos["trailing_sl"] = new_trail
            elif current_price >= pos["sl"]:
                exit_reason = "SL"
            elif current_price <= pos["tp2"] and not tp2_hit:
                pos["tp2_hit"] = True
                pos["trailing_sl"] = current_price * 1.05
                tp2_pnl = pnl_pct
                tp2_usd = pos["size"] * 0.7 * tp2_pnl / 100
                state["capital"] += tp2_usd
                pos["size"] = pos["size"] * 0.3
                pos["remaining_pct"] = 30
                closed.append({
                    "symbol": symbol, "direction": pos["direction"],
                    "entry": pos["entry_price"], "exit": exit_price,
                    "pnl_pct": tp2_pnl, "pnl_usd": tp2_usd,
                    "reason": "TP2(70%平)", "phase": pos["phase"],
                    "closed_at": now.isoformat()
                })
                state["closed"].append(closed[-1])
            elif current_price <= pos["tp1"] and not pos.get("tp1_hit"):
                pos["tp1_hit"] = True
                pos["sl"] = pos["entry_price"]
        
        if not tp2_hit and hours_held >= CONFIG["time_exit_hours"] and not exit_reason:
            exit_reason = "TIME"
        if tp2_hit and hours_held >= CONFIG["time_exit_hours"] * 2 and not exit_reason:
            exit_reason = "TIME(尾倉)"
        
        if exit_reason:
            pnl_usd = pos["size"] * pnl_pct / 100
            state["capital"] += pnl_usd
            
            trail_tag = f"(尾倉{remaining_pct}%)" if tp2_hit else ""
            closed.append({
                "symbol": symbol,
                "direction": pos["direction"],
                "entry": pos["entry_price"],
                "exit": exit_price,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "reason": f"{exit_reason}{trail_tag}",
                "phase": pos["phase"],
                "closed_at": now.isoformat()
            })
            
            state["closed"].append(closed[-1])
        else:
            remaining.append(pos)
    
    state["positions"] = remaining
    save_state(state)
    
    return closed

def get_summary(state):
    closed = state["closed"]
    positions = state.get("positions", [])
    
    wins = [t for t in closed if t["pnl_pct"] > 0]
    losses = [t for t in closed if t["pnl_pct"] <= 0]
    total_win_usd = sum(t["pnl_usd"] for t in wins)
    total_loss_usd = sum(t["pnl_usd"] for t in losses)
    total_pnl_pct = sum(t["pnl_pct"] for t in closed)
    total_pnl_usd = sum(t["pnl_usd"] for t in closed)
    
    unrealized_pnl = 0
    for p in positions:
        current = get_price(p["symbol"])
        if current:
            if p["direction"] == "LONG":
                pnl = (current - p["entry_price"]) / p["entry_price"] * 100
            else:
                pnl = (p["entry_price"] - current) / p["entry_price"] * 100
            unrealized_pnl += p["size"] * pnl / 100
    
    return {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100 if closed else 0,
        "total_pnl_pct": total_pnl_pct,
        "total_pnl_usd": total_pnl_usd,
        "total_win_usd": total_win_usd,
        "total_loss_usd": total_loss_usd,
        "capital": state["capital"],
        "return_pct": (state["capital"] - CONFIG["capital"]) / CONFIG["capital"] * 100,
        "open_positions": len(positions),
        "unrealized_pnl": unrealized_pnl
    }

def format_trade_msg(action, data):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    if action == "OPEN":
        pos, reason = data
        emoji = "🟢" if pos["direction"] == "LONG" else "🔴"
        return f"""📝 **模擬開倉** | {now}

{emoji} **{pos['symbol']}** {pos['direction']}
• 進場: ${pos['entry_price']:.4g}
• 倉位: ${pos['size']:.0f}
• SL: ${pos['sl']:.4g} | TP1: ${pos['tp1']:.4g}
• 階段: {pos['phase']} | RSI: {pos['rsi']:.0f}
• 理由: {reason}"""
    
    elif action == "CLOSE":
        t = data
        emoji = "✅" if t["pnl_pct"] > 0 else "❌"
        return f"""📊 **模擬平倉** | {now}

{emoji} **{t['symbol']}** {t['direction']}
• 進場: ${t['entry']:.4g} → 出場: ${t['exit']:.4g}
• 盈虧: {t['pnl_pct']:+.2f}% (${t['pnl_usd']:+.2f})
• 原因: {t['reason']}"""
    
    elif action == "SUMMARY":
        s = data
        avg_win = s['total_win_usd'] / s['wins'] if s['wins'] > 0 else 0
        avg_loss = s['total_loss_usd'] / s['losses'] if s['losses'] > 0 else 0
        profit_factor = abs(s['total_win_usd'] / s['total_loss_usd']) if s['total_loss_usd'] != 0 else 0
        
        return f"""📈 **模擬交易報告**

💰 **帳戶**
• 初始本金: ${CONFIG['capital']:,.0f}
• 目前餘額: ${s['capital']:,.0f}
• 報酬率: {s['return_pct']:+.2f}%

📊 **已平倉統計** ({s['total_trades']} 筆)
• 勝/敗: {s['wins']}/{s['losses']} | 勝率: {s['win_rate']:.1f}%
• 已實現盈虧: ${s['total_pnl_usd']:+.2f}
• 總獲利: ${s['total_win_usd']:+.2f} (均 ${avg_win:+.1f}/筆)
• 總虧損: ${s['total_loss_usd']:+.2f} (均 ${avg_loss:+.1f}/筆)
• 盈虧比: {profit_factor:.2f}

📍 **持倉中** ({s['open_positions']} 筆)
• 未實現盈虧: ${s['unrealized_pnl']:+.2f}"""

def send_discord(msg):
    if not DISCORD_WEBHOOK or not msg:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except:
        pass

def process_signal(symbol, signal, price, phase, rsi, strength_score=0, strength_grade="", vol_ratio=1):
    state = load_state()
    
    pos, reason = open_position(state, symbol, signal, price, phase, rsi, strength_grade, vol_ratio)
    
    if pos:
        pos["strength_score"] = strength_score
        pos["strength_grade"] = strength_grade
        pos["vol_ratio"] = vol_ratio
        save_state(state)
        msg = format_trade_msg("OPEN", (pos, reason))
        print(msg)
        send_discord(msg)
        return True, reason
    else:
        print(f"⏭️ {symbol}: {reason}")
        return False, reason

def check_and_close():
    state = load_state()
    closed = check_positions(state)
    
    for t in closed:
        msg = format_trade_msg("CLOSE", t)
        print(msg)
        send_discord(msg)
    
    return closed

def show_status():
    state = load_state()
    
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%m/%d %H:%M")
    
    summary = get_summary(state)
    lines = [format_trade_msg("SUMMARY", summary)]
    
    if state["positions"]:
        lines.append("")
        lines.append("**持倉明細：**")
        for p in state["positions"]:
            current = get_price(p["symbol"])
            if current:
                if p["direction"] == "LONG":
                    pnl = (current - p["entry_price"]) / p["entry_price"] * 100
                else:
                    pnl = (p["entry_price"] - current) / p["entry_price"] * 100
                emoji = "📈" if pnl > 0 else "📉"
                pnl_usd = p["size"] * pnl / 100
                dir_emoji = "🟢" if p["direction"] == "LONG" else "🔴"
                lines.append(f"• {dir_emoji} {p['symbol']} {p['direction']}: ${p['entry_price']:.4g} → ${current:.4g} ({pnl:+.1f}% ${pnl_usd:+.1f}) {emoji}")
    
    if state["closed"]:
        lines.append("")
        lines.append(f"**最近平倉 (近5筆)：**")
        for t in state["closed"][-5:]:
            emoji = "✅" if t["pnl_pct"] > 0 else "❌"
            lines.append(f"• {emoji} {t['symbol']} {t['direction']} | {t['reason']} | {t['pnl_pct']:+.2f}% (${t['pnl_usd']:+.1f})")
    
    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "check":
            check_and_close()
        elif sys.argv[1] == "status":
            result = show_status()
            print(result)
            if "--send" in sys.argv:
                send_discord(result)
        elif sys.argv[1] == "reset":
            save_state({"positions": [], "closed": [], "capital": CONFIG["capital"]})
            print("已重置")
    else:
        print(show_status())
