import uuid
from datetime import datetime

from app.models.enums import HiringIntent
from app.schemas.common import CamelModel
from app.schemas.leads import LeadSummary, SignalOut


class CompanySummary(CamelModel):
    id: uuid.UUID
    slug: str
    name: str
    logo: str
    domain: str | None
    industry: str | None
    location: str | None
    size_range: str | None
    intent_score: int | None
    intent: HiringIntent | None
    open_roles: int | None
    relevant_roles: int | None
    hiring_velocity_pct: int | None
    skill_concentration: str | None
    technologies: list[str]
    departments: list[str]
    remote_policy: str | None
    # Count of open leads visible to the caller's workspace (computed, not reported).
    tracked_leads: int
    is_demo: bool


class ActivityPoint(CamelModel):
    period: str
    value: int


class CompanyDetail(CompanySummary):
    overview: str | None
    careers_url: str | None
    repeated_hiring_summary: str | None
    activity: list[ActivityPoint] | None
    leads: list[LeadSummary]
    signals: list[SignalOut]
    updated_at: datetime
