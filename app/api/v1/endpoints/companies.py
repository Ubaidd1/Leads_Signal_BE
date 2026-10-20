from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import DB, Ctx, Paging
from app.models.enums import HiringIntent
from app.repositories.catalog import COMPANY_SORTS, CompanyFilters, SortOrder
from app.schemas.common import Page
from app.schemas.companies import CompanyDetail, CompanySummary
from app.services import catalog as catalog_service

router = APIRouter(prefix="/companies", tags=["companies"])

CompanySort = Literal[tuple(COMPANY_SORTS)]


@router.get("", response_model=Page[CompanySummary])
def list_companies(
    db: DB,
    ctx: Ctx,
    paging: Annotated[Paging, Depends()],
    q: Annotated[str | None, Query(max_length=200)] = None,
    industry: Annotated[str | None, Query(max_length=200)] = None,
    technology: Annotated[list[Annotated[str, Query(max_length=100)]], Query()] = [],  # noqa: B006
    intent: Annotated[list[HiringIntent], Query()] = [],  # noqa: B006
    sort: CompanySort = "intentScore",
    order: SortOrder = "desc",
):
    filters = CompanyFilters(q=q or None, industry=industry or None, technologies=technology, intents=intent)
    return catalog_service.list_companies(
        db, ctx, filters, sort=sort, order=order, page=paging.page, page_size=paging.page_size
    )


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: Annotated[str, Path(max_length=120, description="Company UUID or slug")], db: DB, ctx: Ctx):
    return catalog_service.get_company_detail(db, ctx, company_id)
