"""Background worker: a thread that polls import_draft for pending rows.

One row at a time. Rows are claimed with FOR UPDATE SKIP LOCKED, so running
more than one app process is safe.
"""
import logging
import threading

from sqlalchemy import case, select, update

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import ImportDraft
from app.services import importer
from app.services.llm.langchain import get_llm

log = logging.getLogger("maturinn.worker")
POLL_SECONDS = 1.0


def recover_interrupted() -> None:
    """Rows left mid-run by a restart can't resume; mark them failed so they can be retried."""
    with get_sessionmaker()() as s:
        for row in s.execute(select(ImportDraft).where(ImportDraft.status.in_(("fetching", "extracting")))).scalars():
            row.status = "failed"
            row.error = "interrupted"
            importer.add_event(row, {"t": "error", "code": "interrupted", "detail": ""})
        s.commit()


def claim_next() -> int | None:
    with get_sessionmaker()() as s:
        row_id = s.execute(
            select(ImportDraft.id).where(ImportDraft.status == "pending")
            .order_by(ImportDraft.id).limit(1).with_for_update(skip_locked=True)
        ).scalar()
        if row_id is None:
            return None
        s.execute(update(ImportDraft).where(ImportDraft.id == row_id).values(
            status=case((ImportDraft.kind == "text", "extracting"), else_="fetching")))
        s.commit()
        return row_id


def run_one(row_id: int) -> None:
    with get_sessionmaker()() as s:
        row = s.get(ImportDraft, row_id)
        importer.process(s, row, get_llm(get_settings()))


class Worker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="import-worker", daemon=True)

    def start(self) -> None:
        recover_interrupted()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                row_id = claim_next()
                if row_id is not None:
                    log.info("import %s started", row_id)
                    run_one(row_id)
                    log.info("import %s finished", row_id)
                    continue
            except Exception:
                log.exception("worker error")
            self._stop.wait(POLL_SECONDS)
