from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import LeadScore, LeadSource, Workspace, WorkspaceMembership
from app.models.enums import HiringIntent, LeadStatus
from app.utils.time import utcnow


@pytest.fixture
def catalog(signed_in, make_company, make_lead):
    client, _, workspace = signed_in("user@example.com")
    nova = make_company(name="NovaStack Labs", slug="novastack", relevant_roles_count=3, open_roles_count=8)
    cloud = make_company(name="CloudNova Systems", slug="cloudnova")
    now = utcnow()
    leads = {
        "fullstack": make_lead(
            nova,
            title="Senior Full Stack Engineer",
            service_type="Software Development",
            technologies=["React", "Node.js", "AWS"],
            regions=["international-remote", "pakistan-allowed"],
            hiring_intent=HiringIntent.STRONG,
            score=91,
            posted_at=now - timedelta(days=2),
        ),
        "ai": make_lead(
            cloud,
            title="Lead AI Engineer",
            service_type="AI / ML",
            technologies=["Python", "LLM", "RAG"],
            regions=["worldwide"],
            hiring_intent=HiringIntent.STRONG,
            score=94,
            posted_at=now - timedelta(days=1),
        ),
        "frontend": make_lead(
            nova,
            title="Frontend Engineer",
            service_type="Software Development",
            technologies=["React"],
            regions=["united-states", "canada"],
            hiring_intent=HiringIntent.MEDIUM,
            score=78,
            posted_at=now - timedelta(days=20),
        ),
        "closed": make_lead(cloud, title="Closed Role", score=99, status=LeadStatus.CLOSED),
    }
    return client, leads, {"nova": nova, "cloud": cloud}


def titles(response):
    assert response.status_code == 200, response.text
    return [item["jobTitle"] for item in response.json()["items"]]


def test_default_listing_sorts_by_score_and_hides_closed(catalog):
    client, _, _ = catalog
    response = client.get("/api/v1/leads")
    assert titles(response) == ["Lead AI Engineer", "Senior Full Stack Engineer", "Frontend Engineer"]
    body = response.json()
    assert body["total"] == 3 and body["page"] == 1 and body["pageSize"] == 25 and body["totalPages"] == 1


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": "full stack"}, ["Senior Full Stack Engineer"]),
        ({"q": "cloudnova"}, ["Lead AI Engineer"]),  # company name
        ({"q": "rag"}, ["Lead AI Engineer"]),  # technology, case-insensitive
        ({"q": "100%"}, []),  # LIKE wildcards are escaped
        ({"serviceType": "Software Development"}, ["Senior Full Stack Engineer", "Frontend Engineer"]),
        ({"technology": "React"}, ["Senior Full Stack Engineer", "Frontend Engineer"]),
        ({"technology": ["React", "Python"]}, ["Lead AI Engineer", "Senior Full Stack Engineer", "Frontend Engineer"]),
        ({"technology": ["React", "AWS"], "technologyMatch": "all"}, ["Senior Full Stack Engineer"]),
        ({"intent": "medium"}, ["Frontend Engineer"]),
        ({"intent": ["strong", "medium"], "minScore": 90}, ["Lead AI Engineer", "Senior Full Stack Engineer"]),
        # Worldwide roles match every region filter.
        ({"region": "united-states"}, ["Lead AI Engineer", "Frontend Engineer"]),
        ({"region": "pakistan-allowed"}, ["Lead AI Engineer", "Senior Full Stack Engineer"]),
        ({"freshnessDays": 7}, ["Lead AI Engineer", "Senior Full Stack Engineer"]),
        ({"minScore": 92}, ["Lead AI Engineer"]),
    ],
)
def test_filters(catalog, params, expected):
    client, _, _ = catalog
    assert titles(client.get("/api/v1/leads", params=params)) == expected


def test_company_filter(catalog):
    client, _, companies = catalog
    response = client.get("/api/v1/leads", params={"companyId": str(companies["nova"].id)})
    assert titles(response) == ["Senior Full Stack Engineer", "Frontend Engineer"]


def test_sorting(catalog):
    client, _, _ = catalog
    assert titles(client.get("/api/v1/leads", params={"sort": "postedAt", "order": "asc"})) == [
        "Frontend Engineer",
        "Senior Full Stack Engineer",
        "Lead AI Engineer",
    ]
    assert titles(client.get("/api/v1/leads", params={"sort": "companyName", "order": "asc"}))[0] == "Lead AI Engineer"


def test_pagination_is_deterministic_with_ties(signed_in, make_company, make_lead):
    client, _, _ = signed_in("user@example.com")
    company = make_company()
    created = {str(make_lead(company, title=f"Role {i}", score=80).id) for i in range(7)}
    seen = []
    for page in (1, 2, 3):
        body = client.get("/api/v1/leads", params={"pageSize": 3, "page": page}).json()
        assert body["total"] == 7 and body["totalPages"] == 3
        seen += [item["id"] for item in body["items"]]
    assert len(seen) == 7 and set(seen) == created


