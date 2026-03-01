"""
加密貨幣監控系統 - 統一設定檔
集中管理所有門檻值、倉位資料、Discord webhook 等設定
"""
import os

# ============================================================
# Discord 通知設定
# ============================================================
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_5MIN_THREAD_ID = os.environ.get("DISCORD_5MIN_THREAD_ID", "")

# ============================================================
# 資料儲存路徑
# ============================================================
# 本地模式：使用 ~/.openclaw/
# GitHub 模式：使用 ./state/
IS_LOCAL = True  # 設為 False 可切換到 GitHub 模式

if IS_LOCAL:
    STATE_DIR = os.path.expanduser("~/.openclaw/")
else:
    STATE_DIR = "./state/"
    os.makedirs(STATE_DIR, exist_ok=True)

# State 檔案路徑
OI_STATE_FILE = os.path.join(STATE_DIR, "oi_state_local_v2.json")
OI_SIGNAL_LOG = os.path.join(STATE_DIR, "oi_signals_local_v2.json")
OI_NOTIFIED_FILE = os.path.join(STATE_DIR, "oi_notified_local_v2.json")
OI_PENDING_FILE = os.path.join(STATE_DIR, "oi_pending_v2.json")

# 5 分鐘 OI 預警
OI_5MIN_SNAPSHOT_FILE = os.path.join(STATE_DIR, "oi_5min_snapshots.json")
OI_5MIN_ALERT_HISTORY = os.path.join(STATE_DIR, "oi_5min_alerts.json")

# Paper Trading
PAPER_STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")

# Monitor 系統
MONITOR_SIGNALS_FILE = os.path.join(STATE_DIR, "monitor_signals.json")
OB_STATE_FILE = os.path.join(STATE_DIR, "ob_state.json")
BREAKOUT_STATE_FILE = os.path.join(STATE_DIR, "breakout_state.json")
PULLBACK_STATE_FILE = os.path.join(STATE_DIR, "pullback_state.json")
DUMP_WARNING_STATE_FILE = os.path.join(STATE_DIR, "dump_warning_state.json")
FLASH_CRASH_STATE_FILE = os.path.join(STATE_DIR, "flash_crash_state.json")
BREAKOUT_LEVELS_FILE = os.path.join(STATE_DIR, "breakout_levels.json")

# Signal Tracker
SIGNAL_TRACKER_FILE = os.path.join(STATE_DIR, "signal_tracker.json")

# ============================================================
# OI Scanner 門檻設定
# ============================================================
# 主要門檻
OI_SPIKE_THRESHOLD = 15         # OI 上升 >= 15% 視為激增
OI_DROP_THRESHOLD = -10         # OI 下降 <= -10% 視為暴跌
VOLUME_SPIKE_THRESHOLD = 3.0    # 成交量倍數 >= 3x 視為放量
MIN_OI_USD = 500_000           # 最低 OI（美元）過濾小幣
MIN_VOLUME_24H = 5_000_000     # 最低 24h 成交量
MIN_MARKET_CAP = 10_000_000    # 最低市值（美元）

# 時間窗口
OI_LOOKBACK_HOURS = 1          # OI 變化回溯時間（小時）
PRICE_LOOKBACK_HOURS = 6       # 價格趨勢回溯時間（小時）

# 強度評級門檻
STRENGTH_S = {"oi_change": 30, "vol_ratio": 5}    # S 級：極強信號
STRENGTH_A = {"oi_change": 20, "vol_ratio": 3}    # A 級：強信號
STRENGTH_B = {"oi_change": 15, "vol_ratio": 2}    # B 級：中強信號
# C 級：滿足基本門檻即可

# 通知冷卻時間
NOTIFY_COOLDOWN_HOURS = 6      # 同幣種再次通知間隔（小時）
PENDING_WAIT_HOURS = 1         # 等待確認的時間（小時）

# ============================================================
# 5 分鐘 OI 預警系統
# ============================================================
OI_5MIN_CHANGE_THRESHOLD = 5       # OI 變化 >= 5% 觸發預警
OI_5MIN_CHANGE_EXTREME = 15        # OI 變化 >= 15% 為極端
OI_5MIN_PRICE_MOVE_THRESHOLD = 3   # 價格同步變動 >= 3%
OI_5MIN_ALERT_COOLDOWN_MIN = 30    # 預警冷卻時間（分鐘）

# ============================================================
# Paper Trading 設定
# ============================================================
PAPER_CONFIG = {
    "capital": 10000,           # 初始資金
    "leverage": 5,              # 槓桿倍數
    "position_pct": 10,         # 每筆倉位佔資金比例 (%)
    "max_positions": 10,        # 最大同時持倉數
    "sl_pct": 10,              # 預設止損 (%)
    "tp1_pct": 5,              # 預設 TP1 (%)
    "tp2_pct": 10,             # 預設 TP2 (%)
    "time_exit_hours": 6       # 時間出場（小時）
}

# 動態 TP/SL（基於信號強度）
DYNAMIC_TP_CONFIG = {
    "S": {"tp1": 3, "tp2": 7, "sl": 7},     # S 級信號
    "A": {"tp1": 2, "tp2": 4, "sl": 8},     # A 級信號
    "B": {"tp1": 3, "tp2": 5, "sl": 9},     # B 級信號
    "default": {"tp1": 5, "tp2": 10, "sl": 10}  # 預設
}

