import asyncio
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from utils.logger import get_logger

logger = get_logger("notifier")


_LEVELS = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


class Notifier:
    """Telegram and e-mail for the bot. Every message passes the shared
    NotificationGuard (dedupe + rate limit); e-mail only goes out from
    `notifications.email.min_level` (WARNING) up, Telegram from
    `notifications.telegram.min_level` (INFO) up."""

    def __init__(self, cfg: dict):
        self.tg_cfg = cfg.get("telegram", {})
        self.email_cfg = cfg.get("email", {})

    def _wants(self, channel_cfg: dict, level: str, default: str) -> bool:
        floor = str(channel_cfg.get("min_level", default)).upper()
        return bool(channel_cfg.get("enabled")) and _LEVELS.get(level, 0) >= _LEVELS.get(floor, 0)

    async def send(self, message: str, level: str = "INFO", key: Optional[str] = None,
                   cooldown_sec: Optional[float] = None) -> None:
        from utils.notify_guard import get_guard
        level = level.upper()
        if not (self._wants(self.tg_cfg, level, "INFO") or self._wants(self.email_cfg, level, "WARNING")):
            return
        if not get_guard().allow(message, level, key, cooldown_sec):
            return
        tasks = []
        if self._wants(self.tg_cfg, level, "INFO"):
            tasks.append(self._send_telegram(message))
        if self._wants(self.email_cfg, level, "WARNING"):
            tasks.append(self._send_email(f"[{level}] Trading Alert", message))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_telegram(self, text: str) -> None:
        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self.tg_cfg['bot_token']}/sendMessage"
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={
                    "chat_id": self.tg_cfg["chat_id"],
                    "text": text,
                    "parse_mode": "HTML",
                })
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")

    async def _send_email(self, subject: str, body: str) -> None:
        try:
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.email_cfg["user"]
            msg["To"] = self.email_cfg["to"]
            with smtplib.SMTP(self.email_cfg["smtp_host"], self.email_cfg["smtp_port"]) as s:
                s.starttls()
                s.login(self.email_cfg["user"], self.email_cfg["password"])
                s.send_message(msg)
        except Exception as e:
            logger.error(f"Email send failed: {e}")
