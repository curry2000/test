import json, requests, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

TW = timezone(timedelta(hours=8))

def get_klines(symbol, interval='1h', limit=50, end_time=None):
    url = 'https://fapi.binance.com/fapi/v1/klines'
    params = {'symbol': f'{symbol}USDT', 'interval': interval, 'limit': limit}
    if end_time:
        params['endTime'] = int(end_time * 1000)
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

with open('/Users/xuan/.openclaw/paper_state.json') as f:
    state = json.load(f)
closed = state['closed']

print(f'回測全部 {len(closed)} 筆交易...')
results = []
errors = 0

for i, t in enumerate(closed):
    symbol = t['symbol']
    direction = t['direction']
    closed_at = t.get('closed_at', '')
    try:
        ct = datetime.fromisoformat(closed_at)
        if 'TIME' in t.get('reason',''):
            entry_ts = (ct - timedelta(hours=6)).timestamp()
        elif 'SL' in t.get('reason',''):
            entry_ts = (ct - timedelta(hours=2)).timestamp()
        else:
            entry_ts = (ct - timedelta(hours=4)).timestamp()
    except:
        errors += 1
        continue
    
    klines = get_klines(symbol, '1h', 48, entry_ts)
    if not klines or len(klines) < 24:
        errors += 1
        time.sleep(0.1)
        continue
    
    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    entry_price = closes[-1]
    
    def pct_move(n):
        if len(closes) >= n + 1:
            return (closes[-1] - closes[-(n+1)]) / closes[-(n+1)] * 100
        return None
    
    h24 = max(float(k[2]) for k in klines[-24:])
    l24 = min(float(k[3]) for k in klines[-24:])
    range_pct = (entry_price - l24) / (h24 - l24) * 100 if h24 != l24 else 50
    dist_from_high = (h24 - entry_price) / h24 * 100
    
    vol_recent = sum(volumes[-3:]) / 3 if len(volumes) >= 3 else 0
    vol_prior = sum(volumes[-24:-3]) / 21 if len(volumes) >= 24 else 0
    vol_spike = vol_recent / vol_prior if vol_prior > 0 else 0
    
    move_3h = pct_move(3)
    move_6h = pct_move(6)
    move_12h = pct_move(12)
    move_24h = pct_move(24)
    
    results.append({
        'symbol': symbol,
        'direction': direction,
        'pnl_pct': t['pnl_pct'],
        'pnl_usd': t['pnl_usd'],
        'reason': t['reason'],
        'phase': t.get('phase',''),
        'move_3h': move_3h,
        'move_6h': move_6h,
        'move_12h': move_12h,
        'move_24h': move_24h,
        'range_pct': range_pct,
        'dist_from_high': dist_from_high,
        'vol_spike': vol_spike,
        'is_win': t['pnl_usd'] > 0,
    })
    
    if (i + 1) % 20 == 0:
        print(f'  processed {i+1}/{len(closed)}...')
    time.sleep(0.1)

print(f'成功: {len(results)}/{len(closed)} (失敗: {errors})')