# 成交量倍數調整係數
VOL_RATIO_MULTIPLIERS = {
    3.0: {"tp1": 1.5, "tp2": 1.8},
    2.0: {"tp1": 1.3, "tp2": 1.5},
    1.5: {"tp1": 1.1, "tp2": 1.2}
}

# 資金費率過濾
FUNDING_RATE_THRESHOLD_LONG = None      # LONG 不限制 FR（正費率=趨勢強，勝率更高）
FUNDING_RATE_THRESHOLD_SHORT = 0.0     # SHORT 擋正費率（FR>0% 做空勝率僅 21.9%）

# Grafana OI Dashboard API
GRAFANA_OI_URL = "http://gf.wavelet.pro:3000/api/datasources/proxy/uid/faad6586-bcc7-4462-b66c-4d3fb4d2610c/oi"
GRAFANA_SNAPSHOT_DIR = os.path.join(os.path.expanduser("~"), ".openclaw", "grafana_snapshots")

# RSI 過濾
RSI_EXTREME_HIGH = 80          # RSI >= 80 極端超買
RSI_HIGH = 60                  # RSI >= 60 超買
RSI_EXTREME_LOW = 20           # RSI <= 20 極端超賣
RSI_LOW = 40                   # RSI <= 40 超賣

# ============================================================
# Position Advisor 倉位監控
# ============================================================
POSITIONS = [
    {
        "name": "BTC 幣本位",
        "symbol": "BTCUSDT",
        "entry": 72334.7,
        "liquidation": 47932.6,
        "direction": "LONG",
        "leverage": 20,
        "quantity": 1.4592,
        "margin_coin": 0.0730,
        "margin_unit": "BTC",
        "platform": "OKX"
    },
    {
        "name": "ETH 幣本位",
        "symbol": "ETHUSDT",
        "entry": 2176.58,
        "liquidation": 1402.36,
        "direction": "LONG",
        "leverage": 20,
        "quantity": 21.0529,
        "margin_coin": 1.0928,
        "margin_unit": "ETH",
        "platform": "OKX"
    },
    {
        "name": "BTC U本位 (多)",
        "symbol": "BTCUSDT",
        "entry": 86265.28,
        "liquidation": 41681.49,
        "direction": "LONG",
        "leverage": 30,
        "margin": 2472.40,
        "quantity": 1.109,
        "platform": "Binance"
    },
    {
        "name": "BTC U本位 (空)",
        "symbol": "BTCUSDT",
        "entry": 64782.28,
        "liquidation": 41681.49,
        "direction": "SHORT",
        "leverage": 30,
        "margin": 267.52,
        "quantity": 0.120,
        "platform": "Binance"
    },
    {
        "name": "XAU U本位",
        "symbol": "XAUUSDT",
        "entry": 5342.11,
        "liquidation": 5313.00,
        "direction": "LONG",
        "leverage": 10,
        "margin": 529.17,
        "quantity": 1.000,
        "platform": "Binance"
    }
]

# 倉位警示門檻
POSITION_ALERT_LEVELS = {
    "danger": 20,      # 距離爆倉 <= 20%
    "warning": 30,     # 距離爆倉 <= 30%
    "caution": 40      # 距離爆倉 <= 40%
}

# ============================================================
# Monitor 系統設定
# ============================================================
# 暴跌預警
DUMP_WARNING_THRESHOLD = -5        # 5分鐘跌幅 <= -5%
DUMP_WARNING_EXTREME = -8          # 極端暴跌 <= -8%
FLASH_CRASH_THRESHOLD = -10        # 閃崩 <= -10%

# 突破監控
BREAKOUT_THRESHOLD = 5             # 突破幅度 >= 5%
BREAKOUT_VOLUME_MULTIPLIER = 2.0   # 成交量倍數 >= 2x

# 回調監控
PULLBACK_THRESHOLD = 3             # 回調幅度 >= 3%

# ============================================================
# API 相關設定
# ============================================================
# API 超時設定（秒）
API_TIMEOUT_SHORT = 5
API_TIMEOUT_NORMAL = 10
API_TIMEOUT_LONG = 15

# API 重試設定
API_RETRY_MAX = 3
API_RETRY_DELAY = 1  # 秒

# Rate Limit
API_RATE_LIMIT_DELAY = 0.1  # 秒，避免觸發 rate limit

# ============================================================
# 排除清單
# ============================================================
# 排除的交易對（下架、清算中等）
EXCLUDED_SYMBOLS = set()

# ============================================================
# 技術指標設定
# ============================================================
RSI_PERIOD = 14
ADX_PERIOD = 14
ATR_PERIOD = 14
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2

# ============================================================
# 其他設定
# ============================================================
# 時區
from datetime import timezone, timedelta
TW_TIMEZONE = timezone(timedelta(hours=8))

# 數字格式化
def format_number(n):
    """格式化數字顯示"""
    if n >= 1e9:
        return f"{n/1e9:.1f}B"
    elif n >= 1e6:
        return f"{n/1e6:.1f}M"
    elif n >= 1e3:
        return f"{n/1e3:.1f}K"
    return f"{n:.0f}"

def format_percent(n, decimals=2):
    """格式化百分比顯示"""
    return f"{n:+.{decimals}f}%"
