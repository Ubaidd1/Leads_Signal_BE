from fastapi import APIRouter, Request, status

from app.api.deps import DB, Ctx, client_ip
from app.schemas.auth import UserOut, WorkspaceSummary
from app.schemas.users import ChangePasswordRequest, OnboardingOut, OnboardingPreferences, ProfileUpdate
from app.services import auth as auth_service
from app.services import users as user_service
from app.services import workspaces as workspace_service

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
def get_profile(ctx: Ctx):
    return ctx.user


@router.patch("/me", response_model=UserOut)
def update_profile(body: ProfileUpdate, db: DB, ctx: Ctx):
    return user_service.update_profile(db, ctx, body)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: ChangePasswordRequest, request: Request, db: DB, ctx: Ctx):
    auth_service.change_password(
        db,
        user=ctx.user,
        session=ctx.session,
        current_password=body.current_password,
        new_password=body.new_password,
        ip_address=client_ip(request),
    )


@router.get("/me/onboarding", response_model=OnboardingOut)
def get_onboarding(db: DB, ctx: Ctx):
    record = user_service.get_onboarding(db, ctx.user)
    if record is None or record.onboarding is None:
        return OnboardingOut(preferences=None, completed_at=None)
    return OnboardingOut(preferences=record.onboarding, completed_at=record.onboarding_completed_at)


@router.put("/me/onboarding", response_model=OnboardingOut)
def save_onboarding(body: OnboardingPreferences, db: DB, ctx: Ctx):
    record = user_service.save_onboarding(db, ctx.user, body)
    return OnboardingOut(preferences=record.onboarding, completed_at=record.onboarding_completed_at)


@router.get("/workspaces", response_model=list[WorkspaceSummary])
def list_my_workspaces(db: DB, ctx: Ctx):
    return [
        WorkspaceSummary(id=workspace.id, name=workspace.name, role=role, is_demo=workspace.is_demo)
        for workspace, role in workspace_service.list_user_workspaces(db, ctx.user.id)
    ]
