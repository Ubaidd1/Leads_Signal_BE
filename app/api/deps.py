from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.exceptions import PermissionDenied
from app.core.security import tokens_match
from app.db.session import get_db
from app.models import AuthSession, Workspace
from app.services import auth as auth_service
from app.services import workspaces as workspace_service

settings = get_settings()

DB = Annotated[Session, Depends(get_db)]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: Request) -> str | None:
    # Behind a proxy, run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy> so this is the real client.
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def enforce_csrf(request: Request, session: AuthSession) -> None:
    """Synchroniser token: state-changing requests must echo the session's CSRF token in a header."""
    if request.method in SAFE_METHODS:
        return
    supplied = request.headers.get(settings.csrf_header_name, "")
    if not supplied or not tokens_match(supplied, session.csrf_token):
        raise PermissionDenied("Missing or invalid CSRF token.", code="CSRF_FAILED")


def get_optional_session(request: Request, db: DB) -> AuthSession | None:
    token = request.cookies.get(settings.session_cookie_name)
    session = auth_service.resolve_session(db, token) if token else None
    if session is not None:
        enforce_csrf(request, session)
    return session


def get_auth_session(request: Request, db: DB) -> AuthSession:
    session = auth_service.require_session(db, request.cookies.get(settings.session_cookie_name))
    enforce_csrf(request, session)
    return session


def get_context(request: Request, db: DB, session: Annotated[AuthSession, Depends(get_auth_session)]) -> RequestContext:
    """Resolves the acting workspace from the session and re-validates membership on every request."""
    membership = None
    if session.active_workspace_id:
        membership = workspace_service.get_membership(db, session.user_id, session.active_workspace_id)
    if membership is None:
        fallback = auth_service.default_workspace_id(db, session.user_id)
        if fallback is None:
            raise PermissionDenied("You are not a member of any workspace.", code="NO_WORKSPACE")
        session.active_workspace_id = fallback
        db.commit()
        membership = workspace_service.get_membership(db, session.user_id, fallback)
    return RequestContext(
        user=session.user,
        session=session,
        workspace=db.get(Workspace, membership.workspace_id),
        membership=membership,
        ip_address=client_ip(request),
    )


Ctx = Annotated[RequestContext, Depends(get_context)]


def set_session_cookie(response: Response, token: str, session: AuthSession) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        # Persistent cookie only for "remember me"; otherwise it ends with the browser session.
        max_age=int((session.expires_at - session.last_seen_at).total_seconds()) if session.remember_me else None,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


class Paging:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=settings.max_page_size)
        ] = settings.default_page_size,
    ):
        self.page = page
        self.page_size = page_size
