from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().photos_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Maturinn", lifespan=lifespan)
app.include_router(health.router)
