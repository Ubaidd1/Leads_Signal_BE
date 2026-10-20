"""Tenant-scoped queries for companies and leads.

Every query here goes through ``visible_to`` so a workspace only ever sees the shared catalogue
plus its own private rows.
"""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

from sqlalchemy import Select, String, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.models import Company, HiringSignal, Lead, SavedLead
from app.models.enums import HiringIntent, LeadStatus
from app.utils.time import utcnow

SortOrder = Literal["asc", "desc"]

LEAD_SORTS = {
    "score": Lead.score,
    "postedAt": Lead.posted_at,
    "lastVerifiedAt": Lead.last_verified_at,
    "companyName": Company.name,
    "title": Lead.title,
}
COMPANY_SORTS = {
    "intentScore": Company.intent_score,
    "name": Company.name,
    "hiringVelocity": Company.hiring_velocity_pct,
    "openRoles": Company.open_roles_count,
}


def visible_to(model, workspace_id: uuid.UUID):
    return or_(model.workspace_id.is_(None), model.workspace_id == workspace_id)


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _text_array(values: list[str]):
    return cast(values, ARRAY(String))


def is_saved_expr(workspace_id: uuid.UUID):
    return exists().where(SavedLead.workspace_id == workspace_id, SavedLead.lead_id == Lead.id)


def _ordered(stmt: Select, column, order: SortOrder, tiebreak) -> Select:
    direction = column.desc() if order == "desc" else column.asc()
    # Deterministic pagination: NULLs last, then a unique tiebreaker.
    return stmt.order_by(direction.nulls_last(), tiebreak.desc() if order == "desc" else tiebreak.asc())


