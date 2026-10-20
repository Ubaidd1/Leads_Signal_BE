from datetime import timedelta

from sqlalchemy import select

from app.models import AuditEvent, Workspace, WorkspaceMembership
from app.models.enums import Role
from app.utils.time import utcnow
from tests.conftest import PASSWORD, login


def _membership_id(db, user, workspace):
    return str(
        db.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.user_id == user.id, WorkspaceMembership.workspace_id == workspace.id
            )
        )
    )


def test_owner_and_admin_can_update_settings_member_cannot(signed_in, db):
    owner, _, workspace = signed_in("owner@example.com")
    member, _, _ = signed_in("member@example.com", workspace=workspace, role=Role.MEMBER)
    admin, _, _ = signed_in("admin@example.com", workspace=workspace, role=Role.ADMIN)

    response = member.patch("/api/v1/workspace", json={"name": "Hacked"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    response = admin.patch("/api/v1/workspace", json={"defaultCurrency": "EUR", "defaultGeography": "europe"})
    assert response.status_code == 200
    assert response.json()["defaultCurrency"] == "EUR"

    response = owner.patch("/api/v1/workspace", json={"name": "Renamed"})
    assert response.json()["name"] == "Renamed"
    assert member.get("/api/v1/workspace").json()["name"] == "Renamed"
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "workspace.updated")) is not None


def test_workspace_settings_validation(signed_in):
    owner, _, _ = signed_in("owner@example.com")
    assert owner.patch("/api/v1/workspace", json={"defaultCurrency": "XYZ"}).status_code == 422