# Save
with open('backtest_tail_all.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

# ===== FILTER STRATEGIES =====
def test_filter(name, condition, data):
    """condition returns True = TAKE the trade, False = BLOCK"""
    passed = [r for r in data if condition(r)]
    blocked = [r for r in data if not condition(r)]
    
    p_wins = len([r for r in passed if r['is_win']])
    p_pnl = sum(r['pnl_usd'] for r in passed)
    b_wins = len([r for r in blocked if r['is_win']])
    b_pnl = sum(r['pnl_usd'] for r in blocked)
    
    p_wr = p_wins/len(passed)*100 if passed else 0
    b_wr = b_wins/len(blocked)*100 if blocked else 0
    
    return {
        'name': name,
        'passed': len(passed), 'p_wr': p_wr, 'p_pnl': p_pnl,
        'blocked': len(blocked), 'b_wr': b_wr, 'b_pnl': b_pnl,
    }

# Separate LONG and SHORT
longs = [r for r in results if r['direction'] == 'LONG']
shorts = [r for r in results if r['direction'] == 'SHORT']

print(f'\n全部: {len(results)}, LONG: {len(longs)}, SHORT: {len(shorts)}')
base_wr = len([r for r in results if r['is_win']])/len(results)*100
base_pnl = sum(r['pnl_usd'] for r in results)
print(f'Baseline: 勝率 {base_wr:.1f}%, PnL ${base_pnl:+.0f}')

long_wr = len([r for r in longs if r['is_win']])/len(longs)*100
long_pnl = sum(r['pnl_usd'] for r in longs)
print(f'LONG Baseline: {len(longs)}筆, 勝率 {long_wr:.1f}%, PnL ${long_pnl:+.0f}')

# Define filters (applied to LONG only, SHORT passes through)
filters = [
    # Vol spike filters
    ('vol_spike < 10x', lambda r: r['direction']=='SHORT' or r['vol_spike'] < 10),
    ('vol_spike < 15x', lambda r: r['direction']=='SHORT' or r['vol_spike'] < 15),
    ('vol_spike < 20x', lambda r: r['direction']=='SHORT' or r['vol_spike'] < 20),
    ('vol_spike < 8x', lambda r: r['direction']=='SHORT' or r['vol_spike'] < 8),
    ('vol_spike < 5x', lambda r: r['direction']=='SHORT' or r['vol_spike'] < 5),
    
    # Range position filters
    ('range < 90%', lambda r: r['direction']=='SHORT' or r['range_pct'] < 90),
    ('range < 85%', lambda r: r['direction']=='SHORT' or r['range_pct'] < 85),
    ('range < 80%', lambda r: r['direction']=='SHORT' or r['range_pct'] < 80),
    ('range < 70%', lambda r: r['direction']=='SHORT' or r['range_pct'] < 70),
    
    # Dist from high filters
    ('dist_high > 3%', lambda r: r['direction']=='SHORT' or r['dist_from_high'] > 3),
    ('dist_high > 5%', lambda r: r['direction']=='SHORT' or r['dist_from_high'] > 5),
    ('dist_high > 8%', lambda r: r['direction']=='SHORT' or r['dist_from_high'] > 8),
    ('dist_high > 10%', lambda r: r['direction']=='SHORT' or r['dist_from_high'] > 10),
    
    # Pre-move filters (already moved too much)
    ('6h漲 < 15%', lambda r: r['direction']=='SHORT' or (r['move_6h'] is not None and r['move_6h'] < 15)),
    ('6h漲 < 12%', lambda r: r['direction']=='SHORT' or (r['move_6h'] is not None and r['move_6h'] < 12)),
    ('6h漲 < 10%', lambda r: r['direction']=='SHORT' or (r['move_6h'] is not None and r['move_6h'] < 10)),
    ('12h漲 < 20%', lambda r: r['direction']=='SHORT' or (r['move_12h'] is not None and r['move_12h'] < 20)),
    ('12h漲 < 15%', lambda r: r['direction']=='SHORT' or (r['move_12h'] is not None and r['move_12h'] < 15)),
    ('24h漲 < 25%', lambda r: r['direction']=='SHORT' or (r['move_24h'] is not None and r['move_24h'] < 25)),
    ('24h漲 < 20%', lambda r: r['direction']=='SHORT' or (r['move_24h'] is not None and r['move_24h'] < 20)),
    
    # Combo filters
    ('vol<15 + range<90', lambda r: r['direction']=='SHORT' or (r['vol_spike'] < 15 and r['range_pct'] < 90)),
    ('vol<10 + range<85', lambda r: r['direction']=='SHORT' or (r['vol_spike'] < 10 and r['range_pct'] < 85)),
    ('vol<10 + dist>5%', lambda r: r['direction']=='SHORT' or (r['vol_spike'] < 10 and r['dist_from_high'] > 5)),
    ('vol<15 + 6h<15%', lambda r: r['direction']=='SHORT' or (r['vol_spike'] < 15 and (r['move_6h'] is None or r['move_6h'] < 15))),
    ('vol<10 + 12h<20%', lambda r: r['direction']=='SHORT' or (r['vol_spike'] < 10 and (r['move_12h'] is None or r['move_12h'] < 20))),
    ('range<85 + 6h<12%', lambda r: r['direction']=='SHORT' or (r['range_pct'] < 85 and (r['move_6h'] is None or r['move_6h'] < 12))),
    ('dist>5% + 12h<15%', lambda r: r['direction']=='SHORT' or (r['dist_from_high'] > 5 and (r['move_12h'] is None or r['move_12h'] < 15))),
    
    # OR filters (block if ANY red flag)
    ('排除: vol≥15 OR range≥95', lambda r: r['direction']=='SHORT' or not (r['vol_spike'] >= 15 or r['range_pct'] >= 95)),
    ('排除: vol≥10 OR 6h≥15%', lambda r: r['direction']=='SHORT' or not (r['vol_spike'] >= 10 or (r['move_6h'] is not None and r['move_6h'] >= 15))),
    ('排除: range≥90 AND dist<3%', lambda r: r['direction']=='SHORT' or not (r['range_pct'] >= 90 and r['dist_from_high'] < 3)),
]

print(f'\n{"="*90}')
print(f'{"策略":<25} {"通過":>4} {"勝率":>6} {"PnL":>9} {"被擋":>4} {"擋勝率":>6} {"擋PnL":>9} {"提升":>8}')
print(f'{"="*90}')

# Baseline
print(f'{"Baseline (全部)":<25} {len(results):>4} {base_wr:>5.1f}% ${base_pnl:>+8.0f}    -      -         -        -')
print('-'*90)

best_filters = []
for name, cond in filters:
    r = test_filter(name, cond, results)
    improvement = r['p_pnl'] - base_pnl  # vs just doing nothing with blocked
    # Real improvement: keeping passed + not losing blocked
    real_improvement = r['p_pnl'] - base_pnl + r['b_pnl']  # wait this is 0...
    # Better: if we block these trades, our new PnL = p_pnl
    delta = r['p_pnl'] - base_pnl
    print(f'{name:<25} {r["passed"]:>4} {r["p_wr"]:>5.1f}% ${r["p_pnl"]:>+8.0f} {r["blocked"]:>4} {r["b_wr"]:>5.1f}% ${r["b_pnl"]:>+8.0f} ${-r["b_pnl"]:>+7.0f}')
    best_filters.append((name, r, -r['b_pnl']))  # improvement = saved loss

print(f'\n{"="*90}')
print('提升 = 被擋掉的交易 PnL 取反 (正值 = 省下虧損)')
print()

# Top 10 by improvement
print('=== Top 10 最佳過濾策略 ===')
best_filters.sort(key=lambda x: -x[2])
for name, r, imp in best_filters[:10]:
    print(f'  {name:<25} 通過{r["passed"]}筆 勝率{r["p_wr"]:.1f}% PnL${r["p_pnl"]:+.0f} | 擋{r["blocked"]}筆(${r["b_pnl"]:+.0f}) | 省${imp:+.0f}')

# Show what each top filter blocks (detail)
print('\n=== 最佳策略被擋的交易明細 ===')
top_name, top_cond = None, None
for fname, fcond in filters:
    if fname == best_filters[0][0]:
        top_name, top_cond = fname, fcond
        break

if top_cond:
    blocked = [r for r in results if not top_cond(r)]
    print(f'\n策略: {top_name} (擋 {len(blocked)} 筆)')
    wins_blocked = [r for r in blocked if r['is_win']]
    losses_blocked = [r for r in blocked if not r['is_win']]
    print(f'  誤殺贏家: {len(wins_blocked)}筆 (${sum(r["pnl_usd"] for r in wins_blocked):+.0f})')
    print(f'  正確擋虧: {len(losses_blocked)}筆 (${sum(r["pnl_usd"] for r in losses_blocked):+.0f})')
    print()
    for r in sorted(blocked, key=lambda x: x['pnl_usd']):
        tag = '❌正確擋' if not r['is_win'] else '⚠️誤殺'
        print(f'  {tag} {r["symbol"]:>10} {r["direction"]:>5} {r["pnl_pct"]:+6.1f}% ${r["pnl_usd"]:+7.0f} | vol={r["vol_spike"]:.1f}x range={r["range_pct"]:.0f}% dist={r["dist_from_high"]:.1f}% 6h={r["move_6h"]:+.1f}%' if r["move_6h"] else f'  {tag} {r["symbol"]:>10} {r["direction"]:>5} {r["pnl_pct"]:+6.1f}% ${r["pnl_usd"]:+7.0f}')

