import requests
import os
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
SIGNAL_LOG = "monitor_signals.json"

def load_json(filepath):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return []

def get_current_price(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}-USDT-SWAP"
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0]["last"])
    except:
        pass
    return None

def analyze_signals(logs, days=3):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    cutoff = now - timedelta(days=days)
    
    recent = [l for l in logs if datetime.fromisoformat(l["ts"]) > cutoff]
    
    by_trigger = defaultdict(lambda: {"LONG": {"win": 0, "loss": 0, "returns": []}, "SHORT": {"win": 0, "loss": 0, "returns": []}})
    by_symbol = defaultdict(lambda: {"LONG": {"win": 0, "loss": 0, "returns": []}, "SHORT": {"win": 0, "loss": 0, "returns": []}})
    details = []
    
    for sig in recent:
        if sig["signal"] not in ["LONG", "SHORT"]:
            continue
        
        current = get_current_price(sig["symbol"])
        if current is None:
            continue
        
        entry = sig["entry_price"]
        pnl_pct = (current - entry) / entry * 100
        
        if sig["signal"] == "SHORT":
            pnl_pct = -pnl_pct
        
        is_win = pnl_pct > 0
        trigger = sig.get("trigger", "UNKNOWN")
        symbol = sig["symbol"]
        
        by_trigger[trigger][sig["signal"]]["returns"].append(pnl_pct)
        by_symbol[symbol][sig["signal"]]["returns"].append(pnl_pct)
        
        if is_win:
            by_trigger[trigger][sig["signal"]]["win"] += 1
            by_symbol[symbol][sig["signal"]]["win"] += 1
        else:
            by_trigger[trigger][sig["signal"]]["loss"] += 1
            by_symbol[symbol][sig["signal"]]["loss"] += 1
        
        details.append({
            "symbol": symbol,
            "signal": sig["signal"],
            "trigger": trigger,
            "entry": entry,
            "current": current,
            "pnl": round(pnl_pct, 2),
            "result": "✅" if is_win else "❌",
            "ts": sig["ts"]
        })
    
    return dict(by_trigger), dict(by_symbol), details

def calc_stats(data):
    total = data["win"] + data["loss"]
    if total == 0:
        return None
    win_rate = data["win"] / total * 100
    avg_return = sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0
    return {"win_rate": win_rate, "avg_return": avg_return, "total": total, "wins": data["win"], "losses": data["loss"]}

def generate_suggestions(by_trigger, by_symbol):
    suggestions = []
    
    for trigger, data in by_trigger.items():
        for sig_type in ["LONG", "SHORT"]:
            stats = calc_stats(data[sig_type])
            if not stats:
                continue
            
            if stats["win_rate"] < 40 and stats["total"] >= 5:
                suggestions.append(f"• {trigger} {sig_type} 勝率低 ({stats['win_rate']:.0f}%)，建議收緊條件")
            elif stats["win_rate"] > 70 and stats["total"] >= 5:
                suggestions.append(f"• {trigger} {sig_type} 表現優秀 ({stats['win_rate']:.0f}%)，可考慮加大倉位")
            
            if stats["avg_return"] < -3:
                suggestions.append(f"• {trigger} {sig_type} 虧損大 ({stats['avg_return']:.1f}%)，建議設止損")
    
    for symbol, data in by_symbol.items():
        total_all = sum(d["win"] + d["loss"] for d in data.values())
        if total_all >= 5:
            total_wins = sum(d["win"] for d in data.values())
            total_losses = sum(d["loss"] for d in data.values())
            win_rate = total_wins / (total_wins + total_losses) * 100 if (total_wins + total_losses) > 0 else 0
            if win_rate < 35:
                suggestions.append(f"• {symbol} 整體勝率偏低 ({win_rate:.0f}%)，建議觀望")
    
    if not suggestions:
        suggestions.append("• 目前指標表現穩定，建議維持現有參數")
    
    return suggestions

def format_report(by_trigger, by_symbol, details, days):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")
    
    lines = [f"📊 **技術指標分析報告**", f"週期: 過去 {days} 天 | 生成: {now}", ""]
    
    lines.append("**📈 各觸發類型表現**")
    
    for trigger in ["OB", "RSI", "SUPPORT", "RESISTANCE"]:
        if trigger not in by_trigger:
            continue
        data = by_trigger[trigger]
        
        lines.append(f"\n**{trigger}**")
        for sig_type, emoji in [("LONG", "🟢"), ("SHORT", "🔴")]:
            stats = calc_stats(data[sig_type])
            if not stats:
                continue
            lines.append(f"{emoji} {sig_type}: {stats['win_rate']:.0f}% ({stats['wins']}勝/{stats['losses']}敗) | 報酬 {stats['avg_return']:+.1f}%")
    
    lines.append("")
    lines.append("**📋 各幣種表現**")
    
    for symbol, data in by_symbol.items():
        all_returns = data["LONG"]["returns"] + data["SHORT"]["returns"]
        total_wins = data["LONG"]["win"] + data["SHORT"]["win"]
        total_losses = data["LONG"]["loss"] + data["SHORT"]["loss"]
        total = total_wins + total_losses
        
        if total == 0:
            continue
        
        win_rate = total_wins / total * 100
        avg_return = sum(all_returns) / len(all_returns) if all_returns else 0
        lines.append(f"• {symbol}: {win_rate:.0f}% ({total_wins}勝/{total_losses}敗) | 報酬 {avg_return:+.1f}%")
    
    if details:
        lines.append("")
        lines.append("**📝 近期訊號明細**")
        sorted_details = sorted(details, key=lambda x: x["ts"], reverse=True)[:8]
        for d in sorted_details:
            sig_emoji = "🟢" if d["signal"] == "LONG" else "🔴"
            lines.append(f"{d['result']} {sig_emoji} {d['symbol']} [{d['trigger']}]: ${d['entry']:.2f} → ${d['current']:.2f} ({d['pnl']:+.1f}%)")
    
    lines.append("")
    suggestions = generate_suggestions(by_trigger, by_symbol)
    lines.append("**💡 優化建議**")
    lines.extend(suggestions)
    
    return "\n".join(lines)

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("No webhook")
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def main():
    print("=== Monitor Report Generator ===")
    
    logs = load_json(SIGNAL_LOG)
    if not logs:
        print("無訊號紀錄")
        send_discord("📊 **技術指標報告**: 過去 3 天無訊號紀錄，需累積更多數據")
        return
    
    by_trigger, by_symbol, details = analyze_signals(logs, days=3)
    
    total_signals = len(details)
    print(f"分析 {total_signals} 個訊號")
    
    report = format_report(by_trigger, by_symbol, details, days=3)
    print("\n" + report)
    send_discord(report)

if __name__ == "__main__":
    main()
