import json, requests, time
from datetime import datetime, timezone, timedelta

TW = timezone(timedelta(hours=8))

def get_klines(symbol, interval='1h', limit=30, end_time=None):
    """Get klines from Binance futures"""
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

def calc_adx_dmi(klines, period=14):
    """Calculate ADX, +DI, -DI from klines"""
    if not klines or len(klines) < period + 2:
        return None
    
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]
    
    # True Range, +DM, -DM
    tr_list, pdm_list, ndm_list = [], [], []
    for i in range(1, len(highs)):
        hi, lo, pc = highs[i], lows[i], closes[i-1]
        tr = max(hi - lo, abs(hi - pc), abs(lo - pc))
        
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        
        pdm = up_move if (up_move > down_move and up_move > 0) else 0
        ndm = down_move if (down_move > up_move and down_move > 0) else 0
        
        tr_list.append(tr)
        pdm_list.append(pdm)
        ndm_list.append(ndm)
    
    if len(tr_list) < period:
        return None
    
    # Smoothed values (Wilder's smoothing)
    atr = sum(tr_list[:period])
    smoothed_pdm = sum(pdm_list[:period])
    smoothed_ndm = sum(ndm_list[:period])
    
    dx_list = []
    
    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        smoothed_pdm = smoothed_pdm - (smoothed_pdm / period) + pdm_list[i]
        smoothed_ndm = smoothed_ndm - (smoothed_ndm / period) + ndm_list[i]
        
        if atr == 0:
            continue
        pdi = (smoothed_pdm / atr) * 100
        ndi = (smoothed_ndm / atr) * 100
        
        di_sum = pdi + ndi
        if di_sum == 0:
            continue
        dx = abs(pdi - ndi) / di_sum * 100
        dx_list.append((dx, pdi, ndi))
    
    if len(dx_list) < period:
        return None
    
    # ADX = smoothed DX
    adx = sum(d[0] for d in dx_list[:period]) / period
    for i in range(period, len(dx_list)):
        adx = (adx * (period - 1) + dx_list[i][0]) / period
    
    last_pdi = dx_list[-1][1]
    last_ndi = dx_list[-1][2]
    
    return {'adx': adx, 'pdi': last_pdi, 'ndi': last_ndi}

# Load trades
with open('/Users/xuan/.openclaw/paper_state.json') as f:
    state = json.load(f)

closed = state['closed']
print(f'總交易: {len(closed)}')
print()

results = []
errors = 0

for i, t in enumerate(closed):
    symbol = t['symbol']
    direction = t['direction']
    closed_at = t.get('closed_at', '')
    pnl_pct = t['pnl_pct']
    pnl_usd = t['pnl_usd']
    reason = t['reason']
    phase = t.get('phase', '?')
    
    # Parse entry time (closed_at - 6h for timeout, estimate for others)
    try:
        ct = datetime.fromisoformat(closed_at)
        # Rough estimate: entry ~6h before close for TIME, ~3h for others
        if 'TIME' in reason:
            entry_ts = (ct - timedelta(hours=6)).timestamp()
        else:
            entry_ts = (ct - timedelta(hours=3)).timestamp()
    except:
        errors += 1
        continue
    
    # Get 1h klines ending at entry time (need 30 for ADX calc)
    klines = get_klines(symbol, '1h', 30, entry_ts)
    if not klines:
        errors += 1
        continue
    
    adx_data = calc_adx_dmi(klines)
    if not adx_data:
        errors += 1
        continue
    
    results.append({
        'symbol': symbol,
        'direction': direction,
        'pnl_pct': pnl_pct,
        'pnl_usd': pnl_usd,
        'reason': reason,
        'phase': phase,
        'adx': adx_data['adx'],
        'pdi': adx_data['pdi'],
        'ndi': adx_data['ndi'],
        'di_align': (direction == 'LONG' and adx_data['pdi'] > adx_data['ndi']) or
                    (direction == 'SHORT' and adx_data['ndi'] > adx_data['pdi'])
    })
    
    if (i + 1) % 20 == 0:
        print(f'  processed {i+1}/{len(closed)}...')
    time.sleep(0.1)  # rate limit

print(f'\n成功取得 ADX: {len(results)}/{len(closed)} (失敗: {errors})')

