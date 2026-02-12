#!/usr/bin/env python3
"""
加密貨幣監控 - Discord Webhook 版本（零 Token 消耗）
"""

import requests
import json
import os
from datetime import datetime
from pathlib import Path

# GitHub Actions 無狀態，每次都是新環境
STATE_FILE = Path("/tmp/monitor_state.json")

# ========== Discord Webhook ==========
# 請在 Discord 頻道設定 > 整合 > Webhook 建立一個，然後貼上 URL
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# ========== 監控設定 ==========
ALERTS = {
    "BTC": {
        "danger_levels": [59800, 52000],
        "resistance_levels": [67500, 68800, 71500, 72000, 74000, 76000],
        "support_levels": [66000, 65700, 63800],
    },
    "ETH": {
        "danger_levels": [1750, 1500],
        "resistance_levels": [1980, 2000, 2100, 2150, 2250],
        "support_levels": [1920, 1900, 1850],
    }
}

OI_CHANGE_THRESHOLD = 0.015      # 1.5% OI 變動
PRICE_CHANGE_THRESHOLD = 0.01    # 1% 價格波動

def get_binance_price(symbol):
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            params={"symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        return {
            "price": float(data["lastPrice"]),
            "change_24h": float(data["priceChangePercent"]) / 100
        }
    except:
        return None

def get_binance_oi(symbol):
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        return float(data["openInterest"])
    except:
        return None

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_prices": {}, "last_oi": {}, "triggered_alerts": []}

def save_state(state):
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def send_discord_alert(message):
    if not DISCORD_WEBHOOK_URL:
        print(f"[NO WEBHOOK] {message}")
        return
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={
            "content": message,
            "username": "🔔 加密貨幣監控"
        }, timeout=10)
    except Exception as e:
        print(f"Webhook error: {e}")

def run_monitor():
    state = load_state()
    alerts = []
    
    for symbol in ["BTC", "ETH"]:
        price_data = get_binance_price(symbol)
        current_oi = get_binance_oi(symbol)
        
        if not price_data:
            continue
        
        price = price_data["price"]
        config = ALERTS.get(symbol, {})
        triggered = state.get("triggered_alerts", [])
        
        # 危險線
        for level in config.get("danger_levels", []):
            key = f"{symbol}_danger_{level}"
            if price <= level and key not in triggered:
                alerts.append(f"🚨 **{symbol} 跌破危險線 ${level:,}！** 當前 ${price:,.2f}")
                triggered.append(key)
        
        # 壓力位
        for level in config.get("resistance_levels", []):
            key = f"{symbol}_res_{level}"
            if abs(price - level) / level < 0.01 and key not in triggered:
                alerts.append(f"📈 {symbol} 接近壓力位 ${level:,}（當前 ${price:,.2f}）")
                triggered.append(key)
        
        # 支撐位
        for level in config.get("support_levels", []):
            key = f"{symbol}_sup_{level}"
            if abs(price - level) / level < 0.01 and key not in triggered:
                alerts.append(f"📉 {symbol} 接近支撐位 ${level:,}（當前 ${price:,.2f}）")
                triggered.append(key)
        
        # OI 變動
        last_oi = state.get("last_oi", {}).get(symbol)
        if last_oi and current_oi:
            oi_change = (current_oi - last_oi) / last_oi
            if abs(oi_change) >= OI_CHANGE_THRESHOLD:
                direction = "📈 增加" if oi_change > 0 else "📉 減少"
                alerts.append(f"📊 {symbol} OI {direction} {abs(oi_change)*100:.1f}%")
        
        # 價格波動
        last_price = state.get("last_prices", {}).get(symbol)
        if last_price:
            price_change = (price - last_price) / last_price
            if abs(price_change) >= PRICE_CHANGE_THRESHOLD:
                direction = "🚀 上漲" if price_change > 0 else "💥 下跌"
                alerts.append(f"⚡ {symbol} 快速{direction} {abs(price_change)*100:.1f}%！(${last_price:,.0f} → ${price:,.0f})")
        
        # 更新狀態
        state.setdefault("last_prices", {})[symbol] = price
        if current_oi:
            state.setdefault("last_oi", {})[symbol] = current_oi
        state["triggered_alerts"] = triggered
    
    save_state(state)
    
    if alerts:
        msg = "🔔 **加密貨幣監控警報**\n\n" + "\n".join(alerts) + f"\n\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        send_discord_alert(msg)
        print(msg)
    else:
        print("✅ 無警報")

if __name__ == "__main__":
    run_monitor()
