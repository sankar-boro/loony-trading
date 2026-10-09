#!/usr/bin/env python
"""
Quick Status
============

One-screen snapshot of the entire trading system.  Designed to be the first
thing you run each morning before the market opens.

Usage:
    python scripts/status.py
    python scripts/status.py --watch 30     # refresh every 30s
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

G   = "\033[92m"; R  = "\033[91m"; Y  = "\033[93m"
B   = "\033[1m";  DIM = "\033[2m"; C  = "\033[96m"; E = "\033[0m"
CLR = "\033[2J\033[H"

def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k not in os.environ:
                os.environ[k] = v


def _token_status() -> tuple[str, str, str]:
    """Returns (token_str, status_label, detail)."""
    tf = ROOT / "data" / "upstox_token.json"
    env = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            tok = d.get("access_token", "") or env
            from data_engine.upstox.auth import token_hours_left
            age_h = (time.time() - d.get("obtained_at", 0)) / 3600
            left_h = token_hours_left(d.get("obtained_at", 0))
            if left_h <= 0:
                return tok, f"{R}EXPIRED{E}", f"{age_h:.1f}h old (expired 03:30 IST)"
            if left_h <= 3:
                return tok, f"{Y}EXPIRING{E}", f"expires in {left_h:.1f}h — renew soon"
            return tok, f"{G}valid{E}", f"{age_h:.1f}h old"
        except Exception:
            pass
    if env:
        return env, f"{Y}env-only{E}", "no age info"
    return "", f"{R}MISSING{E}", "run: python scripts/upstox_login.py"


def _market_status() -> tuple[bool, str]:
    try:
        from data_engine.upstox.market_hours import is_market_open, next_market_open, minutes_to_close
        if is_market_open():
            mins = minutes_to_close()
            return True, f"{G}OPEN{E}  {DIM}closes in {mins}m{E}"
        nxt = next_market_open()
        return False, f"{R}CLOSED{E}  {DIM}next: {nxt.strftime('%a %d-%b %H:%M IST')}{E}"
    except Exception as exc:
        return False, f"{DIM}unknown ({exc}){E}"


def _bot_status() -> str:
    sf = ROOT / "data" / "live_positions.json"
    if not sf.exists():
        return f"{DIM}never started{E}"
    age = time.time() - sf.stat().st_mtime
    if age < 300:
        return f"{G}running{E}  {DIM}(updated {int(age)}s ago){E}"
    return f"{Y}inactive{E}  {DIM}(last update {int(age/60)}m ago){E}"


def _dashboard_status() -> str:
    pid_f = ROOT / ".pids" / "dashboard_backend.pid"
    if pid_f.exists():
        try:
            pid = int(pid_f.read_text().strip())
            os.kill(pid, 0)
            return f"{G}running{E}  {DIM}(PID {pid}  http://localhost:8000){E}"
        except (ProcessLookupError, PermissionError):
            pass
    # fallback: check port
    import subprocess
    try:
        out = subprocess.check_output(["lsof", "-ti", "tcp:8000"], text=True).strip()
        if out:
            return f"{G}running{E}  {DIM}(port 8000, PID {out.split()[0]}){E}"
    except Exception:
        pass
    return f"{R}stopped{E}  {DIM}(./loony.sh start){E}"


def _equity_summary() -> str:
    ef = ROOT / "data" / "equity_curve.jsonl"
    if not ef.exists() or ef.stat().st_size == 0:
        return f"{DIM}no data{E}"
    try:
        lines = [l for l in ef.read_text().splitlines() if l.strip()]
        if not lines:
            return f"{DIM}no data{E}"
        last = json.loads(lines[-1])
        first = json.loads(lines[0])
        equity   = last.get("equity", 0)
        capital  = first.get("equity", equity)
        total_r  = (equity - capital) / capital * 100 if capital else 0
        realised = last.get("realised", 0)
        unreal   = last.get("unrealised", 0)
        color = G if total_r >= 0 else R
        return (f"₹{equity:>12,.0f}  "
                f"  total return: {color}{total_r:+.2f}%{E}"
                f"  {DIM}realised:{E} ₹{realised:+,.0f}"
                f"  {DIM}open:{E} ₹{unreal:+,.0f}")
    except Exception:
        return f"{DIM}parse error{E}"


def _positions_summary() -> str:
    sf = ROOT / "data" / "live_positions.json"
    if not sf.exists():
        return f"{DIM}—{E}"
    try:
        state = json.loads(sf.read_text())
        positions = state.get("positions", [])
        cash = state.get("cash", 0)
        if not positions:
            return f"{DIM}no open positions  cash: ₹{cash:,.0f}{E}"
        total_unreal = sum(p.get("unrealised_pnl", 0) for p in positions)
        color = G if total_unreal >= 0 else R
        syms = ", ".join(p["symbol"] for p in positions[:6])
        if len(positions) > 6:
            syms += f" +{len(positions)-6} more"
        return (f"{len(positions)} open  [{syms}]  "
                f"unrealised: {color}₹{total_unreal:+,.0f}{E}")
    except Exception:
        return f"{DIM}parse error{E}"


def _today_pnl() -> str:
    df = ROOT / "data" / "daily_pnl.jsonl"
    if not df.exists():
        return f"{DIM}no data{E}"
    try:
        today = date.today().isoformat()
        lines = [l for l in df.read_text().splitlines() if l.strip()]
        for line in reversed(lines):
            d = json.loads(line)
            if d.get("date") == today:
                r = d.get("realised", 0)
                u = d.get("unrealised", 0)
                trades = d.get("trades", 0)
                wr = d.get("win_rate", 0)
                color = G if r >= 0 else R
                return (f"realised: {color}₹{r:+,.0f}{E}  "
                        f"unrealised: ₹{u:+,.0f}  "
                        f"{DIM}{trades} trades  win rate: {wr:.0f}%{E}")
        return f"{DIM}no entry for today yet{E}"
    except Exception:
        return f"{DIM}parse error{E}"


def _ml_model_status() -> str:
    ens = ROOT / "models" / "ensemble.pkl"
    if not ens.exists():
        return f"{Y}not trained{E}  {DIM}run: python scripts/train_ml.py{E}"
    try:
        import pickle
        with open(ens, "rb") as f:
            data = pickle.load(f)
        age_d = (time.time() - data.get("saved_at", 0)) / 86400
        n = data.get("n_samples", 0)
        syms = data.get("trained_on", [])
        return (f"{G}ready{E}  "
                f"{DIM}{n} samples  {age_d:.0f}d old  "
                f"symbols: {', '.join(syms[:4])}{'...' if len(syms)>4 else ''}{E}")
    except Exception:
        return f"{Y}exists but unreadable{E}"


def _recent_signals() -> list[str]:
    sf = ROOT / "data" / "live_positions.json"
    if not sf.exists():
        return []
    try:
        state = json.loads(sf.read_text())
        log = state.get("signal_log", [])[-5:][::-1]
        rows = []
        for e in log:
            t = e.get("time", "")
            typ = e.get("type", "")
            sym = e.get("symbol", "")
            px = e.get("price", 0)
            pnl = e.get("pnl")
            strat = e.get("strategy", "")
            if typ in ("BUY", "SELL"):
                c = G if typ == "BUY" else R
                rows.append(f"  {DIM}{t}{E}  {c}{typ:<5}{E}  {sym:<14}  ₹{px:,.2f}  [{strat}]")
            elif typ == "CLOSE":
                pnl_s = (f"{G}+₹{pnl:,.0f}{E}" if pnl and pnl >= 0 else f"{R}₹{pnl:,.0f}{E}") if pnl is not None else ""
                rows.append(f"  {DIM}{t}{E}  {Y}CLOSE{E}  {sym:<14}  ₹{px:,.2f}  {pnl_s}")
        return rows
    except Exception:
        return []


def _print_status():
    token_str, tok_status, tok_detail = _token_status()
    mkt_open, mkt_label = _market_status()

    print(f"\n{B}{C}  Loony Trading — Status{E}  "
          f"{DIM}{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{E}")
    print("  " + "═" * 68)

    # Infrastructure
    print(f"\n  {B}System{E}")
    print(f"    Dashboard      {_dashboard_status()}")
    print(f"    Paper bot      {_bot_status()}")
    print(f"    Market         {mkt_label}")
    print(f"    Token          {tok_status}  {DIM}{tok_detail}{E}")
    print(f"    ML model       {_ml_model_status()}")

    # Portfolio
    print(f"\n  {B}Portfolio{E}")
    print(f"    Equity         {_equity_summary()}")
    print(f"    Positions      {_positions_summary()}")
    print(f"    Today P&L      {_today_pnl()}")

    # Recent signals
    rows = _recent_signals()
    if rows:
        print(f"\n  {B}Recent activity{E}")
        for r in rows:
            print(r)

    print("")


def main():
    _load_env()

    watch = 0
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--watch" and i + 2 <= len(sys.argv) - 1:
            try:
                watch = int(sys.argv[i + 2])
            except ValueError:
                watch = 30

    if watch:
        try:
            while True:
                print(CLR, end="")
                _print_status()
                print(f"  {DIM}Refreshing every {watch}s  •  Ctrl+C to exit{E}")
                time.sleep(watch)
        except KeyboardInterrupt:
            print(f"\n  {DIM}Exiting.{E}\n")
    else:
        _print_status()


if __name__ == "__main__":
    main()
