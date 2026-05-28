from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/telegram/test")
def test_telegram() -> dict:
    try:
        from utils.telegram_alerts import TelegramAlerter
        alerter = TelegramAlerter()
        enabled = alerter.enabled
        reachable = alerter.status_check() if enabled else False
        if enabled:
            alerter.send("✅ <b>Loony Trading — Telegram test</b>\nDashboard is connected and notifications are working.")
        return {
            "enabled": enabled, "reachable": reachable,
            "chat_id_set": bool(alerter.chat_id), "token_set": bool(alerter.bot_token),
            "message": "Test message sent" if enabled else "Telegram disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID",
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))