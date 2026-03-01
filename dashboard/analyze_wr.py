#!/usr/bin/env python3
"""勝率優化分析 — 找出能推到 55%+ 的條件組合"""
import json

with open('/Users/xuan/.openclaw/paper_state.json') as f:
    data = json.load(f)

trades = data.get('closed', [])
capital = data.get('capital', 10000)
total = len(trades)
wins = sum(1 for t in trades if t.get('pnl_usd', 0) > 0)

print(f'=== 總覽: {total}筆, WR {wins}/{total} ({wins/total*100:.1f}%), capital ${capital:.0f} ===\n')

# 1. By grade
print('=== 評級 ===')
for g in ['🔥🔥🔥 S級', '🔥🔥 A級', '🔥 B級', 'C級', '?']:
    sub = [t for t in trades if t.get('strength_grade', '?') == g]
    if not sub: continue
    w = sum(1 for t in sub if t.get('pnl_usd', 0) > 0)
    p = sum(t.get('pnl_usd', 0) for t in sub)
    print(f'  {g:14s}: {len(sub):3d}筆 WR {w/len(sub)*100:4.0f}% PnL ${p:+.0f}')

# 2. By direction + phase
print('\n=== 方向+階段 ===')
combos = {}
for t in trades:
    k = f"{t.get('direction', '?')} {t.get('phase', '?')}"
    if k not in combos: combos[k] = {'n': 0, 'w': 0, 'pnl': 0}
    combos[k]['n'] += 1
    combos[k]['pnl'] += t.get('pnl_usd', 0)
    if t.get('pnl_usd', 0) > 0: combos[k]['w'] += 1
for k, v in sorted(combos.items(), key=lambda x: x[1]['pnl']):
    if v['n'] >= 3:
        print(f'  {k:30s}: {v["n"]:3d}筆 WR {v["w"]/v["n"]*100:4.0f}% PnL ${v["pnl"]:+.0f}')

# 3. RSI buckets for LONG
print('\n=== LONG RSI 分佈 ===')
longs = [t for t in trades if t.get('direction') == 'LONG']
buckets = {'<30': [], '30-50': [], '50-60': [], '60-70': [], '70-80': [], '80+': []}
for t in longs:
    r = t.get('rsi', 50)
    if r < 30: buckets['<30'].append(t)
    elif r < 50: buckets['30-50'].append(t)
    elif r < 60: buckets['50-60'].append(t)
    elif r < 70: buckets['60-70'].append(t)
    elif r < 80: buckets['70-80'].append(t)
    else: buckets['80+'].append(t)
for k, sub in buckets.items():
    if not sub: continue
    w = sum(1 for t in sub if t.get('pnl_usd', 0) > 0)
    p = sum(t.get('pnl_usd', 0) for t in sub)
    print(f'  RSI {k:6s}: {len(sub):3d}筆 WR {w/len(sub)*100:4.0f}% PnL ${p:+.0f}')

# 4. Vol ratio buckets
print('\n=== Vol Ratio 分佈 ===')
vol_b = {'<0.5': [], '0.5-1': [], '1-2': [], '2-5': [], '5-10': [], '10+': []}
for t in trades:
    v = t.get('vol_ratio', 1)
    if v < 0.5: vol_b['<0.5'].append(t)
    elif v < 1: vol_b['0.5-1'].append(t)
    elif v < 2: vol_b['1-2'].append(t)
    elif v < 5: vol_b['2-5'].append(t)
    elif v < 10: vol_b['5-10'].append(t)
    else: vol_b['10+'].append(t)
for k, sub in vol_b.items():
    if not sub: continue
    w = sum(1 for t in sub if t.get('pnl_usd', 0) > 0)
    p = sum(t.get('pnl_usd', 0) for t in sub)
    print(f'  vol {k:6s}: {len(sub):3d}筆 WR {w/len(sub)*100:4.0f}% PnL ${p:+.0f}')

