#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime
from pathlib import Path

STATE_FILE = Path("/tmp/monitor_state.json")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

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

OI_CHANGE_THRESHOLD = 0.015
PRICE_CHANGE_THRESHOLD = 0.01
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
RSI_PERIOD = 14

def get_binance_price(symbol):
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            item = data["result"]["list"][0]
            return {
                "price": float(item["lastPrice"]),
                "change_24h": float(item["price24hPcnt"]),
                "source": "Bybit"
            }
    except:
        pass
    
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": f"{symbol}-USDT-SWAP"},
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            item = data["data"][0]
            open_24h = float(item.get("open24h", item["last"]))
            last = float(item["last"])
            change = (last - open_24h) / open_24h if open_24h else 0
            return {
                "price": last,
                "change_24h": change,
                "source": "OKX"
            }
    except:
        pass
    
    try:
        coin_id = "bitcoin" if symbol == "BTC" else "ethereum" if symbol == "ETH" else symbol.lower()
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10
        )
        data = r.json()
        if coin_id in data:
            return {
                "price": float(data[coin_id]["usd"]),
                "change_24h": float(data[coin_id].get("usd_24h_change", 0)) / 100,
                "source": "CoinGecko"
            }
    except:
        pass
    
    return None

def get_binance_oi(symbol):
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear", "symbol": f"{symbol}USDT"},
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            item = data["result"]["list"][0]
            return float(item.get("openInterest", 0))
    except:
        pass
    
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/public/open-interest",
            params={"instId": f"{symbol}-USDT-SWAP"},
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            return float(data["data"][0].get("oi", 0))
    except:
        pass
    
    return None

def get_klines_for_rsi(symbol, interval="1h", limit=50):
    try:
        interval_map = {"15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "interval": interval_map.get(interval, "60"),
                "limit": limit
            },
            timeout=15
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            closes = [float(k[4]) for k in reversed(data["result"]["list"])]
            return closes
    except:
        pass
    
    try:
        interval_map = {"15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={
                "instId": f"{symbol}-USDT-SWAP",
                "bar": interval_map.get(interval, "1H"),
                "limit": str(limit)
            },
            timeout=15
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            closes = [float(k[4]) for k in reversed(data["data"])]
            return closes
    except:
        pass
    
    return []

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def get_rsi(symbol, interval="1h"):
    closes = get_klines_for_rsi(symbol, interval, 50)
    if closes:
        return calculate_rsi(closes, RSI_PERIOD)
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
            "username": "🔔 Monitor"
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
        
        for level in config.get("danger_levels", []):
            key = f"{symbol}_danger_{level}"
            if price <= level and key not in triggered:
                alerts.append(f"🚨 **{symbol} ${level:,}** ${price:,.2f}")
                triggered.append(key)
        
        for level in config.get("resistance_levels", []):
            key = f"{symbol}_res_{level}"
            if abs(price - level) / level < 0.01 and key not in triggered:
                alerts.append(f"📈 {symbol} R ${level:,} (${price:,.2f})")
                triggered.append(key)
        
        for level in config.get("support_levels", []):
            key = f"{symbol}_sup_{level}"
            if abs(price - level) / level < 0.01 and key not in triggered:
                alerts.append(f"📉 {symbol} S ${level:,} (${price:,.2f})")
                triggered.append(key)
        
        last_oi = state.get("last_oi", {}).get(symbol)
        if last_oi and current_oi:
            oi_change = (current_oi - last_oi) / last_oi
            if abs(oi_change) >= OI_CHANGE_THRESHOLD:
                direction = "📈" if oi_change > 0 else "📉"
                alerts.append(f"📊 {symbol} OI {direction} {abs(oi_change)*100:.1f}%")
        
        for tf in ["15m", "30m", "1h", "4h"]:
            rsi = get_rsi(symbol, tf)
            if rsi:
                if rsi <= RSI_OVERSOLD and f"{symbol}_oversold_{tf}" not in triggered:
                    alerts.append(f"🔴 {symbol} {tf} RSI={rsi}")
                    triggered.append(f"{symbol}_oversold_{tf}")
                elif rsi >= RSI_OVERBOUGHT and f"{symbol}_overbought_{tf}" not in triggered:
                    alerts.append(f"🟢 {symbol} {tf} RSI={rsi}")
                    triggered.append(f"{symbol}_overbought_{tf}")
        
        last_price = state.get("last_prices", {}).get(symbol)
        if last_price:
            price_change = (price - last_price) / last_price
            if abs(price_change) >= PRICE_CHANGE_THRESHOLD:
                direction = "🚀" if price_change > 0 else "💥"
                alerts.append(f"⚡ {symbol} {direction} {abs(price_change)*100:.1f}% (${last_price:,.0f}→${price:,.0f})")
        
        state.setdefault("last_prices", {})[symbol] = price
        if current_oi:
            state.setdefault("last_oi", {})[symbol] = current_oi
        state["triggered_alerts"] = triggered
    
    save_state(state)
    
    if alerts:
        msg = "🔔 **Alert**\n\n" + "\n".join(alerts) + f"\n\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        send_discord_alert(msg)
        print(msg)
    else:
        print("OK")

if __name__ == "__main__":
    alerts = run_monitor()
    if not alerts:
        import requests as req
        webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if webhook:
            btc = get_binance_price("BTC")
            eth = get_binance_price("ETH")
            btc_price = btc['price'] if btc else 0
            eth_price = eth['price'] if eth else 0
            btc_src = btc.get('source', '?') if btc else '?'
            eth_src = eth.get('source', '?') if eth else '?'
            
            def rsi_emoji(rsi):
                if rsi is None or rsi == 0: return "❓"
                if rsi <= 30: return "🔴"
                if rsi >= 70: return "🟢"
                return "⚪"
            
            def get_rsi_line(symbol):
                rsis = {}
                for tf in ["15m", "30m", "1h", "4h"]:
                    rsis[tf] = get_rsi(symbol, tf) or 0
                return f"  15m:{rsi_emoji(rsis['15m'])}{rsis['15m']} | 30m:{rsi_emoji(rsis['30m'])}{rsis['30m']} | 1H:{rsi_emoji(rsis['1h'])}{rsis['1h']} | 4H:{rsi_emoji(rsis['4h'])}{rsis['4h']}"
            
            msg = f"✅ **OK** ({btc_src})\n\n"
            msg += f"**BTC** ${btc_price:,.2f}\n"
            msg += get_rsi_line("BTC") + "\n\n"
            msg += f"**ETH** ${eth_price:,.2f}\n"
            msg += get_rsi_line("ETH") + "\n\n"
            msg += f"🔴<30 | ⚪- | 🟢>70\n"
            msg += f"⏰ {datetime.now().strftime('%H:%M:%S UTC')}"
            req.post(webhook, json={"content": msg, "username": "🔔 Monitor"}, timeout=10)
