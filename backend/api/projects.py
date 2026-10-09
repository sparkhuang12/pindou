from __future__ import annotations

import io
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from pindou.coloring import load_coloring_grid
from pindou.stylize import model_api_is_configured

from ..config import settings
from ..dependencies import CurrentUser, ensure_managed_file, get_project_or_404
from ..file_stream import file_response
from ..schemas import (
    ColoringAiPayload,
    ColoringCreatePayload,
    ColoringSavePayload,
    MaskRefinePayload,
    PatternPayload,
    ProjectRenamePayload,
    SelectionPayload,
    StylizePayload,
)
from ..serializers import serialize_project
from ..services.jobs import submit
from ..state import store


router = APIRouter(prefix="/api/projects", tags=["projects"])


async def submit_response(
    user_id: int,
    project_id: str,
    operation: str,
    payload: dict[str, Any],
    *,
    provider: str = "local",
    model_name: str = "",
) -> Response:
    try:
        body, completed = await submit(
            user_id,
            project_id,
            operation,
            payload,
            provider=provider,
            model_name=model_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="处理服务暂时失败，请稍后重试") from exc
    return JSONResponse(body, status_code=200 if completed else 202)


@router.get("")
async def list_projects(user: CurrentUser) -> dict[str, Any]:
    return {"projects": [serialize_project(project) for project in store.list_projects(user["id"])]}


@router.post("", status_code=201)
async def create_project(
    image: Annotated[UploadFile, File()],
    user: CurrentUser,
    name: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    raw = await image.read(settings.max_upload_bytes + 1)
    if not raw:
        raise HTTPException(status_code=400, detail="请选择一张图片")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="图片不能超过 20 MB")
    try:
        opened = Image.open(io.BytesIO(raw))
        if opened.width * opened.height > settings.max_image_pixels:
            raise HTTPException(status_code=413, detail="图片像素数量不能超过 4000 万")
        opened.load()
        source = ImageOps.exif_transpose(opened)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="无法读取该图片格式") from exc
    if source.width < 16 or source.height < 16:
        raise HTTPException(status_code=400, detail="图片尺寸至少为 16 x 16")
    if max(source.size) > settings.max_image_side:
        source.thumbnail((settings.max_image_side, settings.max_image_side), Image.Resampling.LANCZOS)
    source = source.convert("RGBA" if "A" in source.getbands() else "RGB")
    project_id = uuid.uuid4().hex
    project_dir = store.project_directory(user["id"], project_id)
    source_path = project_dir / "source.png"
    source.save(source_path, format="PNG", optimize=True)
    project_name = name.strip() or Path(image.filename or "").stem or "未命名拼豆图"
    try:
        project = store.create_project(
            project_id,
            user["id"],
            project_name,
            source_path,
            original_filename=Path(image.filename or "").name,
            content_type=image.content_type or "application/octet-stream",
            source_bytes=len(raw),
            source_width=source.width,
            source_height=source.height,
        )
    except ValueError as exc:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(project_dir, ignore_errors=True)
        raise
    store.record_activity(
        user_id=user["id"],
        action="project.upload",
        category="project",
        resource_type="project",
        resource_id=project_id,
        input_data={
            "filename": project.get("original_filename"),
            "content_type": project.get("content_type"),
            "upload_bytes": len(raw),
        },
        output_data={"width": source.width, "height": source.height, "source_asset": "source.png"},
    )
    return {"project": serialize_project(project)}


@router.get("/{project_id}")
async def get_project(project_id: str, user: CurrentUser) -> dict[str, Any]:
    return {"project": serialize_project(get_project_or_404(project_id, user["id"]))}


@router.patch("/{project_id}")
async def rename_project(
    project_id: str, payload: ProjectRenamePayload, user: CurrentUser
) -> dict[str, Any]:
    get_project_or_404(project_id, user["id"])
    try:
        project = store.rename_project(project_id, user["id"], payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"project": serialize_project(project)}


