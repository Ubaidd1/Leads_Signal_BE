"""Import every model so Alembic autogenerate and relationship resolution see them."""

from app.models.audit import AuditEvent, RateLimitBucket
from app.models.company import Company
from app.models.lead import HiringSignal, Lead, LeadScore, LeadSource, SavedLead
from app.models.user import AuthSession, PasswordResetToken, User, UserPreference
from app.models.workspace import Workspace, WorkspaceInvitation, WorkspaceMembership

__all__ = [
    "AuditEvent",
    "AuthSession",
    "Company",
    "HiringSignal",
    "Lead",
    "LeadScore",
    "LeadSource",
    "PasswordResetToken",
    "RateLimitBucket",
    "SavedLead",
    "User",
    "UserPreference",
    "Workspace",
    "WorkspaceInvitation",
    "WorkspaceMembership",
]
