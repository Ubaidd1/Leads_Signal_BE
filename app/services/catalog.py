import math
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.exceptions import NotFound
from app.core.permissions import Permission
from app.models import Company, Lead, LeadScore, LeadSource, SavedLead
from app.repositories import catalog as repo
from app.schemas.common import Page
from app.schemas.companies import CompanyDetail, CompanySummary
from app.schemas.leads import (
    LeadCompany,
    LeadDetail,
    LeadSummary,
    SavedLeadOut,
    SaveState,
    ScoreOut,
    SignalOut,
    SourceOut,
)
from app.services import audit


def initials(name: str) -> str:
    words = [word for word in name.split() if word[:1].isalnum()]
    return "".join(word[0] for word in words[:2]).upper() or name[:2].upper()


def _page(items: list, total: int, page: int, page_size: int) -> Page:
    return Page(items=items, total=total, page=page, page_size=page_size, total_pages=math.ceil(total / page_size))


def lead_summary(lead: Lead, company: Company, is_saved: bool) -> LeadSummary:
    return LeadSummary(
        id=lead.id,
        company_id=company.id,
        company_slug=company.slug,
        company_name=company.name,
        company_logo=initials(company.name),
        job_title=lead.title,
        service_type=lead.service_type,
        seniority=lead.seniority,
        lead_score=lead.score,
        hiring_intent=lead.hiring_intent,
        technologies=lead.technologies,
        remote_fit=lead.remote_policy,
        regions=lead.regions,
        salary_min=lead.salary_min,
        salary_max=lead.salary_max,
        salary_currency=lead.salary_currency,
        relevant_open_roles=company.relevant_roles_count,
        open_roles_total=company.open_roles_count,
        verification_status=lead.verification_status,
        posted_at=lead.posted_at,
        last_verified_at=lead.last_verified_at,
        is_saved=is_saved,
        is_demo=lead.is_demo,
    )


def list_leads(db: Session, ctx: RequestContext, filters: repo.LeadFilters, **paging) -> Page[LeadSummary]:
    rows, total = repo.list_leads(db, ctx.workspace.id, filters, **paging)
    return _page([lead_summary(*row) for row in rows], total, paging["page"], paging["page_size"])


def get_lead_detail(db: Session, ctx: RequestContext, lead_id: uuid.UUID) -> LeadDetail:
    row = repo.get_lead(db, ctx.workspace.id, lead_id)
    if row is None:
        raise NotFound()
    lead, company, is_saved = row
    score = db.scalar(
        select(LeadScore).where(LeadScore.lead_id == lead.id).order_by(LeadScore.calculated_at.desc()).limit(1)
    )
    sources = db.scalars(select(LeadSource).where(LeadSource.lead_id == lead.id).order_by(LeadSource.first_seen_at))
    signals = repo.signals_for(db, ctx.workspace.id, company_id=company.id, lead_id=lead.id)
    return LeadDetail(
        **lead_summary(lead, company, is_saved).model_dump(),
        canonical_url=lead.canonical_url,
        careers_url=company.careers_url,
        first_seen_at=lead.first_seen_at,
        last_seen_at=lead.last_seen_at,
        company=LeadCompany(
            id=company.id,
            slug=company.slug,
            name=company.name,
            domain=company.domain,
            industry=company.industry,
            location=company.location,
            size_range=company.size_range,
            open_roles=company.open_roles_count,
            relevant_roles=company.relevant_roles_count,
            hiring_velocity_pct=company.hiring_velocity_pct,
            skill_concentration=company.skill_concentration,
            departments=company.departments,
            repeated_hiring_summary=company.repeated_hiring_summary,
        ),
        sources=[SourceOut.model_validate(source) for source in sources],
        score=ScoreOut.model_validate(score) if score else None,
        timeline=[SignalOut.model_validate(signal) for signal in signals],
    )


# --- saved leads -------------------------------------------------------------------


def _require_visible_lead(db: Session, ctx: RequestContext, lead_id: uuid.UUID) -> None:
    if repo.get_lead(db, ctx.workspace.id, lead_id) is None:
        raise NotFound()


