import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = os.path.expanduser("~/.openclaw/pullback_state.json")

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

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("No webhook")
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def check_pullback_bounce(symbol, name):
    try:
        data = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=20", timeout=5).json()
        if not isinstance(data, list) or len(data) < 10:
            return None
        
        candles = [{"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])} for k in data]
        
        current = candles[-1]
        prev1 = candles[-2]
        prev2 = candles[-3]
        prev3 = candles[-4]
        
        recent_high = max(c["h"] for c in candles[-8:-2])
        recent_low = min(c["l"] for c in candles[-4:-1])
        current_price = current["c"]
        
        pullback_from_high = (recent_high - recent_low) / recent_high * 100
        
        bounce_from_low = (current_price - recent_low) / recent_low * 100
        
        bull_candle = current["c"] > current["o"]
        prev_was_red = prev1["c"] < prev1["o"]
        
        avg_vol = sum(c["v"] for c in candles[-8:-1]) / 7
        vol_ratio = current["v"] / avg_vol if avg_vol > 0 else 1
        
        closes = [c["c"] for c in candles]
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            d = closes[i] - closes[i-1]
            gains.append(d if d > 0 else 0)
            losses.append(-d if d < 0 else 0)
        ag = sum(gains)/len(gains)
        al = sum(losses)/len(losses) if sum(losses)>0 else 0.001
        rsi = 100-(100/(1+ag/al))
        
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
            ob_dist = (current_price - ob["top"]) / current_price * 100
            if ob_dist < 1.5:
                near_ob = True
                ob_info = f"${ob['bottom']:,.0f}-${ob['top']:,.0f}"
        
        signal = False
        reasons = []
        
        if pullback_from_high >= 0.5 and pullback_from_high <= 3.0:
            reasons.append(f"回踩 {pullback_from_high:.1f}%")
        
        if bounce_from_low >= 0.3 and bull_candle:
            reasons.append(f"反彈 {bounce_from_low:.1f}%")
        
        if prev_was_red and bull_candle:
            reasons.append("紅轉綠")
        
        if vol_ratio >= 1.3:
            reasons.append(f"量增 {vol_ratio:.1f}x")
        
        if near_ob:
            reasons.append(f"OB支撐 {ob_info}")
        
        if rsi >= 40 and rsi <= 65:
            reasons.append(f"RSI {rsi:.0f} 健康")
        
        score = 0
        if pullback_from_high >= 0.5 and pullback_from_high <= 3.0:
            score += 1
        if bounce_from_low >= 0.3 and bull_candle:
            score += 1
        if prev_was_red and bull_candle:
            score += 1
        if vol_ratio >= 1.3:
            score += 1
        if near_ob:
            score += 1
        if rsi >= 40 and rsi <= 65:
            score += 1
        
        if score >= 4 and bull_candle and pullback_from_high >= 0.5:
            return {
                "name": name,
                "price": current_price,
                "high": recent_high,
                "low": recent_low,
                "pullback": pullback_from_high,
                "bounce": bounce_from_low,
                "rsi": rsi,
                "vol_ratio": vol_ratio,
                "reasons": reasons,
                "score": score,
                "ob_info": ob_info
            }
        
        print(f"{name}: ${current_price:,.2f} | 回踩{pullback_from_high:.1f}% 反彈{bounce_from_low:.1f}% RSI:{rsi:.0f} Vol:{vol_ratio:.1f}x 綠:{bull_candle} 分數:{score}/6")
        
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
                if (now - last_time).total_seconds() < 1800:
                    print(f"{name}: 30分鐘內已通知，跳過")
                    continue
            
            msg = (
                f"📢 **{result['name']} 回踩反彈信號！**\n\n"
                f"• 現價: ${result['price']:,.2f}\n"
                f"• 近期高點: ${result['high']:,.2f} → 回踩 {result['pullback']:.1f}% → 反彈 {result['bounce']:.1f}%\n"
                f"• 15M RSI: {result['rsi']:.0f} | Vol: {result['vol_ratio']:.1f}x\n"
                f"• 條件: {' | '.join(result['reasons'])}\n"
                f"• 評分: {result['score']}/6\n"
                f"• 🎯 可考慮加倉"
            )
            print(msg)
            send_discord(msg)
            state[key] = now.isoformat()
    
    save_state(state)

if __name__ == "__main__":
    main()
