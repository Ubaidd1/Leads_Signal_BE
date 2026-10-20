from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    DB,
    Ctx,
    clear_session_cookie,
    client_ip,
    get_auth_session,
    get_context,
    get_optional_session,
    set_session_cookie,
    user_agent,
)
from app.core.context import RequestContext
from app.core.permissions import ROLE_PERMISSIONS
from app.models import AuthSession
from app.schemas.auth import (
    AcceptInvitationRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    SessionOut,
    SwitchWorkspaceRequest,
    UserOut,
    WorkspaceSummary,
)
from app.schemas.common import Message
from app.schemas.workspaces import InvitationAccepted
from app.services import auth as auth_service
from app.services import workspaces as workspace_service

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_REQUESTED = "If an account exists for that email, password reset instructions will be sent."


def session_out(ctx: RequestContext) -> SessionOut:
    return SessionOut(
        user=UserOut.model_validate(ctx.user),
        workspace=WorkspaceSummary(
            id=ctx.workspace.id, name=ctx.workspace.name, role=ctx.role, is_demo=ctx.workspace.is_demo
        ),
        permissions=sorted(ROLE_PERMISSIONS[ctx.role]),
        csrf_token=ctx.session.csrf_token,
        expires_at=ctx.session.expires_at,
    )


def _signed_in(request: Request, db, session: AuthSession) -> SessionOut:
    return session_out(get_context(request, db, session))


@router.post("/register", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, request: Request, response: Response, db: DB):
    token, session = auth_service.register(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        workspace_name=body.workspace_name,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    set_session_cookie(response, token, session)
    return _signed_in(request, db, session)


@router.post("/login", response_model=SessionOut)
def login(body: LoginRequest, request: Request, response: Response, db: DB):
    token, session = auth_service.login(
        db,
        email=body.email,
        password=body.password,
        remember_me=body.remember_me,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    set_session_cookie(response, token, session)
    return _signed_in(request, db, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DB, session: Annotated[AuthSession, Depends(get_auth_session)]):
    auth_service.logout(db, session, client_ip(request))
    clear_session_cookie(response)


@router.get("/session", response_model=SessionOut)
def current_session(ctx: Ctx):
    return session_out(ctx)


@router.put("/session/workspace", response_model=SessionOut)
def switch_workspace(body: SwitchWorkspaceRequest, request: Request, db: DB, ctx: Ctx):
    workspace_service.switch_workspace(db, ctx.session, ctx.user.id, body.workspace_id)
    return _signed_in(request, db, ctx.session)


@router.post("/password-reset/request", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(body: PasswordResetRequest, request: Request, db: DB):
    auth_service.request_password_reset(db, email=body.email, ip_address=client_ip(request))
    return Message(message=RESET_REQUESTED)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(body: PasswordResetConfirm, request: Request, db: DB):
    auth_service.confirm_password_reset(
        db, token=body.token, new_password=body.new_password, ip_address=client_ip(request)
    )


@router.post("/invitations/accept", response_model=InvitationAccepted)
def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    response: Response,
    db: DB,
    session: Annotated[AuthSession | None, Depends(get_optional_session)],
):
    token, new_session, workspace_id = workspace_service.accept_invitation(
        db,
        token=body.token,
        current_user=session.user if session else None,
        full_name=body.full_name,
        password=body.password,
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    if token:
        set_session_cookie(response, token, new_session)
    return InvitationAccepted(workspace_id=workspace_id, signed_in=bool(token or session))
