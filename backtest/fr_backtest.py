#!/usr/bin/env python3
"""
回測 Funding Rate 對信號勝率的影響
用 oi_signals + paper_trades 的歷史數據，配 Binance FR 歷史 API
"""

import json
import requests
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import sys

# Binance FR history API
def get_funding_rate_history(symbol, start_ms, end_ms):
    """拉 Binance 永續合約歷史資金費率"""
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params = {
        "symbol": f"{symbol}USDT",
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def get_nearest_fr(fr_data, target_ts_ms):
    """找最接近目標時間的 FR（FR 每 8h 結算一次）"""
    if not fr_data:
        return None
    best = None
    best_diff = float('inf')
    for fr in fr_data:
        diff = abs(fr['fundingTime'] - target_ts_ms)
        if diff < best_diff:
            best_diff = diff
            best = float(fr['fundingRate'])
    return best

def main():
    # Load signals
    with open('/Users/xuan/.openclaw/oi_signals_local_v2.json') as f:
        signals = json.load(f)
    
    # Load paper trades
    with open('/Users/xuan/.openclaw/paper_state.json') as f:
        state = json.load(f)
    trades = state['closed']
    
    print(f"信號總數: {len(signals)}")
    print(f"交易總數: {len(trades)}")
    print(f"日期範圍: {signals[0]['ts'][:10]} ~ {signals[-1]['ts'][:10]}")
    print()
    
    # Match trades to signals by symbol + approximate time
    # Build trade lookup: symbol -> list of trades
    trade_by_sym = defaultdict(list)
    for t in trades:
        trade_by_sym[t['symbol']].append(t)
    
    # Get unique symbols that had LONG or SHORT signals
    actionable = [s for s in signals if s['signal'] in ('LONG', 'SHORT')]
    symbols = list(set(s['symbol'] for s in actionable))
    print(f"可交易信號: {len(actionable)} (LONG/SHORT)")
    print(f"涉及幣種: {len(symbols)}")
    print()
    
    # Get date range for FR query
    from dateutil import parser as dp
    min_ts = min(dp.parse(s['ts']) for s in actionable)
    max_ts = max(dp.parse(s['ts']) for s in actionable)
    start_ms = int(min_ts.timestamp() * 1000) - 8*3600*1000  # buffer
    end_ms = int(max_ts.timestamp() * 1000) + 8*3600*1000
    
    # Batch fetch FR for all symbols
    print("正在拉取 Binance 資金費率歷史...")
    fr_cache = {}
    total = len(symbols)
    for i, sym in enumerate(symbols):
        if (i+1) % 20 == 0:
            print(f"  進度: {i+1}/{total}")
        fr_data = get_funding_rate_history(sym, start_ms, end_ms)
        if fr_data:
            fr_cache[sym] = fr_data
        time.sleep(0.1)  # rate limit
    
    print(f"成功取得 FR 數據: {len(fr_cache)}/{total} 幣種")
    print()
    
    # Analyze: for each LONG/SHORT signal, get FR at signal time
    results = []
    no_fr = 0
    for s in actionable:
        sym = s['symbol']
        if sym not in fr_cache:
            no_fr += 1
            continue
        
        ts = dp.parse(s['ts'])
        ts_ms = int(ts.timestamp() * 1000)
        fr = get_nearest_fr(fr_cache[sym], ts_ms)
        if fr is None:
            no_fr += 1
            continue
        
        # Find matching trade outcome
        sym_trades = trade_by_sym.get(sym, [])
        # Match by direction and close time near signal time
        matched_trade = None
        for t in sym_trades:
            t_close = dp.parse(t['closed_at'])
            t_dir = t['direction']
            # Trade should close AFTER signal, within 6h
            diff_h = (t_close - ts).total_seconds() / 3600
            if 0 < diff_h < 8 and t_dir == s['signal']:
                matched_trade = t
                break
        
        results.append({
            'symbol': sym,
            'signal': s['signal'],
            'ts': s['ts'],
            'fr': fr,
            'fr_pct': fr * 100,
            'rsi': s.get('rsi'),
            'grade': s.get('strength_grade', ''),
            'score': s.get('strength_score', 0),
            'vol_ratio': s.get('vol_ratio', 0),
            'matched': matched_trade is not None,
            'pnl': matched_trade.get('pnl_usd', 0) if matched_trade else None,
            'win': matched_trade.get('pnl_usd', 0) > 0 if matched_trade else None,
            'exit_reason': matched_trade.get('reason', '') if matched_trade else None,
        })
    
    print(f"有 FR 數據的信號: {len(results)}")
    print(f"無 FR 數據: {no_fr}")
    matched = [r for r in results if r['matched']]
    print(f"有配對交易的信號: {len(matched)}")
    print()
    
    # === Analysis ===
    
    # 1. FR distribution for wins vs losses
    print("=" * 60)
    print("📊 FR 與勝率分析")
    print("=" * 60)
    
    # FR buckets
    buckets = [
        ("FR < -0.05%", lambda r: r['fr_pct'] < -0.05),
        ("-0.05% ≤ FR < 0%", lambda r: -0.05 <= r['fr_pct'] < 0),
        ("0% ≤ FR < 0.01%", lambda r: 0 <= r['fr_pct'] < 0.01),
        ("0.01% ≤ FR < 0.03%", lambda r: 0.01 <= r['fr_pct'] < 0.03),
        ("FR ≥ 0.03%", lambda r: r['fr_pct'] >= 0.03),
    ]
    
    for label, fn in buckets:
        bucket_trades = [r for r in matched if fn(r)]
        if not bucket_trades:
            print(f"\n{label}: 無交易")
            continue
        wins = sum(1 for r in bucket_trades if r['win'])
        total_pnl = sum(r['pnl'] for r in bucket_trades)
        wr = wins / len(bucket_trades) * 100
        print(f"\n{label}: {len(bucket_trades)} 筆, 勝率 {wr:.1f}%, PnL ${total_pnl:.0f}")
    
    # 2. LONG vs SHORT breakdown
    print()
    print("=" * 60)
    print("📊 LONG / SHORT 分方向 FR 分析")
    print("=" * 60)
    
    for direction in ['LONG', 'SHORT']:
        print(f"\n--- {direction} ---")
        dir_trades = [r for r in matched if r['signal'] == direction]
        if not dir_trades:
            print("無交易")
            continue
        
        for label, fn in buckets:
            bucket_trades = [r for r in dir_trades if fn(r)]
            if not bucket_trades:
                continue
            wins = sum(1 for r in bucket_trades if r['win'])
            total_pnl = sum(r['pnl'] for r in bucket_trades)
            wr = wins / len(bucket_trades) * 100
            print(f"  {label}: {len(bucket_trades)} 筆, 勝率 {wr:.1f}%, PnL ${total_pnl:.0f}")
    
    # 3. Contrarian analysis (current filter logic)
    print()
    print("=" * 60)
    print("📊 反向 FR 過濾器回測（現有邏輯）")
    print("=" * 60)
    
    # Current filter: LONG blocked if FR > +0.01%, SHORT blocked if FR < -0.05%
    for direction in ['LONG', 'SHORT']:
        dir_trades = [r for r in matched if r['signal'] == direction]
        if direction == 'LONG':
            passed = [r for r in dir_trades if r['fr_pct'] <= 0.01]
            blocked = [r for r in dir_trades if r['fr_pct'] > 0.01]
        else:
            passed = [r for r in dir_trades if r['fr_pct'] >= -0.05]
            blocked = [r for r in dir_trades if r['fr_pct'] < -0.05]
        
        print(f"\n--- {direction} ---")
        if passed:
            w = sum(1 for r in passed if r['win'])
            p = sum(r['pnl'] for r in passed)
            print(f"  通過: {len(passed)} 筆, 勝率 {w/len(passed)*100:.1f}%, PnL ${p:.0f}")
        if blocked:
            w = sum(1 for r in blocked if r['win'])
            p = sum(r['pnl'] for r in blocked)
            print(f"  被擋: {len(blocked)} 筆, 勝率 {w/len(blocked)*100:.1f}%, PnL ${p:.0f}")
        if blocked:
            print(f"  → 擋掉了 ${-p:.0f} 的{'虧損' if p < 0 else '利潤'}")
    
    # 4. All signals (not just matched) - FR distribution
    print()
    print("=" * 60)
    print("📊 全部信號的 FR 分布（含未開倉的）")
    print("=" * 60)
    
    for direction in ['LONG', 'SHORT']:
        dir_sigs = [r for r in results if r['signal'] == direction]
        print(f"\n--- {direction} ({len(dir_sigs)} signals) ---")
        for label, fn in buckets:
            count = sum(1 for r in dir_sigs if fn(r))
            pct = count / len(dir_sigs) * 100 if dir_sigs else 0
            print(f"  {label}: {count} ({pct:.1f}%)")
    
    # 5. Save raw data for further analysis
    output = {
        'generated': datetime.now().isoformat(),
        'total_signals': len(actionable),
        'fr_matched': len(results),
        'trade_matched': len(matched),
        'results': results
    }
    with open('/Users/xuan/.openclaw/workspace/crypto-monitor-deploy/backtest/fr_backtest_results.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print("\n✅ 原始數據已存至 backtest/fr_backtest_results.json")

if __name__ == '__main__':
    main()
