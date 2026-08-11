"""Scheduler status endpoint (MarketPulse AI Phase 11 — spec §55/§36)."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/scheduler/status")
def get_scheduler_status() -> dict:
    from scheduler import get_status
    return get_status()
