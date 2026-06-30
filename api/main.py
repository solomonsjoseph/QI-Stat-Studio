import os
import api.models_db  # ensure all models registered before create_all
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api.database import engine, Base
from api.config import settings

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = settings.fernet  # raises RuntimeError if FERNET_KEY missing
    yield


app = FastAPI(title="QI Stat Studio", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routers import projects, upload, analyze, ai, report, intake, share, settings_router, notifications  # noqa: F401
app.include_router(projects.router)
app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(ai.router)
app.include_router(report.router)
app.include_router(intake.router)
app.include_router(share.router)
app.include_router(settings_router.router)

# Serve frontend static files when web/dist exists (production / Docker)
_dist = os.path.join(os.path.dirname(__file__), "..", "web", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
