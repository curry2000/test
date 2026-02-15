import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = os.path.expanduser("~/.openclaw/breakout_state.json")
LEVELS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "breakout_levels.json")
CHANNEL_ID = "1471200792945098955"

def get_bot_token():
    try:
        with open(os.path.expanduser("~/.openclaw/openclaw.json"), "r") as f:
            config = json.load(f)
        return config.get("channels", {}).get("discord", {}).get("token", "")
    except:
        return ""

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

def load_levels():
    try:
        with open(LEVELS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def send_discord(message, pin=False):
    if not DISCORD_WEBHOOK:
        print("No webhook")
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        print(f"Discord: {r.status_code}")
        if pin and r.status_code in (200, 204):
            bot_token = get_bot_token()
            if bot_token:
                msgs = requests.get(
                    f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages?limit=1",
                    headers={"Authorization": f"Bot {bot_token}"},
                    timeout=10
                ).json()
                if msgs and len(msgs) > 0:
                    requests.put(
                        f"https://discord.com/api/v10/channels/{CHANNEL_ID}/pins/{msgs[0]['id']}",
                        headers={"Authorization": f"Bot {bot_token}"},
                        timeout=10
                    )
    except Exception as e:
        print(f"Error: {e}")

def get_klines(symbol, interval="1h", limit=15):
    try:
        r = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}", timeout=5)
        data = r.json()
        if isinstance(data, list):
            return [{"t":int(k[0]),"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])} for k in data]
    except:
        pass
    return []

def calc_rsi(closes, period=14):
    if len(closes) < period+1:
        return 50
    gains, losses = [], []
    for i in range(len(closes)-period, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(d if d > 0 else 0)
        losses.append(-d if d < 0 else 0)
    ag = sum(gains)/len(gains)
    al = sum(losses)/len(losses) if sum(losses) > 0 else 0.001
    return 100-(100/(1+ag/al))

def check_breakout(symbol, name, level, direction, state, now):
    candles = get_klines(symbol, "1h", 15)
    if len(candles) < 5:
        print(f"{name}: 資料不足")
        return

    prev = candles[-2]
    current = candles[-1]
    prev_close = prev["c"]
    current_price = current["c"]

    avg_vol = sum(c["v"] for c in candles[-11:-1]) / 10
    prev_vol = prev["v"]
    vol_ratio = prev_vol / avg_vol if avg_vol > 0 else 1

    closes = [c["c"] for c in candles]
    rsi = calc_rsi(closes)

    key = f"{symbol}_{level}_{direction}"
    s = state.get(key, {"stage": "watching", "breakout_time": None, "confirmed_count": 0})

    if direction == "above":
        broke = prev_close >= level
        holding = current_price >= level
        failed = current_price < level * 0.997
    else:
        broke = prev_close <= level
        holding = current_price <= level
        failed = current_price > level * 1.003

    stage = s.get("stage", "watching")
    confirmed = s.get("confirmed_count", 0)

    print(f"{name}: ${current_price:,.2f} | 關卡 ${level:,} | 1H收${prev_close:,.2f} | Vol {vol_ratio:.1f}x | RSI {rsi:.0f} | 階段:{stage} 確認:{confirmed}")

    if stage == "watching":
        if broke:
            vol_ok = vol_ratio >= 1.2
            vol_tag = f"✅ 量能 {vol_ratio:.1f}x" if vol_ok else f"⚠️ 量能偏弱 {vol_ratio:.1f}x"
            strength = "強勢突破" if vol_ratio >= 1.5 else ("有效突破" if vol_ok else "弱勢突破")
            dir_text = "突破" if direction == "above" else "跌破"
            emoji = "🚀" if vol_ok else "⚠️"

            msg = (
                f"{emoji} **{name} {dir_text}關卡！（{strength}）**\n\n"
                f"• 1H 收線: ${prev_close:,.2f} {'>' if direction=='above' else '<'} ${level:,}\n"
                f"• 現價: ${current_price:,.2f}\n"
                f"• {vol_tag}（前10根平均）\n"
                f"• RSI: {rsi:.0f}\n"
                f"• ⏳ 等待回踩確認...\n"
                f"• 時間: {now.strftime('%m/%d %H:%M')}"
            )
            send_discord(msg, pin=True)
            s = {"stage": "confirming", "breakout_time": now.isoformat(), "confirmed_count": 0, "vol_ratio": vol_ratio}

    elif stage == "confirming":
        bt = datetime.fromisoformat(s["breakout_time"])
        hours_since = (now - bt).total_seconds() / 3600

        if failed:
            msg = (
                f"❌ **{name} 假突破！**\n\n"
                f"• 現價 ${current_price:,.2f} 跌回關卡 ${level:,} 以下\n"
                f"• 突破後 {hours_since:.1f}h 回落\n"
                f"• ⚠️ 假突破，暫不加倉"
            )
            send_discord(msg)
            s = {"stage": "watching", "breakout_time": None, "confirmed_count": 0}

        elif holding:
            confirmed += 1
            s["confirmed_count"] = confirmed

            if confirmed == 2:
                msg = (
                    f"✅ **{name} 回踩確認！站穩 ${level:,}**\n\n"
                    f"• 現價: ${current_price:,.2f}\n"
                    f"• 突破後連續 {confirmed} 根 1H 站穩\n"
                    f"• 突破量能: {s.get('vol_ratio',0):.1f}x\n"
                    f"• RSI: {rsi:.0f}\n"
                    f"• 🎯 回踩不破，可考慮加倉\n"
                    f"• 時間: {now.strftime('%m/%d %H:%M')}"
                )
                send_discord(msg, pin=True)

            elif confirmed == 4:
                msg = (
                    f"💪 **{name} 強勢站穩 ${level:,}！**\n\n"
                    f"• 現價: ${current_price:,.2f}\n"
                    f"• 連續 {confirmed} 根 1H 站穩（{hours_since:.0f}h）\n"
                    f"• RSI: {rsi:.0f}\n"
                    f"• ✅ 趨勢確立"
                )
                send_discord(msg, pin=True)
                s["stage"] = "confirmed"

        if hours_since > 24 and stage == "confirming":
            s = {"stage": "watching", "breakout_time": None, "confirmed_count": 0}

    elif stage == "confirmed":
        if failed:
            msg = (
                f"⚠️ **{name} 跌回關卡 ${level:,}！**\n\n"
                f"• 現價: ${current_price:,.2f}\n"
                f"• 注意止損保護"
            )
            send_discord(msg)
            s = {"stage": "watching", "breakout_time": None, "confirmed_count": 0}

    state[key] = s

def backtest(symbol, name, level, direction, days=30):
    candles = get_klines(symbol, "1h", min(days*24, 1000))
    if len(candles) < 50:
        print(f"{name}: 資料不足")
        return

    tw_tz = timezone(timedelta(hours=8))
    breakouts = []
    i = 1

    while i < len(candles) - 5:
        prev_c = candles[i-1]["c"]
        if direction == "above":
            triggered = prev_c >= level and candles[i-2]["c"] < level
        else:
            triggered = prev_c <= level and candles[i-2]["c"] > level

        if not triggered:
            i += 1
            continue

        avg_vol = sum(c["v"] for c in candles[max(0,i-11):i-1]) / min(10, max(1, i-1))
        vol_ratio = candles[i-1]["v"] / avg_vol if avg_vol > 0 else 1

        held = 0
        max_profit = 0
        max_dd = 0
        entry = candles[i]["o"]
        failed = False
        fail_bar = 0

        for j in range(i, min(i+24, len(candles))):
            p = candles[j]["c"]
            if direction == "above":
                pnl = (p - entry) / entry * 100
                dd = (candles[j]["l"] - entry) / entry * 100
                if p < level * 0.997:
                    failed = True
                    fail_bar = j - i
                    break
            else:
                pnl = (entry - p) / entry * 100
                dd = (entry - candles[j]["h"]) / entry * 100
            max_profit = max(max_profit, pnl)
            max_dd = min(max_dd, dd)
            held += 1

        final_price = candles[min(i+23, len(candles)-1)]["c"]
        if direction == "above":
            final_pnl = (final_price - entry) / entry * 100
        else:
            final_pnl = (entry - final_price) / entry * 100

        t = datetime.fromtimestamp(candles[i]["t"]/1000, tz=tw_tz)
        breakouts.append({
            "time": t.strftime("%m/%d %H:%M"),
            "entry": entry,
            "vol_ratio": vol_ratio,
            "held": held,
            "max_profit": max_profit,
            "max_dd": max_dd,
            "final_pnl": final_pnl,
            "failed": failed,
            "fail_bar": fail_bar,
            "vol_confirmed": vol_ratio >= 1.2
        })
        i += held + 1

    if not breakouts:
        print(f"\n{name} ${level:,} {'突破' if direction=='above' else '跌破'}: 過去{days}天無觸發")
        return

    total = len(breakouts)
    wins = sum(1 for b in breakouts if b["final_pnl"] > 0)
    vol_confirmed = [b for b in breakouts if b["vol_confirmed"]]
    vol_wins = sum(1 for b in vol_confirmed if b["final_pnl"] > 0)
    no_vol = [b for b in breakouts if not b["vol_confirmed"]]
    no_vol_wins = sum(1 for b in no_vol if b["final_pnl"] > 0)
    false_breakouts = sum(1 for b in breakouts if b["failed"])
    avg_pnl = sum(b["final_pnl"] for b in breakouts) / total
    avg_max_profit = sum(b["max_profit"] for b in breakouts) / total
    avg_max_dd = sum(b["max_dd"] for b in breakouts) / total

    print(f"\n{'='*60}")
    print(f"📊 {name} ${level:,} {'突破' if direction=='above' else '跌破'} 回測 ({days}天)")
    print(f"{'='*60}")
    print(f"總次數: {total} | 勝率: {wins}/{total} ({wins/total*100:.0f}%)")
    print(f"假突破: {false_breakouts}/{total} ({false_breakouts/total*100:.0f}%)")
    print(f"平均PnL: {avg_pnl:+.2f}% | 最大獲利: {avg_max_profit:.2f}% | 最大回撤: {avg_max_dd:.2f}%")
    print(f"")
    print(f"📈 有量突破(≥1.2x): {len(vol_confirmed)}次 | 勝率: {vol_wins}/{len(vol_confirmed)} ({vol_wins/len(vol_confirmed)*100:.0f}%)" if vol_confirmed else "📈 有量突破: 0次")
    if vol_confirmed:
        avg_vol_pnl = sum(b["final_pnl"] for b in vol_confirmed) / len(vol_confirmed)
        print(f"   平均PnL: {avg_vol_pnl:+.2f}%")
    print(f"📉 無量突破(<1.2x): {len(no_vol)}次 | 勝率: {no_vol_wins}/{len(no_vol)} ({no_vol_wins/len(no_vol)*100:.0f}%)" if no_vol else "📉 無量突破: 0次")
    if no_vol:
        avg_novol_pnl = sum(b["final_pnl"] for b in no_vol) / len(no_vol)
        print(f"   平均PnL: {avg_novol_pnl:+.2f}%")

    print(f"\n明細:")
    for b in breakouts:
        vol_tag = "📈" if b["vol_confirmed"] else "📉"
        fail_tag = "❌假突破" if b["failed"] else "✅"
        print(f"  {b['time']} | 入場${b['entry']:,.0f} | Vol {b['vol_ratio']:.1f}x {vol_tag} | PnL {b['final_pnl']:+.2f}% | Max +{b['max_profit']:.2f}%/-{abs(b['max_dd']):.2f}% | {fail_tag}")

def main():
    import sys
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)

    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        levels = load_levels()
        for symbol, cfg in levels.items():
            if cfg.get("above"):
                backtest(symbol, cfg["name"], cfg["above"], "above", days)
            if cfg.get("below"):
                backtest(symbol, cfg["name"], cfg["below"], "below", days)
        return

    state = load_state()
    levels = load_levels()

    for symbol, cfg in levels.items():
        if cfg.get("above"):
            check_breakout(symbol, cfg["name"], cfg["above"], "above", state, now)
        if cfg.get("below"):
            check_breakout(symbol, cfg["name"], cfg["below"], "below", state, now)

    save_state(state)

if __name__ == "__main__":
    main()
