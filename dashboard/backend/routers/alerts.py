from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.base import get_db
from db.models import Alert, AlertTrigger, Stock
from signals.alerts import evaluate_alerts, validate_condition

router = APIRouter()


class CreateAlert(BaseModel):
    name: str
    condition: dict
    symbol: str | None = None  # None = whole universe


def _alert_dict(alert: Alert) -> dict:
    return {
        "id": alert.id,
        "name": alert.name,
        "symbol": alert.stock.symbol if alert.stock else None,
        "condition": alert.condition,
        "is_active": alert.is_active,
        "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
        "created_at": alert.created_at.isoformat(),
    }


@router.get("/alerts")
def list_alerts(db: Session = Depends(get_db)) -> list[dict]:
    return [_alert_dict(a) for a in db.query(Alert).order_by(desc(Alert.created_at)).all()]


@router.post("/alerts")
def create_alert(body: CreateAlert, db: Session = Depends(get_db)) -> dict:
    error = validate_condition(body.condition)
    if error:
        raise HTTPException(400, error)

    stock_id = None
    if body.symbol:
        stock = db.query(Stock).filter(Stock.symbol == body.symbol.upper()).first()
        if not stock:
            raise HTTPException(404, f"Unknown symbol: {body.symbol}")
        stock_id = stock.id

    alert = Alert(name=body.name, stock_id=stock_id, condition=body.condition)
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _alert_dict(alert)


@router.patch("/alerts/{alert_id}")
def toggle_alert(alert_id: int, is_active: bool, db: Session = Depends(get_db)) -> dict:
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    alert.is_active = is_active
    db.commit()
    db.refresh(alert)
    return _alert_dict(alert)


@router.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)) -> dict:
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(404, "Alert not found")
    db.delete(alert)
    db.commit()
    return {"deleted": alert_id}


@router.get("/alerts/{alert_id}/triggers")
def list_triggers(alert_id: int, limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    rows = (
        db.query(AlertTrigger, Stock.symbol)
        .join(Stock, AlertTrigger.stock_id == Stock.id)
        .filter(AlertTrigger.alert_id == alert_id)
        .order_by(desc(AlertTrigger.created_at))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": trigger.id, "symbol": symbol, "signal_id": trigger.signal_id,
            "matched_values": trigger.matched_values, "created_at": trigger.created_at.isoformat(),
        }
        for trigger, symbol in rows
    ]


@router.post("/alerts/evaluate")
def run_evaluation(
    timeframe: str = Query("1d", description='signal bar size to evaluate against, e.g. "1d", "30m"'),
    db: Session = Depends(get_db),
) -> dict:
    """Manual evaluation trigger — a scheduler replaces this call site in
    Phase 11, same as /api/news/ingest and the signal-engine runner.
    `timeframe` selects daily vs. intraday signals (docs/intraday_gaps.md
    §5) — an alert only fires against the latest signal of the timeframe
    you ask for."""
    from utils.telegram_alerts import TelegramAlerter
    summary = evaluate_alerts(db, notifier=TelegramAlerter(), timeframe=timeframe)
    return {
        "alerts_checked": summary.alerts_checked,
        "timeframe": timeframe,
        "triggers": [
            {"alert_id": e.alert_id, "alert_name": e.alert_name, "symbol": e.symbol,
             "matched_values": e.matched_values}
            for e in summary.triggers
        ],
    }
