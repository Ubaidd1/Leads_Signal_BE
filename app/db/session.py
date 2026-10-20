from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def make_engine(url: str, **kwargs) -> Engine:
    # Force UTF-8 on the client side: on a SQL_ASCII server psycopg would otherwise return bytes.
    return create_engine(url, pool_pre_ping=True, connect_args={"client_encoding": "utf8"}, **kwargs)


engine = make_engine(
    settings.database_url, pool_size=settings.database_pool_size, max_overflow=settings.database_max_overflow
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """One session per request. Services commit explicitly; anything uncommitted is rolled back."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
