import os
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings

# --- point the app at the dedicated test database BEFORE importing anything that builds an engine ---
_base = Settings()
_test_url = os.environ.get("TEST_DATABASE_URL") or _base.test_database_url
if not _test_url:
    raise RuntimeError("TEST_DATABASE_URL is not set; refusing to run tests.")
if not make_url(_test_url).database.endswith("_test") or _test_url == _base.database_url:
    raise RuntimeError("TEST_DATABASE_URL must point to a separate database whose name ends in '_test'.")
os.environ["DATABASE_URL"] = _test_url
os.environ["ENVIRONMENT"] = "test"
os.environ["TRUSTED_ORIGINS"] = "http://localhost:3000"
get_settings.cache_clear()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import get_db, make_engine  # noqa: E402
from app.integrations.email import ConsoleEmailBackend, EmailMessage  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Company, Lead, User, Workspace, WorkspaceMembership  # noqa: E402
from app.models.enums import HiringIntent, Role, VerificationStatus  # noqa: E402
from app.utils.time import utcnow  # noqa: E402

PASSWORD = "correct horse battery"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def engine():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", _test_url.replace("%", "%%"))
    # Rebuild from scratch: this also verifies that migrations apply cleanly.
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    engine = make_engine(_test_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    """Each test runs in an outer transaction that is rolled back; service commits become savepoints."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False, autoflush=False
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def make_client(db) -> Callable[[], TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    clients = []

    def factory() -> TestClient:
        client = TestClient(app)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def outbox(monkeypatch) -> list[EmailMessage]:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(ConsoleEmailBackend, "send", lambda self, message: sent.append(message))
    return sent


# --- factories ---------------------------------------------------------------------


@pytest.fixture
def make_user(db):
    def factory(email: str, *, workspace: Workspace | None = None, role: Role = Role.OWNER, name: str = "Test User"):
        user = User(email=email, password_hash=hash_password(PASSWORD), full_name=name, password_changed_at=utcnow())
        db.add(user)
        if workspace is None:
            workspace = Workspace(name=f"{name} Workspace")
            db.add(workspace)
        db.flush()
        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=role))
        db.commit()
        return user, workspace

    return factory


@pytest.fixture
def make_company(db):
    counter = iter(range(10_000))

    def factory(*, workspace_id=None, name=None, **fields) -> Company:
        n = next(counter)
        company = Company(
            workspace_id=workspace_id,
            slug=fields.pop("slug", f"company-{n}"),
            name=name or f"Company {n}",
            technologies=fields.pop("technologies", []),
            departments=fields.pop("departments", []),
            **fields,
        )
        db.add(company)
        db.commit()
        return company

    return factory


@pytest.fixture
def make_lead(db):
    def factory(company: Company, *, workspace_id="inherit", **fields) -> Lead:
        lead = Lead(
            company_id=company.id,
            workspace_id=company.workspace_id if workspace_id == "inherit" else workspace_id,
            title=fields.pop("title", "Engineer"),
            technologies=fields.pop("technologies", []),
            regions=fields.pop("regions", []),
            hiring_intent=fields.pop("hiring_intent", HiringIntent.MEDIUM),
            verification_status=fields.pop("verification_status", VerificationStatus.VERIFIED),
            score=fields.pop("score", 80),
            posted_at=fields.pop("posted_at", utcnow()),
            **fields,
        )
        db.add(lead)
        db.commit()
        return lead

    return factory


def login(client: TestClient, email: str, password: str = PASSWORD, **extra) -> dict:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers["X-CSRF-Token"] = body["csrfToken"]
    return body


@pytest.fixture
def signed_in(make_client, make_user):
    """Returns a factory: (email, **user kwargs) -> (client, user, workspace) with an authenticated client."""

    def factory(email: str, **kwargs):
        user, workspace = make_user(email, **kwargs)
        client = make_client()
        login(client, email)
        return client, user, workspace

    return factory
