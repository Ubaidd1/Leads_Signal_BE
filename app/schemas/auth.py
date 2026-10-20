import uuid
from datetime import datetime
from typing import Annotated

from pydantic import EmailStr, Field

from app.models.enums import Role
from app.schemas.common import CamelModel, RequestModel

Password = Annotated[str, Field(min_length=1, max_length=256)]


class RegisterRequest(RequestModel):
    email: EmailStr
    password: Password
    full_name: Annotated[str, Field(min_length=1, max_length=200)]
    workspace_name: Annotated[str, Field(min_length=1, max_length=200)]


class LoginRequest(RequestModel):
    email: EmailStr
    password: Password
    remember_me: bool = False


class PasswordResetRequest(RequestModel):
    email: EmailStr


class PasswordResetConfirm(RequestModel):
    token: Annotated[str, Field(min_length=1, max_length=200)]
    new_password: Password


class AcceptInvitationRequest(RequestModel):
    token: Annotated[str, Field(min_length=1, max_length=200)]
    full_name: Annotated[str | None, Field(max_length=200)] = None
    password: Password | None = None


class SwitchWorkspaceRequest(RequestModel):
    workspace_id: uuid.UUID


class UserOut(CamelModel):
    id: uuid.UUID
    email: str
    full_name: str
    job_title: str | None
    timezone: str
    last_login_at: datetime | None


class WorkspaceSummary(CamelModel):
    id: uuid.UUID
    name: str
    role: Role
    is_demo: bool


class SessionOut(CamelModel):
    user: UserOut
    workspace: WorkspaceSummary
    permissions: list[str]
    # Send back in the X-CSRF-Token header on every state-changing request.
    csrf_token: str
    expires_at: datetime
