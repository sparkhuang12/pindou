from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response

from ..dependencies import CurrentAdmin, ensure_managed_file
from ..file_stream import file_response
from ..schemas import AdminMessagePayload, AdminUserPayload
from ..serializers import serialize_project
from ..state import store


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview")
async def overview(admin: CurrentAdmin) -> dict[str, Any]:
    return {"overview": store.admin_overview(), "admin": admin}


@router.get("/users")
async def users(
    admin: CurrentAdmin,
    query: str = "",
    status: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    del admin
    return {
        "users": store.list_admin_users(
            query=query, status=status, limit=limit, offset=offset
        )
    }


@router.get("/users/{user_id}")
async def user_detail(user_id: int, admin: CurrentAdmin) -> dict[str, Any]:
    del admin
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "user": target,
        "usage": store.user_dashboard(user_id),
        "projects": [serialize_project(item, admin=True) for item in store.list_projects(user_id)],
        "activities": store.list_activity(user_id=user_id, limit=50),
        "jobs": store.list_jobs(user_id=user_id, limit=50),
        "messages": store.list_messages(user_id=user_id, limit=50),
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: int, payload: AdminUserPayload, admin: CurrentAdmin
) -> dict[str, Any]:
    if user_id == admin["id"] and (payload.role != "admin" or payload.status != "active"):
        raise HTTPException(status_code=400, detail="不能停用或降级当前管理员账户")
    try:
        user = store.update_user_admin(user_id, role=payload.role, status=payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.record_activity(
        user_id=admin["id"],
        action="admin.user.update",
        category="admin",
        resource_type="user",
        resource_id=str(user_id),
        input_data=payload.model_dump(),
        output_data={"role": user["role"], "status": user["status"]},
    )
    return {"user": user}


@router.get("/projects")
async def projects(admin: CurrentAdmin, query: str = "", limit: int = 100) -> dict[str, Any]:
    del admin
    return {
        "projects": [
            serialize_project(item, admin=True)
            for item in store.list_admin_projects(query=query, limit=limit)
        ]
    }


@router.get("/projects/{project_id}/assets/{kind}", include_in_schema=False)
async def project_asset(
    project_id: str,
    kind: Literal["source", "mask", "cutout", "stylized", "painted", "pattern", "preview"],
    admin: CurrentAdmin,
) -> Response:
    del admin
    project = store.get_project_admin(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    field = {
        "source": "source_path", "mask": "mask_path", "cutout": "cutout_path",
        "stylized": "stylized_path", "painted": "painted_path",
        "pattern": "pattern_path", "preview": "preview_path",
    }[kind]
    path = ensure_managed_file(project, field)
    return file_response(path, "image/png")


@router.get("/activity")
async def activity(
    admin: CurrentAdmin,
    user_id: int | None = None,
    action: str = "",
    status: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    del admin
    return {
        "activities": store.list_activity(
            user_id=user_id, action=action, status=status, limit=limit, offset=offset
        )
    }


@router.get("/jobs")
async def jobs(
    admin: CurrentAdmin, user_id: int | None = None, limit: int = 100
) -> dict[str, Any]:
    del admin
    return {"jobs": store.list_jobs(user_id=user_id, limit=limit)}


@router.get("/messages")
async def messages(
    admin: CurrentAdmin, status: str = "", limit: int = 100
) -> dict[str, Any]:
    del admin
    return {"messages": store.list_messages(status=status, limit=limit)}


@router.put("/messages/{message_id}")
async def update_message(
    message_id: str, payload: AdminMessagePayload, admin: CurrentAdmin
) -> dict[str, Any]:
    try:
        message = store.update_message_admin(message_id, payload.status, payload.admin_note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.record_activity(
        user_id=admin["id"],
        action="admin.message.update",
        category="admin",
        resource_type="message",
        resource_id=message_id,
        input_data=payload.model_dump(),
        output_data={"status": message["status"]},
    )
    return {"message": message}
