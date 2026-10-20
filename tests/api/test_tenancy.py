"""Cross-workspace isolation: knowing a record's id must never grant access to it."""

import pytest
from sqlalchemy import select

from app.models import HiringSignal, SavedLead
from app.utils.time import utcnow


@pytest.fixture
def two_workspaces(signed_in, make_company, make_lead):
    client_a, _, workspace_a = signed_in("a@example.com")
    client_b, _, workspace_b = signed_in("b@example.com")
    shared_company = make_company(name="Shared Co", slug="shared-co")
    shared_lead = make_lead(shared_company, title="Shared Role")
    private_company = make_company(workspace_id=workspace_a.id, name="Private A Co", slug="private-a")
    private_lead = make_lead(private_company, title="Private A Role")
    # A private import attached to a shared company must stay private too.
    private_on_shared = make_lead(shared_company, workspace_id=workspace_a.id, title="A Import On Shared")
    return {
        "a": client_a,
        "b": client_b,
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "shared_company": shared_company,
        "shared_lead": shared_lead,
        "private_company": private_company,
        "private_lead": private_lead,
        "private_on_shared": private_on_shared,
    }


def _titles(response):
    return {item["jobTitle"] for item in response.json()["items"]}


def test_lead_lists_are_scoped(two_workspaces):
    a, b = two_workspaces["a"], two_workspaces["b"]
    assert _titles(a.get("/api/v1/leads")) == {"Shared Role", "Private A Role", "A Import On Shared"}
    assert _titles(b.get("/api/v1/leads")) == {"Shared Role"}
    # Text search must not reach around the scope either.
    assert _titles(b.get("/api/v1/leads", params={"q": "Private"})) == set()


def test_lead_detail_is_scoped(two_workspaces):
    b = two_workspaces["b"]
    for key in ("private_lead", "private_on_shared"):
        response = b.get(f"/api/v1/leads/{two_workspaces[key].id}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert b.get(f"/api/v1/leads/{two_workspaces['shared_lead'].id}").status_code == 200


def test_cannot_save_or_unsave_foreign_lead(two_workspaces, db):
    b = two_workspaces["b"]
    lead_id = two_workspaces["private_lead"].id
    assert b.put(f"/api/v1/leads/{lead_id}/save").status_code == 404
    assert b.delete(f"/api/v1/leads/{lead_id}/save").status_code == 404
    assert db.scalar(select(SavedLead).where(SavedLead.lead_id == lead_id)) is None


def test_saved_leads_are_per_workspace(two_workspaces):
    a, b = two_workspaces["a"], two_workspaces["b"]
    shared_id = two_workspaces["shared_lead"].id
    assert a.put(f"/api/v1/leads/{shared_id}/save").status_code == 200

    assert [item["lead"]["id"] for item in a.get("/api/v1/saved-leads").json()["items"]] == [str(shared_id)]
    assert b.get("/api/v1/saved-leads").json()["total"] == 0
    assert b.get(f"/api/v1/leads/{shared_id}").json()["isSaved"] is False
    assert b.get("/api/v1/leads", params={"saved": True}).json()["total"] == 0
    # B unsaving does not touch A's bookmark.
    assert b.delete(f"/api/v1/leads/{shared_id}/save").status_code == 204
    assert a.get(f"/api/v1/leads/{shared_id}").json()["isSaved"] is True


def test_company_endpoints_are_scoped(two_workspaces):
    a, b = two_workspaces["a"], two_workspaces["b"]
    private = two_workspaces["private_company"]
    assert {item["name"] for item in b.get("/api/v1/companies").json()["items"]} == {"Shared Co"}
    assert b.get(f"/api/v1/companies/{private.id}").status_code == 404
    assert b.get("/api/v1/companies/private-a").status_code == 404
    assert a.get("/api/v1/companies/private-a").status_code == 200

    # Shared company detail only shows each workspace its own view of the leads.
    shared_slug = two_workspaces["shared_company"].slug
    detail_a = a.get(f"/api/v1/companies/{shared_slug}").json()
    detail_b = b.get(f"/api/v1/companies/{shared_slug}").json()
    assert {lead["jobTitle"] for lead in detail_a["leads"]} == {"Shared Role", "A Import On Shared"}
    assert {lead["jobTitle"] for lead in detail_b["leads"]} == {"Shared Role"}
    assert detail_a["trackedLeads"] == 2 and detail_b["trackedLeads"] == 1


def test_company_lead_filter_cannot_reach_foreign_company(two_workspaces):
    b = two_workspaces["b"]
    response = b.get("/api/v1/leads", params={"companyId": str(two_workspaces["private_company"].id)})
    assert response.json()["total"] == 0


def test_hiring_signals_are_scoped(two_workspaces, db):
    shared = two_workspaces["shared_company"]
    db.add_all(
        [
            HiringSignal(company_id=shared.id, signal_type="new_role", description="public", occurred_at=utcnow()),
            HiringSignal(
                company_id=shared.id,
                workspace_id=two_workspaces["workspace_a"].id,
                signal_type="new_role",
                description="private to A",
                occurred_at=utcnow(),
            ),
            HiringSignal(
                company_id=shared.id,
                lead_id=two_workspaces["private_on_shared"].id,
                signal_type="role_verified",
                description="about A's private lead",
                occurred_at=utcnow(),
            ),
        ]
    )
    db.commit()
    a, b = two_workspaces["a"], two_workspaces["b"]
    signals_b = {s["description"] for s in b.get(f"/api/v1/companies/{shared.id}").json()["signals"]}
    signals_a = {s["description"] for s in a.get(f"/api/v1/companies/{shared.id}").json()["signals"]}
    assert signals_b == {"public"}
    assert signals_a == {"public", "private to A", "about A's private lead"}
    timeline_b = b.get(f"/api/v1/leads/{two_workspaces['shared_lead'].id}").json()["timeline"]
    assert {s["description"] for s in timeline_b} == {"public"}
