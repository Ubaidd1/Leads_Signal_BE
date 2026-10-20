from dataclasses import dataclass

from app.core.exceptions import PermissionDenied
from app.core.permissions import Permission, has_permission
from app.models import AuthSession, User, Workspace, WorkspaceMembership


@dataclass
class RequestContext:
    """Who is calling and which workspace they are acting in, resolved server-side from the session."""

    user: User
    session: AuthSession
    workspace: Workspace
    membership: WorkspaceMembership
    ip_address: str | None

    @property
    def role(self):
        return self.membership.role

    def require(self, permission: Permission) -> None:
        if not has_permission(self.membership.role, permission):
            raise PermissionDenied()