@router.post("/{project_id}/duplicate", status_code=201)
async def duplicate_project(project_id: str, user: CurrentUser) -> dict[str, Any]:
    try:
        project = store.duplicate_project(project_id, user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.record_activity(
        user_id=user["id"],
        action="project.duplicate",
        category="project",
        resource_type="project",
        resource_id=project["id"],
        output_data={"source_project_id": project_id},
    )
    return {"project": serialize_project(project)}


@router.delete("/{project_id}")
async def delete_project(project_id: str, user: CurrentUser) -> dict[str, bool]:
    get_project_or_404(project_id, user["id"])
    store.cancel_project_jobs(project_id, user["id"])
    deleted = store.delete_project(project_id, user["id"])
    if deleted is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project_dir = (store.projects_dir / str(user["id"]) / project_id).resolve()
    expected_parent = (store.projects_dir / str(user["id"])).resolve()
    if project_dir.parent == expected_parent and project_dir.is_dir():
        try:
            shutil.rmtree(project_dir)
        except OSError as exc:
            raise HTTPException(status_code=500, detail="项目文件删除失败") from exc
    return {"ok": True}


@router.post("/{project_id}/extract")
async def extract(project_id: str, payload: SelectionPayload, user: CurrentUser) -> Response:
    project = get_project_or_404(project_id, user["id"])
    ensure_managed_file(project, "source_path")
    return await submit_response(user["id"], project_id, "extract", payload.model_dump())


@router.post("/{project_id}/mask/refine")
async def refine_mask(
    project_id: str, payload: MaskRefinePayload, user: CurrentUser
) -> Response:
    project = get_project_or_404(project_id, user["id"])
    ensure_managed_file(project, "source_path")
    ensure_managed_file(project, "mask_path")
    if not payload.keep and not payload.remove:
        raise HTTPException(status_code=400, detail="请先添加至少一处轮廓修正")
    return await submit_response(user["id"], project_id, "refine_mask", payload.model_dump())


@router.post("/{project_id}/stylize")
async def stylize(project_id: str, payload: StylizePayload, user: CurrentUser) -> Response:
    project = get_project_or_404(project_id, user["id"])
    ensure_managed_file(project, "cutout_path")
    if payload.provider == "model" and not model_api_is_configured():
        raise HTTPException(status_code=400, detail="请先在服务端配置模型 API")
    model_name = os.environ.get("PINDOU_MODEL_NAME", "") if payload.provider == "model" else ""
    return await submit_response(
        user["id"], project_id, "stylize", payload.model_dump(),
        provider=payload.provider, model_name=model_name,
    )


@router.post("/{project_id}/coloring")
async def create_coloring(
    project_id: str, payload: ColoringCreatePayload, user: CurrentUser
) -> Response:
    project = get_project_or_404(project_id, user["id"])
    if not project.get("stylized_path") and not project.get("cutout_path"):
        raise HTTPException(status_code=400, detail="请先抠出主体，再创建上色画布")
    return await submit_response(user["id"], project_id, "create_coloring", payload.model_dump())


@router.get("/{project_id}/coloring")
async def get_coloring(project_id: str, user: CurrentUser) -> dict[str, Any]:
    project = get_project_or_404(project_id, user["id"])
    try:
        grid = load_coloring_grid(ensure_managed_file(project, "coloring_path"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="上色画布文件已损坏") from exc
    return {"coloring": grid}


@router.put("/{project_id}/coloring")
async def save_coloring(
    project_id: str, payload: ColoringSavePayload, user: CurrentUser
) -> Response:
    project = get_project_or_404(project_id, user["id"])
    ensure_managed_file(project, "coloring_path")
    return await submit_response(user["id"], project_id, "save_coloring", payload.model_dump())


@router.post("/{project_id}/coloring/ai")
async def ai_coloring(project_id: str, payload: ColoringAiPayload, user: CurrentUser) -> Response:
    if not model_api_is_configured():
        raise HTTPException(status_code=400, detail="请先在服务端配置模型 API")
    project = get_project_or_404(project_id, user["id"])
    ensure_managed_file(project, "coloring_path")
    return await submit_response(
        user["id"], project_id, "ai_coloring", payload.model_dump(),
        provider="model", model_name=os.environ.get("PINDOU_MODEL_NAME", "pixel-art-editor"),
    )


@router.post("/{project_id}/pattern")
async def pattern(project_id: str, payload: PatternPayload, user: CurrentUser) -> Response:
    project = get_project_or_404(project_id, user["id"])
    if not any(project.get(field) for field in ("painted_path", "stylized_path", "cutout_path", "source_path")):
        raise HTTPException(status_code=400, detail="没有可用于生成图纸的图片")
    return await submit_response(user["id"], project_id, "generate_pattern", payload.model_dump())


@router.get("/{project_id}/assets/{kind}", include_in_schema=False)
async def project_asset(
    project_id: str,
    kind: Literal["source", "mask", "cutout", "stylized", "painted", "pattern", "preview"],
    user: CurrentUser,
) -> Response:
    field = {
        "source": "source_path", "mask": "mask_path", "cutout": "cutout_path",
        "stylized": "stylized_path", "painted": "painted_path",
        "pattern": "pattern_path", "preview": "preview_path",
    }[kind]
    path = ensure_managed_file(get_project_or_404(project_id, user["id"]), field)
    return file_response(path, "image/png")


@router.get("/{project_id}/download/{kind}", include_in_schema=False)
async def download_artifact(
    project_id: str,
    kind: Literal["png", "json", "csv"],
    user: CurrentUser,
) -> Response:
    field, media_type, filename = {
        "png": ("pattern_path", "image/png", "pattern.png"),
        "json": ("json_path", "application/json", "pattern.json"),
        "csv": ("csv_path", "text/csv", "matrix.csv"),
    }[kind]
    path = ensure_managed_file(get_project_or_404(project_id, user["id"]), field)
    return file_response(path, media_type, filename=filename)