def _paginate(db: Session, stmt: Select, page: int, page_size: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return rows, total


# --- leads -----------------------------------------------------------------------


@dataclass
class LeadFilters:
    q: str | None = None
    service_types: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    technology_match: Literal["any", "all"] = "any"
    intents: list[HiringIntent] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    freshness_days: int | None = None
    min_score: int | None = None
    company_id: uuid.UUID | None = None
    saved_only: bool = False
    include_closed: bool = False


def lead_query(workspace_id: uuid.UUID, filters: LeadFilters) -> Select:
    saved = is_saved_expr(workspace_id)
    stmt = (
        select(Lead, Company, saved.label("is_saved"))
        .join(Company, Company.id == Lead.company_id)
        .where(visible_to(Lead, workspace_id), visible_to(Company, workspace_id))
    )
    if not filters.include_closed:
        stmt = stmt.where(Lead.status == LeadStatus.OPEN)
    if filters.q:
        pattern = _like(filters.q)
        stmt = stmt.where(
            or_(
                Lead.title.ilike(pattern),
                Company.name.ilike(pattern),
                func.array_to_string(Lead.technologies, " ").ilike(pattern),
            )
        )
    if filters.service_types:
        stmt = stmt.where(Lead.service_type.in_(filters.service_types))
    if filters.technologies:
        values = _text_array(filters.technologies)
        stmt = stmt.where(
            Lead.technologies.contains(values)
            if filters.technology_match == "all"
            else Lead.technologies.overlap(values)
        )
    if filters.intents:
        stmt = stmt.where(Lead.hiring_intent.in_(filters.intents))
    if filters.regions:
        # Worldwide-remote roles are open to every region.
        stmt = stmt.where(Lead.regions.overlap(_text_array(sorted({*filters.regions, "worldwide"}))))
    if filters.freshness_days:
        cutoff = utcnow() - timedelta(days=filters.freshness_days)
        stmt = stmt.where(func.coalesce(Lead.posted_at, Lead.first_seen_at) >= cutoff)
    if filters.min_score is not None:
        stmt = stmt.where(Lead.score >= filters.min_score)
    if filters.company_id:
        stmt = stmt.where(Lead.company_id == filters.company_id)
    if filters.saved_only:
        stmt = stmt.where(saved)
    return stmt


def list_leads(
    db: Session,
    workspace_id: uuid.UUID,
    filters: LeadFilters,
    *,
    sort: str,
    order: SortOrder,
    page: int,
    page_size: int,
) -> tuple[list, int]:
    stmt = _ordered(lead_query(workspace_id, filters), LEAD_SORTS[sort], order, Lead.id)
    return _paginate(db, stmt, page, page_size)


def get_lead(db: Session, workspace_id: uuid.UUID, lead_id: uuid.UUID):
    """Returns (Lead, Company, is_saved) or None. Closed leads stay reachable by id."""
    stmt = lead_query(workspace_id, LeadFilters(include_closed=True)).where(Lead.id == lead_id)
    return db.execute(stmt).first()


def list_saved_leads(db: Session, workspace_id: uuid.UUID, *, page: int, page_size: int) -> tuple[list, int]:
    stmt = (
        select(SavedLead, Lead, Company)
        .join(Lead, Lead.id == SavedLead.lead_id)
        .join(Company, Company.id == Lead.company_id)
        .where(
            SavedLead.workspace_id == workspace_id,
            # Re-check visibility: a lead may have been re-scoped since it was saved.
            visible_to(Lead, workspace_id),
            visible_to(Company, workspace_id),
        )
        .order_by(SavedLead.created_at.desc(), SavedLead.id.desc())
    )
    return _paginate(db, stmt, page, page_size)


def signals_for(
    db: Session, workspace_id: uuid.UUID, *, company_id: uuid.UUID, lead_id: uuid.UUID | None = None, limit: int = 20
) -> list[HiringSignal]:
    """Company timeline, or a lead timeline (that lead's signals plus company-wide ones)."""
    stmt = (
        select(HiringSignal)
        .outerjoin(Lead, Lead.id == HiringSignal.lead_id)
        .where(
            HiringSignal.company_id == company_id,
            visible_to(HiringSignal, workspace_id),
            or_(HiringSignal.lead_id.is_(None), visible_to(Lead, workspace_id)),
        )
        .order_by(HiringSignal.occurred_at.desc(), HiringSignal.id)
        .limit(limit)
    )
    if lead_id:
        stmt = stmt.where(or_(HiringSignal.lead_id.is_(None), HiringSignal.lead_id == lead_id))
    return list(db.scalars(stmt))


# --- companies -------------------------------------------------------------------


@dataclass
class CompanyFilters:
    q: str | None = None
    industry: str | None = None
    technologies: list[str] = field(default_factory=list)
    intents: list[HiringIntent] = field(default_factory=list)


def tracked_leads_expr(workspace_id: uuid.UUID):
    return (
        select(func.count(Lead.id))
        .where(Lead.company_id == Company.id, Lead.status == LeadStatus.OPEN, visible_to(Lead, workspace_id))
        .correlate(Company)
        .scalar_subquery()
    )


def list_companies(
    db: Session,
    workspace_id: uuid.UUID,
    filters: CompanyFilters,
    *,
    sort: str,
    order: SortOrder,
    page: int,
    page_size: int,
) -> tuple[list, int]:
    stmt = select(Company, tracked_leads_expr(workspace_id).label("tracked_leads")).where(
        visible_to(Company, workspace_id)
    )
    if filters.q:
        pattern = _like(filters.q)
        stmt = stmt.where(
            or_(
                Company.name.ilike(pattern),
                Company.industry.ilike(pattern),
                func.array_to_string(Company.technologies, " ").ilike(pattern),
            )
        )
    if filters.industry:
        stmt = stmt.where(Company.industry.ilike(_like(filters.industry)))
    if filters.technologies:
        stmt = stmt.where(Company.technologies.overlap(_text_array(filters.technologies)))
    if filters.intents:
        stmt = stmt.where(Company.intent_level.in_(filters.intents))
    stmt = _ordered(stmt, COMPANY_SORTS[sort], order, Company.id)
    return _paginate(db, stmt, page, page_size)


def get_company(db: Session, workspace_id: uuid.UUID, id_or_slug: str):
    """Looks up by UUID, or by slug (the workspace's private company wins over a shared one)."""
    stmt = select(Company, tracked_leads_expr(workspace_id).label("tracked_leads")).where(
        visible_to(Company, workspace_id)
    )
    try:
        stmt = stmt.where(Company.id == uuid.UUID(id_or_slug))
    except ValueError:
        stmt = stmt.where(Company.slug == id_or_slug).order_by(Company.workspace_id.is_(None)).limit(1)
    return db.execute(stmt).first()
