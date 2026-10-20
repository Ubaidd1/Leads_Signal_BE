import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.enums import HiringIntent, str_enum


class Company(UUIDPrimaryKey, Timestamps, Base):
    """A hiring organisation.

    ``workspace_id IS NULL`` means the company belongs to the shared catalogue; otherwise it
    is private to that workspace (customer imports, demo fixtures).
    """

    __tablename__ = "companies"
    __table_args__ = (
        Index("uq_companies_shared_slug", "slug", unique=True, postgresql_where=text("workspace_id IS NULL")),
        Index("uq_companies_workspace_slug", "workspace_id", "slug", unique=True, postgresql_where=text("workspace_id IS NOT NULL")),
        Index("ix_companies_technologies", "technologies", postgresql_using="gin"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200), index=True)
    domain: Mapped[str | None] = mapped_column(String(255))
    careers_url: Mapped[str | None] = mapped_column(String(1000))
    industry: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(200))
    size_range: Mapped[str | None] = mapped_column(String(50))
    overview: Mapped[str | None] = mapped_column(Text)
    remote_policy: Mapped[str | None] = mapped_column(String(200))
    technologies: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    departments: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)

    # Reported hiring metrics. Populated by ingestion (or the demo seed); NULL means unknown,
    # never zero-filled.
    intent_score: Mapped[int | None] = mapped_column(Integer)
    intent_level: Mapped[HiringIntent | None] = mapped_column(str_enum(HiringIntent, "company_intent"))
    open_roles_count: Mapped[int | None] = mapped_column(Integer)
    relevant_roles_count: Mapped[int | None] = mapped_column(Integer)
    hiring_velocity_pct: Mapped[int | None] = mapped_column(Integer)
    skill_concentration: Mapped[str | None] = mapped_column(String(50))
    repeated_hiring_summary: Mapped[str | None] = mapped_column(Text)
    # Ordered list of {"period": str, "value": int}.
    activity_series: Mapped[list | None] = mapped_column(JSONB)

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    leads: Mapped[list["Lead"]] = relationship(back_populates="company")  # noqa: F821
