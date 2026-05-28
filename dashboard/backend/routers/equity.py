from fastapi import APIRouter
from ..utils import read_jsonl
from ..config import _EQUITY_FILE

router = APIRouter()

@router.get("/equity")
def get_equity() -> list[dict]:
    return read_jsonl(_EQUITY_FILE)