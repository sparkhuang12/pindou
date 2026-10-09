from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, Response

from .config import settings
from .state import store


def request_ip(request: Request) -> str:
    if os.environ.get("PINDOU_TRUST_PROXY", "0") == "1":
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded[:64]
    return (request.client.host if request.client else "")[:64]


async def require_user(request: Request) -> dict[str, Any]:
    user_id = store.read_session_token(request.cookies.get(settings.session_cookie))
    if user_id is None:
        raise HTTPException(status_code=401, detail="请先登录")
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="登录状态已失效")
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="账户已被停用")
    return user


CurrentUser = Annotated[dict[str, Any], Depends(require_user)]


async def require_admin(user: CurrentUser) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


CurrentAdmin = Annotated[dict[str, Any], Depends(require_admin)]


def set_session(response: Response, user_id: int) -> None:
    response.set_cookie(
        settings.session_cookie,
        store.create_session_token(user_id),
        max_age=30 * 24 * 3600,
        httponly=True,
        secure=os.environ.get("PINDOU_COOKIE_SECURE", "0") == "1",
        samesite="lax",
        path="/",
    )


def get_project_or_404(project_id: str, user_id: int) -> dict[str, Any]:
    project = store.get_project(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def ensure_managed_file(project: dict[str, Any], field: str) -> Path:
    value = project.get(field)
    if not value:
        raise HTTPException(status_code=404, detail="文件尚未生成")
    path = Path(value).resolve()
    if not path.is_relative_to(store.data_dir) or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return path
