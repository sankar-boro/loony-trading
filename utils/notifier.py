import asyncio
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from utils.logger import get_logger

logger = get_logger("notifier")


class Notifier:
    def __init__(self, cfg: dict):
        self.tg_cfg = cfg.get("telegram", {})
        self.email_cfg = cfg.get("email", {})

    async def send(self, message: str, level: str = "INFO") -> None:
        tasks = []
        if self.tg_cfg.get("enabled"):
            tasks.append(self._send_telegram(message))
        if self.email_cfg.get("enabled"):
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
