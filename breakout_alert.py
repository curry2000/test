"""
突破/跌破監控系統
監控指定價位的突破確認，發送通知
"""
import os
import json
from datetime import datetime

# 使用共用模組
from config import (
    BREAKOUT_STATE_FILE,
    BREAKOUT_LEVELS_FILE,
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
        with open(BREAKOUT_STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    """儲存狀態"""
    os.makedirs(os.path.dirname(BREAKOUT_STATE_FILE), exist_ok=True)
    with open(BREAKOUT_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_levels():
    """載入監控關卡設定"""
    try:
        with open(BREAKOUT_LEVELS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


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


def calc_rsi(closes, period=14):
    """計算 RSI"""
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
    """檢查突破/跌破狀態"""
    # 取得 K 線資料
    klines = get_klines(symbol, "1h", 15)
    if not klines or len(klines) < 5:
        print(f"{name}: 資料不足")
        return
    
    # 轉換格式（exchange_api 返回的格式）
    candles = [{"t": k["open_time"], "o": k["open"], "h": k["high"], 
                "l": k["low"], "c": k["close"], "v": k["volume"]} for k in klines]

    prev = candles[-2]
    current = candles[-1]
    prev_close = prev["c"]
    current_price = current["c"]

    # 計算量能比例
    avg_vol = sum(c["v"] for c in candles[-11:-1]) / 10
    prev_vol = prev["v"]
    vol_ratio = prev_vol / avg_vol if avg_vol > 0 else 1

    # 計算 RSI
    closes = [c["c"] for c in candles]
    rsi = calc_rsi(closes)

    # 取得或初始化狀態
    key = f"{symbol}_{level}_{direction}"
    s = state.get(key, {"stage": "watching", "breakout_time": None, "confirmed_count": 0})

    # 判斷突破/跌破
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

    # 階段 1: 監控中
    if stage == "watching":
        if broke:
            vol_ok = vol_ratio >= 1.2
            vol_tag = f"✅ 量能 {vol_ratio:.1f}x" if vol_ok else f"⚠️ 量能偏弱 {vol_ratio:.1f}x"
            strength = "強勢突破" if vol_ratio >= 1.5 else ("有效突破" if vol_ok else "弱勢突破")
            dir_text = "突破" if direction == "above" else "跌破"
            emoji = "🚀" if vol_ok else "⚠️"

            msg = (
                f"{emoji} **{name} {dir_text}關卡！[BN本地]（{strength}）**\n\n"
                f"• 1H 收線: ${prev_close:,.2f} {'>' if direction=='above' else '<'} ${level:,}\n"
                f"• 現價: ${current_price:,.2f}\n"
                f"• {vol_tag}（前10根平均）\n"
                f"• RSI: {rsi:.0f}\n"
                f"• ⏳ 等待回踩確認...\n"
                f"• 時間: {now.strftime('%m/%d %H:%M')}"
            )
            send_discord(msg, pin=True)
            s = {"stage": "confirming", "breakout_time": now.isoformat(), "confirmed_count": 0, "vol_ratio": vol_ratio}

    # 階段 2: 確認中
    elif stage == "confirming":
        bt = datetime.fromisoformat(s["breakout_time"])
        hours_since = (now - bt).total_seconds() / 3600

        if failed:
            msg = (
                f"❌ **{name} 假突破！[BN本地]**\n\n"
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
                    f"✅ **{name} 回踩確認！[BN本地] 站穩 ${level:,}**\n\n"
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
                    f"💪 **{name} 強勢站穩 ${level:,}！[BN本地]**\n\n"
                    f"• 現價: ${current_price:,.2f}\n"
                    f"• 連續 {confirmed} 根 1H 站穩（{hours_since:.0f}h）\n"
                    f"• RSI: {rsi:.0f}\n"
                    f"• ✅ 趨勢確立"
                )
                send_discord(msg, pin=True)
                s["stage"] = "confirmed"

        # 超過 24 小時未確認，重置
        if hours_since > 24 and stage == "confirming":
            s = {"stage": "watching", "breakout_time": None, "confirmed_count": 0}

    # 階段 3: 已確認
    elif stage == "confirmed":
        if failed:
            msg = (
                f"⚠️ **{name} 跌回關卡 ${level:,}！[BN本地]**\n\n"
                f"• 現價: ${current_price:,.2f}\n"
                f"• 注意止損保護"
            )
            send_discord(msg)
            s = {"stage": "watching", "breakout_time": None, "confirmed_count": 0}

    state[key] = s


def backtest(symbol, name, level, direction, days=30):
    """回測突破策略（保留原始功能）"""
    klines = get_klines(symbol, "1h", min(days*24, 1000))
    if not klines or len(klines) < 50:
        print(f"{name}: 資料不足")
        return
    
    # 轉換格式
    candles = [{"t": k["open_time"], "o": k["open"], "h": k["high"],
                "l": k["low"], "c": k["close"], "v": k["volume"]} for k in klines]

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

        t = datetime.fromtimestamp(candles[i]["t"]/1000, tz=TW_TIMEZONE)
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

    # 統計結果
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
    """主程序"""
    import sys
    now = datetime.now(TW_TIMEZONE)

    # 回測模式
    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        levels = load_levels()
        for symbol, cfg in levels.items():
            if cfg.get("above"):
                backtest(symbol, cfg["name"], cfg["above"], "above", days)
            if cfg.get("below"):
                backtest(symbol, cfg["name"], cfg["below"], "below", days)
        return

    # 監控模式
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
