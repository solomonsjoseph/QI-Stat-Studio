import api.models_db  # ensure all models registered before create_all
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.database import engine, Base
from api.config import settings

Base.metadata.create_all(bind=engine)

app = FastAPI(title="QI Stat Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def check_config():
    _ = settings.fernet  # raises RuntimeError if FERNET_KEY missing

from api.routers import projects, upload, analyze, ai, report
app.include_router(projects.router)
app.include_router(upload.router)
app.include_router(analyze.router)
app.include_router(ai.router)
app.include_router(report.router)
