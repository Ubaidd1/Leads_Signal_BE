import pytest

from app.core.exceptions import RateLimited
from app.core.permissions import Permission, has_permission
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.models.enums import Role
from app.services import rate_limit


def test_password_hashing():
    hashed = hash_password("s3cret password")
    assert hashed.startswith("$argon2id$")
    assert hashed != hash_password("s3cret password")  # salted
    assert verify_password(hashed, "s3cret password")
    assert not verify_password(hashed, "wrong")
    assert not verify_password(None, "anything")
    assert not verify_password("not-a-hash", "anything")


def test_tokens_are_unique_and_hashed():
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100
    token = tokens.pop()
    assert len(token) >= 43 and hash_token(token) != token and len(hash_token(token)) == 64


def test_role_permissions():
    assert has_permission(Role.MEMBER, Permission.SAVED_LEADS_WRITE)
    assert not has_permission(Role.MEMBER, Permission.WORKSPACE_UPDATE)
    assert not has_permission(Role.MEMBER, Permission.MEMBERS_MANAGE)
    assert has_permission(Role.ADMIN, Permission.MEMBERS_MANAGE)
    assert has_permission(Role.OWNER, Permission.INTEGRATIONS_MANAGE)


def test_rate_limit_window(db):
    for _ in range(3):
        rate_limit.hit(db, "unit:key", limit=3, window_seconds=60)
    with pytest.raises(RateLimited) as excinfo:
        rate_limit.hit(db, "unit:key", limit=3, window_seconds=60)
    assert 0 < excinfo.value.retry_after <= 61
    rate_limit.hit(db, "unit:other", limit=3, window_seconds=60)  # keys are independent
