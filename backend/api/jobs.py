from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..dependencies import CurrentUser
from ..serializers import serialize_job
from ..services.jobs import build_result
from ..state import store


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: str, user: CurrentUser) -> dict[str, Any]:
    job = store.get_job(job_id, user_id=user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] == "completed":
        return build_result(job, user["id"])
    return {"job": serialize_job(job)}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, user: CurrentUser) -> dict[str, Any]:
    job = store.request_cancel_job(job_id, user["id"])
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": serialize_job(job)}
