#!/usr/bin/env python3
"""
5-Minute OI Alert System (預警版)
- 每 5 分鐘抓取所有 USDT 永續合約的 OI
- 與上一次快照比較，偵測異常 OI 變化
- 發送 Discord 預警（不開倉）
- 完全獨立於 oi_scanner.py
"""

import json
import os
import time
from datetime import datetime, timedelta

# 使用共用模組
from config import (
    OI_5MIN_SNAPSHOT_FILE,
    OI_5MIN_ALERT_HISTORY,
    OI_5MIN_CHANGE_THRESHOLD,
    OI_5MIN_CHANGE_EXTREME,
    OI_5MIN_PRICE_MOVE_THRESHOLD,
    OI_5MIN_ALERT_COOLDOWN_MIN,
    MIN_OI_USD,
    MIN_VOLUME_24H,
    EXCLUDED_SYMBOLS,
    TW_TIMEZONE,
    DISCORD_5MIN_THREAD_ID
)
from exchange_api import (
    get_open_interest,
    get_ticker,
    get_all_tickers,
    get_klines,
    get_exchange_info
)
from notify import send_discord_message


def get_trading_symbols():
    """取得目前可交易的 USDT 永續合約"""
    try:
        info = get_exchange_info()
        symbols = []
        for s in info.get("symbols", []):
            base = s.get("base", s.get("symbol", "").replace("USDT", ""))
            if (s.get("status") == "TRADING" and
                base not in EXCLUDED_SYMBOLS and
                base):
                symbols.append(base)
        return symbols
    except Exception as e:
        print(f"[ERROR] get_trading_symbols: {e}")
    return []


def calc_rsi(symbol, period=14):
    """計算 1H RSI"""
    try:
        klines = get_klines(symbol, "1h", period + 2)
        if not klines or len(klines) < period + 1:
            return None
        
        closes = [k["close"] for k in klines]
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    except:
        return None


def load_snapshots():
    """載入上次的 OI 快照"""
    if os.path.exists(OI_5MIN_SNAPSHOT_FILE):
        try:
            with open(OI_5MIN_SNAPSHOT_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"timestamp": None, "data": {}}


def save_snapshots(snapshots):
    """儲存 OI 快照"""
    os.makedirs(os.path.dirname(OI_5MIN_SNAPSHOT_FILE), exist_ok=True)
    with open(OI_5MIN_SNAPSHOT_FILE, "w") as f:
        json.dump(snapshots, f)


def load_alert_history():
    """載入預警歷史（冷卻用）"""
    if os.path.exists(OI_5MIN_ALERT_HISTORY):
        try:
            with open(OI_5MIN_ALERT_HISTORY) as f:
                return json.load(f)
        except:
            pass
    return {}


def save_alert_history(history):
    """儲存預警歷史"""
    os.makedirs(os.path.dirname(OI_5MIN_ALERT_HISTORY), exist_ok=True)
    with open(OI_5MIN_ALERT_HISTORY, "w") as f:
        json.dump(history, f)


def is_in_cooldown(symbol, history):
    """檢查是否在冷卻期"""
    last = history.get(symbol)
    if not last:
        return False
    try:
        last_time = datetime.fromisoformat(last)
        now = datetime.now(TW_TIMEZONE)
        diff = (now - last_time).total_seconds() / 60
        return diff < OI_5MIN_ALERT_COOLDOWN_MIN
    except:
        return False


def send_discord_alert(alerts):
    """發送 Discord 預警"""
    if not alerts:
        return

    now = datetime.now(TW_TIMEZONE)
    lines = [f"## ⚡ 5min OI 預警 | {now.strftime('%m/%d %H:%M')}"]
    lines.append("")

    for a in alerts:
        level = "🔴" if a["oi_change"] >= OI_5MIN_CHANGE_EXTREME else "🟡"
        direction = "📈" if a["price_change"] > 0 else "📉"

        lines.append(f"{level} **{a['symbol']}** | OI {a['oi_change']:+.1f}% | 價格 {a['price_change']:+.1f}%")
        lines.append(f"   價格 ${a['price']:.4g} | RSI {a['rsi']:.0f} | OI ${a['oi_usd']/1e6:.1f}M | 24h量 ${a['volume_24h']/1e6:.0f}M")

        # 判斷信號類型
        if a["oi_change"] > 0 and a["price_change"] > 0:
            sig = "LONG 信號（OI↑ 價格↑）"
        elif a["oi_change"] > 0 and a["price_change"] < 0:
            sig = "SHAKEOUT 疑似（OI↑ 價格↓）"
        elif a["oi_change"] < 0 and a["price_change"] > 0:
            sig = "SQUEEZE 疑似（OI↓ 價格↑）"
        else:
            sig = "SHORT 信號（OI↑ 價格↓）" if a["oi_change"] > 0 else "清倉（OI↓ 價格↓）"
        lines.append(f"   → {direction} {sig}")
        lines.append("")

    lines.append(f"*⚠️ 僅預警，不自動開倉*")

    message = "\n".join(lines)
    success = send_discord_message(message, thread_id=DISCORD_5MIN_THREAD_ID)
    
    if success:
        print(f"[OK] Discord 預警已發送 ({len(alerts)} 筆)")
    else:
        print(f"[ERROR] Discord 預警發送失敗")


