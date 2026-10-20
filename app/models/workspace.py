import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import Role, str_enum
from app.models.user import User


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200))
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    default_geography: Mapped[str] = mapped_column(String(64), default="Worldwide")
    # Demo workspaces hold fixture data only; see scripts/seed_demo.py.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkspaceMembership(UUIDPrimaryKey, Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(str_enum(Role, "workspace_role"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship()
    user: Mapped[User] = relationship()


class WorkspaceInvitation(UUIDPrimaryKey, Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        # At most one pending invitation per email per workspace.
        Index(
            "uq_workspace_invitations_pending",
            "workspace_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(str_enum(Role, "invitation_role"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace: Mapped[Workspace] = relationship()