# Save results
with open('backtest_adx_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print('\n=== ADX 分佈 ===')
from collections import defaultdict

# ADX buckets
adx_b = defaultdict(lambda: {'n':0,'w':0,'pnl':0})
for r in results:
    adx = r['adx']
    if adx < 15: k = '<15'
    elif adx < 20: k = '15-20'
    elif adx < 25: k = '20-25'
    elif adx < 30: k = '25-30'
    elif adx < 40: k = '30-40'
    else: k = '40+'
    adx_b[k]['n'] += 1
    adx_b[k]['pnl'] += r['pnl_usd']
    if r['pnl_usd'] > 0: adx_b[k]['w'] += 1

print('\nBy ADX:')
for k in ['<15','15-20','20-25','25-30','30-40','40+']:
    s = adx_b.get(k)
    if s and s['n']:
        wr = s['w']/s['n']*100
        print(f'  ADX {k:>5}: {s["n"]:>3}筆, 勝率{wr:>5.1f}%, PnL ${s["pnl"]:>+8.0f}')

# DI alignment
print('\nBy DI 方向一致性 (LONG時+DI>-DI / SHORT時-DI>+DI):')
for aligned in [True, False]:
    trades = [r for r in results if r['di_align'] == aligned]
    if not trades: continue
    w = len([t for t in trades if t['pnl_usd'] > 0])
    p = sum(t['pnl_usd'] for t in trades)
    label = '✅方向一致' if aligned else '❌方向不一致'
    print(f'  {label}: {len(trades)}筆, 勝率{w/len(trades)*100:.1f}%, PnL ${p:+.0f}')

# Combined: ADX >= 25 AND DI aligned
print('\n=== 過濾策略回測 ===')

strategies = [
    ('Baseline (全部)', lambda r: True),
    ('ADX >= 20', lambda r: r['adx'] >= 20),
    ('ADX >= 25', lambda r: r['adx'] >= 25),
    ('DI 方向一致', lambda r: r['di_align']),
    ('ADX>=20 + DI一致', lambda r: r['adx'] >= 20 and r['di_align']),
    ('ADX>=25 + DI一致', lambda r: r['adx'] >= 25 and r['di_align']),
    ('ADX<20 排除', lambda r: r['adx'] >= 20),  # same as above
    ('ADX>=25 OR DI一致', lambda r: r['adx'] >= 25 or r['di_align']),
]

print(f'\n{"策略":<20} {"交易數":>5} {"勝率":>6} {"PnL":>10} {"平均PnL":>8} {"被擋":>4}')
print('-' * 60)
for name, filt in strategies:
    passed = [r for r in results if filt(r)]
    blocked = [r for r in results if not filt(r)]
    if not passed:
        continue
    w = len([t for t in passed if t['pnl_usd'] > 0])
    p = sum(t['pnl_usd'] for t in passed)
    avg = p / len(passed)
    blocked_pnl = sum(t['pnl_usd'] for t in blocked)
    print(f'{name:<20} {len(passed):>5} {w/len(passed)*100:>5.1f}% ${p:>+9.0f} ${avg:>+7.1f} {len(blocked):>4}筆(${blocked_pnl:+.0f})')

# TIME trades specifically
print('\n=== TIME 超時交易 ADX 分析 ===')
time_trades = [r for r in results if 'TIME' in r['reason']]
print(f'TIME 交易有 ADX 數據: {len(time_trades)}')
for t in sorted(time_trades, key=lambda x: x['pnl_pct']):
    align = '✅' if t['di_align'] else '❌'
    print(f'  {t["symbol"]:>10} {t["direction"]:>5} {t["pnl_pct"]:+6.1f}% ADX={t["adx"]:.1f} +DI={t["pdi"]:.1f} -DI={t["ndi"]:.1f} {align}')

# Blocked TIME trades
blocked_time = [t for t in time_trades if t['adx'] < 20 or not t['di_align']]
print(f'\nADX<20 或 DI不一致 會擋掉的 TIME: {len(blocked_time)}筆')
blocked_pnl = sum(t['pnl_usd'] for t in blocked_time)
print(f'  被擋PnL: ${blocked_pnl:+.0f}')
still_in = [t for t in time_trades if t['adx'] >= 20 and t['di_align']]
still_pnl = sum(t['pnl_usd'] for t in still_in)
print(f'  保留的: {len(still_in)}筆, PnL ${still_pnl:+.0f}')

