import uuid

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(
    db: Session,
    action: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: object = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    """Adds an audit event to the current transaction; it is committed with the change it describes."""
    db.add(
        AuditEvent(
            action=action,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip_address=ip_address,
            details=details,
        )
    )