def batch_get_tickers():
    """批次取得所有 ticker（一次 API call）"""
    try:
        tickers = get_all_tickers()
        result = {}
        for t in tickers:
            sym = t["symbol"]
            if sym.endswith("USDT"):
                base = sym[:-4]
                result[base] = {
                    "price": t["price"],
                    "volume_24h": t["volume_24h"],
                    "price_change_pct": t["price_change_pct"],
                }
        return result
    except Exception as e:
        print(f"[ERROR] batch_get_tickers: {e}")
    return {}


def scan():
    """主掃描邏輯"""
    now = datetime.now(TW_TIMEZONE)
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] 5min OI 掃描開始")

    # 載入上次快照
    prev = load_snapshots()
    prev_data = prev.get("data", {})
    prev_ts = prev.get("timestamp")

    if prev_ts:
        print(f"  上次快照: {prev_ts}")
    else:
        print("  首次執行，建立基準快照")

    # 批次取得所有 ticker（1 次 API call）
    all_tickers = batch_get_tickers()
    print(f"  Tickers: {len(all_tickers)}")

    # 先用成交量過濾，只對高量幣查 OI（減少 API calls）
    high_vol_symbols = [s for s, t in all_tickers.items()
                        if t["volume_24h"] >= MIN_VOLUME_24H]
    print(f"  高量幣 (>{MIN_VOLUME_24H/1e6:.0f}M): {len(high_vol_symbols)}")

    current_data = {}
    alerts = []
    alert_history = load_alert_history()

    for i, symbol in enumerate(high_vol_symbols):
        oi = get_open_interest(symbol)
        if oi is None:
            continue

        ticker = all_tickers[symbol]
        price = ticker["price"]
        oi_usd = oi * price

        current_data[symbol] = {
            "oi": oi,
            "price": price,
            "oi_usd": oi_usd,
        }

        # 過濾 OI 太小的
        if oi_usd < MIN_OI_USD:
            continue

        # 比較上次
        if symbol not in prev_data:
            continue

        prev_oi = prev_data[symbol].get("oi", 0)
        prev_price = prev_data[symbol].get("price", 0)

        if prev_oi <= 0 or prev_price <= 0:
            continue

        oi_change = (oi - prev_oi) / prev_oi * 100
        price_change = (price - prev_price) / prev_price * 100

        # 檢查門檻
        if abs(oi_change) >= OI_5MIN_CHANGE_THRESHOLD:
            if is_in_cooldown(symbol, alert_history):
                print(f"  {symbol}: OI {oi_change:+.1f}% (冷卻中)")
                continue

            rsi = calc_rsi(symbol) or 50

            alerts.append({
                "symbol": symbol,
                "oi_change": oi_change,
                "price_change": price_change,
                "price": price,
                "rsi": rsi,
                "oi_usd": oi_usd,
                "volume_24h": ticker["volume_24h"],
            })

            alert_history[symbol] = now.isoformat()
            print(f"  🚨 {symbol}: OI {oi_change:+.1f}% 價格 {price_change:+.1f}%")

        # Rate limit: ~5 req/sec
        if (i + 1) % 5 == 0:
            time.sleep(0.3)

    # 儲存快照
    save_snapshots({
        "timestamp": now.isoformat(),
        "data": current_data,
    })

    # 清理過期冷卻
    cutoff = (now - timedelta(hours=24)).isoformat()
    alert_history = {k: v for k, v in alert_history.items() if v > cutoff}
    save_alert_history(alert_history)

    # 排序發送
    alerts.sort(key=lambda x: -abs(x["oi_change"]))

    if alerts:
        send_discord_alert(alerts)
        print(f"  預警: {len(alerts)} 筆")
    else:
        print(f"  無異常")

    print(f"  快照已儲存 ({len(current_data)} 幣)")


if __name__ == "__main__":
    scan()
