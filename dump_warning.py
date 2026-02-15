import requests
import os
import json
from datetime import datetime, timezone, timedelta

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = os.path.expanduser("~/.openclaw/dump_warning_state.json")
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

def send_discord(message):
    if not DISCORD_WEBHOOK:
        print("No webhook")
        return
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
        print(f"Discord: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def get_klines(symbol, interval, limit):
    try:
        r = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}", timeout=10)
        d = r.json()
        if isinstance(d, list):
            return [{"t":int(k[0]),"o":float(k[1]),"h":float(k[2]),"l":float(k[3]),"c":float(k[4]),"v":float(k[5])} for k in d]
    except:
        pass
    return []

def calc_rsi_series(closes, period=14):
    if len(closes) < period+1:
        return [50]*len(closes)
    rsis = [50]*period
    gains, losses = [], []
    for i in range(1, period+1):
        d = closes[i]-closes[i-1]
        gains.append(d if d>0 else 0)
        losses.append(-d if d<0 else 0)
    ag = sum(gains)/period
    al = sum(losses)/period
    for i in range(period, len(closes)):
        d = closes[i]-closes[i-1]
        g = d if d>0 else 0
        l = -d if d<0 else 0
        ag = (ag*(period-1)+g)/period
        al = (al*(period-1)+l)/period
        rsis.append(100 if al==0 else 100-(100/(1+ag/al)))
    return rsis

def get_top_coins(limit=50):
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10)
        data = r.json()
        if not isinstance(data, list):
            return []
        usdt = [d for d in data if d["symbol"].endswith("USDT")]
        usdt.sort(key=lambda x: float(x.get("quoteVolume", 0)), reverse=True)
        return [d["symbol"] for d in usdt[:limit]]
    except:
        return []

def scan_coin(symbol, candles_1h_map=None):
    c5 = get_klines(symbol, "5m", 60)
    if len(c5) < 40:
        return None

    closes = [c["c"] for c in c5]
    highs = [c["h"] for c in c5]
    volumes = [c["v"] for c in c5]
    rsis = calc_rsi_series(closes)

    i = len(c5) - 1
    rsi_now = rsis[i]
    price_now = closes[i]

    if rsi_now < 65:
        return None

    score = 0
    signals = []
    lb = min(36, i)

    w_rsi = rsis[max(0,i-lb):i+1]
    w_high = highs[max(0,i-lb):i+1]

    if len(w_rsi) > 6:
        rsi_peak_val = max(w_rsi)
        rsi_peak_idx = w_rsi.index(rsi_peak_val)
        price_peak_idx = w_high.index(max(w_high))

        if price_peak_idx > rsi_peak_idx + 3 and rsi_peak_val - w_rsi[price_peak_idx] > 8:
            div = rsi_peak_val - w_rsi[price_peak_idx]
            if div > 15:
                score += 40
                signals.append(f"RSI強背離(差{div:.0f})")
            else:
                score += 25
                signals.append(f"RSI背離(差{div:.0f})")

    for c in c5[-7:]:
        wick = (c["h"] - max(c["o"],c["c"])) / c["o"] * 100
        body = abs(c["c"]-c["o"])/c["o"]*100
        if wick > 3 and body < 1:
            score += 30
            signals.append(f"假突破(影{wick:.1f}%)")
            break
        elif wick > 2 and c["c"] < c["o"]:
            score += 20
            signals.append(f"沖高回落(影{wick:.1f}%)")
            break

    if i >= 12:
        first = sum(volumes[i-12:i-6])/6
        second = sum(volumes[i-6:i+1])/7
        if first > 0:
            ratio = second/first
            if ratio < 0.35:
                score += 25
                signals.append(f"量枯竭({ratio:.2f}x)")
            elif ratio < 0.5:
                score += 15
                signals.append(f"量萎縮({ratio:.2f}x)")

    red_count = sum(1 for j in range(max(0,i-4),i+1) if c5[j]["c"] < c5[j]["o"])
    if red_count >= 4:
        score += 25
        signals.append(f"連{red_count}紅K")
    elif red_count >= 3:
        drop = (c5[i-2]["o"]-closes[i])/c5[i-2]["o"]*100
        if drop > 2:
            score += 15
            signals.append(f"連3紅跌{drop:.1f}%")

    if rsi_now > 85:
        score += 15
        signals.append(f"RSI極高{rsi_now:.0f}")
    elif rsi_now > 75:
        score += 8

    if i >= 24:
        rng_h = max(closes[i-24:i+1])
        rng_l = min(closes[i-24:i+1])
        if rng_h > 0 and (rng_h-rng_l)/rng_h*100 < 3 and rsi_now > 70:
            score += 15
            signals.append("高位盤整")

    c1h = candles_1h_map.get(symbol) if candles_1h_map else None
    if not c1h:
        c1h = get_klines(symbol, "1h", 30)
    if c1h and len(c1h) > 15:
        rsi_1h = calc_rsi_series([c["c"] for c in c1h])
        if len(rsi_1h) >= 3:
            r1h = rsi_1h[-1]
            r1h_p = rsi_1h[-3]
            if r1h < r1h_p - 5 and r1h > 55:
                score += 20
                signals.append(f"1H RSI轉弱({r1h_p:.0f}→{r1h:.0f})")
            elif r1h > 80:
                score += 10
                signals.append(f"1H超買{r1h:.0f}")

    if score >= 55 and len(signals) >= 2:
        name = symbol.replace("USDT", "")
        grade = ""
        emoji = ""
        if score >= 75:
            grade = "高危"
            emoji = "🔴"
        elif score >= 60:
            grade = "警戒"
            emoji = "🟡"
        else:
            grade = "注意"
            emoji = "⚠️"

        return {
            "symbol": name,
            "price": price_now,
            "rsi": rsi_now,
            "score": score,
            "grade": grade,
            "emoji": emoji,
            "signals": signals
        }

    return None

