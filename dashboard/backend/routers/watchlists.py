"""
User-editable, multi-list watchlists (MarketPulse AI Phase 5) — distinct
from the legacy `/api/watchlist` (singular), which is a read-only,
hardcoded-symbol live-price panel. This is DB-backed CRUD.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from db.models import Stock, Watchlist, WatchlistItem

router = APIRouter()


class CreateWatchlist(BaseModel):
    name: str = "My Stocks"


class AddItem(BaseModel):
    symbol: str


def _watchlist_dict(watchlist: Watchlist) -> dict:
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "created_at": watchlist.created_at.isoformat(),
        "symbols": [item.stock.symbol for item in watchlist.items],
    }


@router.get("/watchlists")
def list_watchlists(db: Session = Depends(get_db)) -> list[dict]:
    return [_watchlist_dict(w) for w in db.query(Watchlist).order_by(Watchlist.created_at).all()]


@router.post("/watchlists")
def create_watchlist(body: CreateWatchlist, db: Session = Depends(get_db)) -> dict:
    watchlist = Watchlist(name=body.name)
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return _watchlist_dict(watchlist)


@router.delete("/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db)) -> dict:
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(404, "Watchlist not found")
    db.delete(watchlist)
    db.commit()
    return {"deleted": watchlist_id}


@router.post("/watchlists/{watchlist_id}/items")
def add_item(watchlist_id: int, body: AddItem, db: Session = Depends(get_db)) -> dict:
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(404, "Watchlist not found")
    stock = db.query(Stock).filter(Stock.symbol == body.symbol.upper()).first()
    if not stock:
        raise HTTPException(404, f"Unknown symbol: {body.symbol}")
    exists = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.stock_id == stock.id)
        .first()
    )
    if not exists:
        db.add(WatchlistItem(watchlist_id=watchlist_id, stock_id=stock.id))
        db.commit()
    db.refresh(watchlist)
    return _watchlist_dict(watchlist)


@router.delete("/watchlists/{watchlist_id}/items/{symbol}")
def remove_item(watchlist_id: int, symbol: str, db: Session = Depends(get_db)) -> dict:
    watchlist = db.query(Watchlist).filter(Watchlist.id == watchlist_id).first()
    if not watchlist:
        raise HTTPException(404, "Watchlist not found")
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if stock:
        db.query(WatchlistItem).filter(
            WatchlistItem.watchlist_id == watchlist_id, WatchlistItem.stock_id == stock.id,
        ).delete()
        db.commit()
    db.refresh(watchlist)
    return _watchlist_dict(watchlist)
