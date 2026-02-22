import json, requests, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

TW = timezone(timedelta(hours=8))

# Load all signals from last 5 days
with open('/Users/xuan/.openclaw/oi_signals_local_v2.json') as f:
    signals = json.load(f)

cutoff = datetime.now(TW) - timedelta(days=5)
recent = []
for s in signals:
    try:
        ts = datetime.fromisoformat(s['ts'])
        if ts >= cutoff:
            recent.append(s)
    except:
        pass

print(f'最近 5 天信號: {len(recent)}')

# Deduplicate: same symbol+signal within 1h = same signal
deduped = []
seen = {}
for s in recent:
    key = f"{s['symbol']}_{s['signal']}"
    ts = datetime.fromisoformat(s['ts'])
    if key in seen:
        if (ts - seen[key]).total_seconds() < 3600:
            continue
    seen[key] = ts
    deduped.append(s)

print(f'去重後: {len(deduped)}')

# For each signal, check what happened 1h, 2h, 4h, 6h after
def get_price_at(symbol, target_ts):
    """Get price at a specific timestamp"""
    try:
        r = requests.get('https://fapi.binance.com/fapi/v1/klines', params={
            'symbol': f'{symbol}USDT',
            'interval': '5m',
            'startTime': int(target_ts * 1000),
            'limit': 1
        }, timeout=5)
        if r.status_code == 200:
            k = r.json()
            if k:
                return float(k[0][4])  # close
    except:
        pass
    return None

results = []
for i, s in enumerate(deduped):
    symbol = s['symbol']
    signal = s['signal']
    entry_price = s['entry_price']
    ts = datetime.fromisoformat(s['ts'])
    entry_ts = ts.timestamp()
    
    # Get prices at 30m, 1h, 2h, 4h, 6h after
    outcomes = {}
    for label, hours in [('30m', 0.5), ('1h', 1), ('2h', 2), ('4h', 4), ('6h', 6)]:
        target = entry_ts + hours * 3600
        # Don't look into future
        if datetime.fromtimestamp(target, TW) > datetime.now(TW):
            break
        price = get_price_at(symbol, target)
        if price and entry_price > 0:
            if signal in ('LONG', 'SQUEEZE'):
                pnl = (price - entry_price) / entry_price * 100
            else:  # SHORT, SHAKEOUT
                pnl = (entry_price - price) / entry_price * 100
            outcomes[label] = {'price': price, 'pnl': pnl}
    
    if outcomes:
        results.append({
            'symbol': symbol,
            'signal': signal,
            'entry_price': entry_price,
            'ts': s['ts'],
            'rsi': s.get('rsi', 50),
            'score': s.get('strength_score', 0),
            'grade': s.get('strength_grade', ''),
            'oi_change': s.get('oi_change_pct', 0),
            'vol_ratio': s.get('vol_ratio', 0),
            'price_1h': s.get('price_change_1h', 0),
            'outcomes': outcomes,
        })
    
    if (i+1) % 20 == 0:
        print(f'  processed {i+1}/{len(deduped)}...')
    time.sleep(0.15)

print(f'\n有結果的信號: {len(results)}')

