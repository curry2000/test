import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = os.path.expanduser("~/.openclaw/pullback_state.json")
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

def calc_atr(candles, period=14):
    trs = []
    for i in range(1, min(period+1, len(candles))):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0

def calc_rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, min(period+1, len(closes))):
        d = closes[i] - closes[i-1]
        gains.append(d if d > 0 else 0)
        losses.append(-d if d < 0 else 0)
    ag = sum(gains)/len(gains) if gains else 0
    al = sum(losses)/len(losses) if losses else 0.001
    if al == 0:
        return 100
    return 100-(100/(1+ag/al))

def check_1h_structure(symbol):
    try:
        data = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit=20", timeout=5).json()
        if not isinstance(data, list) or len(data) < 10:
            return None
        candles = [{"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])} for k in data]
        closes = [c["c"] for c in candles]
        rsi_1h = calc_rsi(closes)
        ma7 = sum(closes[-7:]) / 7
        score = 0
        reasons = []
        if closes[-1] > ma7:
            score += 1
            reasons.append("價>MA7")
        if candles[-2]["c"] > candles[-2]["o"]:
            score += 1
            reasons.append("上根綠K")
        if candles[-2]["l"] > candles[-3]["l"]:
            score += 1
            reasons.append("低點墊高")
        bull_count = sum(1 for c in candles[-4:] if c["c"] > c["o"])
        if bull_count >= 3:
            score += 1
            reasons.append(f"近4根{bull_count}綠")
        if 40 <= rsi_1h <= 70:
            score += 1
            reasons.append(f"RSI {rsi_1h:.0f}")
        return {"score": score, "rsi": rsi_1h, "reasons": reasons, "stable": score >= 3}
    except:
        return None

def check_pullback_bounce(symbol, name):
    try:
        data = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=30", timeout=5).json()
        if not isinstance(data, list) or len(data) < 15:
            return None
        candles = [{"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])} for k in data]
        current = candles[-1]
        prev1 = candles[-2]
        current_price = current["c"]

        atr = calc_atr(candles[-15:], 14)
        atr_pct = (atr / current_price * 100) if current_price > 0 else 1
        min_pullback = max(atr_pct * 1.2, 1.0)
        max_pullback = atr_pct * 5

        recent_high = max(c["h"] for c in candles[-12:-2])
        recent_low = min(c["l"] for c in candles[-4:-1])
        pullback_from_high = (recent_high - recent_low) / recent_high * 100
        bounce_from_low = (current_price - recent_low) / recent_low * 100

        bull_candle = current["c"] > current["o"]
        prev_was_red = prev1["c"] < prev1["o"]

        avg_vol = sum(c["v"] for c in candles[-10:-1]) / 9
        vol_ratio = current["v"] / avg_vol if avg_vol > 0 else 1

        closes = [c["c"] for c in candles]
        rsi = calc_rsi(closes)

        bull_obs = []
        for i in range(2, len(candles)-1):
            p, c, n = candles[i-1], candles[i], candles[i+1]
            if p["c"] < p["o"] and c["c"] > c["o"] and n["c"] > n["o"]:
                if n["c"] > p["o"] and current_price > p["c"]:
                    bull_obs.append({"top": p["o"], "bottom": p["c"]})
        near_ob = False
        ob_info = ""
        if bull_obs:
            ob = bull_obs[-1]
            ob_dist = abs(current_price - ob["top"]) / current_price * 100
            if ob_dist < 1.0:
                near_ob = True
                ob_info = f"${ob['bottom']:,.0f}-${ob['top']:,.0f}"

        score = 0
        reasons = []

        if pullback_from_high >= min_pullback and pullback_from_high <= max_pullback:
            score += 1
            reasons.append(f"回踩 {pullback_from_high:.1f}%(門檻{min_pullback:.1f}%)")

        if bounce_from_low >= 0.3 and bull_candle:
            score += 1
            reasons.append(f"反彈 {bounce_from_low:.1f}%")

        if prev_was_red and bull_candle:
            score += 1
            reasons.append("紅轉綠")

        if vol_ratio >= 1.0:
            score += 1
            reasons.append(f"量能 {vol_ratio:.1f}x")

        if near_ob:
            score += 1
            reasons.append(f"OB支撐 {ob_info}")

        if rsi >= 35 and rsi <= 60:
            score += 1
            reasons.append(f"RSI {rsi:.0f} 健康")

        print(f"{name}: ${current_price:,.2f} | 回踩{pullback_from_high:.1f}%(門檻{min_pullback:.1f}%) 反彈{bounce_from_low:.1f}% RSI:{rsi:.0f} Vol:{vol_ratio:.1f}x 綠:{bull_candle} 分數:{score}/6")

        if score >= 4 and bull_candle and pullback_from_high >= min_pullback and vol_ratio >= 1.0:
            structure = check_1h_structure(symbol)
            if not structure or not structure["stable"]:
                s_score = structure["score"] if structure else 0
                s_reasons = ", ".join(structure["reasons"]) if structure else "無資料"
                print(f"  → 1H結構不穩({s_score}/5: {s_reasons})，跳過")
                return None
            reasons.append(f"1H穩({structure['score']}/5: {', '.join(structure['reasons'])})")
            return {
                "name": name, "price": current_price, "high": recent_high,
                "low": recent_low, "pullback": pullback_from_high,
                "bounce": bounce_from_low, "rsi": rsi,
                "rsi_1h": structure["rsi"], "vol_ratio": vol_ratio,
                "reasons": reasons, "score": score, "ob_info": ob_info,
                "atr_pct": atr_pct
            }
    except Exception as e:
        print(f"{name} error: {e}")
    return None

def main():
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    state = load_state()
    for symbol, name in [("BTCUSDT","BTC"), ("ETHUSDT","ETH")]:
        result = check_pullback_bounce(symbol, name)
        if result:
            key = f"{symbol}_pullback"
            last_notify = state.get(key, "")
            if last_notify:
                last_time = datetime.fromisoformat(last_notify)
                if (now - last_time).total_seconds() < 7200:
                    print(f"{name}: 2小時內已通知，跳過")
                    continue
            msg = (
                f"📢 **{result['name']} 回踩反彈信號！[BN本地]**\n\n"
                f"• 現價: ${result['price']:,.2f}\n"
                f"• 近期高點: ${result['high']:,.2f} → 回踩 {result['pullback']:.1f}% → 反彈 {result['bounce']:.1f}%\n"
                f"• ATR波動率: {result['atr_pct']:.2f}% | 動態門檻: {result['atr_pct']*1.2:.1f}%\n"
                f"• 15M RSI: {result['rsi']:.0f} | 1H RSI: {result['rsi_1h']:.0f} | Vol: {result['vol_ratio']:.1f}x\n"
                f"• 條件({result['score']}/6): {' | '.join(result['reasons'])}\n"
                f"• 🎯 可考慮加倉"
            )
            print(msg)
            send_discord(msg, pin=True)
            state[key] = now.isoformat()
    save_state(state)

if __name__ == "__main__":
    main()
