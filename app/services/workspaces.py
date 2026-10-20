import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.context import RequestContext
from app.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import Permission
from app.core.security import generate_token, hash_password, hash_token
from app.integrations.email import EmailMessage, get_email_backend
from app.models import AuthSession, User, Workspace, WorkspaceInvitation, WorkspaceMembership
from app.models.enums import Role
from app.services import audit
from app.services.auth import create_session, normalize_email, validate_new_password
from app.utils.time import utcnow

settings = get_settings()


def list_user_workspaces(db: Session, user_id: uuid.UUID) -> list[tuple[Workspace, Role]]:
    rows = db.execute(
        select(Workspace, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(WorkspaceMembership.created_at, Workspace.id)
    ).all()
    return [(workspace, role) for workspace, role in rows]


def get_membership(db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id, WorkspaceMembership.workspace_id == workspace_id
        )
    )


def switch_workspace(db: Session, session: AuthSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    # A workspace the caller does not belong to is indistinguishable from one that does not exist.
    if get_membership(db, user_id, workspace_id) is None:
        raise NotFound()
    session.active_workspace_id = workspace_id
    db.commit()


def update_settings(db: Session, ctx: RequestContext, changes: dict) -> Workspace:
    ctx.require(Permission.WORKSPACE_UPDATE)
    workspace = ctx.workspace
    for field, value in changes.items():
        setattr(workspace, field, value)
    audit.record(
        db,
        "workspace.updated",
        actor_user_id=ctx.user.id,
        workspace_id=workspace.id,
        target_type="workspace",
        target_id=workspace.id,
        ip_address=ctx.ip_address,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return workspace


# --- members --------------------------------------------------------------------


def list_members(db: Session, ctx: RequestContext) -> list[WorkspaceMembership]:
    ctx.require(Permission.MEMBERS_VIEW)
    return list(
        db.scalars(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == ctx.workspace.id)
            .order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)
        )
    )


def _get_member(db: Session, ctx: RequestContext, membership_id: uuid.UUID) -> WorkspaceMembership:
    membership = db.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.id == membership_id, WorkspaceMembership.workspace_id == ctx.workspace.id)
        .with_for_update()
    )
    if membership is None:
        raise NotFound()
    return membership


def _owner_count(db: Session, workspace_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.role == Role.OWNER)
    )


def _check_can_manage(ctx: RequestContext, target_role: Role, new_role: Role | None = None) -> None:
    ctx.require(Permission.MEMBERS_MANAGE)
    if ctx.role != Role.OWNER and (target_role == Role.OWNER or new_role == Role.OWNER):
        raise PermissionDenied("Only owners can manage owners.")


def change_member_role(db: Session, ctx: RequestContext, membership_id: uuid.UUID, role: Role) -> WorkspaceMembership:
    membership = _get_member(db, ctx, membership_id)
    _check_can_manage(ctx, membership.role, role)
    if membership.role == Role.OWNER and role != Role.OWNER and _owner_count(db, ctx.workspace.id) <= 1:
        raise Conflict("A workspace must keep at least one owner.", code="LAST_OWNER")
    previous = membership.role
    membership.role = role
    audit.record(
        db,
        "member.role_changed",
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace.id,
        target_type="membership",
        target_id=membership.id,
        ip_address=ctx.ip_address,
        details={"from": previous.value, "to": role.value, "user_id": str(membership.user_id)},
    )
    db.commit()
    return membership


def remove_member(db: Session, ctx: RequestContext, membership_id: uuid.UUID) -> None:
    membership = _get_member(db, ctx, membership_id)
    leaving_self = membership.user_id == ctx.user.id
    if not leaving_self:
        _check_can_manage(ctx, membership.role)
    if membership.role == Role.OWNER and _owner_count(db, ctx.workspace.id) <= 1:
        raise Conflict("A workspace must keep at least one owner.", code="LAST_OWNER")
    db.delete(membership)
    audit.record(
        db,
        "member.removed",
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace.id,
        target_type="membership",
        target_id=membership.id,
        ip_address=ctx.ip_address,
        details={"user_id": str(membership.user_id), "self": leaving_self},
    )
    db.commit()


# --- invitations ------------------------------------------------------------------


