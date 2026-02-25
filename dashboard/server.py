#!/usr/bin/env python3
"""
Crypto Monitor Dashboard — 簡約可視化儀表板
本地 HTTP server，讀取 state files 提供 API + 前端頁面
"""
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone, timedelta

# Paths
STATE_DIR = os.path.expanduser("~/.openclaw")
PAPER_STATE = os.path.join(STATE_DIR, "paper_state.json")
SIGNALS_FILE = os.path.join(STATE_DIR, "oi_signals_local_v2.json")
OI_5MIN_ALERTS = os.path.join(STATE_DIR, "oi_5min_alerts.json")
PENDING_FILE = os.path.join(STATE_DIR, "oi_pending_v2.json")

TW = timezone(timedelta(hours=8))

# Add parent dir for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return None


def get_paper_stats():
    data = load_json(PAPER_STATE)
    if not data:
        return {"error": "no data"}

    trades = data.get("closed", [])
    positions = data.get("positions", [])
    capital = data.get("capital", 10000)

    # Capital curve
    cap_curve = [10000]
    running = 10000
    for t in trades:
        running += t.get("pnl_usd", 0)
        cap_curve.append(round(running, 2))

    # Win rate over time (rolling 20)
    wr_curve = []
    for i in range(20, len(trades) + 1):
        window = trades[i-20:i]
        wins = sum(1 for t in window if t.get("pnl_usd", 0) > 0)
        wr_curve.append(round(wins / 20 * 100, 1))

    # Overall stats
    total = len(trades)
    wins = sum(1 for t in trades if t.get("pnl_usd", 0) > 0)
    total_pnl = sum(t.get("pnl_usd", 0) for t in trades)

    # By direction
    dir_stats = {}
    for d in ["LONG", "SHORT"]:
        subset = [t for t in trades if t.get("direction") == d]
        w = sum(1 for t in subset if t.get("pnl_usd", 0) > 0)
        pnl = sum(t.get("pnl_usd", 0) for t in subset)
        dir_stats[d] = {
            "count": len(subset),
            "wins": w,
            "wr": round(w / len(subset) * 100, 1) if subset else 0,
            "pnl": round(pnl, 2)
        }

    # By exit reason
    exit_stats = {}
    for t in trades:
        reason = t.get("reason", "unknown")
        if reason not in exit_stats:
            exit_stats[reason] = {"count": 0, "pnl": 0, "wins": 0}
        exit_stats[reason]["count"] += 1
        exit_stats[reason]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            exit_stats[reason]["wins"] += 1
    for v in exit_stats.values():
        v["pnl"] = round(v["pnl"], 2)
        v["wr"] = round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0

    # By grade
    grade_stats = {}
    for t in trades:
        g = t.get("strength_grade", "unknown")
        if g not in grade_stats:
            grade_stats[g] = {"count": 0, "pnl": 0, "wins": 0}
        grade_stats[g]["count"] += 1
        grade_stats[g]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            grade_stats[g]["wins"] += 1
    for v in grade_stats.values():
        v["pnl"] = round(v["pnl"], 2)
        v["wr"] = round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0

    # By phase
    phase_stats = {}
    for t in trades:
        p = t.get("phase", "unknown")
        if p not in phase_stats:
            phase_stats[p] = {"count": 0, "pnl": 0, "wins": 0}
        phase_stats[p]["count"] += 1
        phase_stats[p]["pnl"] += t.get("pnl_usd", 0)
        if t.get("pnl_usd", 0) > 0:
            phase_stats[p]["wins"] += 1
    for v in phase_stats.values():
        v["pnl"] = round(v["pnl"], 2)
        v["wr"] = round(v["wins"] / v["count"] * 100, 1) if v["count"] else 0

    # Recent trades
    recent = []
    for t in trades[-30:]:
        recent.append({
            "symbol": t.get("symbol", "?"),
            "direction": t.get("direction", "?"),
            "entry": t.get("entry", 0),
            "exit": t.get("exit", 0),
            "pnl_pct": round(t.get("pnl_pct", 0), 2),
            "pnl_usd": round(t.get("pnl_usd", 0), 2),
            "reason": t.get("reason", "?"),
            "grade": t.get("strength_grade", "?"),
            "phase": t.get("phase", "?"),
            "rsi": round(t.get("rsi", 0), 1),
            "vol_ratio": round(t.get("vol_ratio", 0), 2),
            "closed_at": t.get("closed_at", "")[:19]
        })

    # Open positions
    open_pos = []
    for p in (positions if isinstance(positions, list) else []):
        open_pos.append({
            "symbol": p.get("symbol", "?"),
            "direction": p.get("direction", "?"),
            "entry": p.get("entry", 0),
            "grade": p.get("strength_grade", "?"),
            "phase": p.get("phase", "?"),
            "opened_at": p.get("opened_at", p.get("open_time", ""))[:19]
        })

    # Daily PnL
    daily_pnl = {}
    for t in trades:
        day = t.get("closed_at", "")[:10]
        if day:
            daily_pnl[day] = daily_pnl.get(day, 0) + t.get("pnl_usd", 0)
    daily_pnl = {k: round(v, 2) for k, v in sorted(daily_pnl.items())}

    return {
        "capital": round(capital, 2),
        "total_trades": total,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "total_pnl": round(total_pnl, 2),
        "open_positions": open_pos,
        "capital_curve": cap_curve,
        "wr_curve": wr_curve,
        "dir_stats": dir_stats,
        "exit_stats": exit_stats,
        "grade_stats": grade_stats,
        "phase_stats": phase_stats,
        "recent_trades": recent,
        "daily_pnl": daily_pnl
    }


def get_signals(limit=50):
    data = load_json(SIGNALS_FILE)
    if not data:
        return []
    signals = []
    for s in data[-limit:]:
        signals.append({
            "ts": s.get("ts", "")[:19],
            "symbol": s.get("symbol", "?"),
            "signal": s.get("signal", "?"),
            "price": s.get("entry_price", 0),
            "oi_pct": round(s.get("oi_change_pct", 0), 1),
            "price_1h": round(s.get("price_change_1h", 0), 1),
            "rsi": round(s.get("rsi", 0), 1),
            "grade": s.get("strength_grade", "?"),
            "score": s.get("strength_score", 0),
            "cvd": s.get("cvd_tag", "")
        })
    return signals


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/stats":
            self._json_response(get_paper_stats())
        elif path == "/api/signals":
            qs = parse_qs(parsed.query)
            limit = int(qs.get("limit", [100])[0])
            self._json_response(get_signals(limit))
        elif path == "/" or path == "/index.html":
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def _json_response(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Suppress logs


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8088
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"🚀 Dashboard running at http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
