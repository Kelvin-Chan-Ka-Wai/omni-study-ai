import os
import sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

STORAGE_DIR = Path(os.environ.get("OMNISTUDY_STORAGE_DIR", Path(__file__).resolve().parent / "storage")).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = STORAGE_DIR / "study_history.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db() -> None:
    import models  # noqa: F401
    # Back up existing SQLite safely (including committed WAL contents) before schema additions.
    if DB_PATH.exists():
        backup = STORAGE_DIR / "backups" / ("before-upgrade-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db")
        with engine.connect() as connection:
            additions = {
                "exam_sessions": {"draft_json": "TEXT", "result_json": "TEXT", "deadline_at": "TEXT", "paused_remaining": "FLOAT", "grace_started_at": "TEXT"},
                "wrong_question_bank": {"original_json": "TEXT", "variant_history_json": "TEXT", "next_review_at": "DATETIME"},
            }
            pending = []
            for table, fields in additions.items():
                existing = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")}
                if existing:
                    pending.extend((table, name, kind) for name, kind in fields.items() if name not in existing)
        if pending:
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(backup) as target:
                source.backup(target)
            backup.chmod(0o600)
            with engine.begin() as connection:
                for table, name, kind in pending:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE exam_sessions SET status = 'in_progress' WHERE status = 'grading'")
        connection.exec_driver_sql("UPDATE generation_jobs SET status = 'failed', message = 'App restarted; previously saved work is preserved. Retry generation.' WHERE status IN ('queued', 'running')")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
