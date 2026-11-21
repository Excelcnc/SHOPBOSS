from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def SessionLocal():
    engine()
    return _Session()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_engine():
    """Used by tests after changing DATABASE_URL."""
    global _engine, _Session
    _engine = None
    _Session = None


def add_missing_columns(eng) -> list[str]:
    """Add columns that exist in the models but not yet in the database (until Alembic migrations exist).

    New columns are added as nullable with the model's scalar default as server default, so existing
    rows stay valid. Never drops or changes anything.
    """
    from sqlalchemy import inspect, text
    insp = inspect(eng)
    added = []
    with eng.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(dialect=eng.dialect)}'
                d = col.default.arg if col.default is not None and col.default.is_scalar else None
                if isinstance(d, bool):
                    ddl += f" DEFAULT {'TRUE' if d else 'FALSE'}"
                elif isinstance(d, (int, float)):
                    ddl += f" DEFAULT {d}"
                elif isinstance(d, str):
                    ddl += " DEFAULT '" + d.replace("'", "''") + "'"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added