def main():
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    state = load_state()

    coins = get_top_coins(80)
    if not coins:
        print("Failed to get coin list")
        return

    print(f"Scanning {len(coins)} coins for dump warnings...")

    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=10)
        ticker_data = r.json()
        price_changes = {}
        if isinstance(ticker_data, list):
            for t in ticker_data:
                price_changes[t["symbol"]] = float(t.get("priceChangePercent", 0))
    except:
        price_changes = {}

    candidates = []
    for sym in coins:
        chg = price_changes.get(sym, 0)
        if chg > 10:
            candidates.append(sym)

    if not candidates:
        candidates = coins[:20]

    print(f"  Pre-filter: {len(candidates)} coins with 24H change > 10%")

    import time
    alerts = []
    for sym in candidates:
        try:
            result = scan_coin(sym)
            if result:
                key = f"{result['symbol']}_dump"
                last = state.get(key, "")
                if last:
                    try:
                        lt = datetime.fromisoformat(last)
                        if (now - lt).total_seconds() < 3600:
                            print(f"  {result['symbol']}: 1H內已通知，跳過")
                            continue
                    except:
                        pass

                alerts.append(result)
                state[key] = now.isoformat()
                print(f"  {result['emoji']} {result['symbol']} ${result['price']:.4f} 分{result['score']} {result['grade']} | {', '.join(result['signals'])}")
            time.sleep(0.1)
        except Exception as e:
            print(f"  {sym} error: {e}")

    if alerts:
        alerts.sort(key=lambda x: x["score"], reverse=True)

        lines = [f"⚠️ **下跌預警** | {now.strftime('%m/%d %H:%M')}\n"]
        for a in alerts[:8]:
            sig_text = " + ".join(a["signals"][:3])
            lines.append(
                f"{a['emoji']} **{a['symbol']}** ${a['price']:,.4f} | "
                f"分數 {a['score']} ({a['grade']}) | RSI {a['rsi']:.0f}\n"
                f"  → {sig_text}"
            )
        lines.append("\n💡 預警≠做空信號，建議：有多單先收利潤/移止損")

        msg = "\n".join(lines)
        print(f"\n{msg}")
        send_discord(msg)
    else:
        print("No dump warnings")

    save_state(state)

if __name__ == "__main__":
    main()
