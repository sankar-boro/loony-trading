#!/usr/bin/env python
"""
Order Manager
=============

Interactive order placement, management, and tracking.
Supports all order types and works in sandbox mode for safe testing.

Usage:
    python scripts/order.py                        # interactive menu
    python scripts/order.py --sandbox              # use sandbox environment
    python scripts/order.py orders                 # view open orders
    python scripts/order.py place                  # place new order (guided)
    python scripts/order.py cancel <order_id>      # cancel specific order
    python scripts/order.py history                # today's order history
    python scripts/order.py trades                 # today's trade history
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROD_BASE    = "https://api.upstox.com/v2"
SANDBOX_BASE = "https://api-sandbox.upstox.com/v2"

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; B = "\033[1m"
DIM = "\033[2m"; CYAN = "\033[96m"; RESET = "\033[0m"

def green(s):  return f"{G}{s}{RESET}"
def red(s):    return f"{R}{s}{RESET}"
def yellow(s): return f"{Y}{s}{RESET}"
def bold(s):   return f"{B}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"
def cyan(s):   return f"{CYAN}{s}{RESET}"

STATUS_COLOURS = {
    "complete":   green,
    "open":       cyan,
    "pending":    yellow,
    "cancelled":  dim,
    "rejected":   red,
    "trigger pending": yellow,
}


# ── env + token ───────────────────────────────────────────────────────────────

def _load_env():
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def _find_token(explicit=None, sandbox=False) -> str:
    if explicit:
        return explicit
    if sandbox:
        t = os.environ.get("UPSTOX_SANDBOX_TOKEN", "").strip()
        if t:
            return t
        tf = ROOT / "data" / "upstox_sandbox_token.json"
        if tf.exists():
            try:
                d = json.loads(tf.read_text())
                age = (time.time() - d.get("obtained_at", 0)) / 3600
                if d.get("access_token") and age < 720:
                    return d["access_token"]
            except Exception:
                pass
        print(f"{R}No sandbox token.{RESET}  Run: python scripts/upstox_login.py --sandbox")
        sys.exit(1)
    t = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if t:
        return t
    tf = ROOT / "data" / "upstox_token.json"
    if tf.exists():
        try:
            d = json.loads(tf.read_text())
            from data_engine.upstox.auth import token_hours_left
            if d.get("access_token") and token_hours_left(d.get("obtained_at", 0)) > 0:
                return d["access_token"]
        except Exception:
            pass
    print(f"{R}No token.{RESET}  Run: python scripts/upstox_login.py")
    sys.exit(1)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get(base: str, token: str, path: str) -> tuple[int, dict]:
    import requests
    try:
        r = requests.get(f"{base}{path}", headers=_headers(token), timeout=10)
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {"error": str(e)}


def _post(base: str, token: str, path: str, body: dict) -> tuple[int, dict]:
    import requests
    try:
        r = requests.post(
            f"{base}{path}", headers={**_headers(token), "Content-Type": "application/json"},
            json=body, timeout=15,
        )
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {"error": str(e)}


def _put(base: str, token: str, path: str, body: dict) -> tuple[int, dict]:
    import requests
    try:
        r = requests.put(
            f"{base}{path}", headers={**_headers(token), "Content-Type": "application/json"},
            json=body, timeout=15,
        )
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {"error": str(e)}


def _delete(base: str, token: str, path: str) -> tuple[int, dict]:
    import requests
    try:
        r = requests.delete(f"{base}{path}", headers=_headers(token), timeout=15)
        return r.status_code, (r.json() if r.content else {})
    except Exception as e:
        return 0, {"error": str(e)}


# ── instrument lookup ─────────────────────────────────────────────────────────

COMMON_ISINS = {
    "RELIANCE": "INE002A01018", "TCS": "INE467B01029",
    "HDFCBANK": "INE040A01034", "INFY": "INE009A01021",
    "ICICIBANK": "INE090A01021", "SBIN": "INE062A01020",
    "WIPRO": "INE075A01022", "ADANIENT": "INE423A01024",
    "BAJFINANCE": "INE296A01032", "KOTAKBANK": "INE237A01036",
    "AXISBANK": "INE238A01034", "LT": "INE018A01030",
    "MARUTI": "INE585B01010", "SUNPHARMA": "INE044A01036",
    "HINDUNILVR": "INE030A01027",
}


def _resolve_instrument(base: str, token: str, symbol: str) -> str | None:
    """Return instrument_token for a symbol (NSE_EQ|ISIN format)."""
    sym = symbol.upper().strip()
    # Direct ISIN
    isin = COMMON_ISINS.get(sym)
    if isin:
        return f"NSE_EQ|{isin}"
    # Search API
    code, resp = _get(base, token, f"/instruments/search?query={sym}&segment=NSE_EQ")
    if code == 200:
        raw = resp.get("data", [])
        items = (raw.get("items", []) if isinstance(raw, dict) else raw) or []
        for item in items:
            if item.get("trading_symbol", "").upper() == sym:
                isin = item.get("isin", "")
                if isin:
                    return f"NSE_EQ|{isin}"
        if items:
            isin = items[0].get("isin", "")
            if isin:
                return f"NSE_EQ|{isin}"
    return None


def _get_ltp(base: str, token: str, instrument_token: str) -> float | None:
    import requests
    enc = instrument_token.replace("|", "%7C").replace(" ", "%20")
    try:
        r = requests.get(
            f"{base}/market-quote/ltp?instrument_key={enc}",
            headers=_headers(token), timeout=8,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            resp_key = instrument_token.replace("|", ":")
            return data.get(resp_key, {}).get("last_price")
    except Exception:
        pass
    return None


# ── order display ─────────────────────────────────────────────────────────────

def _fmt_order(o: dict, idx: int = 0) -> str:
    status = o.get("status", "").lower()
    colr = STATUS_COLOURS.get(status, str)
    sym      = o.get("trading_symbol", o.get("instrument_token", "?"))
    oid      = o.get("order_id", "?")
    txn      = o.get("transaction_type", "?")
    qty      = o.get("quantity", 0)
    filled   = o.get("filled_quantity", 0)
    price    = o.get("price", 0)
    avg_p    = o.get("average_price", 0)
    otype    = o.get("order_type", "?")
    prod     = o.get("product", "?")
    tag      = o.get("tag", "")
    ts       = o.get("order_timestamp", o.get("placed_by", ""))[:19] if o.get("order_timestamp") else ""
    msg      = o.get("status_message", "")

    txn_s    = green(txn) if txn == "BUY" else red(txn)
    stat_s   = colr(status.upper())
    idx_s    = dim(f"[{idx}]") if idx else ""

    line = (f"  {idx_s} {sym:<14}  {txn_s}  {otype:<6}  {prod:<3}  "
            f"Qty:{qty}/{filled}  ₹{price:>8,.2f}"
            + (f"  avg₹{avg_p:,.2f}" if avg_p else "")
            + f"  {stat_s}"
            + (f"  {dim(tag)}" if tag else "")
            + (f"  {dim(ts)}" if ts else ""))
    if msg and status in ("rejected", "cancelled"):
        line += f"\n      {red(msg)}"
    line += f"\n      {dim(f'order_id: {oid}')}"
    return line


# ── subcommands ───────────────────────────────────────────────────────────────

def cmd_orders(base: str, token: str, verbose: bool = False) -> None:
    print(bold("\n  Open / Recent Orders"))
    print("  " + "─" * 70)
    code, resp = _get(base, token, "/order/retrieve-all")
    if code in (401, 403):
        print(f"  {yellow('Requires trading token')}")
        return
    if code != 200:
        print(f"  {red(f'Error: HTTP {code}')}  {resp.get('message', '')}")
        return

    orders = resp.get("data", [])
    if not orders:
        print("  No orders today.")
        return

    # Group by status
    open_orders   = [o for o in orders if o.get("status", "").lower() in ("open", "pending", "trigger pending")]
    closed_orders = [o for o in orders if o.get("status", "").lower() not in ("open", "pending", "trigger pending")]

    if open_orders:
        print(f"\n  {bold('Open  (' + str(len(open_orders)) + ')')}")
        for i, o in enumerate(open_orders, 1):
            print(_fmt_order(o, i))

    if closed_orders:
        print(f"\n  {bold('Closed today  (' + str(len(closed_orders)) + ')')}")
        for o in closed_orders[-10:]:
            print(_fmt_order(o))

    print()


def cmd_history(base: str, token: str) -> None:
    print(bold("\n  Order History (today)"))
    print("  " + "─" * 70)
    code, resp = _get(base, token, "/order/retrieve-all")
    if code != 200:
        print(f"  {red(f'HTTP {code}')}  {resp.get('message', '')}")
        return
    orders = resp.get("data", [])
    for o in orders:
        print(_fmt_order(o))
    print(f"\n  {len(orders)} orders total today.\n")


def cmd_trades(base: str, token: str) -> None:
    print(bold("\n  Trade Book (today's fills)"))
    print("  " + "─" * 70)
    code, resp = _get(base, token, "/order/trades/get-trades-for-day")
    if code in (401, 403):
        print(f"  {yellow('Requires trading token')}")
        return
    if code != 200:
        print(f"  {red(f'HTTP {code}')}  {resp.get('message', '')}")
        return
    trades = resp.get("data", [])
    if not trades:
        print("  No fills today.")
        return
    print(f"  {'Symbol':<14}  {'Type':>5}  {'Qty':>6}  {'Price':>10}  {'Product':>7}  Time")
    print("  " + "─" * 70)
    for t in trades:
        sym   = t.get("trading_symbol", "?")
        txn   = t.get("transaction_type", "?")
        qty   = t.get("quantity", 0)
        price = float(t.get("average_price", 0))
        prod  = t.get("product", "?")
        ts    = t.get("exchange_timestamp", "")[:19]
        txn_s = green(f"{txn:>5}") if txn == "BUY" else red(f"{txn:>5}")
        print(f"  {sym:<14}  {txn_s}  {qty:>6,}  ₹{price:>8,.2f}  {prod:>7}  {ts}")
    print(f"\n  {len(trades)} fills.\n")


def cmd_cancel(base: str, token: str, order_id: str) -> None:
    print(f"\n  Cancelling order {cyan(order_id)}...")
    code, resp = _delete(base, token, f"/order/cancel?order_id={order_id}")
    if code == 200:
        cxl_id = resp.get("data", {}).get("order_id", order_id)
        print(f"  {green('Cancelled')}  order_id: {cxl_id}")
    else:
        msg = resp.get("message") or resp.get("errors", [{}])[0].get("message", "")
        print(f"  {red(f'Cancel failed: HTTP {code}')}  {msg}")
    print()


def cmd_cancel_all(base: str, token: str) -> None:
    code, resp = _get(base, token, "/order/retrieve-all")
    if code != 200:
        print(f"  {red(f'HTTP {code}')}"); return
    open_orders = [o for o in resp.get("data", [])
                   if o.get("status", "").lower() in ("open", "pending")]
    if not open_orders:
        print("  No open orders to cancel.")
        return
    print(f"\n  Found {len(open_orders)} open order(s).")
    confirm = input("  Cancel all? [y/N]: ").strip().lower()
    if confirm != "y":
        print("  Aborted.")
        return
    for o in open_orders:
        cmd_cancel(base, token, o["order_id"])


def cmd_place(base: str, token: str, sandbox: bool) -> None:
    print(bold(f"\n  Place Order {'[SANDBOX]' if sandbox else '[LIVE]'}"))
    print("  " + "─" * 50)

    if sandbox:
        print(f"  {yellow('Sandbox mode')} — orders are simulated, no real money involved.\n")

    # Symbol
    symbol = input("  Symbol (e.g. RELIANCE, TCS): ").strip().upper()
    if not symbol:
        print("  Cancelled."); return

    print(f"  Looking up {symbol}...")
    instrument_token = _resolve_instrument(base, token, symbol)
    if not instrument_token:
        print(f"  {red(f'Symbol {symbol!r} not found.')} Check the symbol and try again.")
        return
    print(f"  {green('Found')}  instrument_token: {instrument_token}")

    # Fetch LTP
    ltp = _get_ltp(base, token, instrument_token)
    if ltp:
        print(f"  Current LTP: ₹{ltp:,.2f}")

    # Transaction type
    txn_input = input("\n  Transaction [B]uy / [S]ell: ").strip().upper()
    txn = "BUY" if txn_input in ("B", "BUY") else "SELL" if txn_input in ("S", "SELL") else ""
    if not txn:
        print("  Invalid. Enter B or S."); return

    # Quantity
    qty_s = input("  Quantity: ").strip()
    try:
        qty = int(qty_s)
        assert qty > 0
    except Exception:
        print("  Invalid quantity."); return

    # Order type
    print("  Order type: [M]arket  [L]imit  [S]top-Loss  [SM] SL-Market")
    ot_input = input("  → ").strip().upper()
    ot_map = {"M": "MARKET", "L": "LIMIT", "S": "SL", "SM": "SL-M",
              "MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
    order_type = ot_map.get(ot_input)
    if not order_type:
        print("  Invalid order type."); return

    # Price
    price = 0.0
    trigger_price = 0.0
    if order_type in ("LIMIT", "SL"):
        try:
            price = float(input(f"  Limit price [LTP={ltp or '?'}]: ").strip() or "0")
        except Exception:
            print("  Invalid price."); return
    if order_type in ("SL", "SL-M"):
        try:
            trigger_price = float(input("  Trigger price: ").strip() or "0")
        except Exception:
            print("  Invalid trigger price."); return

    # Product
    print("  Product: [D] Delivery  [I] Intraday  [MTF] Margin")
    prod_input = input("  → ").strip().upper()
    prod_map = {"D": "D", "I": "I", "MTF": "MTF",
                "DELIVERY": "D", "INTRADAY": "I"}
    product = prod_map.get(prod_input, "D")

    # Validity
    val_input = input("  Validity: [D]ay / [I]OC (default: DAY): ").strip().upper()
    validity = "IOC" if val_input in ("I", "IOC") else "DAY"

    # Tag
    tag = input("  Tag (optional, press Enter to skip): ").strip() or "loony-order"

    # Summary
    print()
    print(bold("  Order Summary:"))
    print(f"    Symbol:     {symbol}  ({instrument_token})")
    print(f"    Type:       {txn}  {order_type}  {product}  {validity}")
    print(f"    Qty:        {qty:,}")
    if price:        print(f"    Price:      ₹{price:,.2f}")
    if trigger_price: print(f"    Trigger:    ₹{trigger_price:,.2f}")
    if ltp:          print(f"    LTP:        ₹{ltp:,.2f}")
    print(f"    Tag:        {tag}")
    if sandbox:
        print(f"    Mode:       {yellow('SANDBOX (simulated)')}")
    else:
        est_value = qty * (price or ltp or 0)
        print(f"    Est. Value: ₹{est_value:,.2f}")

    print()
    confirm = input("  Confirm and place? [y/N]: ").strip().lower()
    if confirm != "y":
        print("  Cancelled.\n"); return

    body = {
        "quantity":         qty,
        "product":          product,
        "validity":         validity,
        "price":            price,
        "instrument_token": instrument_token,
        "order_type":       order_type,
        "transaction_type": txn,
        "tag":              tag,
    }
    if trigger_price:
        body["trigger_price"] = trigger_price

    print("  Placing order...")
    code, resp = _post(base, token, "/order/place", body)

    if code == 200:
        order_id = resp.get("data", {}).get("order_id", "?")
        print(f"\n  {green('Order placed!')}  order_id: {order_id}")
    else:
        msg = resp.get("message") or (resp.get("errors") or [{}])[0].get("message", "")
        print(f"\n  {red(f'Failed: HTTP {code}')}  {msg}")

    print()


def cmd_modify(base: str, token: str) -> None:
    print(bold("\n  Modify Order"))
    print("  " + "─" * 50)

    order_id = input("  Order ID to modify: ").strip()
    if not order_id:
        print("  Cancelled."); return

    # Show current order details
    code, resp = _get(base, token, f"/order/history?order_id={order_id}")
    if code == 200:
        history = resp.get("data", [])
        if history:
            latest = history[-1]
            print(f"\n  Current: {_fmt_order(latest)}\n")

    # New params
    qty_s   = input("  New quantity (Enter to keep): ").strip()
    price_s = input("  New price    (Enter to keep): ").strip()

    body: dict = {"order_id": order_id, "validity": "DAY"}
    if qty_s:
        try:
            body["quantity"] = int(qty_s)
        except Exception:
            print("  Invalid quantity."); return
    if price_s:
        try:
            body["price"] = float(price_s)
            body["order_type"] = "LIMIT"
        except Exception:
            print("  Invalid price."); return

    if len(body) == 2:  # only order_id + validity, nothing changed
        print("  Nothing changed."); return

    code, resp = _put(base, token, "/order/modify", body)
    if code == 200:
        mod_id = resp.get("data", {}).get("order_id", order_id)
        print(f"\n  {green('Modified!')}  order_id: {mod_id}")
    else:
        msg = resp.get("message") or (resp.get("errors") or [{}])[0].get("message", "")
        print(f"\n  {red(f'Failed: HTTP {code}')}  {msg}")
    print()


# ── interactive menu ──────────────────────────────────────────────────────────

def _menu(base: str, token: str, sandbox: bool) -> None:
    mode = yellow("SANDBOX") if sandbox else green("LIVE")
    print(bold(f"\n  Order Manager  [{mode}]"))
    print("  " + "─" * 40)
    print("  [1] View open orders")
    print("  [2] Place new order")
    print("  [3] Cancel order")
    print("  [4] Cancel all open orders")
    print("  [5] Modify order")
    print("  [6] Order history")
    print("  [7] Trade history (fills)")
    print("  [q] Quit")
    print()

    choice = input("  → ").strip().lower()

    if choice == "1":
        cmd_orders(base, token)
    elif choice == "2":
        cmd_place(base, token, sandbox)
    elif choice == "3":
        cmd_orders(base, token)
        oid = input("  Enter order_id to cancel: ").strip()
        if oid:
            cmd_cancel(base, token, oid)
    elif choice == "4":
        cmd_cancel_all(base, token)
    elif choice == "5":
        cmd_modify(base, token)
    elif choice == "6":
        cmd_history(base, token)
    elif choice == "7":
        cmd_trades(base, token)
    elif choice in ("q", "quit", "exit"):
        print()
        return
    else:
        print("  Invalid choice.")

    # Loop back
    again = input("\n  Back to menu? [Y/n]: ").strip().lower()
    if again not in ("n", "no"):
        _menu(base, token, sandbox)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upstox order manager")
    parser.add_argument("command", nargs="?",
                        choices=["orders", "place", "cancel", "cancelall",
                                 "history", "trades", "modify"],
                        help="Subcommand (default: interactive menu)")
    parser.add_argument("order_id", nargs="?", help="Order ID (for cancel/modify)")
    parser.add_argument("--sandbox", action="store_true",
                        help="Use sandbox environment (safe testing)")
    parser.add_argument("--token",   help="Explicit access token")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    _load_env()
    token = _find_token(args.token, sandbox=args.sandbox)
    base  = SANDBOX_BASE if args.sandbox else PROD_BASE

    if args.sandbox:
        print(f"\n  {yellow('Sandbox mode')}  API: {base}")

    if args.command == "orders":
        cmd_orders(base, token, args.verbose)
    elif args.command == "place":
        cmd_place(base, token, args.sandbox)
    elif args.command == "cancel":
        if args.order_id:
            cmd_cancel(base, token, args.order_id)
        else:
            cmd_orders(base, token)
            oid = input("  Enter order_id to cancel: ").strip()
            if oid:
                cmd_cancel(base, token, oid)
    elif args.command == "cancelall":
        cmd_cancel_all(base, token)
    elif args.command == "history":
        cmd_history(base, token)
    elif args.command == "trades":
        cmd_trades(base, token)
    elif args.command == "modify":
        cmd_modify(base, token)
    else:
        _menu(base, token, args.sandbox)


if __name__ == "__main__":
    main()