def test_member_management_rules(signed_in, db):
    owner, owner_user, workspace = signed_in("owner@example.com")
    admin, admin_user, _ = signed_in("admin@example.com", workspace=workspace, role=Role.ADMIN)
    member, member_user, _ = signed_in("member@example.com", workspace=workspace, role=Role.MEMBER)
    owner_mid = _membership_id(db, owner_user, workspace)
    admin_mid = _membership_id(db, admin_user, workspace)
    member_mid = _membership_id(db, member_user, workspace)

    assert len(member.get("/api/v1/workspace/members").json()) == 3
    # Members cannot manage anyone.
    assert member.patch(f"/api/v1/workspace/members/{admin_mid}", json={"role": "member"}).status_code == 403
    # Admins cannot grant or touch ownership.
    assert admin.patch(f"/api/v1/workspace/members/{member_mid}", json={"role": "owner"}).status_code == 403
    assert admin.delete(f"/api/v1/workspace/members/{owner_mid}").status_code == 403
    # Admins can manage members.
    response = admin.patch(f"/api/v1/workspace/members/{member_mid}", json={"role": "admin"})
    assert response.status_code == 200 and response.json()["role"] == "admin"
    # The last owner cannot be demoted or removed, even by themselves.
    response = owner.patch(f"/api/v1/workspace/members/{owner_mid}", json={"role": "admin"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "LAST_OWNER"
    assert owner.delete(f"/api/v1/workspace/members/{owner_mid}").status_code == 409
    # Removal takes effect on the next request.
    assert owner.delete(f"/api/v1/workspace/members/{admin_mid}").status_code == 204
    response = admin.get("/api/v1/workspace")
    assert response.status_code == 403 and response.json()["error"]["code"] == "NO_WORKSPACE"


def test_member_can_leave_workspace(signed_in, db):
    _, _, workspace = signed_in("owner@example.com")
    member, member_user, _ = signed_in("member@example.com", workspace=workspace, role=Role.MEMBER)
    assert member.delete(f"/api/v1/workspace/members/{_membership_id(db, member_user, workspace)}").status_code == 204


def test_cannot_manage_members_of_another_workspace(signed_in, db):
    owner_a, _, _ = signed_in("a@example.com")
    _, user_b, workspace_b = signed_in("b@example.com")
    foreign = _membership_id(db, user_b, workspace_b)
    assert owner_a.patch(f"/api/v1/workspace/members/{foreign}", json={"role": "member"}).status_code == 404
    assert owner_a.delete(f"/api/v1/workspace/members/{foreign}").status_code == 404


def _invite_token(outbox) -> str:
    return outbox[-1].body.split("token=")[1].split()[0]


def test_invitation_flow_for_new_user(signed_in, make_client, outbox):
    owner, _, workspace = signed_in("owner@example.com")
    response = owner.post("/api/v1/workspace/invitations", json={"email": "New@Example.com", "role": "member"})
    assert response.status_code == 201
    assert owner.post("/api/v1/workspace/invitations", json={"email": "new@example.com"}).status_code == 409
    assert [item["email"] for item in owner.get("/api/v1/workspace/invitations").json()] == ["new@example.com"]

    invitee = make_client()
    token = _invite_token(outbox)
    response = invitee.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert response.status_code == 422  # name + password needed for a new account

    response = invitee.post(
        "/api/v1/auth/invitations/accept", json={"token": token, "fullName": "Newbie", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json() == {"workspaceId": str(workspace.id), "signedIn": True}
    session = invitee.get("/api/v1/auth/session").json()
    assert session["workspace"]["role"] == "member"
    # Single use.
    assert make_client().post("/api/v1/auth/invitations/accept", json={"token": token}).status_code == 422


def test_invitation_for_existing_user_requires_matching_sign_in(signed_in, make_client, outbox):
    owner, _, workspace = signed_in("owner@example.com")
    existing, _, _ = signed_in("existing@example.com")
    owner.post("/api/v1/workspace/invitations", json={"email": "existing@example.com", "role": "admin"})
    token = _invite_token(outbox)

    anonymous = make_client()
    response = anonymous.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SIGN_IN_REQUIRED"

    response = existing.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert response.status_code == 200
    workspaces = existing.get("/api/v1/workspaces").json()
    assert {item["role"] for item in workspaces} == {"owner", "admin"}
    switched = existing.put("/api/v1/auth/session/workspace", json={"workspaceId": str(workspace.id)})
    assert switched.status_code == 200 and switched.json()["workspace"]["role"] == "admin"


def test_member_cannot_invite_and_admin_cannot_invite_owner(signed_in):
    _, _, workspace = signed_in("owner@example.com")
    member, _, _ = signed_in("member@example.com", workspace=workspace, role=Role.MEMBER)
    admin, _, _ = signed_in("admin@example.com", workspace=workspace, role=Role.ADMIN)
    assert member.post("/api/v1/workspace/invitations", json={"email": "x@example.com"}).status_code == 403
    assert (
        admin.post("/api/v1/workspace/invitations", json={"email": "x@example.com", "role": "owner"}).status_code == 403
    )


def test_revoked_invitation_cannot_be_accepted(signed_in, make_client, outbox):
    owner, _, _ = signed_in("owner@example.com")
    invitation = owner.post("/api/v1/workspace/invitations", json={"email": "x@example.com"}).json()
    assert owner.delete(f"/api/v1/workspace/invitations/{invitation['id']}").status_code == 204
    response = make_client().post(
        "/api/v1/auth/invitations/accept",
        json={"token": _invite_token(outbox), "fullName": "X", "password": PASSWORD},
    )
    assert response.status_code == 422


def test_switch_to_foreign_workspace_is_not_found(signed_in):
    client_a, _, _ = signed_in("a@example.com")
    _, _, workspace_b = signed_in("b@example.com")
    response = client_a.put("/api/v1/auth/session/workspace", json={"workspaceId": str(workspace_b.id)})
    assert response.status_code == 404


def test_login_lands_in_first_workspace(make_user, make_client, db):
    user, first = make_user("multi@example.com")
    second = Workspace(name="Second")
    db.add(second)
    db.flush()
    # now() is fixed per transaction, so make the later membership explicitly newer.
    db.add(
        WorkspaceMembership(
            workspace_id=second.id, user_id=user.id, role=Role.MEMBER, created_at=utcnow() + timedelta(minutes=1)
        )
    )
    db.commit()
    body = login(make_client(), "multi@example.com", PASSWORD)
    assert body["workspace"]["id"] == str(first.id)
