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


# (table, column, SQL type) of nullable columns added after a release; init_db adds them to old databases.
NEW_COLUMNS = [("child", "due_date", "DATE"), ("chat_message", "logged", "JSON")]


def init_db(data_dir: Path) -> None:
    from . import models  # noqa: F401  registers the tables

    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / 'frecklebubby.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA secure_delete=ON")  # deleted data (M16) is overwritten in the file, not only unlinked
        cur.close()

    # shortcut: no Alembic yet; add it before the first schema change after v0.1.0.
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        # Columns added after 0.1.0: create_all does not add them to an existing table. All are nullable.
        for table, column, kind in NEW_COLUMNS:
            if column not in {r[1] for r in conn.execute(text(f'PRAGMA table_info("{table}")'))}:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {kind}'))
        _merge_play_bath(conn)
        conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunk USING fts5(source_id UNINDEXED, heading, text, "
                          "tokenize='porter unicode61')"))
    SessionLocal.configure(bind=engine)


_TS = "strftime('%Y-%m-%dT%H:%M:%SZ', {})"  # SQL: a time as UTCDateTime text


def _merge_play_bath(conn) -> None:
    """0.2.2: activity timers run in parallel (one per kind), and the play and bath types become activities.
    Idempotent: a second run finds no old rows."""
    if "kind" not in {r[1] for r in conn.execute(text('PRAGMA table_info("timer")'))}:
        # SQLite cannot change a UNIQUE constraint: make the table again and copy the rows.
        conn.execute(text("ALTER TABLE timer RENAME TO timer_old"))
        Base.metadata.tables["timer"].create(conn)
        conn.execute(text(
            "INSERT INTO timer (id, child_id, type, kind, started_at, paused_at, paused_seconds, data, started_by) "
            "SELECT id, child_id, type, CASE type WHEN 'activity' THEN coalesce(json_extract(data, '$.kind'), '') "
            "ELSE '' END, started_at, paused_at, paused_seconds, data, started_by FROM timer_old"))
        conn.execute(text("DROP TABLE timer_old"))
    conn.execute(text("UPDATE entry SET type = 'activity', data = json_object('kind', 'bath') WHERE type = 'bath'"))
    # The tummy part of a play entry has no own times: approximate it as tummy_seconds from the play start.
    tummy = "json_extract(data, '$.tummy_seconds')"
    conn.execute(text(
        "INSERT INTO entry (child_id, type, started_at, ended_at, data, source, created_by, created_at, updated_at) "
        f"SELECT child_id, 'activity', started_at, {_TS.format(f"started_at, '+' || CAST({tummy} AS INTEGER) || ' seconds'")}, "
        "json_object('kind', 'tummyTime'), source, created_by, created_at, updated_at "
        f"FROM entry WHERE type = 'play' AND {tummy} > 0"))
    conn.execute(text(
        "UPDATE entry SET type = 'activity', data = json_object('kind', CASE json_extract(data, '$.kind') "
        "WHEN 'outdoor' THEN 'outdoorPlay' ELSE 'indoorPlay' END) WHERE type = 'play'"))
    conn.execute(text(
        "INSERT OR IGNORE INTO timer (child_id, type, kind, started_at, paused_seconds, data, started_by) "
        f"SELECT child_id, 'activity', 'tummyTime', {_TS.format("json_extract(data, '$.tummy_started_at')")}, 0, "
        "json_object('kind', 'tummyTime'), started_by FROM timer "
        "WHERE type = 'play' AND json_extract(data, '$.tummy_started_at') IS NOT NULL"))
    conn.execute(text("UPDATE OR IGNORE timer SET type = 'activity', kind = 'indoorPlay', "
                      "data = json_object('kind', 'indoorPlay') WHERE type = 'play'"))
    conn.execute(text("DELETE FROM timer WHERE type = 'play'"))  # only when an indoor play timer ran already
    conn.execute(text("UPDATE reminder SET type = 'activity' WHERE type IN ('play', 'bath')"))


def get_session() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)
