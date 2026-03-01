"""
回調反彈監控系統
監控價格回調後反彈的加倉機會
"""
import os
import json
from datetime import datetime

# 使用共用模組
from config import (
    PULLBACK_STATE_FILE,
    TW_TIMEZONE,
    DISCORD_THREAD_TECH
)

CHANNEL_ID = DISCORD_THREAD_TECH
from exchange_api import get_klines
from notify import send_discord_message



def get_bot_token():
    """取得 Discord Bot Token（用於釘選）"""
    try:
        with open(os.path.expanduser("~/.openclaw/openclaw.json"), "r") as f:
            config = json.load(f)
        return config.get("channels", {}).get("discord", {}).get("token", "")
    except:
        return ""


def load_state():
    """載入狀態"""
    try:
        with open(PULLBACK_STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    """儲存狀態"""
    os.makedirs(os.path.dirname(PULLBACK_STATE_FILE), exist_ok=True)
    with open(PULLBACK_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def send_discord(message, pin=False):
    """發送 Discord 訊息（含釘選功能）"""
    import requests
    
    success = send_discord_message(message, thread_id=DISCORD_THREAD_TECH)
    
    if success and pin:
        bot_token = get_bot_token()
        if bot_token:
            try:
                # 取得最新訊息
                msgs = requests.get(
                    f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages?limit=1",
                    headers={"Authorization": f"Bot {bot_token}"},
                    timeout=10
                ).json()
                
                if msgs and len(msgs) > 0:
                    # 釘選訊息
                    requests.put(
                        f"https://discord.com/api/v10/channels/{CHANNEL_ID}/pins/{msgs[0]['id']}",
                        headers={"Authorization": f"Bot {bot_token}"},
                        timeout=10
                    )
            except Exception as e:
                print(f"Pin failed: {e}")


def calc_atr(candles, period=14):
    """計算 ATR"""
    trs = []
    for i in range(1, min(period+1, len(candles))):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i-1]["c"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0


def calc_rsi(closes, period=14):
    """計算 RSI"""
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
    """檢查 1H 結構是否穩定"""
    try:
        klines = get_klines(symbol, "1h", 20)
        if not klines or len(klines) < 10:
            return None
        
        # 轉換格式
        candles = [{"o": k["open"], "h": k["high"], "l": k["low"], 
                    "c": k["close"], "v": k["volume"]} for k in klines]
        
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
    """檢查回調反彈信號"""
    try:
        klines = get_klines(symbol, "15m", 30)
        if not klines or len(klines) < 15:
            return None
        
        # 轉換格式
        candles = [{"o": k["open"], "h": k["high"], "l": k["low"],
                    "c": k["close"], "v": k["volume"]} for k in klines]
        
        current = candles[-1]
        prev1 = candles[-2]
        current_price = current["c"]

        # 計算 ATR 和動態門檻
        atr = calc_atr(candles[-15:], 14)
        atr_pct = (atr / current_price * 100) if current_price > 0 else 1
        min_pullback = max(atr_pct * 1.2, 1.0)
        max_pullback = atr_pct * 5

        # 找最近高低點
        recent_high = max(c["h"] for c in candles[-12:-2])
        recent_low = min(c["l"] for c in candles[-4:-1])
        pullback_from_high = (recent_high - recent_low) / recent_high * 100
        bounce_from_low = (current_price - recent_low) / recent_low * 100

        # 判斷當前 K 線
        bull_candle = current["c"] > current["o"]
        prev_was_red = prev1["c"] < prev1["o"]

        # 計算量能
        avg_vol = sum(c["v"] for c in candles[-10:-1]) / 9
        vol_ratio = current["v"] / avg_vol if avg_vol > 0 else 1

        # 計算 RSI
        closes = [c["c"] for c in candles]
        rsi = calc_rsi(closes)

        # 找 Order Block 支撐
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

        # 評分系統
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

        # 判斷是否觸發信號
        if score >= 4 and bull_candle and pullback_from_high >= min_pullback and vol_ratio >= 1.0:
            # 檢查 1H 結構
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
    """主程序"""
    now = datetime.now(TW_TIMEZONE)
    state = load_state()
    
    # 監控幣種
    for symbol, name in [("BTCUSDT","BTC"), ("ETHUSDT","ETH")]:
        result = check_pullback_bounce(symbol, name)
        if result:
            key = f"{symbol}_pullback"
            last_notify = state.get(key, "")
            
            # 檢查冷卻時間（2小時）
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
