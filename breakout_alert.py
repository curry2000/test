import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = os.path.expanduser("~/.openclaw/breakout_state.json")

ALERTS = [
    {"symbol": "BTCUSDT", "name": "BTC", "level": 70300, "direction": "above"},
    {"symbol": "ETHUSDT", "name": "ETH", "level": 2100, "direction": "above"},
]

def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_1h_close(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=2"
        r = requests.get(url, timeout=5)
        data = r.json()
        if isinstance(data, list) and len(data) >= 2:
            prev_close = float(data[-2][4])
            current = float(data[-1][4])
            return prev_close, current
    except:
        pass
    return None, None

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
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    state = load_state()
    
    for alert in ALERTS:
        sym = alert["symbol"]
        name = alert["name"]
        level = alert["level"]
        
        prev_close, current = get_1h_close(sym)
        if prev_close is None:
            continue
        
        key = f"{sym}_{level}"
        already_notified = state.get(key, False)
        
        if alert["direction"] == "above" and prev_close >= level and not already_notified:
            msg = (
                f"🚨 **{name} 突破確認！**\n\n"
                f"• 1H 收線: ${prev_close:,.2f} > ${level:,}\n"
                f"• 現價: ${current:,.2f}\n"
                f"• ✅ 站穩壓力位，可考慮加倉\n"
                f"• 時間: {now.strftime('%m/%d %H:%M')}"
            )
            print(msg)
            send_discord(msg)
            state[key] = True
            
        elif alert["direction"] == "above" and prev_close < level:
            if already_notified:
                state[key] = False
        
        status = "✅" if prev_close and prev_close >= level else "❌"
        print(f"{name}: 1H收線 ${prev_close:,.2f} {'>' if prev_close >= level else '<'} ${level:,} {status}")
    
    save_state(state)

if __name__ == "__main__":
    main()
