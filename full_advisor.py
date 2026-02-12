#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime
from pathlib import Path

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
STATE_FILE = Path(__file__).parent / "full_advisor_state.json"

POSITIONS = [
    {
        "id": "BTC_COIN",
        "name": "BTC 幣本位",
        "symbol": "BTC",
        "entry": 75225,
        "size": 0.9046,
        "liq_price": 40336,
        "leverage": 2.2,
        "add_levels": [
            {"price": 63000, "amount": 0.3, "note": "第一批"},
            {"price": 59800, "amount": 0.3, "note": "第二批"},
            {"price": 57000, "amount": 0.3, "note": "第三批"},
        ]
    },
    {
        "id": "BTC_USDT",
        "name": "BTC U本位",
        "symbol": "BTC",
        "entry": 86265,
        "size": 1.109,
        "liq_price": 45667,
        "leverage": 2.1,
        "strategy": "reduce",
        "reduce_levels": [
            {"price": 72000, "percent": 30, "note": "反彈減倉"},
            {"price": 76000, "percent": 30, "note": "接近成本"},
            {"price": 80000, "percent": 40, "note": "回本清倉"},
        ]
    },
    {
        "id": "ETH_COIN",
        "name": "ETH 幣本位",
        "symbol": "ETH",
        "entry": 2253.98,
        "size": 15.45,
        "liq_price": 1234,
        "leverage": 2.2,
        "add_levels": [
            {"price": 1800, "amount": 5, "note": "第一批"},
            {"price": 1650, "amount": 5, "note": "第二批"},
            {"price": 1500, "amount": 5, "note": "第三批"},
        ]
    }
]

THRESHOLDS = {
    "rsi_oversold": 30,
    "rsi_extreme": 25,
    "fear_greed_buy": 20,
    "fear_greed_strong_buy": 10,
    "funding_negative_periods": 3,
    "min_score_to_add": 70,
    "price_near_level_pct": 3,
}

def get_price(symbol):
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
                'price': float(item["lastPrice"]),
                'change_24h': float(item["price24hPcnt"]) * 100
            }
    except:
        pass
    
    try:
        r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr',
                         params={'symbol': f'{symbol}USDT'}, timeout=10)
        d = r.json()
        return {
            'price': float(d['lastPrice']),
            'change_24h': float(d['priceChangePercent'])
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
            return {
                'price': float(item["last"]),
                'change_24h': 0
            }
    except:
        pass
    
    return None

def get_rsi(symbol, interval='1d'):
    try:
        interval_map = {"1d": "D", "4h": "240", "1h": "60"}
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={
                "category": "linear",
                "symbol": f"{symbol}USDT",
                "interval": interval_map.get(interval, "D"),
                "limit": 20
            },
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            closes = [float(k[4]) for k in reversed(data["result"]["list"])]
            deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [d if d > 0 else 0 for d in deltas]
            losses = [-d if d < 0 else 0 for d in deltas]
            avg_gain = sum(gains[-14:]) / 14
            avg_loss = sum(losses[-14:]) / 14
            if avg_loss == 0:
                return 100
            rs = avg_gain / avg_loss
            return round(100 - (100 / (1 + rs)), 2)
    except:
        pass
    return None

def get_funding(symbol):
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/funding/history",
            params={"category": "linear", "symbol": f"{symbol}USDT", "limit": 10},
            timeout=10
        )
        data = r.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            rates = [float(d['fundingRate']) for d in data["result"]["list"]]
            return {
                'current': rates[0],
                'negative_count': sum(1 for r in rates if r < 0)
            }
    except:
        pass
    return None

def get_fear_greed():
    try:
        r = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
        return int(r.json()['data'][0]['value'])
    except:
        return None

def analyze_position(pos, market_data):
    symbol = pos['symbol']
    price = market_data[symbol]['price']
    
    if price == 0:
        return None
    
    entry = pos['entry']
    liq = pos['liq_price']
    
    pnl_pct = (price - entry) / entry * 100
    liq_distance = (price - liq) / price * 100
    recover_pct = (entry - price) / price * 100 if price < entry else 0
    
    result = {
        'id': pos['id'],
        'name': pos['name'],
        'symbol': symbol,
        'entry': entry,
        'current_price': price,
        'pnl_pct': round(pnl_pct, 2),
        'liq_distance': round(liq_distance, 2),
        'recover_pct': round(recover_pct, 2),
        'alerts': [],
        'actions': []
    }
    
    if pos.get('strategy') == 'reduce':
        result['strategy'] = 'reduce'
        for level in pos.get('reduce_levels', []):
            target = level['price']
            if price >= target * 0.97:
                result['alerts'].append(f"📈 接近減倉點 ${target:,}（{level['note']}）")
                result['actions'].append({
                    'action': 'reduce',
                    'price': target,
                    'percent': level['percent'],
                    'note': level['note']
                })
    else:
        result['strategy'] = 'add'
        for level in pos.get('add_levels', []):
            target = level['price']
            distance_to_target = (price - target) / price * 100
            
            if distance_to_target <= THRESHOLDS['price_near_level_pct']:
                result['alerts'].append(f"📉 接近補倉點 ${target:,}（{level['note']}）")
                result['actions'].append({
                    'action': 'add',
                    'price': target,
                    'amount': level['amount'],
                    'note': level['note']
                })
            
            if price <= target:
                new_size = pos['size'] + level['amount']
                new_entry = (pos['size'] * entry + level['amount'] * price) / new_size
                new_recover = (new_entry - price) / price * 100
                result[f'if_add_at_{target}'] = {
                    'new_entry': round(new_entry, 2),
                    'new_recover_pct': round(new_recover, 2)
                }
    
    return result

