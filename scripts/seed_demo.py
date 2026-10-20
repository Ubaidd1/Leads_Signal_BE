"""Idempotent development seed: a demo workspace + user holding the prototype fixtures.

    python -m scripts.seed_demo

All rows are flagged ``is_demo`` and scoped to the demo workspace, so they are never visible to
real workspaces. Refuses to run when ENVIRONMENT=production.

Saved searches and alerts are seeded once their tables exist (Phase 2).
"""

import os
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Company, HiringSignal, Lead, LeadScore, LeadSource, User, Workspace, WorkspaceMembership
from app.models.enums import HiringIntent, Role, VerificationStatus
from app.utils.time import utcnow
from scripts.demo_fixtures import COMPANIES, LEADS, TIMELINE, fixture_breakdown

DEMO_EMAIL = "demo@hiringintel.ai"
DEMO_WORKSPACE = "ZoneX Agency (Demo)"
FIXTURE_SOURCE = "demo_fixture"
FIXTURE_SCORE_VERSION = "demo-fixture"


def seed_user_and_workspace(db: Session) -> tuple[Workspace, str | None]:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    generated_password = None
    if user is None:
        password = os.environ.get("DEMO_USER_PASSWORD")
        if not password:
            password = generated_password = secrets.token_urlsafe(12)
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(password),
            full_name="ZoneX Dev",
            job_title="Agency Partner",
            password_changed_at=utcnow(),
        )
        db.add(user)
        db.flush()

    workspace = db.scalar(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(Workspace.is_demo.is_(True), WorkspaceMembership.user_id == user.id)
    )
    if workspace is None:
        workspace = Workspace(name=DEMO_WORKSPACE, is_demo=True)
        db.add(workspace)
        db.flush()
        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
    return workspace, generated_password


def seed_companies(db: Session, workspace: Workspace) -> dict[str, Company]:
    by_slug = {}
    for data in COMPANIES:
        data = dict(data)
        activity = data.pop("activity")
        company = db.scalar(select(Company).where(Company.workspace_id == workspace.id, Company.slug == data["slug"]))
        if company is None:
            company = Company(workspace_id=workspace.id, slug=data["slug"], is_demo=True)
            db.add(company)
        for field, value in data.items():
            setattr(company, field, HiringIntent(value) if field == "intent_level" else value)
        company.careers_url = f"https://{data['slug']}.example/careers"
        company.activity_series = [{"period": f"P{i + 1}", "value": value} for i, value in enumerate(activity)]
        by_slug[company.slug] = company
    db.flush()
    return by_slug


def seed_leads(db: Session, workspace: Workspace, companies: dict[str, Company]) -> int:
    now = utcnow()
    created = 0
    for index, row in enumerate(LEADS):
        fixture_id, slug, title, service, score, intent, techs, remote, regions, salary, posted_ago, verified_ago = row
        company = companies[slug]
        source = db.scalar(
            select(LeadSource).where(
                LeadSource.source_type == FIXTURE_SOURCE, LeadSource.source_record_id == fixture_id
            )
        )
        if source is not None:
            continue  # Already seeded; leave timestamps and history untouched.

        lead = Lead(
            workspace_id=workspace.id,
            company_id=company.id,
            title=title,
            service_type=service,
            seniority="Lead / Principal" if index % 3 == 0 else "Senior",
            technologies=techs,
            remote_policy=remote,
            regions=regions,
            salary_min=salary[0],
            salary_max=salary[1],
            salary_currency=salary[2],
            hiring_intent=HiringIntent(intent),
            verification_status=VerificationStatus.HIGH_CONFIDENCE if score >= 88 else VerificationStatus.VERIFIED,
            canonical_url=f"https://{slug}.example/jobs/{fixture_id}",
            posted_at=now - posted_ago,
            first_seen_at=now - posted_ago,
            last_seen_at=now - verified_ago,
            last_verified_at=now - verified_ago,
            score=score,
            score_version=FIXTURE_SCORE_VERSION,
            is_demo=True,
        )
        db.add(lead)
        db.flush()
        db.add(
            LeadSource(
                lead_id=lead.id,
                source_type=FIXTURE_SOURCE,
                source_name="Demo fixture (prototype src/data/leads.js)",
                source_url=None,
                source_record_id=fixture_id,
                first_seen_at=now - posted_ago,
                last_seen_at=now - verified_ago,
                verified_at=None,
            )
        )
        db.add(
            LeadScore(
                lead_id=lead.id,
                version=FIXTURE_SCORE_VERSION,
                total=score,
                components=fixture_breakdown(score),
                rationale=(
                    f"{company.name} is showing {intent} hiring intent with {company.relevant_roles_count} relevant "
                    f"roles, recent verified activity, and strong alignment with {techs[0]} and {techs[1]}. "
                    "(Illustrative demo score; not produced by the scoring engine.)"
                ),
                calculated_at=now,
            )
        )
        for ago, signal_type, description in TIMELINE:
            db.add(
                HiringSignal(
                    workspace_id=workspace.id,
                    company_id=company.id,
                    lead_id=lead.id,
                    signal_type=signal_type,
                    description=description.format(title=title),
                    occurred_at=now - ago,
                    is_demo=True,
                )
            )
        created += 1
    return created


def main() -> int:
    settings = get_settings()
    if settings.environment == "production":
        print("Refusing to seed demo data in production.", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        workspace, generated_password = seed_user_and_workspace(db)
        companies = seed_companies(db, workspace)
        created = seed_leads(db, workspace, companies)
        db.commit()
    print(f"Demo workspace ready: {len(companies)} companies, {created} new leads ({len(LEADS)} total).")
    print(f"Sign in as {DEMO_EMAIL}")
    if generated_password:
        print(f"Generated password (shown once): {generated_password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