@pytest.mark.parametrize(
    "params",
    [
        {"pageSize": 101},
        {"pageSize": 0},
        {"page": 0},
        {"sort": "password_hash"},
        {"order": "sideways"},
        {"intent": "extreme"},
        {"region": "mars"},
        {"minScore": 101},
        {"companyId": "not-a-uuid"},
    ],
)
def test_invalid_query_parameters_are_rejected(catalog, params):
    client, _, _ = catalog
    response = client.get("/api/v1/leads", params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_save_and_unsave_are_idempotent(catalog, db):
    client, leads, _ = catalog
    lead_id = leads["ai"].id
    first = client.put(f"/api/v1/leads/{lead_id}/save")
    second = client.put(f"/api/v1/leads/{lead_id}/save")
    assert first.status_code == second.status_code == 200
    assert first.json()["savedAt"] == second.json()["savedAt"]
    assert client.get("/api/v1/saved-leads").json()["total"] == 1

    listing = {item["id"]: item["isSaved"] for item in client.get("/api/v1/leads").json()["items"]}
    assert listing[str(lead_id)] is True and listing[str(leads["fullstack"].id)] is False
    assert client.get(f"/api/v1/leads/{lead_id}").json()["isSaved"] is True
    assert titles(client.get("/api/v1/leads", params={"saved": True})) == ["Lead AI Engineer"]

    assert client.delete(f"/api/v1/leads/{lead_id}/save").status_code == 204
    assert client.delete(f"/api/v1/leads/{lead_id}/save").status_code == 204
    assert client.get("/api/v1/saved-leads").json()["total"] == 0


def test_saved_leads_are_shared_across_workspace_members(catalog, signed_in, db):
    client, leads, _ = catalog
    workspace = db.scalar(select(Workspace).join(WorkspaceMembership).limit(1))
    teammate, _, _ = signed_in("teammate@example.com", workspace=workspace)
    client.put(f"/api/v1/leads/{leads['ai'].id}/save")
    assert teammate.get("/api/v1/saved-leads").json()["total"] == 1


def test_unknown_lead_is_404(catalog):
    client, _, _ = catalog
    response = client.get("/api/v1/leads/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "RESOURCE_NOT_FOUND", "message": "The requested resource was not found."}
    }
    assert client.put("/api/v1/leads/00000000-0000-0000-0000-000000000000/save").status_code == 404


def test_lead_detail_includes_provenance_score_and_company(catalog, db):
    client, leads, _ = catalog
    lead = leads["fullstack"]
    db.add(
        LeadSource(
            lead_id=lead.id,
            source_type="company_careers",
            source_name="NovaStack careers page",
            source_url="https://novastack.example/careers/1",
            source_record_id="nova-1",
        )
    )
    db.add(LeadScore(lead_id=lead.id, version="v1", total=91, components={"relevance": 24}, rationale="Because."))
    db.commit()
    body = client.get(f"/api/v1/leads/{lead.id}").json()
    assert body["company"]["name"] == "NovaStack Labs"
    assert body["relevantOpenRoles"] == 3 and body["openRolesTotal"] == 8
    assert body["companyLogo"] == "NL"
    assert body["sources"][0]["sourceName"] == "NovaStack careers page"
    assert body["score"]["components"] == {"relevance": 24}
    assert body["score"]["max"]["relevance"] == 25
    assert body["timeline"] == []


def test_lead_detail_without_score_returns_null(catalog):
    client, leads, _ = catalog
    assert client.get(f"/api/v1/leads/{leads['ai'].id}").json()["score"] is None


def test_closed_lead_is_reachable_by_id(catalog):
    client, leads, _ = catalog
    assert client.get(f"/api/v1/leads/{leads['closed'].id}").status_code == 200


def test_company_list_and_detail(catalog):
    client, _, companies = catalog
    body = client.get("/api/v1/companies", params={"sort": "name", "order": "asc"}).json()
    assert [item["name"] for item in body["items"]] == ["CloudNova Systems", "NovaStack Labs"]
    assert {item["name"]: item["trackedLeads"] for item in body["items"]} == {
        "CloudNova Systems": 1,  # the closed lead is not counted
        "NovaStack Labs": 2,
    }
    searched = client.get("/api/v1/companies", params={"q": "stack", "sort": "name", "order": "asc"}).json()
    assert [item["name"] for item in searched["items"]] == ["NovaStack Labs"]

    by_slug = client.get("/api/v1/companies/novastack").json()
    by_id = client.get(f"/api/v1/companies/{companies['nova'].id}").json()
    assert by_slug == by_id
    assert [lead["jobTitle"] for lead in by_slug["leads"]] == ["Senior Full Stack Engineer", "Frontend Engineer"]
    assert client.get("/api/v1/companies/does-not-exist").status_code == 404
    assert client.get("/api/v1/companies", params={"sort": "secret"}).status_code == 422


def test_timestamps_are_utc(catalog):
    client, leads, _ = catalog
    saved_at = client.put(f"/api/v1/leads/{leads['ai'].id}/save").json()["savedAt"]
    assert saved_at.endswith(("+00:00", "Z"))
