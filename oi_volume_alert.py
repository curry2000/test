#!/usr/bin/env python3
"""
OI + Volume 異動警報（抓莊神器）
監控 5 分鐘內 OI 和成交量的異常變動
"""
import requests
import os
import json
from datetime import datetime
from pathlib import Path

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path("/tmp/oi_volume_state.json")
HEADERS = {"User-Agent": "Mozilla/5.0"}

SYMBOLS = ["BTC", "ETH", "SOL", "DOGE", "XRP"]

THRESHOLDS = {
    "oi_change_pct": 2.0,
    "volume_spike_mult": 2.0,
    "price_change_pct": 1.0,
}

def get_okx_data(symbol):
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
                "source": "OKX"
            }
    except Exception as e:
        print(f"OKX ticker error for {symbol}: {e}")
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
            return float(data["data"][0].get("oi", 0))
    except Exception as e:
        print(f"OKX OI error for {symbol}: {e}")
    return None

def get_okx_recent_volume(symbol, minutes=5):
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": f"{symbol}-USDT-SWAP", "bar": "1m", "limit": str(minutes)},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            volumes = [float(k[5]) for k in data["data"]]
            return sum(volumes)
    except Exception as e:
        print(f"OKX volume error for {symbol}: {e}")
    return None

def get_avg_volume(symbol, periods=30):
    try:
        r = requests.get(
            "https://www.okx.com/api/v5/market/candles",
            params={"instId": f"{symbol}-USDT-SWAP", "bar": "5m", "limit": str(periods)},
            headers=HEADERS,
            timeout=10
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            volumes = [float(k[5]) for k in data["data"][1:]]
            return sum(volumes) / len(volumes) if volumes else 0
    except Exception as e:
        print(f"OKX avg volume error for {symbol}: {e}")
    return 0

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"prices": {}, "oi": {}, "alerts": []}

def save_state(state):
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def send_discord(msg, username="🔔 OI/Volume 異動"):
    print(msg)
    if WEBHOOK:
        try:
            r = requests.post(WEBHOOK, json={"content": msg, "username": username}, timeout=10)
            print(f"Discord: {r.status_code}")
        except Exception as e:
            print(f"Discord error: {e}")

def main():
    print("=== OI/Volume Alert Start ===")
    state = load_state()
    alerts = []
    
    for symbol in SYMBOLS:
        print(f"\nChecking {symbol}...")
        
        ticker = get_okx_data(symbol)
        current_oi = get_okx_oi(symbol)
        recent_vol = get_okx_recent_volume(symbol, 5)
        avg_vol = get_avg_volume(symbol, 30)
        
        if not ticker:
            print(f"  No ticker data")
            continue
        
        price = ticker["price"]
        last_price = state.get("prices", {}).get(symbol, price)
        last_oi = state.get("oi", {}).get(symbol)
        
        price_change = (price - last_price) / last_price * 100 if last_price else 0
        oi_change = ((current_oi - last_oi) / last_oi * 100) if last_oi and current_oi else 0
        vol_mult = (recent_vol / avg_vol) if avg_vol and recent_vol else 1
        
        print(f"  Price: ${price:,.2f} ({price_change:+.2f}%)")
        print(f"  OI: {current_oi:,.0f} ({oi_change:+.2f}%)" if current_oi else "  OI: N/A")
        print(f"  Vol 5m: {recent_vol:,.0f} ({vol_mult:.1f}x avg)" if recent_vol else "  Vol: N/A")
        
        signal_strength = 0
        signals = []
        
        if abs(oi_change) >= THRESHOLDS["oi_change_pct"]:
            signal_strength += 1
            direction = "📈 增加" if oi_change > 0 else "📉 減少"
            signals.append(f"OI {direction} {abs(oi_change):.1f}%")
        
        if vol_mult >= THRESHOLDS["volume_spike_mult"]:
            signal_strength += 1
            signals.append(f"成交量 {vol_mult:.1f}x 平均")
        
        if abs(price_change) >= THRESHOLDS["price_change_pct"]:
            signal_strength += 1
            direction = "上漲" if price_change > 0 else "下跌"
            signals.append(f"價格{direction} {abs(price_change):.1f}%")
        
        if signal_strength >= 2:
            alert_key = f"{symbol}_{datetime.now().strftime('%H%M')}"
            if alert_key not in state.get("alerts", []):
                emoji = "🚀" if price_change > 0 else "💥"
                direction_hint = "可能拉盤" if (oi_change > 0 and price_change > 0) else "可能砸盤" if (oi_change > 0 and price_change < 0) else "觀察中"
                
                alert = f"{emoji} **{symbol}** 異動警報！\n"
                alert += f"價格: ${price:,.2f}\n"
                alert += f"信號: {' | '.join(signals)}\n"
                alert += f"判斷: **{direction_hint}**"
                
                alerts.append(alert)
                state.setdefault("alerts", []).append(alert_key)
                if len(state["alerts"]) > 100:
                    state["alerts"] = state["alerts"][-50:]
        
        state.setdefault("prices", {})[symbol] = price
        if current_oi:
            state.setdefault("oi", {})[symbol] = current_oi
    
    if alerts:
        msg = "🔔 **OI/成交量異動**\n\n" + "\n\n".join(alerts) + f"\n\n⏰ {datetime.now().strftime('%H:%M')}"
        send_discord(msg)
    else:
        print("\nNo alerts triggered")
    
    save_state(state)
    print("\n=== Done ===")

if __name__ == "__main__":
    main()
