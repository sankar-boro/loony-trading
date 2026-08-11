from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from signals.copilot import answer_query

router = APIRouter()


class CopilotQuery(BaseModel):
    question: str


@router.post("/copilot/query")
def copilot_query(body: CopilotQuery, db: Session = Depends(get_db)) -> dict:
    result = answer_query(db, body.question)
    return {
        "answer": result.answer,
        "confidence": result.confidence,
        "evidence": result.evidence,
        "insufficient_evidence": result.insufficient_evidence,
    }
