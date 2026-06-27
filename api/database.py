from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from api.config import settings

connect_args = {"check_same_thread": False} if "sqlite" in settings.db_url else {}
engine = create_engine(settings.db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
