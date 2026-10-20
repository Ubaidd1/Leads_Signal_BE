import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field

from app.models.enums import Role
from app.schemas.common import CamelModel, RequestModel
from app.schemas.constants import Currency, Region


class WorkspaceOut(CamelModel):
    id: uuid.UUID
    name: str
    default_currency: str
    default_geography: str
    is_demo: bool
    created_at: datetime


class WorkspaceUpdate(RequestModel):
    name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    default_currency: Currency | None = None
    default_geography: Region | None = None


class MemberOut(CamelModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    joined_at: datetime


class MemberRoleUpdate(RequestModel):
    role: Role


class InvitationCreate(RequestModel):
    email: EmailStr
    role: Role = Role.MEMBER


class InvitationOut(CamelModel):
    id: uuid.UUID
    email: str
    role: Role
    expires_at: datetime
    created_at: datetime


class InvitationAccepted(CamelModel):
    workspace_id: uuid.UUID
    signed_in: bool