def create_invitation(db: Session, ctx: RequestContext, email: str, role: Role) -> WorkspaceInvitation:
    _check_can_manage(ctx, Role.MEMBER, role)
    email = normalize_email(email)
    existing_member = db.scalar(
        select(WorkspaceMembership.id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == ctx.workspace.id, User.email == email)
    )
    if existing_member:
        raise Conflict("This person is already a member of the workspace.", code="ALREADY_MEMBER")

    token = generate_token()
    invitation = WorkspaceInvitation(
        workspace_id=ctx.workspace.id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by_user_id=ctx.user.id,
        expires_at=utcnow() + timedelta(days=settings.invitation_ttl_days),
    )
    db.add(invitation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("An invitation is already pending for this email.", code="INVITATION_PENDING") from None
    audit.record(
        db,
        "invitation.created",
        actor_user_id=ctx.user.id,
        workspace_id=ctx.workspace.id,
        target_type="invitation",
        target_id=invitation.id,
        ip_address=ctx.ip_address,
        details={"email": email, "role": role.value},
    )
    db.commit()

    link = f"{settings.frontend_base_url}/accept-invitation?token={token}"
    get_email_backend().send(
        EmailMessage(
            to=email,
            subject=f"You have been invited to {ctx.workspace.name} on Hiring Intelligence",
            body=f"{ctx.user.full_name} invited you to join {ctx.workspace.name}.\n"
            f"Accept within {settings.invitation_ttl_days} days: {link}",
        )
    )
    return invitation


def list_pending_invitations(db: Session, ctx: RequestContext) -> list[WorkspaceInvitation]:
    ctx.require(Permission.MEMBERS_MANAGE)
    return list(
        db.scalars(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.workspace_id == ctx.workspace.id,
                WorkspaceInvitation.accepted_at.is_(None),
                WorkspaceInvitation.revoked_at.is_(None),
                WorkspaceInvitation.expires_at > utcnow(),
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        )
    )


def revoke_invitation(db: Session, ctx: RequestContext, invitation_id: uuid.UUID) -> None:
    ctx.require(Permission.MEMBERS_MANAGE)
    invitation = db.scalar(
        select(WorkspaceInvitation).where(
            WorkspaceInvitation.id == invitation_id, WorkspaceInvitation.workspace_id == ctx.workspace.id
        )
    )
    if invitation is None or invitation.accepted_at is not None:
        raise NotFound()
    if invitation.revoked_at is None:
        invitation.revoked_at = utcnow()
        audit.record(
            db,
            "invitation.revoked",
            actor_user_id=ctx.user.id,
            workspace_id=ctx.workspace.id,
            target_type="invitation",
            target_id=invitation.id,
            ip_address=ctx.ip_address,
        )
    db.commit()


def accept_invitation(
    db: Session,
    *,
    token: str,
    current_user: User | None,
    full_name: str | None,
    password: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str | None, AuthSession | None, uuid.UUID]:
    """Joins the invited workspace.

    Existing accounts must be signed in as the invited email. New accounts are created from
    ``full_name`` + ``password`` and signed in; the new session token is returned in that case.
    """
    invitation = db.scalar(
        select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == hash_token(token)).with_for_update()
    )
    now = utcnow()
    if invitation is None or invitation.accepted_at or invitation.revoked_at or invitation.expires_at <= now:
        raise ValidationFailed("This invitation is invalid or has expired.", code="INVALID_INVITATION")

    existing = db.scalar(select(User).where(User.email == invitation.email))
    new_token = new_session = None
    if existing is not None:
        if current_user is None or current_user.id != existing.id:
            raise PermissionDenied("Sign in as the invited account to accept this invitation.", code="SIGN_IN_REQUIRED")
        user = existing
    else:
        if not full_name or not password:
            raise ValidationFailed("Full name and password are required to create your account.")
        validate_new_password(password)
        user = User(
            email=invitation.email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            password_changed_at=now,
        )
        db.add(user)
        db.flush()

    if get_membership(db, user.id, invitation.workspace_id) is None:
        db.add(WorkspaceMembership(workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role))
    invitation.accepted_at = now
    if existing is None:
        new_token, new_session = create_session(
            db,
            user,
            remember_me=False,
            workspace_id=invitation.workspace_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        user.last_login_at = now
    audit.record(
        db,
        "invitation.accepted",
        actor_user_id=user.id,
        workspace_id=invitation.workspace_id,
        target_type="invitation",
        target_id=invitation.id,
        ip_address=ip_address,
    )
    db.commit()
    return new_token, new_session, invitation.workspace_id
