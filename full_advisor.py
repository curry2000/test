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
        "name": "BTC-C",
        "symbol": "BTC",
        "entry": 75225,
        "size": 0.9046,
        "liq_price": 40336,
        "leverage": 2.2,
        "add_levels": [
            {"price": 63000, "amount": 0.3, "note": "L1"},
            {"price": 59800, "amount": 0.3, "note": "L2"},
            {"price": 57000, "amount": 0.3, "note": "L3"},
        ]
    },
    {
        "id": "BTC_USDT",
        "name": "BTC-U",
        "symbol": "BTC",
        "entry": 86265,
        "size": 1.109,
        "liq_price": 45667,
        "leverage": 2.1,
        "strategy": "reduce",
        "reduce_levels": [
            {"price": 72000, "percent": 30, "note": "L1"},
            {"price": 76000, "percent": 30, "note": "L2"},
            {"price": 80000, "percent": 40, "note": "L3"},
        ]
    },
    {
        "id": "ETH_COIN",
        "name": "ETH-C",
        "symbol": "ETH",
        "entry": 2253.98,
        "size": 15.45,
        "liq_price": 1234,
        "leverage": 2.2,
        "add_levels": [
            {"price": 1800, "amount": 5, "note": "L1"},
            {"price": 1650, "amount": 5, "note": "L2"},
            {"price": 1500, "amount": 5, "note": "L3"},
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
        r = requests.get('https://fapi.binance.com/fapi/v1/ticker/24hr',
                         params={'symbol': f'{symbol}USDT'}, timeout=10)
        d = r.json()
        return {
            'price': float(d['lastPrice']),
            'change_24h': float(d['priceChangePercent'])
        }
    except:
        return None

def get_rsi(symbol, interval='1d'):
    try:
        r = requests.get('https://fapi.binance.com/fapi/v1/klines',
                         params={'symbol': f'{symbol}USDT', 'interval': interval, 'limit': 20}, timeout=10)
        closes = [float(k[4]) for k in r.json()]
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
        return None

def get_funding(symbol):
    try:
        r = requests.get('https://fapi.binance.com/fapi/v1/fundingRate',
                         params={'symbol': f'{symbol}USDT', 'limit': 10}, timeout=10)
        rates = [float(d['fundingRate']) for d in r.json()]
        return {
            'current': rates[0],
            'negative_count': sum(1 for r in rates if r < 0)
        }
    except:
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
                result['alerts'].append(f"📈 ${target:,} {level['percent']}%")
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
                result['alerts'].append(f"📉 ${target:,} {level['amount']} {symbol}")
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
            details.append(f"✅ FGI={fg} +25")
        elif fg < THRESHOLDS['fear_greed_buy']:
            score += 15
            details.append(f"✅ FGI={fg} +15")
        else:
            details.append(f"❌ FGI={fg}")
    
    for symbol in ['BTC', 'ETH']:
        rsi = market_data[symbol].get('rsi')
        if rsi:
            if rsi < THRESHOLDS['rsi_extreme']:
                score += 15
                details.append(f"✅ {symbol} RSI {rsi} +15")
            elif rsi < THRESHOLDS['rsi_oversold']:
                score += 10
                details.append(f"✅ {symbol} RSI {rsi} +10")
    
    for symbol in ['BTC', 'ETH']:
        funding = market_data[symbol].get('funding')
        if funding and funding['negative_count'] >= THRESHOLDS['funding_negative_periods']:
            score += 10
            details.append(f"✅ {symbol} FR- ({funding['negative_count']}/10) +10")
    
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
    
    market_score, score_details = calculate_market_score(market_data)
    
    position_results = []
    for pos in POSITIONS:
        result = analyze_position(pos, market_data)
        position_results.append(result)
    
    return {
        'market': market_data,
        'market_score': market_score,
        'score_details': score_details,
        'positions': position_results
    }

def format_report(analysis):
    lines = [
        "=" * 50,
        "📊 **Report**",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 50,
        "",
        f"**Score: {analysis['market_score']}/100**",
        f"FGI: {analysis['market']['fear_greed']}",
        "",
    ]
    
    for detail in analysis['score_details']:
        lines.append(f"  {detail}")
    
    lines.append("")
    lines.append("=" * 50)
    lines.append("**Positions**")
    lines.append("=" * 50)
    
    for pos in analysis['positions']:
        lines.append("")
        emoji = "🔴" if pos['pnl_pct'] < -20 else "🟠" if pos['pnl_pct'] < -10 else "🟡" if pos['pnl_pct'] < 0 else "🟢"
        lines.append(f"{emoji} **{pos['name']}**")
        lines.append(f"   E: ${pos['entry']:,} | P: ${pos['current_price']:,.2f}")
        lines.append(f"   PnL: {pos['pnl_pct']:+.2f}% | Rec: {pos['recover_pct']:.1f}%")
        lines.append(f"   Liq: {pos['liq_distance']:.1f}%")
        
        if pos['strategy'] == 'reduce':
            lines.append(f"   📌 REDUCE")
            for level in POSITIONS[analysis['positions'].index(pos)].get('reduce_levels', []):
                status = "⬅️" if abs(pos['current_price'] - level['price']) / level['price'] < 0.03 else ""
                lines.append(f"      ${level['price']:,} {level['percent']}% {status}")
        else:
            lines.append(f"   📌 ADD")
            for level in POSITIONS[analysis['positions'].index(pos)].get('add_levels', []):
                status = "⬅️" if pos['current_price'] <= level['price'] * 1.05 else ""
                lines.append(f"      ${level['price']:,} {level['amount']} {pos['symbol']} {status}")
        
        if pos['alerts']:
            for alert in pos['alerts']:
                lines.append(f"   ⚠️ {alert}")
    
    lines.append("")
    lines.append("=" * 50)
    
    if analysis['market_score'] >= 70:
        lines.append("🟢 Good")
    elif analysis['market_score'] >= 50:
        lines.append("🟡 Wait")
    else:
        lines.append("🔴 Hold")
    
    return "\n".join(lines)

def send_webhook(message):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            requests.post(DISCORD_WEBHOOK_URL, json={
                "content": chunk,
                "username": "📊 Advisor"
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
            alerts_to_send.append(f"🎯 Score {analysis['market_score']}")
            state['alerted'].append(score_key)
    
    if alerts_to_send:
        msg = "🔔 **Alert**\n\n" + "\n".join(alerts_to_send)
        msg += f"\n\n⏰ {datetime.now().strftime('%H:%M')}"
        send_webhook(msg)
    
    save_state(state)
    return alerts_to_send

def main():
    analysis = run_full_analysis()
    report = format_report(analysis)
    print(report)
    
    alerts = check_and_alert(analysis)
    if alerts:
        print("\nSent:")
        for a in alerts:
            print(f"  {a}")
    
    with open(Path(__file__).parent / "full_report.json", "w") as f:
        json.dump(analysis, f, indent=2, default=str)

if __name__ == "__main__":
    main()