# 5. Exit reason
print('\n=== 出場方式 ===')
exits = {}
for t in trades:
    r = t.get('reason', '?')
    if r not in exits: exits[r] = {'n': 0, 'w': 0, 'pnl': 0}
    exits[r]['n'] += 1
    exits[r]['pnl'] += t.get('pnl_usd', 0)
    if t.get('pnl_usd', 0) > 0: exits[r]['w'] += 1
for r, v in sorted(exits.items(), key=lambda x: x[1]['pnl']):
    print(f'  {r:24s}: {v["n"]:3d}筆 WR {v["w"]/v["n"]*100:4.0f}% PnL ${v["pnl"]:+.0f}')

# 6. TIME exit deep dive
time_trades = [t for t in trades if t.get('reason', '') == 'TIME']
if time_trades:
    time_w = sum(1 for t in time_trades if t.get('pnl_usd', 0) > 0)
    time_p = sum(t.get('pnl_usd', 0) for t in time_trades)
    print(f'\n=== TIME 出場: {len(time_trades)}筆 WR {time_w/len(time_trades)*100:.0f}% PnL ${time_p:.0f} ===')
    for g in ['🔥🔥🔥 S級', '🔥🔥 A級', '🔥 B級', 'C級', '?']:
        sub = [t for t in time_trades if t.get('strength_grade', '?') == g]
        if not sub: continue
        w = sum(1 for t in sub if t.get('pnl_usd', 0) > 0)
        p = sum(t.get('pnl_usd', 0) for t in sub)
        print(f'  TIME {g:14s}: {len(sub):3d}筆 WR {w/len(sub)*100:4.0f}% PnL ${p:+.0f}')

# 7. Simulation: what combos get >55% WR
print('\n=== 模擬：哪些條件組合能推到 55%+ ===')
filters = [
    ("B+級 only", lambda t: t.get('strength_grade', '') in ['🔥🔥🔥 S級', '🔥🔥 A級', '🔥 B級']),
    ("B+級 & vol<5", lambda t: t.get('strength_grade', '') in ['🔥🔥🔥 S級', '🔥🔥 A級', '🔥 B級'] and t.get('vol_ratio', 1) < 5),
    ("排除TIME虧損", lambda t: not (t.get('reason', '') == 'TIME' and t.get('pnl_usd', 0) < 0)),
    ("LONG RSI<70 only", lambda t: t.get('direction') != 'LONG' or t.get('rsi', 50) < 70),
    ("vol<5 only", lambda t: t.get('vol_ratio', 1) < 5),
    ("vol<3 only", lambda t: t.get('vol_ratio', 1) < 3),
    ("排除啟動初期虧損", lambda t: not ('啟動初期' in t.get('phase', '') and t.get('pnl_usd', 0) < 0)),
    ("B+級 & vol<3", lambda t: t.get('strength_grade', '') in ['🔥🔥🔥 S級', '🔥🔥 A級', '🔥 B級'] and t.get('vol_ratio', 1) < 3),
    ("A+級 only", lambda t: t.get('strength_grade', '') in ['🔥🔥🔥 S級', '🔥🔥 A級']),
]

for name, fn in filters:
    filtered = [t for t in trades if fn(t)]
    if not filtered: continue
    fw = sum(1 for t in filtered if t.get('pnl_usd', 0) > 0)
    fp = sum(t.get('pnl_usd', 0) for t in filtered)
    wr = fw / len(filtered) * 100
    marker = "✅" if wr >= 55 else ("🟡" if wr >= 50 else "❌")
    print(f'  {marker} {name:25s}: {len(filtered):3d}筆 WR {wr:4.1f}% PnL ${fp:+.0f}')

# 8. Write results to file for easy reading
with open('/Users/xuan/.openclaw/workspace/crypto-monitor-deploy/dashboard/wr_analysis.txt', 'w') as f:
    f.write('Analysis complete - see terminal output\n')

print('\n✅ Done')
