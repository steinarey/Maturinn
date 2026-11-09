import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import admin, api, auth, health, imports, ingredients, pages, shopping
from app.routers.auth import LoginRequired, login_required_handler, reissue_cookie_middleware, require_user
from app.worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    if get_settings().worker_enabled:
        worker = Worker()
        worker.start()
    yield
    if worker:
        worker.stop()


# Our own log lines (imports, worker) go to the container log next to uvicorn's.
_log = logging.getLogger("maturinn")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False

settings = get_settings()
settings.photos_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Maturinn", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.add_exception_handler(LoginRequired, login_required_handler)
app.middleware("http")(reissue_cookie_middleware)

# Open: health check and the login page. Everything else needs a logged-in user.
app.include_router(health.router)
app.include_router(auth.router)
guarded = [Depends(require_user)]
for r in (admin.router, api.router, ingredients.router, imports.router, shopping.router, pages.router):
    app.include_router(r, dependencies=guarded)


@app.get("/photos/{path:path}", dependencies=guarded, include_in_schema=False)
def photo(path: str):
    """Uploaded photos (behind login, unlike /static). Names are random, so cache hard."""
    root = settings.photos_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root) or not file.is_file():
        raise HTTPException(404)
    return FileResponse(file, headers={"Cache-Control": "private, max-age=31536000, immutable"})
