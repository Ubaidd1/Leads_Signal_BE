import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import Conflict, InvalidCredentials, NotAuthenticated, PermissionDenied, ValidationFailed
from app.core.security import generate_token, hash_password, hash_token, password_needs_rehash, verify_password
from app.integrations.email import EmailMessage, get_email_backend
from app.models import AuthSession, PasswordResetToken, User, Workspace, WorkspaceMembership
from app.models.enums import Role
from app.services import audit, rate_limit
from app.utils.time import utcnow

settings = get_settings()

# Argon2 cost is per call, so cap the input to keep hashing bounded.
MAX_PASSWORD_LENGTH = 256


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_new_password(password: str) -> None:
    if len(password) < settings.password_min_length:
        raise ValidationFailed(f"Password must be at least {settings.password_min_length} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationFailed(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


# --- sessions -----------------------------------------------------------------


def create_session(
    db: Session,
    user: User,
    *,
    remember_me: bool,
    workspace_id: uuid.UUID | None,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str, AuthSession]:
    """Creates a new server-side session. Only the token digest is stored; the raw token goes in the cookie."""
    now = utcnow()
    lifetime = (
        timedelta(days=settings.session_remember_me_days)
        if remember_me
        else timedelta(hours=settings.session_absolute_timeout_hours)
    )
    token = generate_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=generate_token(),
        active_workspace_id=workspace_id,
        remember_me=remember_me,
        last_seen_at=now,
        expires_at=now + lifetime,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:300] or None,
    )
    db.add(session)
    return token, session


def resolve_session(db: Session, token: str) -> AuthSession | None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.revoked_at is not None:
        return None
    now = utcnow()
    idle_limit = timedelta(minutes=settings.session_idle_timeout_minutes)
    if session.expires_at <= now or (not session.remember_me and session.last_seen_at + idle_limit <= now):
        return None
    if not session.user.is_active:
        return None
    # Throttle writes: only refresh activity once a minute.
    if now - session.last_seen_at > timedelta(minutes=1):
        session.last_seen_at = now
        db.commit()
    return session


def revoke_session(db: Session, session: AuthSession) -> None:
    session.revoked_at = utcnow()


def revoke_user_sessions(db: Session, user_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None) -> None:
    stmt = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    db.execute(stmt.values(revoked_at=utcnow()))


def default_workspace_id(db: Session, user_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(WorkspaceMembership.workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(WorkspaceMembership.created_at, WorkspaceMembership.id)
        .limit(1)
    )


# --- account lifecycle ----------------------------------------------------------


def register(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    workspace_name: str,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[str, AuthSession]:
    if not settings.allow_registration:
        raise PermissionDenied("Self-service registration is disabled. Ask a workspace admin for an invitation.")
    rate_limit.hit(
        db,
        f"register:ip:{ip_address}",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )
    validate_new_password(password)
    email = normalize_email(email)
    if get_user_by_email(db, email):
        raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN")

    user = User(
        email=email, password_hash=hash_password(password), full_name=full_name.strip(), password_changed_at=utcnow()
    )
    workspace = Workspace(name=workspace_name.strip())
    db.add_all([user, workspace])
    db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER))
    token, session = create_session(
        db, user, remember_me=False, workspace_id=workspace.id, ip_address=ip_address, user_agent=user_agent
    )
    user.last_login_at = utcnow()
    audit.record(db, "auth.register", actor_user_id=user.id, workspace_id=workspace.id, ip_address=ip_address)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN") from None
    return token, session


def login(
    db: Session, *, email: str, password: str, remember_me: bool, ip_address: str | None, user_agent: str | None
) -> tuple[str, AuthSession]:
    email = normalize_email(email)
    window = settings.login_rate_window_seconds
    # Per-IP limit is looser than per-account so shared NATs are not locked out.
    rate_limit.hit(db, f"login:ip:{ip_address}", limit=settings.login_rate_limit * 5, window_seconds=window)
    rate_limit.hit(db, f"login:email:{email}", limit=settings.login_rate_limit, window_seconds=window)

    user = get_user_by_email(db, email)
    if not verify_password(user.password_hash if user else None, password) or not user.is_active:
        audit.record(db, "auth.login_failed", actor_user_id=user.id if user else None, ip_address=ip_address)
        db.commit()
        raise InvalidCredentials()

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    token, session = create_session(
        db,
        user,
        remember_me=remember_me,
        workspace_id=default_workspace_id(db, user.id),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    user.last_login_at = utcnow()
    audit.record(
        db, "auth.login", actor_user_id=user.id, workspace_id=session.active_workspace_id, ip_address=ip_address
    )
    db.commit()
    return token, session


def logout(db: Session, session: AuthSession, ip_address: str | None) -> None:
    revoke_session(db, session)
    audit.record(db, "auth.logout", actor_user_id=session.user_id, ip_address=ip_address)
    db.commit()


def request_password_reset(db: Session, *, email: str, ip_address: str | None) -> None:
    """Always behaves the same from the caller's perspective, whether or not the account exists."""
    email = normalize_email(email)
    window = settings.reset_rate_window_seconds
    rate_limit.hit(db, f"reset:ip:{ip_address}", limit=settings.reset_rate_limit * 4, window_seconds=window)
    rate_limit.hit(db, f"reset:email:{email}", limit=settings.reset_rate_limit, window_seconds=window)

    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        return

    now = utcnow()
    # Only the newest link is valid.
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = generate_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    audit.record(db, "auth.password_reset_requested", actor_user_id=user.id, ip_address=ip_address)
    db.commit()

    link = f"{settings.frontend_base_url}/reset-password?token={token}"
    get_email_backend().send(
        EmailMessage(
            to=user.email,
            subject="Reset your Hiring Intelligence password",
            body=(
                f"Use this link within {settings.password_reset_ttl_minutes} minutes to set a new password:\n"
                f"{link}\n\nIf you did not request this, you can ignore this email."
            ),
        )
    )


def confirm_password_reset(db: Session, *, token: str, new_password: str, ip_address: str | None) -> None:
    validate_new_password(new_password)
    reset = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)).with_for_update()
    )
    now = utcnow()
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise ValidationFailed("This password reset link is invalid or has expired.", code="INVALID_RESET_TOKEN")
    user = db.get(User, reset.user_id)
    reset.used_at = now
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    revoke_user_sessions(db, user.id)
    audit.record(db, "auth.password_reset_completed", actor_user_id=user.id, ip_address=ip_address)
    db.commit()


def change_password(
    db: Session, *, user: User, session: AuthSession, current_password: str, new_password: str, ip_address: str | None
) -> None:
    if not verify_password(user.password_hash, current_password):
        raise ValidationFailed("Current password is incorrect.", code="INVALID_CURRENT_PASSWORD")
    validate_new_password(new_password)
    user.password_hash = hash_password(new_password)
    user.password_changed_at = utcnow()
    # Sign out every other device; the current session stays valid.
    revoke_user_sessions(db, user.id, except_session_id=session.id)
    audit.record(db, "auth.password_changed", actor_user_id=user.id, ip_address=ip_address)
    db.commit()


def require_session(db: Session, token: str | None) -> AuthSession:
    session = resolve_session(db, token) if token else None
    if session is None:
        raise NotAuthenticated()
    return session
