from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import api, health, ingredients, pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


settings = get_settings()
settings.photos_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Maturinn", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.mount("/photos", StaticFiles(directory=settings.photos_dir), name="photos")
app.include_router(health.router)
app.include_router(api.router)
app.include_router(ingredients.router)
app.include_router(pages.router)
