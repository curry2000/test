#!/usr/bin/env python3
"""
OI & Price 異動警報（抓莊神器加強版）
比原版更快：監控 15-30 分鐘內的異動
"""
import requests
import os
import json
from datetime import datetime
from pathlib import Path

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path("/tmp/oi_alert_state.json")
HEADERS = {"User-Agent": "Mozilla/5.0"}

SYMBOLS = [
    "BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "AVAX", "LINK", "DOT",
    "MATIC", "UNI", "ATOM", "LTC", "FIL", "APT", "ARB", "OP", "SUI",
    "PEPE", "SHIB", "WIF", "BONK", "FLOKI", "MEME", "1000SATS",
    "ORDI", "INJ", "SEI", "TIA", "JTO", "PYTH", "JUP", "WLD", "STRK",
    "NEAR", "FTM", "SAND", "MANA", "AXS", "GALA", "IMX", "BLUR"
]

THRESHOLDS = {
    "oi_change_pct": 1.5,
    "price_change_pct": 0.8,
    "oi_mcap_ratio_min": 5.0,
}

def get_okx_ticker(symbol):
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/ticker",
            params={"instId": f"{symbol}-USDT-SWAP"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            d = data["data"][0]
            return {
                "price": float(d["last"]),
                "vol_24h": float(d.get("vol24h", 0)),
                "change_24h": float(d.get("sodUtc8", d["last"])),
            }
    except:
        pass
    return None

def get_okx_oi(symbol):
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/public/open-interest",
            params={"instId": f"{symbol}-USDT-SWAP"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            oi_coin = float(data["data"][0].get("oi", 0))
            return oi_coin
    except:
        pass
    return None

def get_binance_oi(symbol):
    try:
        r = requests.get(
            "https://fapi.binance.com/fapi/v1/openInterest",
            params={"symbol": f"{symbol}USDT"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if "openInterest" in data:
            return float(data["openInterest"])
    except:
        pass
    return None

def get_market_cap(symbol):
    try:
        coin_map = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "DOGE": "dogecoin",
            "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "LINK": "chainlink",
            "DOT": "polkadot", "MATIC": "matic-network", "UNI": "uniswap", "ATOM": "cosmos",
            "LTC": "litecoin", "FIL": "filecoin", "APT": "aptos", "ARB": "arbitrum",
            "OP": "optimism", "SUI": "sui", "PEPE": "pepe", "SHIB": "shiba-inu",
            "WIF": "dogwifhat", "BONK": "bonk", "NEAR": "near", "FTM": "fantom",
            "INJ": "injective-protocol", "SEI": "sei-network", "TIA": "celestia",
        }
        if symbol not in coin_map:
            return None
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_map[symbol], "vs_currencies": "usd", "include_market_cap": "true"},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        coin_id = coin_map[symbol]
        if coin_id in data and "usd_market_cap" in data[coin_id]:
            return data[coin_id]["usd_market_cap"]
    except:
        pass
    return None

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"prices": {}, "oi": {}, "alerts": [], "last_check": None}

def save_state(state):
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def send_discord(msg):
    print(msg)
    if WEBHOOK:
        try:
            for i in range(0, len(msg), 1900):
                requests.post(WEBHOOK, json={"content": msg[i:i+1900], "username": "🔔 抓莊神器"}, timeout=10)
        except Exception as e:
            print(f"Discord error: {e}")

def main():
    print(f"=== OI Alert Start {datetime.now().strftime('%H:%M:%S')} ===")
    state = load_state()
    alerts = []
    
    for symbol in SYMBOLS:
        ticker = get_okx_ticker(symbol)
        if not ticker:
            continue
        
        price = ticker["price"]
        
        current_oi = get_okx_oi(symbol)
        if not current_oi:
            current_oi = get_binance_oi(symbol)
        
        if not current_oi:
            continue
        
        oi_usd = current_oi * price
        
        last_price = state.get("prices", {}).get(symbol, price)
        last_oi = state.get("oi", {}).get(symbol, current_oi)
        
        price_change = (price - last_price) / last_price * 100 if last_price else 0
        oi_change = (current_oi - last_oi) / last_oi * 100 if last_oi else 0
        
        mcap = get_market_cap(symbol)
        oi_mcap_ratio = (oi_usd / mcap * 100) if mcap and mcap > 0 else 0
        
        state.setdefault("prices", {})[symbol] = price
        state.setdefault("oi", {})[symbol] = current_oi
        
        if abs(oi_change) >= THRESHOLDS["oi_change_pct"] or abs(price_change) >= THRESHOLDS["price_change_pct"]:
            if abs(oi_change) < 0.5 and abs(price_change) < 0.5:
                continue
            
            alert_key = f"{symbol}_{datetime.now().strftime('%H%M')}"
            recent_alerts = [a for a in state.get("alerts", []) if a.startswith(symbol)]
            if len(recent_alerts) >= 3:
                continue
            
            if alert_key in state.get("alerts", []):
                continue
            
            if oi_change > 0 and price_change > 0:
                emoji = "🟢"
                signal = "OI↑ 價格↑ 可能拉盤"
            elif oi_change > 0 and price_change < 0:
                emoji = "🔴"
                signal = "OI↑ 價格↓ 可能誘空"
            elif oi_change < 0 and price_change > 0:
                emoji = "🟡"
                signal = "OI↓ 價格↑ 空頭平倉"
            else:
                emoji = "⚫"
                signal = "OI↓ 價格↓ 多頭平倉"
            
            alert = f"{emoji} **{symbol}USDT**\n"
            alert += f"OI 變動: {oi_change:+.1f}% | 價格: {price_change:+.1f}%\n"
            alert += f"OI: ${oi_usd/1e6:.1f}M"
            if oi_mcap_ratio > 0:
                alert += f" | OI/市值: {oi_mcap_ratio:.1f}%"
            alert += f"\n判斷: **{signal}**"
            
            alerts.append(alert)
            state.setdefault("alerts", []).append(alert_key)
            
            print(f"ALERT: {symbol} OI:{oi_change:+.1f}% Price:{price_change:+.1f}%")
    
    if len(state.get("alerts", [])) > 200:
        state["alerts"] = state["alerts"][-100:]
    
    if alerts:
        msg = "🔔 **OI & Price 異動**\n\n" + "\n\n".join(alerts[:5]) + f"\n\n⏰ {datetime.now().strftime('%H:%M')}"
        send_discord(msg)
    else:
        print("No alerts")
    
    save_state(state)
    print("=== Done ===")

if __name__ == "__main__":
    main()
