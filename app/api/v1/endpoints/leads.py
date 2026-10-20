import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, Ctx, Paging
from app.models.enums import HiringIntent
from app.repositories.catalog import LEAD_SORTS, LeadFilters, SortOrder
from app.schemas.common import Page
from app.schemas.constants import Region
from app.schemas.leads import LeadDetail, LeadSummary, SavedLeadOut, SaveState
from app.services import catalog as catalog_service

router = APIRouter(tags=["leads"])

LeadSort = Literal[tuple(LEAD_SORTS)]
Term = Annotated[str, Query(max_length=100)]


def lead_filters(
    q: Annotated[
        str | None, Query(max_length=200, description="Free text over job title, company and technologies")
    ] = None,
    service_type: Annotated[list[Term], Query(alias="serviceType")] = [],  # noqa: B006
    technology: Annotated[list[Term], Query()] = [],  # noqa: B006
    technology_match: Annotated[Literal["any", "all"], Query(alias="technologyMatch")] = "any",
    intent: Annotated[list[HiringIntent], Query()] = [],  # noqa: B006
    region: Annotated[list[Region], Query()] = [],  # noqa: B006
    freshness_days: Annotated[int | None, Query(alias="freshnessDays", ge=1, le=365)] = None,
    min_score: Annotated[int | None, Query(alias="minScore", ge=0, le=100)] = None,
    company_id: Annotated[uuid.UUID | None, Query(alias="companyId")] = None,
    saved: bool = False,
) -> LeadFilters:
    return LeadFilters(
        q=q or None,
        service_types=service_type,
        technologies=technology,
        technology_match=technology_match,
        intents=intent,
        regions=region,
        freshness_days=freshness_days,
        min_score=min_score,
        company_id=company_id,
        saved_only=saved,
    )


@router.get("/leads", response_model=Page[LeadSummary])
def list_leads(
    db: DB,
    ctx: Ctx,
    filters: Annotated[LeadFilters, Depends(lead_filters)],
    paging: Annotated[Paging, Depends()],
    sort: LeadSort = "score",
    order: SortOrder = "desc",
):
    return catalog_service.list_leads(
        db, ctx, filters, sort=sort, order=order, page=paging.page, page_size=paging.page_size
    )


@router.get("/leads/{lead_id}", response_model=LeadDetail)
def get_lead(lead_id: uuid.UUID, db: DB, ctx: Ctx):
    return catalog_service.get_lead_detail(db, ctx, lead_id)


@router.put("/leads/{lead_id}/save", response_model=SaveState)
def save_lead(lead_id: uuid.UUID, db: DB, ctx: Ctx):
    return catalog_service.save_lead(db, ctx, lead_id)


@router.delete("/leads/{lead_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def unsave_lead(lead_id: uuid.UUID, db: DB, ctx: Ctx):
    catalog_service.unsave_lead(db, ctx, lead_id)


@router.get("/saved-leads", response_model=Page[SavedLeadOut])
def list_saved_leads(db: DB, ctx: Ctx, paging: Annotated[Paging, Depends()]):
    return catalog_service.list_saved_leads(db, ctx, page=paging.page, page_size=paging.page_size)