def save_lead(db: Session, ctx: RequestContext, lead_id: uuid.UUID) -> SaveState:
    ctx.require(Permission.SAVED_LEADS_WRITE)
    _require_visible_lead(db, ctx, lead_id)
    # Idempotent: a second save is a no-op that returns the original timestamp.
    inserted = db.execute(
        insert(SavedLead)
        .values(id=uuid.uuid4(), workspace_id=ctx.workspace.id, lead_id=lead_id, saved_by_user_id=ctx.user.id)
        .on_conflict_do_nothing(index_elements=["workspace_id", "lead_id"])
        .returning(SavedLead.id)
    ).scalar_one_or_none()
    if inserted:
        audit.record(
            db,
            "lead.saved",
            actor_user_id=ctx.user.id,
            workspace_id=ctx.workspace.id,
            target_type="lead",
            target_id=lead_id,
        )
    db.commit()
    saved_at = db.scalar(
        select(SavedLead.created_at).where(SavedLead.workspace_id == ctx.workspace.id, SavedLead.lead_id == lead_id)
    )
    return SaveState(lead_id=lead_id, is_saved=True, saved_at=saved_at)


def unsave_lead(db: Session, ctx: RequestContext, lead_id: uuid.UUID) -> None:
    ctx.require(Permission.SAVED_LEADS_WRITE)
    _require_visible_lead(db, ctx, lead_id)
    result = db.execute(
        delete(SavedLead).where(SavedLead.workspace_id == ctx.workspace.id, SavedLead.lead_id == lead_id)
    )
    if result.rowcount:
        audit.record(
            db,
            "lead.unsaved",
            actor_user_id=ctx.user.id,
            workspace_id=ctx.workspace.id,
            target_type="lead",
            target_id=lead_id,
        )
    db.commit()


def list_saved_leads(db: Session, ctx: RequestContext, *, page: int, page_size: int) -> Page[SavedLeadOut]:
    rows, total = repo.list_saved_leads(db, ctx.workspace.id, page=page, page_size=page_size)
    items = [
        SavedLeadOut(
            saved_at=saved.created_at, saved_by_user_id=saved.saved_by_user_id, lead=lead_summary(lead, company, True)
        )
        for saved, lead, company in rows
    ]
    return _page(items, total, page, page_size)


# --- companies -----------------------------------------------------------------------


def company_summary(company: Company, tracked_leads: int) -> CompanySummary:
    return CompanySummary(
        id=company.id,
        slug=company.slug,
        name=company.name,
        logo=initials(company.name),
        domain=company.domain,
        industry=company.industry,
        location=company.location,
        size_range=company.size_range,
        intent_score=company.intent_score,
        intent=company.intent_level,
        open_roles=company.open_roles_count,
        relevant_roles=company.relevant_roles_count,
        hiring_velocity_pct=company.hiring_velocity_pct,
        skill_concentration=company.skill_concentration,
        technologies=company.technologies,
        departments=company.departments,
        remote_policy=company.remote_policy,
        tracked_leads=tracked_leads,
        is_demo=company.is_demo,
    )


def list_companies(db: Session, ctx: RequestContext, filters: repo.CompanyFilters, **paging) -> Page[CompanySummary]:
    rows, total = repo.list_companies(db, ctx.workspace.id, filters, **paging)
    return _page([company_summary(*row) for row in rows], total, paging["page"], paging["page_size"])


def get_company_detail(db: Session, ctx: RequestContext, id_or_slug: str) -> CompanyDetail:
    row = repo.get_company(db, ctx.workspace.id, id_or_slug)
    if row is None:
        raise NotFound()
    company, tracked = row
    lead_rows, _ = repo.list_leads(
        db,
        ctx.workspace.id,
        repo.LeadFilters(company_id=company.id),
        sort="score",
        order="desc",
        page=1,
        page_size=50,
    )
    signals = repo.signals_for(db, ctx.workspace.id, company_id=company.id)
    return CompanyDetail(
        **company_summary(company, tracked).model_dump(),
        overview=company.overview,
        careers_url=company.careers_url,
        repeated_hiring_summary=company.repeated_hiring_summary,
        activity=company.activity_series,
        leads=[lead_summary(*lead_row) for lead_row in lead_rows],
        signals=[SignalOut.model_validate(signal) for signal in signals],
        updated_at=company.updated_at,
    )
