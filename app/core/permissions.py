from enum import StrEnum

from app.models.enums import Role


class Permission(StrEnum):
    WORKSPACE_UPDATE = "workspace:update"
    MEMBERS_VIEW = "members:view"
    MEMBERS_MANAGE = "members:manage"
    SAVED_LEADS_WRITE = "saved_leads:write"
    SAVED_SEARCHES_WRITE = "saved_searches:write"
    EXPORTS_CREATE = "exports:create"
    INTEGRATIONS_MANAGE = "integrations:manage"
    DATA_SOURCES_MANAGE = "data_sources:manage"


_MEMBER = {
    Permission.MEMBERS_VIEW,
    Permission.SAVED_LEADS_WRITE,
    Permission.SAVED_SEARCHES_WRITE,
    Permission.EXPORTS_CREATE,
}
_ADMIN = _MEMBER | {
    Permission.WORKSPACE_UPDATE,
    Permission.MEMBERS_MANAGE,
    Permission.INTEGRATIONS_MANAGE,
    Permission.DATA_SOURCES_MANAGE,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.MEMBER: frozenset(_MEMBER),
    Role.ADMIN: frozenset(_ADMIN),
    # Owners additionally manage other owners (enforced in services.workspaces).
    Role.OWNER: frozenset(_ADMIN),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
