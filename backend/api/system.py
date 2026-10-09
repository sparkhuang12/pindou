from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from pindou.coloring import DEFAULT_COLORING_PROMPT
from pindou.palette import load_palette
from pindou.stylize import DEFAULT_PIXEL_PROMPT, model_api_is_configured

from ..config import settings
from ..dependencies import CurrentUser
from ..state import store


router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    if not settings.data_dir.exists():
        raise HTTPException(status_code=503, detail="数据目录尚未就绪")
    try:
        with store.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="数据库尚未就绪") from exc
    return {"status": "ok"}


@router.get("/config")
async def config() -> dict[str, Any]:
    return {
        "model_api_configured": model_api_is_configured(),
        "default_prompt": DEFAULT_PIXEL_PROMPT,
        "default_coloring_prompt": DEFAULT_COLORING_PROMPT,
        "task_mode": settings.task_mode,
        "limits": {
            "upload_mb": settings.max_upload_bytes // 1024 // 1024,
            "grid_max": 100,
            "max_projects": settings.max_projects_per_user,
            "max_storage_bytes": settings.max_storage_bytes_per_user,
        },
    }


@router.get("/palette")
async def palette(user: CurrentUser) -> dict[str, Any]:
    del user
    return {
        "colors": [
            {"code": color.code, "hex": color.hex, "family": color.family}
            for color in load_palette()
        ]
    }
