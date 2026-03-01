#!/usr/bin/env python3
"""
Grafana OI Dashboard 快照收集器
每 15 分鐘存一次快照到本地，供未來回測用
"""

import json
import os
import requests
from datetime import datetime, timezone, timedelta

from config import GRAFANA_OI_URL, GRAFANA_SNAPSHOT_DIR

def collect_snapshot():
    tw_tz = timezone(timedelta(hours=8))
    now = datetime.now(tw_tz)
    
    try:
        r = requests.get(GRAFANA_OI_URL, timeout=15)
        if r.status_code != 200:
            print(f"❌ Grafana API 回傳 {r.status_code}")
            return False
        
        data = r.json().get("data", [])
        if not data:
            print("❌ Grafana 回傳空數據")
            return False
        
        # 按日期建立資料夾
        date_dir = os.path.join(GRAFANA_SNAPSHOT_DIR, now.strftime("%Y-%m-%d"))
        os.makedirs(date_dir, exist_ok=True)
        
        # 檔名用時間戳
        filename = now.strftime("%H%M") + ".json"
        filepath = os.path.join(date_dir, filename)
        
        # 只保留回測需要的欄位，減少磁碟用量
        slim_data = []
        for coin in data:
            slim_data.append({
                "s": coin.get("symbol"),
                "fr": coin.get("FR"),
                "lsur": coin.get("LSUR"),
                "ps": coin.get("PS_Bias"),
                "idi": coin.get("iDI_1h"),
                "adi": coin.get("aDI_1h"),
                "oi": coin.get("OI$M"),
                "oi1h": coin.get("OI_1h"),
                "p": coin.get("Price"),
                "ls1h": coin.get("LS_1h"),
            })
        
        snapshot = {
            "ts": now.isoformat(),
            "count": len(slim_data),
            "data": slim_data
        }
        
        with open(filepath, 'w') as f:
            json.dump(snapshot, f, separators=(',', ':'))
        
        print(f"✅ 快照已存: {filepath} ({len(slim_data)} 幣種, {os.path.getsize(filepath)/1024:.1f}KB)")
        
        # 清理 14 天前的舊數據
        cleanup_old_snapshots(14)
        
        return True
        
    except Exception as e:
        print(f"❌ 收集失敗: {e}")
        return False

def cleanup_old_snapshots(keep_days=14):
    """清理超過 keep_days 的舊快照"""
    tw_tz = timezone(timedelta(hours=8))
    cutoff = datetime.now(tw_tz) - timedelta(days=keep_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    
    if not os.path.exists(GRAFANA_SNAPSHOT_DIR):
        return
    
    for dirname in os.listdir(GRAFANA_SNAPSHOT_DIR):
        if dirname < cutoff_str:
            dirpath = os.path.join(GRAFANA_SNAPSHOT_DIR, dirname)
            if os.path.isdir(dirpath):
                import shutil
                shutil.rmtree(dirpath)
                print(f"🗑️ 已清理舊快照: {dirname}")

def lookup_snapshot(symbol, target_time):
    """查詢某幣種在某時間點的 Grafana 數據（供回測用）"""
    if isinstance(target_time, str):
        from dateutil import parser as dp
        target_time = dp.parse(target_time)
    
    date_str = target_time.strftime("%Y-%m-%d")
    time_str = target_time.strftime("%H%M")
    date_dir = os.path.join(GRAFANA_SNAPSHOT_DIR, date_str)
    
    if not os.path.exists(date_dir):
        return None
    
    # 找最接近的快照檔案
    files = sorted(os.listdir(date_dir))
    best_file = None
    best_diff = float('inf')
    
    target_min = target_time.hour * 60 + target_time.minute
    for f in files:
        if not f.endswith('.json'):
            continue
        try:
            h, m = int(f[:2]), int(f[2:4])
            file_min = h * 60 + m
            diff = abs(file_min - target_min)
            if diff < best_diff:
                best_diff = diff
                best_file = f
        except:
            continue
    
    if not best_file or best_diff > 30:  # 超過 30 分鐘差距不採用
        return None
    
    filepath = os.path.join(date_dir, best_file)
    with open(filepath) as f:
        snapshot = json.load(f)
    
    for coin in snapshot.get("data", []):
        if coin.get("s") == symbol:
            return coin
    
    return None

if __name__ == "__main__":
    collect_snapshot()
