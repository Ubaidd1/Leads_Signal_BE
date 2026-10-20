from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import RateLimited

_UPSERT = text(
    """
    INSERT INTO rate_limit_buckets (key, window_start, count)
    VALUES (:key, :window_start, 1)
    ON CONFLICT (key) DO UPDATE SET
        count = CASE WHEN rate_limit_buckets.window_start = EXCLUDED.window_start
                     THEN rate_limit_buckets.count + 1 ELSE 1 END,
        window_start = EXCLUDED.window_start
    RETURNING count
    """
)


def hit(db: Session, key: str, *, limit: int, window_seconds: int) -> None:
    """Counts one attempt against ``key`` and raises RateLimited once ``limit`` is exceeded.

    The increment is committed immediately so it survives a failed request.
    """
    now = datetime.now(UTC).timestamp()
    window_start = datetime.fromtimestamp(now - now % window_seconds, UTC)
    count = db.execute(_UPSERT, {"key": key[:200], "window_start": window_start}).scalar_one()
    db.commit()
    if count > limit:
        retry_after = int(window_start.timestamp() + window_seconds - now) + 1
        raise RateLimited(retry_after)


def purge_expired(db: Session, older_than_seconds: int = 86400) -> int:
    result = db.execute(
        text("DELETE FROM rate_limit_buckets WHERE window_start < now() - make_interval(secs => :s)"),
        {"s": older_than_seconds},
    )
    db.commit()
    return result.rowcount
