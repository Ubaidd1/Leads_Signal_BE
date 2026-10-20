import uuid

from fastapi import APIRouter, status

from app.api.deps import DB, Ctx
from app.schemas.workspaces import (
    InvitationCreate,
    InvitationOut,
    MemberOut,
    MemberRoleUpdate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services import workspaces as workspace_service

router = APIRouter(prefix="/workspace", tags=["workspace"])


def member_out(membership) -> MemberOut:
    return MemberOut(
        id=membership.id,
        user_id=membership.user_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.get("", response_model=WorkspaceOut)
def get_workspace(ctx: Ctx):
    return ctx.workspace


@router.patch("", response_model=WorkspaceOut)
def update_workspace(body: WorkspaceUpdate, db: DB, ctx: Ctx):
    return workspace_service.update_settings(db, ctx, body.model_dump(exclude_unset=True, exclude_none=True))


@router.get("/members", response_model=list[MemberOut])
def list_members(db: DB, ctx: Ctx):
    return [member_out(membership) for membership in workspace_service.list_members(db, ctx)]


@router.patch("/members/{membership_id}", response_model=MemberOut)
def change_member_role(membership_id: uuid.UUID, body: MemberRoleUpdate, db: DB, ctx: Ctx):
    return member_out(workspace_service.change_member_role(db, ctx, membership_id, body.role))


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(membership_id: uuid.UUID, db: DB, ctx: Ctx):
    workspace_service.remove_member(db, ctx, membership_id)


@router.get("/invitations", response_model=list[InvitationOut])
def list_invitations(db: DB, ctx: Ctx):
    return workspace_service.list_pending_invitations(db, ctx)


@router.post("/invitations", response_model=InvitationOut, status_code=status.HTTP_201_CREATED)
def create_invitation(body: InvitationCreate, db: DB, ctx: Ctx):
    return workspace_service.create_invitation(db, ctx, body.email, body.role)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: uuid.UUID, db: DB, ctx: Ctx):
    workspace_service.revoke_invitation(db, ctx, invitation_id)
