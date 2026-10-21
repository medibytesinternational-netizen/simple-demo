from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import clock
from .config import settings


def utcnow() -> datetime:
    return clock.now()


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_sqlite_columns() -> None:
    """Apply the small additive migrations needed by the demo database.

    The project intentionally has no migration framework. These ALTERs keep an
    existing rehearsal database usable when new task lifecycle columns are added.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    additions = {
        "tasks": {
            "assigned_to": "VARCHAR",
            "assigned_at": "DATETIME",
            "assigned_by": "VARCHAR",
            "acknowledged_at": "DATETIME",
            "acknowledged_by": "VARCHAR",
            "escalation_level": "INTEGER DEFAULT 0",
            "escalated_at": "DATETIME",
            "escalation_reason": "TEXT",
        },
        "bill_line_items": {
            "expected_amount": "FLOAT",
        },
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            rows = connection.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