# Save for later analysis
with open('signal_outcomes_5d.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# === ANALYSIS ===
print('\n' + '='*80)
print('📊 信號觸發後的表現分析（最近 5 天）')
print('='*80)

# By signal type
for sig_type in ['LONG', 'SHORT', 'SHAKEOUT', 'SQUEEZE']:
    sig_results = [r for r in results if r['signal'] == sig_type]
    if not sig_results:
        continue
    
    print(f'\n--- {sig_type} ({len(sig_results)}筆) ---')
    for tf in ['30m', '1h', '2h', '4h', '6h']:
        has_tf = [r for r in sig_results if tf in r['outcomes']]
        if not has_tf:
            continue
        pnls = [r['outcomes'][tf]['pnl'] for r in has_tf]
        wins = len([p for p in pnls if p > 0])
        avg = sum(pnls) / len(pnls)
        print(f'  {tf}: {len(has_tf)}筆, 勝率{wins/len(has_tf)*100:.0f}%, 平均{avg:+.2f}%')

# Winners vs Losers at 6h
print('\n' + '='*80)
print('📈 6h 後結果分析')
print('='*80)

has_6h = [r for r in results if '6h' in r['outcomes']]
if has_6h:
    winners_6h = [r for r in has_6h if r['outcomes']['6h']['pnl'] > 3]  # >3% = good trade
    losers_6h = [r for r in has_6h if r['outcomes']['6h']['pnl'] < -3]  # <-3% = bad trade
    flat_6h = [r for r in has_6h if -3 <= r['outcomes']['6h']['pnl'] <= 3]
    
    print(f'大贏(>3%): {len(winners_6h)}, 大虧(<-3%): {len(losers_6h)}, 平盤: {len(flat_6h)}')
    
    def avg_metric(trades, key):
        vals = [t.get(key, 0) for t in trades if t.get(key) is not None]
        return sum(vals)/len(vals) if vals else 0
    
    print(f'\n{"指標":<15} {"大贏":>10} {"平盤":>10} {"大虧":>10}')
    print('-'*50)
    for key, label in [('rsi','RSI'), ('score','Score'), ('oi_change','OI變化%'), ('vol_ratio','量能比'), ('price_1h','1H價格%')]:
        w = avg_metric(winners_6h, key)
        f = avg_metric(flat_6h, key)
        l = avg_metric(losers_6h, key)
        print(f'{label:<15} {w:>10.1f} {f:>10.1f} {l:>10.1f}')

# Early signal: 30min performance as predictor
print('\n' + '='*80)
print('⏱️ 30 分鐘內表現 vs 最終結果')
print('='*80)

has_both = [r for r in results if '30m' in r['outcomes'] and '6h' in r['outcomes']]
if has_both:
    # If up 30m → how often up 6h?
    up_30m = [r for r in has_both if r['outcomes']['30m']['pnl'] > 0]
    down_30m = [r for r in has_both if r['outcomes']['30m']['pnl'] <= 0]
    
    if up_30m:
        up_then_up = len([r for r in up_30m if r['outcomes']['6h']['pnl'] > 0])
        avg_6h = sum(r['outcomes']['6h']['pnl'] for r in up_30m) / len(up_30m)
        print(f'30min 正收益 ({len(up_30m)}筆): 6h 勝率 {up_then_up/len(up_30m)*100:.0f}%, 平均 {avg_6h:+.2f}%')
    
    if down_30m:
        down_then_up = len([r for r in down_30m if r['outcomes']['6h']['pnl'] > 0])
        avg_6h = sum(r['outcomes']['6h']['pnl'] for r in down_30m) / len(down_30m)
        print(f'30min 負收益 ({len(down_30m)}筆): 6h 勝率 {down_then_up/len(down_30m)*100:.0f}%, 平均 {avg_6h:+.2f}%')

# Top winners and losers detail
print('\n--- Top 10 大贏家 ---')
sorted_6h = sorted(has_6h, key=lambda x: -x['outcomes']['6h']['pnl'])
for r in sorted_6h[:10]:
    o = r['outcomes']
    m30 = o.get('30m', {}).get('pnl', 0)
    h6 = o['6h']['pnl']
    print(f"  {r['symbol']:>10} {r['signal']:>8} 6h={h6:+.1f}% 30m={m30:+.1f}% | RSI={r['rsi']:.0f} score={r['score']} OI={r['oi_change']:+.1f}% vol={r['vol_ratio']:.1f}x | {r['ts'][:16]}")

print('\n--- Top 10 大虧家 ---')
for r in sorted_6h[-10:]:
    o = r['outcomes']
    m30 = o.get('30m', {}).get('pnl', 0)
    h6 = o['6h']['pnl']
    print(f"  {r['symbol']:>10} {r['signal']:>8} 6h={h6:+.1f}% 30m={m30:+.1f}% | RSI={r['rsi']:.0f} score={r['score']} OI={r['oi_change']:+.1f}% vol={r['vol_ratio']:.1f}x | {r['ts'][:16]}")

