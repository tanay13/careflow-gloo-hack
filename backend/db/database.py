"""SQLite engine/session management.

The engine is swappable so the evaluation suite can run against an isolated
temporary database without touching the demo database.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


engine: Engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


# Append-only audit log enforced at the database layer: nobody (including the
# agent) can rewrite or delete history through the application.
AUDIT_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
       BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;""",
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
       BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;""",
]


def init_db(eng: Engine | None = None) -> None:
    import models.entities  # noqa: F401  (register tables)

    eng = eng or engine
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        for stmt in AUDIT_TRIGGERS:
            conn.execute(text(stmt))


def drop_all(eng: Engine | None = None) -> None:
    import models.entities  # noqa: F401

    eng = eng or engine
    with eng.begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS audit_no_update"))
        conn.execute(text("DROP TRIGGER IF EXISTS audit_no_delete"))
    Base.metadata.drop_all(eng)


def use_engine(eng: Engine) -> None:
    """Rebind the global session factory (used by the isolated eval runner)."""
    global engine
    engine = eng
    SessionLocal.configure(bind=eng)


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
