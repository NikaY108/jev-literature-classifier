from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.database import init_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings().ensure_directories()
    init_database()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(router)

static_dir = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")
