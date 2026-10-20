from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.exceptions import Conflict, ValidationFailed
from app.core.security import verify_password
from app.models import User, UserPreference
from app.schemas.users import OnboardingPreferences, ProfileUpdate
from app.services import audit
from app.services.auth import get_user_by_email, normalize_email
from app.utils.time import utcnow


def update_profile(db: Session, ctx: RequestContext, data: ProfileUpdate) -> User:
    user = ctx.user
    changes = data.model_dump(exclude_unset=True, exclude={"current_password", "email"})
    if "full_name" in changes and changes["full_name"] is None:
        raise ValidationFailed("Full name cannot be empty.")
    for field, value in changes.items():
        setattr(user, field, value)

    if data.email is not None and normalize_email(data.email) != user.email:
        # Changing the login identifier requires re-authentication.
        if not data.current_password or not verify_password(user.password_hash, data.current_password):
            raise ValidationFailed(
                "Current password is required to change your email.", code="INVALID_CURRENT_PASSWORD"
            )
        new_email = normalize_email(data.email)
        if get_user_by_email(db, new_email):
            raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN")
        audit.record(
            db, "user.email_changed", actor_user_id=user.id, ip_address=ctx.ip_address, details={"from": user.email}
        )
        user.email = new_email
        changes["email"] = new_email

    if changes:
        audit.record(db, "user.profile_updated", actor_user_id=user.id, details={"fields": sorted(changes)})
    db.commit()
    return user


def get_onboarding(db: Session, user: User) -> UserPreference | None:
    return db.get(UserPreference, user.id)


def save_onboarding(db: Session, user: User, preferences: OnboardingPreferences) -> UserPreference:
    record = db.get(UserPreference, user.id) or UserPreference(user_id=user.id)
    record.onboarding = preferences.model_dump(by_alias=True)
    record.onboarding_completed_at = record.onboarding_completed_at or utcnow()
    db.add(record)
    db.commit()
    return record