def calculate_market_score(market_data):
    score = 0
    details = []
    
    fg = market_data.get('fear_greed')
    if fg:
        if fg < THRESHOLDS['fear_greed_strong_buy']:
            score += 25
            details.append(f"✅ 極度恐慌 FGI={fg} +25")
        elif fg < THRESHOLDS['fear_greed_buy']:
            score += 15
            details.append(f"✅ 恐慌 FGI={fg} +15")
        else:
            details.append(f"❌ 情緒未達恐慌 FGI={fg}")
    
    for symbol in ['BTC', 'ETH']:
        rsi = market_data[symbol].get('rsi')
        if rsi:
            if rsi < THRESHOLDS['rsi_extreme']:
                score += 15
                details.append(f"✅ {symbol} RSI極度超賣 ({rsi}) +15")
            elif rsi < THRESHOLDS['rsi_oversold']:
                score += 10
                details.append(f"✅ {symbol} RSI超賣 ({rsi}) +10")
    
    for symbol in ['BTC', 'ETH']:
        funding = market_data[symbol].get('funding')
        if funding and funding['negative_count'] >= THRESHOLDS['funding_negative_periods']:
            score += 10
            details.append(f"✅ {symbol} 資金費率負值 ({funding['negative_count']}/10) +10")
    
    return score, details

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'alerted': []}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def run_full_analysis():
    market_data = {
        'fear_greed': get_fear_greed(),
        'timestamp': datetime.now().isoformat()
    }
    
    for symbol in ['BTC', 'ETH']:
        price_data = get_price(symbol)
        market_data[symbol] = {
            'price': price_data['price'] if price_data else 0,
            'change_24h': price_data['change_24h'] if price_data else 0,
            'rsi': get_rsi(symbol),
            'funding': get_funding(symbol)
        }
    
    if market_data['BTC']['price'] == 0 and market_data['ETH']['price'] == 0:
        return None
    
    market_score, score_details = calculate_market_score(market_data)
    
    position_results = []
    for pos in POSITIONS:
        if market_data[pos['symbol']]['price'] > 0:
            result = analyze_position(pos, market_data)
            if result:
                position_results.append(result)
    
    return {
        'market': market_data,
        'market_score': market_score,
        'score_details': score_details,
        'positions': position_results
    }

def format_report(analysis):
    lines = [
        "🔔 **倉位分析報告**",
        "",
        f"**市場評分: {analysis['market_score']}/100**",
        f"恐懼貪婪指數: {analysis['market']['fear_greed']}",
        "",
    ]
    
    for detail in analysis['score_details']:
        lines.append(f"  {detail}")
    
    lines.append("")
    lines.append("---")
    lines.append("**📊 倉位狀態**")
    
    for pos in analysis['positions']:
        lines.append("")
        emoji = "🔴" if pos['pnl_pct'] < -20 else "🟠" if pos['pnl_pct'] < -10 else "🟡" if pos['pnl_pct'] < 0 else "🟢"
        lines.append(f"{emoji} **{pos['name']}**")
        lines.append(f"成本: ${pos['entry']:,} | 現價: ${pos['current_price']:,.2f}")
        lines.append(f"盈虧: {pos['pnl_pct']:+.2f}% | 回本需漲: {pos['recover_pct']:.1f}%")
        lines.append(f"距強平: {pos['liq_distance']:.1f}%")
        
        if pos['strategy'] == 'reduce':
            lines.append(f"策略: **減倉**")
        else:
            lines.append(f"策略: **補倉**")
        
        if pos['alerts']:
            for alert in pos['alerts']:
                lines.append(f"⚠️ {alert}")
    
    lines.append("")
    lines.append("---")
    
    if analysis['market_score'] >= 70:
        lines.append("💡 市場條件良好，可考慮執行計畫")
    elif analysis['market_score'] >= 50:
        lines.append("💡 市場條件一般，保持觀望")
    else:
        lines.append("💡 市場條件未達標，建議等待")
    
    lines.append(f"\n⏰ {datetime.now().strftime('%H:%M:%S')}")
    
    return "\n".join(lines)

def send_webhook(message):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            requests.post(DISCORD_WEBHOOK_URL, json={
                "content": chunk,
                "username": "📊 倉位顧問"
            }, timeout=10)
    except Exception as e:
        print(f"Webhook error: {e}")

def check_and_alert(analysis):
    state = load_state()
    alerts_to_send = []
    
    for pos in analysis['positions']:
        for alert in pos['alerts']:
            alert_key = f"{pos['id']}_{alert}"
            if alert_key not in state['alerted']:
                alerts_to_send.append(f"**{pos['name']}**: {alert}")
                state['alerted'].append(alert_key)
    
    if analysis['market_score'] >= THRESHOLDS['min_score_to_add']:
        score_key = f"score_{analysis['market_score']}"
        if score_key not in state['alerted']:
            alerts_to_send.append(f"🎯 市場評分達 {analysis['market_score']}，補倉條件改善中！")
            state['alerted'].append(score_key)
    
    if alerts_to_send:
        msg = "🔔 **倉位提醒**\n\n" + "\n".join(alerts_to_send)
        msg += f"\n\n⏰ {datetime.now().strftime('%H:%M')}"
        send_webhook(msg)
    
    save_state(state)
    return alerts_to_send

def main():
    analysis = run_full_analysis()
    
    if not analysis:
        print("無法取得市場數據")
        return
    
    report = format_report(analysis)
    print(report)
    send_webhook(report)
    
    alerts = check_and_alert(analysis)
    if alerts:
        print("\n已發送警報:")
        for a in alerts:
            print(f"  {a}")
    
    with open(Path(__file__).parent / "full_report.json", "w") as f:
        json.dump(analysis, f, indent=2, default=str)

if __name__ == "__main__":
    main()
