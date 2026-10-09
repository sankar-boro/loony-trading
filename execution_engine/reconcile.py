"""Compare the bot's position book with what Upstox actually holds.

Pure functions only, so the rules are easy to test; main.py's bot fetches
the broker data and acts on the result (see UpstoxTradingBot._reconcile).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Mismatch:
    key: str            # instrument key, e.g. "NSE_EQ|INE002A01018"
    bot_qty: float      # signed: +long, -short
    broker_qty: int     # signed net quantity at the broker
    kind: str           # "missing_at_broker" | "untracked_at_broker"

    @property
    def broker_cover(self) -> float:
        """How much of the bot's position the broker actually backs (≥ 0)."""
        if self.bot_qty > 0:
            return max(self.broker_qty, 0)
        if self.bot_qty < 0:
            return max(-self.broker_qty, 0)
        return 0


def _key(row: dict) -> str:
    return row.get("instrument_token") or row.get("instrument_key") or ""


def broker_net_quantities(positions: list[dict], holdings: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Return (total, today) signed net quantities per instrument key.

    `today` covers short-term positions only (intraday, F&O and today's
    delivery trades). `total` adds long-term holdings, including T1 shares
    that are bought but not yet settled.
    """
    today: dict[str, int] = {}
    for row in positions:
        k = _key(row)
        if k:
            today[k] = today.get(k, 0) + int(row.get("quantity") or 0)
    total = dict(today)
    for row in holdings:
        k = _key(row)
        if k:
            total[k] = total.get(k, 0) + int(row.get("quantity") or 0) + int(row.get("t1_quantity") or 0)
    return total, today


def compare_books(expected: dict[str, float], broker_total: dict[str, int],
                  broker_today: dict[str, int]) -> list[Mismatch]:
    """Find where the bot's book and the broker disagree in a way that matters.

    - missing_at_broker: the bot thinks it holds more (in its direction) than
      the broker has. Dangerous: a stop-loss would send an order for shares
      that are not there and open a new position the other way.
    - untracked_at_broker: the broker shows a position opened today that the
      bot is not tracking. Holdings are deliberately ignored here, since they
      can be the account owner's own long-term shares.

    The broker holding *more* than the bot in the same direction is not a
    mismatch for the same reason.
    """
    out: list[Mismatch] = []
    for key, bot_qty in expected.items():
        if not bot_qty:
            continue
        b = broker_total.get(key, 0)
        short_of = b < bot_qty if bot_qty > 0 else b > bot_qty
        if short_of:
            out.append(Mismatch(key, bot_qty, b, "missing_at_broker"))
    for key, b in broker_today.items():
        if b and not expected.get(key):
            out.append(Mismatch(key, 0.0, b, "untracked_at_broker"))
    return out
