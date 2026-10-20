import uuid
from datetime import datetime

from app.models.enums import HiringIntent, VerificationStatus
from app.schemas.common import CamelModel

SCORE_MAX = {
    "relevance": 25,
    "hiringIntent": 20,
    "freshness": 15,
    "remoteFit": 10,
    "commercialValue": 10,
    "companyActivity": 10,
    "seniority": 5,
    "dataQuality": 5,
}


class LeadSummary(CamelModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_slug: str
    company_name: str
    company_logo: str
    job_title: str
    service_type: str | None
    seniority: str | None
    lead_score: int | None
    hiring_intent: HiringIntent | None
    technologies: list[str]
    remote_fit: str | None
    regions: list[str]
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    relevant_open_roles: int | None
    open_roles_total: int | None
    verification_status: VerificationStatus
    posted_at: datetime | None
    last_verified_at: datetime | None
    is_saved: bool
    is_demo: bool


class LeadCompany(CamelModel):
    id: uuid.UUID
    slug: str
    name: str
    domain: str | None
    industry: str | None
    location: str | None
    size_range: str | None
    open_roles: int | None
    relevant_roles: int | None
    hiring_velocity_pct: int | None
    skill_concentration: str | None
    departments: list[str]
    repeated_hiring_summary: str | None


class SourceOut(CamelModel):
    source_type: str
    source_name: str
    source_url: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    verified_at: datetime | None


class ScoreOut(CamelModel):
    total: int
    version: str
    components: dict[str, int]
    max: dict[str, int] = SCORE_MAX
    rationale: str | None
    calculated_at: datetime


class SignalOut(CamelModel):
    signal_type: str
    description: str
    occurred_at: datetime
    lead_id: uuid.UUID | None


class LeadDetail(LeadSummary):
    canonical_url: str | None
    careers_url: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    company: LeadCompany
    sources: list[SourceOut]
    score: ScoreOut | None
    timeline: list[SignalOut]


class SavedLeadOut(CamelModel):
    saved_at: datetime
    saved_by_user_id: uuid.UUID | None
    lead: LeadSummary


class SaveState(CamelModel):
    lead_id: uuid.UUID
    is_saved: bool
    saved_at: datetime | None
