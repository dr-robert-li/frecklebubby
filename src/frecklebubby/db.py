"""Engine, session and schema creation."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import String, TypeDecorator, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

SessionLocal = sessionmaker(expire_on_commit=False)


class UTCDateTime(TypeDecorator):
    """Stores aware datetimes as UTC ISO 8601 text ("2026-11-20T01:02:03Z"); the fixed format keeps text order = time order."""

    impl = String(20)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def process_result_value(self, value: str | None, dialect) -> datetime | None:
        return None if value is None else datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


def init_db(data_dir: Path) -> None:
    from . import models  # noqa: F401  registers the tables

    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / 'frecklebubby.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    # shortcut: no Alembic yet; add it before the first schema change after v0.1.0.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunk USING fts5(source_id UNINDEXED, heading, text)"))
    SessionLocal.configure(bind=engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
