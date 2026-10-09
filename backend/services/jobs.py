from __future__ import annotations

import os
import socket
import time
import asyncio
import contextlib
from typing import Any

from pindou.coloring import load_coloring_grid

from ..config import settings
from ..serializers import serialize_job, serialize_project
from ..state import store
from .processing import ProcessingError, execute_operation, managed_file


def enqueue(
    user_id: int,
    project_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    provider: str = "local",
    model_name: str = "",
) -> dict[str, Any]:
    job_id = store.enqueue_job(
        user_id,
        project_id,
        operation,
        provider=provider,
        model_name=model_name,
        input_data=payload,
    )
    return store.get_job(job_id, user_id=user_id) or {}


async def execute_job(job: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    heartbeat_task = asyncio.create_task(_heartbeat(job))
    try:
        if store.is_job_cancel_requested(job["id"]):
            raise ProcessingError("用户已取消任务")
        output = await execute_operation(job)
        if store.is_job_cancel_requested(job["id"]):
            raise ProcessingError("用户已取消任务")
    except Exception as exc:
        public_error = (
            str(exc) if isinstance(exc, ProcessingError) else "处理服务暂时失败，请稍后重试"
        )
        store.finish_job(
            job["id"],
            status="failed",
            error_message=public_error,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        raise
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
    store.finish_job(
        job["id"],
        status="completed",
        output_data=output,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return store.get_job(job["id"]) or job


async def submit(
    user_id: int,
    project_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    provider: str = "local",
    model_name: str = "",
) -> tuple[dict[str, Any], bool]:
    job = enqueue(
        user_id,
        project_id,
        operation,
        payload,
        provider=provider,
        model_name=model_name,
    )
    if settings.task_mode == "eager":
        claimed = store.claim_job(job["id"], f"eager:{os.getpid()}")
        if claimed is None:
            raise RuntimeError("无法抢占刚创建的本地任务")
        job = await execute_job(claimed)
        return build_result(job, user_id), True
    return {"job": serialize_job(job)}, False


def build_result(job: dict[str, Any], user_id: int) -> dict[str, Any]:
    result: dict[str, Any] = {"job": serialize_job(job)}
    project_id = job.get("project_id")
    project = store.get_project(str(project_id), user_id) if project_id else None
    if project is not None:
        result["project"] = serialize_project(project)
        if job["operation"] in {"create_coloring", "save_coloring", "ai_coloring"} and project.get("coloring_path"):
            result["coloring"] = load_coloring_grid(managed_file(project, "coloring_path"))
    if job["operation"] == "generate_pattern":
        result["counts"] = job.get("output", {}).get("counts", {})
    return result


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def _heartbeat(job: dict[str, Any]) -> None:
    worker_id = str(job.get("worker_id") or "")
    if not worker_id:
        return
    interval = max(5.0, min(30.0, settings.worker_stale_seconds / 3))
    while True:
        await asyncio.sleep(interval)
        store.touch_job(job["id"], worker_id)
