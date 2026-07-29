from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

BASE_DIR = Path("/home/z/z/backend")
DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "timeline.sqlite"

DATABASE_URL = (
    os.getenv("TIMELINE_DB_URL")
    or os.getenv("DATABASE_URL")
    or os.getenv("DB_URL")
    or f"sqlite:///{DEFAULT_DB_PATH}"
)

if DATABASE_URL.startswith("sqlite:///"):
    raw_path = DATABASE_URL.replace("sqlite:///", "", 1)
    db_file = Path(raw_path)
    if not db_file.is_absolute():
        db_file = (Path.cwd() / db_file).resolve()
    db_file.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
)

Base = declarative_base()

def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS timeline_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    meta TEXT
                )
                """
            )
        )

init_db()

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()