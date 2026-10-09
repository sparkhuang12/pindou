from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from pindou.coloring import (
    DEFAULT_COLORING_PROMPT,
    coloring_to_pattern,
    create_coloring_grid,
    load_coloring_grid,
    render_coloring,
    render_line_art,
    sample_model_colors,
    save_coloring_grid,
    validate_coloring_cells,
)
from pindou.palette import BeadColor, load_palette
from pindou.quantize import image_to_pattern
from pindou.render import render_pattern, render_preview, save_mask, save_pattern_data
from pindou.segmentation import apply_mask_edits, make_subject_mask, make_subject_mask_from_box
from pindou.stylize import local_pixel_art, model_pixel_art

from ..state import store


class ProcessingError(RuntimeError):
    """A user-visible background processing failure."""


def _atomic_write(path: Path, writer: Callable[[Path], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}{path.suffix}")
    try:
        writer(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def managed_file(project: dict[str, Any], field: str) -> Path:
    value = project.get(field)
    if not value:
        raise ProcessingError("所需的项目文件尚未生成")
    path = Path(value).resolve()
    if not path.is_relative_to(store.data_dir) or not path.is_file():
        raise ProcessingError("项目文件不存在或不在受控目录中")
    return path


def select_palette(codes: list[str]) -> tuple[list[BeadColor], list[str]]:
    palette = load_palette()
    requested = list(dict.fromkeys(code.strip().upper() for code in codes if code.strip()))
    if not requested:
        return palette, []
    if any(len(code) > 8 for code in requested):
        raise ProcessingError("色号格式无效")
    known = {color.code for color in palette}
    invalid = sorted(set(requested) - known)
    if invalid:
        raise ProcessingError(f"未知色号：{', '.join(invalid[:8])}")
    allowed = set(requested)
    return [color for color in palette if color.code in allowed], requested


def persist_coloring(
    project: dict[str, Any],
    user_id: int,
    grid: dict[str, Any],
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_dir = store.project_directory(user_id, project["id"])
    coloring_path = project_dir / "coloring.json"
    painted_path = project_dir / "painted.png"
    cell_size = max(8, min(24, 960 // max(grid["cols"], grid["rows"])))
    temporary_dir = Path(tempfile.mkdtemp(prefix="coloring-", dir=project_dir))
    try:
        save_coloring_grid(grid, temporary_dir / "coloring.json")
        render_coloring(grid, cell_size=cell_size).save(
            temporary_dir / "painted.png", format="PNG", optimize=True
        )
        os.replace(temporary_dir / "coloring.json", coloring_path)
        os.replace(temporary_dir / "painted.png", painted_path)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return store.update_project(
        project["id"],
        user_id,
        status="coloring",
        coloring_path=str(coloring_path.resolve()),
        painted_path=str(painted_path.resolve()),
        pattern_path=None,
        preview_path=None,
        json_path=None,
        csv_path=None,
        settings_json=json.dumps(settings or project["settings"], ensure_ascii=False),
        bead_count=0,
        colors_used=0,
        cols=grid["cols"],
        rows=grid["rows"],
    )


def extract_subject(project: dict[str, Any], user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with Image.open(managed_file(project, "source_path")) as opened:
        image = opened.convert("RGBA")
    left = int(round(float(payload["x"]) * image.width))
    top = int(round(float(payload["y"]) * image.height))
    right = int(round((float(payload["x"]) + float(payload["width"])) * image.width))
    bottom = int(round((float(payload["y"]) + float(payload["height"])) * image.height))
    mask_result = make_subject_mask_from_box(image, (left, top, right, bottom))
    project_dir = store.project_directory(user_id, project["id"])
    mask_path = project_dir / "mask.png"
    cutout_path = project_dir / "cutout.png"
    alpha = Image.fromarray((mask_result.mask.astype(np.uint8) * 255), mode="L")
    cutout = image.copy()
    cutout.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ProcessingError("选区中没有识别到主体")
    margin = max(2, int(round(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.025)))
    crop_box = (
        max(0, bbox[0] - margin),
        max(0, bbox[1] - margin),
        min(image.width, bbox[2] + margin),
        min(image.height, bbox[3] + margin),
    )
    _atomic_write(mask_path, lambda path: save_mask(mask_result.mask, path))
    _atomic_write(
        cutout_path,
        lambda path: cutout.crop(crop_box).save(path, format="PNG", optimize=True),
    )
    selection = {
        **payload,
        "method": mask_result.method,
        "pixel_box": [left, top, right, bottom],
    }
    store.update_project(
        project["id"],
        user_id,
        status="extracted",
        mask_path=str(mask_path.resolve()),
        cutout_path=str(cutout_path.resolve()),
        stylized_path=None,
        coloring_path=None,
        painted_path=None,
        pattern_path=None,
        preview_path=None,
        json_path=None,
        csv_path=None,
        selection_json=json.dumps(selection, ensure_ascii=False),
        bead_count=0,
        colors_used=0,
    )
    return {"method": mask_result.method, "cutout_asset": "cutout.png", "crop_box": list(crop_box)}


def refine_mask(project: dict[str, Any], user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with Image.open(managed_file(project, "source_path")) as opened:
        image = opened.convert("RGBA")
    with Image.open(managed_file(project, "mask_path")) as opened:
        current_mask = np.asarray(opened.convert("L")) > 16
    keep = [
        (round(float(point["x"]) * image.width), round(float(point["y"]) * image.height))
        for point in payload.get("keep", [])
    ]
    remove = [
        (round(float(point["x"]) * image.width), round(float(point["y"]) * image.height))
        for point in payload.get("remove", [])
    ]
    mask = apply_mask_edits(current_mask, keep, remove, radius=int(payload.get("radius", 32)))
    alpha = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    cutout = image.copy()
    cutout.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox is None:
        raise ProcessingError("修正后没有识别到主体")
    margin = max(2, int(round(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.025)))
    crop_box = (
        max(0, bbox[0] - margin),
        max(0, bbox[1] - margin),
        min(image.width, bbox[2] + margin),
        min(image.height, bbox[3] + margin),
    )
    project_dir = store.project_directory(user_id, project["id"])
    mask_path = project_dir / "mask.png"
    cutout_path = project_dir / "cutout.png"
    _atomic_write(mask_path, lambda path: save_mask(mask, path))
    _atomic_write(
        cutout_path,
        lambda path: cutout.crop(crop_box).save(path, format="PNG", optimize=True),
    )
    selection = {
        **project["selection"],
        "method": "manual-refine",
        "refine": {"keep": len(keep), "remove": len(remove), "radius": int(payload["radius"])},
    }
    store.update_project(
        project["id"],
        user_id,
        status="extracted",
        mask_path=str(mask_path.resolve()),
        cutout_path=str(cutout_path.resolve()),
        stylized_path=None,
        coloring_path=None,
        painted_path=None,
        pattern_path=None,
        preview_path=None,
        json_path=None,
        csv_path=None,
        selection_json=json.dumps(selection, ensure_ascii=False),
        bead_count=0,
        colors_used=0,
    )
    return {"method": "manual-refine", "cutout_asset": "cutout.png", "crop_box": list(crop_box)}


async def stylize_subject(
    project: dict[str, Any], user_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    with Image.open(managed_file(project, "cutout_path")) as opened:
        cutout = opened.convert("RGBA")
    if payload.get("provider") == "model":
        styled = await model_pixel_art(cutout, str(payload.get("prompt", "")))
    else:
        styled = local_pixel_art(
            cutout,
            pixel_resolution=int(payload.get("pixel_resolution", 72)),
            color_count=int(payload.get("color_count", 20)),
        )
    project_dir = store.project_directory(user_id, project["id"])
    styled_path = project_dir / "stylized.png"
    _atomic_write(styled_path, lambda path: styled.save(path, format="PNG", optimize=True))
    settings = {**project["settings"], "stylize": payload}
    store.update_project(
        project["id"],
        user_id,
        status="stylized",
        stylized_path=str(styled_path.resolve()),
        coloring_path=None,
        painted_path=None,
        pattern_path=None,
        preview_path=None,
        json_path=None,
        csv_path=None,
        settings_json=json.dumps(settings, ensure_ascii=False),
        bead_count=0,
        colors_used=0,
    )
    return {"stylized_asset": "stylized.png", "width": styled.width, "height": styled.height}


def coloring_source(project: dict[str, Any], source: str) -> Path:
    if source == "stylized":
        return managed_file(project, "stylized_path")
    if source == "cutout":
        return managed_file(project, "cutout_path")
    for field in ("stylized_path", "cutout_path"):
        if project.get(field):
            return managed_file(project, field)
    raise ProcessingError("请先抠出主体，再创建上色画布")


def create_coloring(project: dict[str, Any], user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with Image.open(coloring_source(project, str(payload.get("source", "auto")))) as opened:
        image = opened.convert("RGBA")
    mask = make_subject_mask(image, method="auto").mask
    palette, requested = select_palette(list(payload.get("palette_codes", [])))
    grid = create_coloring_grid(
        image,
        mask,
        palette,
        cols=int(payload["cols"]),
        rows=int(payload["rows"]),
        coverage=float(payload["coverage"]),
        padding=float(payload["padding"]),
        smooth_cells=int(payload["smooth_cells"]),
    )
    coloring_settings = {**payload, "palette_codes": requested}
    settings = {**project["settings"], "coloring": coloring_settings}
    persist_coloring(project, user_id, grid, settings=settings)
    return {
        "cols": grid["cols"],
        "rows": grid["rows"],
        "occupied_cells": sum(sum(1 for value in row if value) for row in grid["mask"]),
        "painted_asset": "painted.png",
    }


def save_coloring(project: dict[str, Any], user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    grid = load_coloring_grid(managed_file(project, "coloring_path"))
    try:
        grid["cells"] = validate_coloring_cells(
            payload.get("cells", []), grid["mask"], rows=grid["rows"], cols=grid["cols"]
        )
    except (TypeError, ValueError) as exc:
        raise ProcessingError(f"保存上色失败：{exc}") from exc
    persist_coloring(project, user_id, grid)
    return {"saved": True, "cols": grid["cols"], "rows": grid["rows"]}


async def ai_color(project: dict[str, Any], user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    grid = load_coloring_grid(managed_file(project, "coloring_path"))
    coloring_settings = project["settings"].get("coloring", {})
    palette, _ = select_palette(
        list(payload.get("palette_codes") or coloring_settings.get("palette_codes", []))
    )
    line_art = render_line_art(grid)
    prompt = str(payload.get("prompt", "")).strip() or DEFAULT_COLORING_PROMPT
    model_result = await model_pixel_art(line_art, prompt)
    grid = sample_model_colors(model_result, grid, palette)
    persist_coloring(project, user_id, grid)
    return {"painted_asset": "painted.png", "cols": grid["cols"], "rows": grid["rows"]}


def pattern_source(project: dict[str, Any], source: str) -> Path:
    requested = {
        "painted": "painted_path",
        "stylized": "stylized_path",
        "cutout": "cutout_path",
        "original": "source_path",
    }.get(source)
    if requested:
        return managed_file(project, requested)
    for field in ("painted_path", "stylized_path", "cutout_path", "source_path"):
        if project.get(field):
            return managed_file(project, field)
    raise ProcessingError("没有可用于生成图纸的图片")


def generate_pattern(project: dict[str, Any], user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    source_path = pattern_source(project, str(payload.get("source", "auto")))
    palette, requested = select_palette(list(payload.get("palette_codes", [])))
    cols = int(payload["cols"])
    rows = int(payload["rows"])
    if source_path == Path(project.get("painted_path") or ""):
        grid = load_coloring_grid(managed_file(project, "coloring_path"))
        if cols != grid["cols"] or rows != grid["rows"]:
            raise ProcessingError("上色画布格数已固定，如需改尺寸请重新生成轮廓")
        result = coloring_to_pattern(grid, palette)
    else:
        with Image.open(source_path) as opened:
            image = opened.convert("RGBA")
        if source_path == Path(project.get("source_path") or "") and project.get("mask_path"):
            with Image.open(managed_file(project, "mask_path")) as mask_image:
                mask = np.asarray(mask_image.convert("L")) > 0
        else:
            mask = make_subject_mask(image, method="auto").mask
        result = image_to_pattern(
            image,
            mask,
            palette,
            cols=cols,
            rows=rows,
            coverage_threshold=float(payload["coverage"]),
            padding=float(payload["padding"]),
            smooth_cells=int(payload["smooth_cells"]),
        )
    project_dir = store.project_directory(user_id, project["id"])
    pattern_path = project_dir / "pattern.png"
    preview_path = project_dir / "preview.png"
    json_path = project_dir / "pattern.json"
    csv_path = project_dir / "matrix.csv"
    cell_size = max(14, min(28, 980 // max(cols, rows)))
    temporary_dir = Path(tempfile.mkdtemp(prefix="pattern-", dir=project_dir))
    try:
        render_pattern(result, palette, cell_size=cell_size, title=project["name"]).save(
            temporary_dir / "pattern.png"
        )
        render_preview(result, palette, cell_size=max(8, cell_size // 2)).save(
            temporary_dir / "preview.png"
        )
        save_pattern_data(
            result,
            palette,
            output_json=temporary_dir / "pattern.json",
            output_csv=temporary_dir / "matrix.csv",
            source_image=source_path.name,
        )
        for name, target in {
            "pattern.png": pattern_path,
            "preview.png": preview_path,
            "pattern.json": json_path,
            "matrix.csv": csv_path,
        }.items():
            os.replace(temporary_dir / name, target)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    pattern_settings = {**payload, "palette_codes": requested}
    settings = {**project["settings"], "pattern": pattern_settings}
    store.update_project(
        project["id"],
        user_id,
        status="completed",
        pattern_path=str(pattern_path.resolve()),
        preview_path=str(preview_path.resolve()),
        json_path=str(json_path.resolve()),
        csv_path=str(csv_path.resolve()),
        settings_json=json.dumps(settings, ensure_ascii=False),
        bead_count=result.bead_count,
        colors_used=result.colors_used,
        cols=result.cols,
        rows=result.rows,
    )
    return {
        "pattern_asset": "pattern.png",
        "json_asset": "pattern.json",
        "csv_asset": "matrix.csv",
        "bead_count": result.bead_count,
        "colors_used": result.colors_used,
        "counts": result.counts,
    }


async def execute_operation(job: dict[str, Any]) -> dict[str, Any]:
    user_id = int(job["user_id"])
    project_id = str(job["project_id"])
    project = store.get_project(project_id, user_id)
    if project is None:
        raise ProcessingError("项目不存在或已被删除")
    payload = dict(job.get("input") or {})
    operation = job["operation"]
    if operation == "extract":
        return extract_subject(project, user_id, payload)
    if operation == "refine_mask":
        return refine_mask(project, user_id, payload)
    if operation == "stylize":
        return await stylize_subject(project, user_id, payload)
    if operation == "create_coloring":
        return create_coloring(project, user_id, payload)
    if operation == "save_coloring":
        return save_coloring(project, user_id, payload)
    if operation == "ai_coloring":
        return await ai_color(project, user_id, payload)
    if operation == "generate_pattern":
        return generate_pattern(project, user_id, payload)
    raise ProcessingError(f"未知处理任务：{operation}")
