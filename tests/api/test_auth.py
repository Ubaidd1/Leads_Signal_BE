from datetime import timedelta

from sqlalchemy import select

from app.models import AuthSession, User
from app.utils.time import utcnow
from tests.conftest import PASSWORD, login

REGISTER = {
    "email": "Owner@Example.com",
    "password": PASSWORD,
    "fullName": "Olive Owner",
    "workspaceName": "Acme Agency",
}


def test_register_creates_owner_workspace_and_session(client, db):
    response = client.post("/api/v1/auth/register", json=REGISTER)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["email"] == "owner@example.com"
    assert body["workspace"] == {"id": body["workspace"]["id"], "name": "Acme Agency", "role": "owner", "isDemo": False}
    assert "workspace:update" in body["permissions"]
    assert "passwordHash" not in body["user"] and "password_hash" not in response.text

    cookie = response.headers["set-cookie"]
    assert "hi_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    # Not "remember me": a browser-session cookie.
    assert "Max-Age" not in cookie

    stored = db.scalar(select(User).where(User.email == "owner@example.com"))
    assert stored.password_hash.startswith("$argon2")
    token = client.cookies.get("hi_session")
    assert db.scalar(select(AuthSession.token_hash)) != token  # only a digest is stored

    assert client.get("/api/v1/auth/session").json()["user"]["fullName"] == "Olive Owner"


def test_register_rejects_duplicate_email_and_weak_password(client, make_user):
    make_user("taken@example.com")
    response = client.post("/api/v1/auth/register", json={**REGISTER, "email": "TAKEN@example.com"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"

    response = client.post("/api/v1/auth/register", json={**REGISTER, "email": "new@example.com", "password": "short"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_validation_errors_use_standard_format(client):
    response = client.post("/api/v1/auth/register", json={"email": "not-an-email", "unknown": 1})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    fields = {detail["field"] for detail in error["details"]}
    assert {"email", "password", "fullName", "workspaceName", "unknown"} <= fields


def test_login_success_and_generic_failures(client, make_user):
    make_user("user@example.com")
    wrong_password = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "nope"})
    unknown_user = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"

    body = login(client, "USER@example.com")
    assert body["workspace"]["role"] == "owner"
    assert body["csrfToken"]


def test_remember_me_sets_persistent_cookie(client, make_user):
    make_user("user@example.com")
    response = client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": PASSWORD, "rememberMe": True}
    )
    assert "Max-Age=" in response.headers["set-cookie"]


def test_private_endpoints_require_authentication(client):
    for path in ["/api/v1/auth/session", "/api/v1/me", "/api/v1/leads", "/api/v1/companies", "/api/v1/workspace"]:
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_garbage_session_cookie_is_rejected(client):
    client.cookies.set("hi_session", "forged-token")
    assert client.get("/api/v1/me").status_code == 401


def test_logout_revokes_session(signed_in):
    client, _, _ = signed_in("user@example.com")
    cookie = client.cookies.get("hi_session")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("hi_session", cookie)  # replaying the old cookie must not work
    assert client.get("/api/v1/me").status_code == 401


def test_state_changing_requests_require_csrf_token(signed_in):
    client, _, _ = signed_in("user@example.com")
    token = client.headers.pop("X-CSRF-Token")
    response = client.patch("/api/v1/me", json={"fullName": "X"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"
    response = client.patch("/api/v1/me", json={"fullName": "X"}, headers={"X-CSRF-Token": "wrong"})
    assert response.status_code == 403
    response = client.patch("/api/v1/me", json={"fullName": "X"}, headers={"X-CSRF-Token": token})
    assert response.status_code == 200


def test_untrusted_origin_is_rejected(client, make_user):
    make_user("user@example.com")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": PASSWORD},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200


def test_expired_and_idle_sessions_are_rejected(signed_in, db):
    client, user, _ = signed_in("user@example.com")
    session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))

    session.last_seen_at = utcnow() - timedelta(days=2)  # beyond the idle timeout
    db.commit()
    assert client.get("/api/v1/me").status_code == 401

    session.last_seen_at = utcnow()
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_deactivated_user_loses_access(signed_in, db):
    client, user, _ = signed_in("user@example.com")
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/me").status_code == 401


def test_change_password_revokes_other_sessions(signed_in, make_client):
    client, _, _ = signed_in("user@example.com")
    other_device = make_client()
    login(other_device, "user@example.com")

    response = client.post(
        "/api/v1/me/password", json={"currentPassword": "wrong", "newPassword": "a brand new password"}
    )
    assert response.status_code == 422

    response = client.post(
        "/api/v1/me/password", json={"currentPassword": PASSWORD, "newPassword": "a brand new password"}
    )
    assert response.status_code == 204
    assert client.get("/api/v1/me").status_code == 200
    assert other_device.get("/api/v1/me").status_code == 401
    login(make_client(), "user@example.com", "a brand new password")


def test_password_reset_does_not_reveal_accounts(client, make_user, outbox):
    make_user("user@example.com")
    known = client.post("/api/v1/auth/password-reset/request", json={"email": "user@example.com"})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [message.to for message in outbox] == ["user@example.com"]


def _reset_token(outbox) -> str:
    return outbox[-1].body.split("token=")[1].split()[0]


def test_password_reset_flow(signed_in, make_client, outbox):
    existing_session, _, _ = signed_in("user@example.com")
    client = make_client()
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@example.com"})
    token = _reset_token(outbox)

    weak = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "newPassword": "short"})
    assert weak.status_code == 422

    response = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "newPassword": "reset password 1"}
    )
    assert response.status_code == 204
    # Single use.
    again = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "newPassword": "reset password 2"})
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "INVALID_RESET_TOKEN"
    # All existing sessions are signed out; the new password works.
    assert existing_session.get("/api/v1/me").status_code == 401
    login(client, "user@example.com", "reset password 1")


def test_password_reset_only_latest_token_is_valid(client, make_user, outbox):
    make_user("user@example.com")
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@example.com"})
    first = _reset_token(outbox)
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@example.com"})
    response = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": first, "newPassword": "reset password 1"}
    )
    assert response.status_code == 422


def test_password_reset_token_expires(client, make_user, outbox, db):
    from app.models import PasswordResetToken

    make_user("user@example.com")
    client.post("/api/v1/auth/password-reset/request", json={"email": "user@example.com"})
    db.scalar(select(PasswordResetToken)).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    response = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": _reset_token(outbox), "newPassword": "reset password 1"}
    )
    assert response.status_code == 422


def test_login_is_rate_limited(client, make_user):
    make_user("user@example.com")
    for _ in range(10):
        assert (
            client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "bad"}).status_code == 401
        )
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": PASSWORD})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) > 0


def test_password_reset_is_rate_limited(client):
    for _ in range(5):
        assert client.post("/api/v1/auth/password-reset/request", json={"email": "a@example.com"}).status_code == 202
    assert client.post("/api/v1/auth/password-reset/request", json={"email": "a@example.com"}).status_code == 429
