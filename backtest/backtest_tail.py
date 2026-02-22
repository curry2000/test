import json, requests, time
from datetime import datetime, timezone, timedelta

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

# All TIME trades + all TP/TRAIL winners for comparison
time_trades = [t for t in closed if t['reason'] == 'TIME']
winners = [t for t in closed if t['reason'] in ('TP2(70%平)', 'TRAIL(尾倉30%)', 'TRAIL_FULL')]

print(f'TIME超時: {len(time_trades)}, TP/TRAIL贏家: {len(winners)}')
print()

def analyze_pre_entry(trades, label):
    results = []
    for t in trades:
        symbol = t['symbol']
        direction = t['direction']
        closed_at = t.get('closed_at', '')
        try:
            ct = datetime.fromisoformat(closed_at)
            if 'TIME' in t.get('reason',''):
                entry_ts = (ct - timedelta(hours=6)).timestamp()
            elif 'TRAIL' in t.get('reason','') or 'TP' in t.get('reason',''):
                entry_ts = (ct - timedelta(hours=4)).timestamp()
            else:
                entry_ts = (ct - timedelta(hours=3)).timestamp()
        except:
            continue
        
        # Get 24h of 1h klines before entry
        klines = get_klines(symbol, '1h', 48, entry_ts)
        if not klines or len(klines) < 24:
            time.sleep(0.1)
            continue
        
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]  # base volume
        entry_price = closes[-1]
        
        # How much had price moved in last 1h, 3h, 6h, 12h, 24h before entry?
        def pct_move(n):
            if len(closes) >= n + 1:
                return (closes[-1] - closes[-(n+1)]) / closes[-(n+1)] * 100
            return None
        
        move_1h = pct_move(1)
        move_3h = pct_move(3)
        move_6h = pct_move(6)
        move_12h = pct_move(12)
        move_24h = pct_move(24)
        
        # Where in the range? (entry price relative to 24h high/low)
        h24 = max(float(k[2]) for k in klines[-24:])
        l24 = min(float(k[3]) for k in klines[-24:])
        range_pct = (entry_price - l24) / (h24 - l24) * 100 if h24 != l24 else 50
        
        # Volume trend: last 3h avg vs previous 21h avg
        vol_recent = sum(volumes[-3:]) / 3 if len(volumes) >= 3 else 0
        vol_prior = sum(volumes[-24:-3]) / 21 if len(volumes) >= 24 else 0
        vol_spike = vol_recent / vol_prior if vol_prior > 0 else 0
        
        # How far from 24h high?
        dist_from_high = (h24 - entry_price) / h24 * 100
        
        results.append({
            'symbol': symbol,
            'direction': direction,
            'pnl_pct': t['pnl_pct'],
            'pnl_usd': t['pnl_usd'],
            'reason': t['reason'],
            'phase': t.get('phase',''),
            'move_1h': move_1h,
            'move_3h': move_3h,
            'move_6h': move_6h,
            'move_12h': move_12h,
            'move_24h': move_24h,
            'range_pct': range_pct,  # 100 = at 24h high, 0 = at 24h low
            'dist_from_high': dist_from_high,
            'vol_spike': vol_spike,
        })
        time.sleep(0.1)
    
    return results

print('分析 TIME 超時交易...')
time_results = analyze_pre_entry(time_trades, 'TIME')
print(f'  成功: {len(time_results)}')

print('分析 TP/TRAIL 贏家...')
win_results = analyze_pre_entry(winners, 'WINNER')
print(f'  成功: {len(win_results)}')

# Print TIME details
print('\n=== TIME 超時交易：進場前價格走勢 ===')
print(f'{"幣種":>10} {"方向":>5} {"PnL%":>6} | {"1h漲跌":>6} {"3h漲跌":>6} {"6h漲跌":>6} {"12h漲跌":>7} {"24h漲跌":>7} | {"24h位置":>6} {"離高點":>5} {"量能比":>5}')
print('-' * 110)
for r in sorted(time_results, key=lambda x: x['pnl_pct']):
    m1 = f"{r['move_1h']:+.1f}%" if r['move_1h'] is not None else '?'
    m3 = f"{r['move_3h']:+.1f}%" if r['move_3h'] is not None else '?'
    m6 = f"{r['move_6h']:+.1f}%" if r['move_6h'] is not None else '?'
    m12 = f"{r['move_12h']:+.1f}%" if r['move_12h'] is not None else '?'
    m24 = f"{r['move_24h']:+.1f}%" if r['move_24h'] is not None else '?'
    print(f"{r['symbol']:>10} {r['direction']:>5} {r['pnl_pct']:+6.1f}% | {m1:>6} {m3:>6} {m6:>6} {m12:>7} {m24:>7} | {r['range_pct']:>5.0f}% {r['dist_from_high']:>4.1f}% {r['vol_spike']:>5.1f}x")

# Print WINNER details
print('\n=== TP/TRAIL 贏家：進場前價格走勢 ===')
print(f'{"幣種":>10} {"方向":>5} {"PnL%":>6} | {"1h漲跌":>6} {"3h漲跌":>6} {"6h漲跌":>6} {"12h漲跌":>7} {"24h漲跌":>7} | {"24h位置":>6} {"離高點":>5} {"量能比":>5}')
print('-' * 110)
for r in sorted(win_results, key=lambda x: x['pnl_pct']):
    m1 = f"{r['move_1h']:+.1f}%" if r['move_1h'] is not None else '?'
    m3 = f"{r['move_3h']:+.1f}%" if r['move_3h'] is not None else '?'
    m6 = f"{r['move_6h']:+.1f}%" if r['move_6h'] is not None else '?'
    m12 = f"{r['move_12h']:+.1f}%" if r['move_12h'] is not None else '?'
    m24 = f"{r['move_24h']:+.1f}%" if r['move_24h'] is not None else '?'
    print(f"{r['symbol']:>10} {r['direction']:>5} {r['pnl_pct']:+6.1f}% | {m1:>6} {m3:>6} {m6:>6} {m12:>7} {m24:>7} | {r['range_pct']:>5.0f}% {r['dist_from_high']:>4.1f}% {r['vol_spike']:>5.1f}x")

# Statistical comparison
print('\n=== TIME輸家 vs 贏家 統計比較 ===')
time_losers = [r for r in time_results if r['pnl_usd'] <= 0]
time_winners_sub = [r for r in time_results if r['pnl_usd'] > 0]

def avg(lst, key):
    vals = [x[key] for x in lst if x[key] is not None]
    return sum(vals)/len(vals) if vals else 0

print(f'{"指標":<15} {"TIME輸(n={len(time_losers)})":>18} {"TIME贏(n={len(time_winners_sub)})":>18} {"TP/TRAIL贏(n={len(win_results)})":>20}')
for key, label in [('move_1h','1h漲跌'), ('move_3h','3h漲跌'), ('move_6h','6h漲跌'), 
                    ('move_12h','12h漲跌'), ('move_24h','24h漲跌'), 
                    ('range_pct','24h位置%'), ('dist_from_high','離高點%'), ('vol_spike','量能比')]:
    v1 = avg(time_losers, key)
    v2 = avg(time_winners_sub, key)
    v3 = avg(win_results, key)
    fmt = '.1f' if 'spike' not in key else '.2f'
    print(f'{label:<15} {v1:>18.2f} {v2:>18.2f} {v3:>20.2f}')

