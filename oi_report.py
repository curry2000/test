import requests
import os
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
SIGNAL_LOG = "signal_log.json"

def load_json(filepath):
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except:
        return []

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

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
    
    results = {"LONG": {"win": 0, "loss": 0, "returns": []}, "SHORT": {"win": 0, "loss": 0, "returns": []}}
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
        
        results[sig["signal"]]["returns"].append(pnl_pct)
        if is_win:
            results[sig["signal"]]["win"] += 1
        else:
            results[sig["signal"]]["loss"] += 1
        
        details.append({
            "symbol": sig["symbol"],
            "signal": sig["signal"],
            "entry": entry,
            "current": current,
            "pnl": round(pnl_pct, 2),
            "result": "✅" if is_win else "❌",
            "ts": sig["ts"]
        })
    
    return results, details

def calc_confidence(wins, total):
    if total < 5:
        return "樣本不足"
    elif total < 10:
        return "低信心"
    elif total < 20:
        return "中信心"
    else:
        return "高信心"

def generate_suggestions(results):
    suggestions = []
    
    for sig_type in ["LONG", "SHORT"]:
        data = results[sig_type]
        total = data["win"] + data["loss"]
        if total == 0:
            continue
        
        win_rate = data["win"] / total * 100
        avg_return = sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0
        
        if win_rate < 40:
            suggestions.append(f"• {sig_type} 勝率偏低 ({win_rate:.0f}%)，建議提高 OI 閾值過濾弱訊號")
        elif win_rate > 70:
            suggestions.append(f"• {sig_type} 勝率優秀 ({win_rate:.0f}%)，可考慮降低閾值增加訊號量")
        
        if avg_return < -2:
            suggestions.append(f"• {sig_type} 平均報酬為負 ({avg_return:.1f}%)，建議加入止損或縮短持倉")
        
        if total < 10:
            suggestions.append(f"• {sig_type} 樣本數不足 ({total})，需更多數據驗證")
    
    if not suggestions:
        suggestions.append("• 目前指標表現穩定，建議維持現有參數")
    
    return suggestions

def format_report(results, details, days):
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")
    
    lines = [f"📊 **OI 指標分析報告**", f"週期: 過去 {days} 天 | 生成: {now}", ""]
    
    lines.append("**📈 勝率統計**")
    
    for sig_type, emoji in [("LONG", "🟢"), ("SHORT", "🔴")]:
        data = results[sig_type]
        total = data["win"] + data["loss"]
        if total == 0:
            lines.append(f"{emoji} {sig_type}: 無訊號")
            continue
        
        win_rate = data["win"] / total * 100
        avg_return = sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0
        confidence = calc_confidence(data["win"], total)
        
        lines.append(f"{emoji} **{sig_type}**")
        lines.append(f"• 勝率: {win_rate:.1f}% ({data['win']}勝/{data['loss']}敗)")
        lines.append(f"• 平均報酬: {avg_return:+.2f}%")
        lines.append(f"• 信心水平: {confidence}")
        lines.append("")
    
    if details:
        lines.append("**📋 近期訊號明細**")
        sorted_details = sorted(details, key=lambda x: x["ts"], reverse=True)[:10]
        for d in sorted_details:
            sig_emoji = "🟢" if d["signal"] == "LONG" else "🔴"
            lines.append(f"{d['result']} {sig_emoji} {d['symbol']}: ${d['entry']:.4g} → ${d['current']:.4g} ({d['pnl']:+.1f}%)")
        lines.append("")
    
    suggestions = generate_suggestions(results)
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
    print("=== OI Report Generator ===")
    
    logs = load_json(SIGNAL_LOG)
    if not logs:
        print("無訊號紀錄")
        send_discord("📊 **OI 報告**: 過去 3 天無訊號紀錄，需累積更多數據")
        return
    
    results, details = analyze_signals(logs, days=3)
    
    total_signals = sum(r["win"] + r["loss"] for r in results.values())
    print(f"分析 {total_signals} 個訊號")
    
    report = format_report(results, details, days=3)
    print("\n" + report)
    send_discord(report)

if __name__ == "__main__":
    main()
