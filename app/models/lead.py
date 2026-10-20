import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.models.company import Company
from app.models.enums import HiringIntent, LeadStatus, VerificationStatus, str_enum


class Lead(UUIDPrimaryKey, Timestamps, Base):
    """A hiring opportunity: one canonical (deduplicated) job opening at a company."""

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_technologies", "technologies", postgresql_using="gin"),
        Index("ix_leads_regions", "regions", postgresql_using="gin"),
        Index("ix_leads_score_id", "score", "id"),
        Index("ix_leads_posted_at_id", "posted_at", "id"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    service_type: Mapped[str | None] = mapped_column(String(100), index=True)
    seniority: Mapped[str | None] = mapped_column(String(100))
    technologies: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    remote_policy: Mapped[str | None] = mapped_column(String(200))
    # Normalised geography tags used for filtering, e.g. "worldwide", "united-states", "pakistan-allowed".
    regions: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    hiring_intent: Mapped[HiringIntent | None] = mapped_column(str_enum(HiringIntent, "lead_intent"), index=True)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus, "verification_status"), default=VerificationStatus.UNVERIFIED
    )
    status: Mapped[LeadStatus] = mapped_column(str_enum(LeadStatus, "lead_status"), default=LeadStatus.OPEN)
    canonical_url: Mapped[str | None] = mapped_column(String(1000))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Denormalised from the latest LeadScore for filtering and sorting.
    score: Mapped[int | None] = mapped_column(Integer)
    score_version: Mapped[str | None] = mapped_column(String(32))

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Company] = relationship(back_populates="leads")
    sources: Mapped[list["LeadSource"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    scores: Mapped[list["LeadScore"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class LeadSource(UUIDPrimaryKey, Base):
    """Provenance: one source record that was deduplicated into a lead."""

    __tablename__ = "lead_sources"
    __table_args__ = (UniqueConstraint("source_type", "source_record_id"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(50))
    source_name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_record_id: Mapped[str] = mapped_column(String(300))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead] = relationship(back_populates="sources")


class LeadScore(UUIDPrimaryKey, Base):
    """Versioned score calculation. The latest row is mirrored onto Lead.score."""

    __tablename__ = "lead_scores"
    __table_args__ = (Index("ix_lead_scores_lead_calculated", "lead_id", "calculated_at"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(32))
    total: Mapped[int] = mapped_column(Integer)
    # {"relevance": 23, "hiringIntent": 18, ...}
    components: Mapped[dict] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped[Lead] = relationship(back_populates="scores")


class HiringSignal(UUIDPrimaryKey, Base):
    """A dated hiring event for a company, optionally tied to a specific lead."""

    __tablename__ = "hiring_signals"
    __table_args__ = (Index("ix_hiring_signals_company_occurred", "company_id", "occurred_at"),)

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    signal_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SavedLead(UUIDPrimaryKey, Base):
    """Workspace-shared bookmark of a canonical lead (the lead itself is never copied)."""

    __tablename__ = "saved_leads"
    __table_args__ = (UniqueConstraint("workspace_id", "lead_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    saved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped[Lead] = relationship()
