from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from ..config import settings
from ..dependencies import CurrentUser, request_ip, set_session
from ..schemas import (
    AccountDeletePayload,
    AuthPayload,
    MessagePayload,
    PasswordChangePayload,
    ProfilePayload,
)
from ..state import store


router = APIRouter(prefix="/api", tags=["account"])


@router.post("/auth/register")
async def register(payload: AuthPayload, request: Request, response: Response) -> dict[str, Any]:
    try:
        user = store.create_user(payload.email, payload.password, payload.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_session(response, user["id"])
    store.record_activity(
        user_id=user["id"],
        action="auth.register",
        category="account",
        ip_address=request_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        input_data={"email": user["email"], "display_name": user["display_name"]},
        output_data={"user_id": user["id"]},
    )
    return {"user": user}


@router.post("/auth/login")
async def login(payload: AuthPayload, request: Request, response: Response) -> dict[str, Any]:
    user = store.authenticate(payload.email, payload.password, request_ip(request))
    if user is None:
        store.record_activity(
            user_id=None,
            action="auth.login",
            category="account",
            status="failed",
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", ""),
            input_data={"email": payload.email.strip().lower()[:254]},
            error_message="invalid credentials or disabled account",
        )
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    set_session(response, user["id"])
    store.record_activity(
        user_id=user["id"],
        action="auth.login",
        category="account",
        ip_address=request_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        output_data={"role": user["role"]},
    )
    return {"user": user}


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(settings.session_cookie, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    return {"user": user}


@router.put("/profile")
async def update_profile(payload: ProfilePayload, user: CurrentUser) -> dict[str, Any]:
    try:
        updated = store.update_user(user["id"], payload.display_name, payload.bio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": updated}


@router.put("/password")
async def change_password(payload: PasswordChangePayload, user: CurrentUser) -> dict[str, Any]:
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    try:
        updated = store.change_password(user["id"], payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": updated}


@router.get("/account/export")
async def export_account(user: CurrentUser) -> dict[str, Any]:
    projects = store.list_projects(user["id"])
    return {
        "user": user,
        "projects": [
            {
                "id": item["id"],
                "name": item["name"],
                "status": item["status"],
                "selection": item["selection"],
                "settings": item["settings"],
                "bead_count": item["bead_count"],
                "colors_used": item["colors_used"],
                "cols": item["cols"],
                "rows": item["rows"],
                "original_filename": item["original_filename"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "assets": {field: bool(item.get(field)) for field in store.ASSET_FIELDS},
            }
            for item in projects
        ],
    }


@router.delete("/account")
async def delete_account(payload: AccountDeletePayload, user: CurrentUser, response: Response) -> dict[str, bool]:
    if user.get("role") == "admin":
        raise HTTPException(status_code=400, detail="管理员账户不能从用户端注销")
    try:
        if not store.verify_user_password(user["id"], payload.password):
            raise ValueError("当前密码不正确")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for project in store.list_projects(user["id"]):
        store.cancel_project_jobs(project["id"], user["id"])
        project_dir = (store.projects_dir / str(user["id"]) / project["id"]).resolve()
        expected_parent = (store.projects_dir / str(user["id"])).resolve()
        if project_dir.parent == expected_parent:
            import shutil

            shutil.rmtree(project_dir, ignore_errors=True)
    store.delete_user(user["id"])
    response.delete_cookie(settings.session_cookie, path="/")
    return {"ok": True}


@router.get("/account/usage")
async def account_usage(user: CurrentUser) -> dict[str, Any]:
    return {"usage": store.user_dashboard(user["id"])}


@router.get("/activity")
async def user_activity(user: CurrentUser, limit: int = 50) -> dict[str, Any]:
    return {"activities": store.list_activity(user_id=user["id"], limit=min(limit, 100))}


@router.get("/messages")
async def user_messages(user: CurrentUser) -> dict[str, Any]:
    return {"messages": store.list_messages(user_id=user["id"], limit=50)}


@router.post("/messages", status_code=201)
async def create_user_message(payload: MessagePayload, user: CurrentUser) -> dict[str, Any]:
    try:
        message = store.create_message(user["id"], payload.subject, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": message}
