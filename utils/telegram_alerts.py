"""
Telegram Alerts — trade notifications, daily summary, risk alerts.

Setup:
1. Create bot via @BotFather → get TELEGRAM_BOT_TOKEN
2. Send any message to your bot → get TELEGRAM_CHAT_ID via getUpdates
3. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Alert levels:
- INFO:     trade executed, daily P&L summary
- WARNING:  strategy size reduced, approaching circuit
- CRITICAL: strategy disabled, portfolio halted, circuit hit
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Optional

from utils.logger import get_logger

logger = get_logger("telegram_alerts")

_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramAlerter:
    """
    Non-blocking Telegram notifications for the trading bot.

    All sends are dispatched in background threads so they never block
    the trading loop.
    """

    def __init__(
        self,
        bot_token:    Optional[str] = None,
        chat_id:      Optional[str] = None,
        enabled:      bool = True,
        min_level:    str = "INFO",    # INFO | WARNING | CRITICAL
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id   = chat_id   or os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled   = enabled and bool(self.bot_token) and bool(self.chat_id)
        self.min_level = min_level
        self._level_rank = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}

        if not self.enabled:
            logger.info("TelegramAlerter: disabled (no token/chat_id configured)")

    def _should_send(self, level: str) -> bool:
        return (self.enabled and
                self._level_rank.get(level, 0) >= self._level_rank.get(self.min_level, 0))

    def _send_async(self, text: str) -> None:
        """Send in background thread — never blocks the caller."""
        def _post():
            try:
                import requests
                resp = requests.post(
                    _SEND_URL.format(token=self.bot_token),
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                    timeout=5,
                )
                if resp.status_code != 200:
                    logger.warning(f"Telegram send failed: {resp.text[:100]}")
            except Exception as e:
                logger.debug(f"Telegram send error: {e}")

        t = threading.Thread(target=_post, daemon=True)
        t.start()

    def send(self, text: str, level: str = "INFO", key: Optional[str] = None,
             cooldown_sec: Optional[float] = None) -> bool:
        """Send unless below min_level or stopped by the shared
        NotificationGuard (dedupe / named-key cooldown / rate limit).
        Returns whether it was sent."""
        from utils.notify_guard import get_guard
        if self._should_send(level) and get_guard().allow(text, level, key, cooldown_sec):
            self._send_async(text)
            return True
        return False

    # ── Pre-formatted alert methods ───────────────────────────────────────────

    def trade_alert(
        self,
        strategy:  str,
        symbol:    str,
        direction: str,
        qty:       int,
        price:     float,
        pnl:       Optional[float] = None,
    ) -> None:
        emoji  = "🟢" if direction == "BUY" else "🔴"
        pnl_str = f"\nP&L: ₹{pnl:+,.0f}" if pnl is not None else ""
        text = (
            f"{emoji} <b>TRADE</b> [{strategy}]\n"
            f"{symbol} {direction} {qty} @ ₹{price:,.2f}{pnl_str}\n"
            f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
        )
        self.send(text, "INFO")

    def risk_alert(
        self,
        alert_type: str,     # "strategy_disabled" | "portfolio_halt" | "circuit" | "drawdown"
        detail:     str,
        level:      str = "CRITICAL",
    ) -> None:
        emoji_map = {
            "strategy_disabled": "⛔",
            "portfolio_halt":    "🚨",
            "circuit":           "⚠️",
            "drawdown":          "📉",
        }
        emoji = emoji_map.get(alert_type, "⚠️")
        text  = (
            f"{emoji} <b>RISK ALERT</b> [{alert_type.upper()}]\n"
            f"{detail}\n"
            f"<i>{datetime.now().strftime('%H:%M:%S')}</i>"
        )
        self.send(text, level)

    def daily_summary(
        self,
        capital:       float,
        daily_pnl:     float,
        trade_count:   int,
        win_rate:      float,
        drawdown_pct:  float,
        top_winners:   list = None,
        top_losers:    list = None,
    ) -> None:
        pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
        lines = [
            f"{pnl_emoji} <b>DAILY SUMMARY</b>",
            f"P&L: ₹{daily_pnl:+,.0f} ({daily_pnl/capital*100:+.2f}%)",
            f"Trades: {trade_count} | Win rate: {win_rate:.0%}",
            f"Max DD: {drawdown_pct:.2f}%",
        ]
        if top_winners:
            lines.append("📈 Winners: " + ", ".join(str(w) for w in top_winners[:3]))
        if top_losers:
            lines.append("📉 Losers: " + ", ".join(str(l) for l in top_losers[:3]))
        lines.append(f"<i>{datetime.now().strftime('%d-%b-%Y %H:%M')}</i>")
        self.send("\n".join(lines), "INFO")

    def circuit_alert(self, symbol: str, circuit_type: str, price: float) -> None:
        self.risk_alert(
            "circuit",
            f"{symbol} hit {circuit_type} CIRCUIT @ ₹{price:,.2f}\n"
            f"Positions may be ILLIQUID — check immediately!",
            "CRITICAL",
        )

    def market_halt_alert(self, level_pct: float, resume_time: Optional[str] = None) -> None:
        resume = f"\nResume: {resume_time}" if resume_time else "\nRest-of-day halt"
        self.risk_alert(
            "portfolio_halt",
            f"NSE MARKET CIRCUIT: Nifty moved {level_pct:.0f}%{resume}",
            "CRITICAL",
        )

    def strategy_disabled_alert(self, strategy: str, reason: str) -> None:
        self.risk_alert(
            "strategy_disabled",
            f"Strategy <b>{strategy}</b> auto-disabled\nReason: {reason}",
            "CRITICAL",
        )

    def status_check(self) -> bool:
        """Returns True if Telegram is reachable (quick connectivity test)."""
        if not self.enabled:
            return False
        try:
            import requests
            resp = requests.get(
                f"https://api.telegram.org/bot{self.bot_token}/getMe",
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False
