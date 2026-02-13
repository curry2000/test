import requests
import json
import os
from datetime import datetime, timezone, timedelta

STATE_FILE = os.path.expanduser("~/.openclaw/paper_state.json")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

CONFIG = {
    "capital": 10000,
    "position_pct": 10,
    "max_positions": 5,
    "sl_pct": 4,
    "tp1_pct": 3,
    "tp2_pct": 5,
    "time_exit_hours": 4
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

def should_open_position(signal, phase, rsi):
    if "⚠️" in phase:
        return False, "高位/低位風險"
    
    if signal == "LONG" and rsi > 75:
        return False, "RSI 過高"
    if signal == "SHORT" and rsi < 25:
        return False, "RSI 過低"
    
    if "🌱" in phase:
        return True, "啟動初期，最佳進場"
    if "🔥" in phase:
        return True, "行情中段，謹慎進場"
    
    return True, "符合條件"

def open_position(state, symbol, signal, entry_price, phase, rsi):
    if len(state["positions"]) >= CONFIG["max_positions"]:
        return None, "已達最大持倉數"
    
    for p in state["positions"]:
        if p["symbol"] == symbol:
            return None, "已有持倉"
    
    should_open, reason = should_open_position(signal, phase, rsi)
    if not should_open:
        return None, f"不開倉: {reason}"
    
    position_size = state["capital"] * CONFIG["position_pct"] / 100
    
    if signal == "LONG":
        sl = entry_price * (1 - CONFIG["sl_pct"] / 100)
        tp1 = entry_price * (1 + CONFIG["tp1_pct"] / 100)
        tp2 = entry_price * (1 + CONFIG["tp2_pct"] / 100)
    else:
        sl = entry_price * (1 + CONFIG["sl_pct"] / 100)
        tp1 = entry_price * (1 - CONFIG["tp1_pct"] / 100)
        tp2 = entry_price * (1 - CONFIG["tp2_pct"] / 100)
    
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
        
        if pos["direction"] == "LONG":
            pnl_pct = (current_price - pos["entry_price"]) / pos["entry_price"] * 100
            
            if current_price <= pos["sl"]:
                exit_reason = "SL"
            elif current_price >= pos["tp1"] and not pos["tp1_hit"]:
                pos["tp1_hit"] = True
                pos["sl"] = pos["entry_price"]
            elif current_price >= pos["tp2"]:
                exit_reason = "TP2"
        else:
            pnl_pct = (pos["entry_price"] - current_price) / pos["entry_price"] * 100
            
            if current_price >= pos["sl"]:
                exit_reason = "SL"
            elif current_price <= pos["tp1"] and not pos["tp1_hit"]:
                pos["tp1_hit"] = True
                pos["sl"] = pos["entry_price"]
            elif current_price <= pos["tp2"]:
                exit_reason = "TP2"
        
        if hours_held >= CONFIG["time_exit_hours"] and not exit_reason:
            exit_reason = "TIME"
        
        if exit_reason:
            pnl_usd = pos["size"] * pnl_pct / 100
            state["capital"] += pnl_usd
            
            closed.append({
                "symbol": symbol,
                "direction": pos["direction"],
                "entry": pos["entry_price"],
                "exit": exit_price,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "reason": exit_reason,
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
    if not closed:
        return None
    
    wins = len([t for t in closed if t["pnl_pct"] > 0])
    losses = len([t for t in closed if t["pnl_pct"] <= 0])
    total_pnl = sum(t["pnl_pct"] for t in closed)
    total_usd = sum(t["pnl_usd"] for t in closed)
    
    return {
        "total_trades": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(closed) * 100 if closed else 0,
        "total_pnl_pct": total_pnl,
        "total_pnl_usd": total_usd,
        "capital": state["capital"],
        "return_pct": (state["capital"] - CONFIG["capital"]) / CONFIG["capital"] * 100
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
        return f"""📈 **模擬交易統計**

• 總交易: {s['total_trades']} 筆
• 勝/敗: {s['wins']}/{s['losses']}
• 勝率: {s['win_rate']:.1f}%
• 累計盈虧: {s['total_pnl_pct']:+.2f}%
• 本金: ${CONFIG['capital']:.0f} → ${s['capital']:.0f}
• 報酬率: {s['return_pct']:+.2f}%"""

def send_discord(msg):
    if not DISCORD_WEBHOOK or not msg:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
    except:
        pass

def process_signal(symbol, signal, price, phase, rsi):
    state = load_state()
    
    pos, reason = open_position(state, symbol, signal, price, phase, rsi)
    
    if pos:
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
    
    lines = [f"📊 **模擬交易狀態** | {now}", ""]
    
    if state["positions"]:
        lines.append(f"**持倉中 ({len(state['positions'])})**")
        for p in state["positions"]:
            current = get_price(p["symbol"])
            if current:
                if p["direction"] == "LONG":
                    pnl = (current - p["entry_price"]) / p["entry_price"] * 100
                else:
                    pnl = (p["entry_price"] - current) / p["entry_price"] * 100
                emoji = "📈" if pnl > 0 else "📉"
                lines.append(f"• {p['symbol']} {p['direction']}: ${p['entry_price']:.4g} → ${current:.4g} ({pnl:+.1f}%) {emoji}")
        lines.append("")
    
    summary = get_summary(state)
    if summary:
        lines.append(format_trade_msg("SUMMARY", summary))
    else:
        lines.append("尚無已平倉交易")
    
    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "check":
            check_and_close()
        elif sys.argv[1] == "status":
            print(show_status())
        elif sys.argv[1] == "reset":
            save_state({"positions": [], "closed": [], "capital": CONFIG["capital"]})
            print("已重置")
    else:
        print(show_status())
