from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1"))
    except Exception as e:  # report, don't crash
        return JSONResponse({"status": "error", "db": str(e.__class__.__name__)}, status_code=503)
    return {"status": "ok", "db": "ok"}
