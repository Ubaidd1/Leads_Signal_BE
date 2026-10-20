from tests.conftest import PASSWORD, login


def test_update_profile(signed_in):
    client, _, _ = signed_in("user@example.com")
    response = client.patch(
        "/api/v1/me", json={"fullName": "New Name", "jobTitle": "Partner", "timezone": "Asia/Karachi"}
    )
    assert response.status_code == 200
    assert response.json()["fullName"] == "New Name"
    assert response.json()["timezone"] == "Asia/Karachi"
    assert client.get("/api/v1/me").json()["jobTitle"] == "Partner"


def test_profile_rejects_invalid_timezone_and_unknown_fields(signed_in):
    client, _, _ = signed_in("user@example.com")
    assert client.patch("/api/v1/me", json={"timezone": "Mars/Base"}).status_code == 422
    assert client.patch("/api/v1/me", json={"isActive": False}).status_code == 422


def test_email_change_requires_current_password(signed_in, make_user, make_client):
    client, _, _ = signed_in("user@example.com")
    make_user("other@example.com")
    response = client.patch("/api/v1/me", json={"email": "new@example.com"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    response = client.patch("/api/v1/me", json={"email": "other@example.com", "currentPassword": PASSWORD})
    assert response.status_code == 409

    response = client.patch("/api/v1/me", json={"email": "New@Example.com", "currentPassword": PASSWORD})
    assert response.status_code == 200
    assert response.json()["email"] == "new@example.com"
    login(make_client(), "new@example.com")


def test_onboarding_round_trip(signed_in):
    client, _, _ = signed_in("user@example.com")
    assert client.get("/api/v1/me/onboarding").json() == {"preferences": None, "completedAt": None}
    preferences = {"services": ["AI / ML"], "technologies": ["Python", "RAG"], "region": "europe", "freshnessDays": 14}
    response = client.put("/api/v1/me/onboarding", json=preferences)
    assert response.status_code == 200
    body = client.get("/api/v1/me/onboarding").json()
    assert body["preferences"] == preferences
    assert body["completedAt"]


def test_onboarding_validates_allowlists(signed_in):
    client, _, _ = signed_in("user@example.com")
    assert client.put("/api/v1/me/onboarding", json={"region": "mars"}).status_code == 422
    assert client.put("/api/v1/me/onboarding", json={"freshnessDays": 5}).status_code == 422
