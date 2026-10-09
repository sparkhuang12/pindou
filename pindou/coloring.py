from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw

from .palette import BeadColor, hex_to_rgb, palette_as_lookup
from .quantize import PaletteMatcher, PatternResult, image_to_pattern


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_COLORING_PROMPT = (
    "为这张像素方格线稿上色，保持画布尺寸、主体轮廓和每个方格的位置完全不变。"
    "使用协调、清晰、适合拼豆的有限色板，不添加背景、文字、阴影特效或新物体。"
)


def create_coloring_grid(
    image: Image.Image,
    mask: np.ndarray,
    palette: list[BeadColor],
    *,
    cols: int,
    rows: int,
    coverage: float,
    padding: float,
    smooth_cells: int,
) -> dict[str, Any]:
    """Convert a cutout into a separately editable shape mask and color grid."""

    result = image_to_pattern(
        image,
        mask,
        palette,
        cols=cols,
        rows=rows,
        coverage_threshold=coverage,
        padding=padding,
        smooth_cells=smooth_cells,
    )
    lookup = palette_as_lookup(palette)
    shape = [[code is not None for code in row] for row in result.matrix]
    cells = [
        [lookup[code].hex if code is not None else None for code in row]
        for row in result.matrix
    ]
    return {
        "version": 1,
        "cols": cols,
        "rows": rows,
        "mask": shape,
        "cells": cells,
    }


def validate_coloring_cells(
    cells: Sequence[Sequence[str | None]],
    mask: Sequence[Sequence[bool]],
    *,
    rows: int,
    cols: int,
) -> list[list[str | None]]:
    if len(cells) != rows or len(mask) != rows:
        raise ValueError("上色矩阵高度与轮廓不一致")

    clean: list[list[str | None]] = []
    for row_index in range(rows):
        if len(cells[row_index]) != cols or len(mask[row_index]) != cols:
            raise ValueError("上色矩阵宽度与轮廓不一致")
        clean_row: list[str | None] = []
        for col_index, value in enumerate(cells[row_index]):
            if not mask[row_index][col_index]:
                clean_row.append(None)
                continue
            if value is None or value == "":
                clean_row.append(None)
                continue
            normalized = str(value).strip().lower()
            if not HEX_COLOR.fullmatch(normalized):
                raise ValueError(f"第 {row_index + 1} 行第 {col_index + 1} 格颜色无效")
            clean_row.append(normalized)
        clean.append(clean_row)
    return clean


def save_coloring_grid(grid: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(grid, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")


def load_coloring_grid(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("上色文件格式无效")
    rows = int(data.get("rows", 0))
    cols = int(data.get("cols", 0))
    if not 8 <= rows <= 100 or not 8 <= cols <= 100:
        raise ValueError("上色文件格数无效")
    mask = data.get("mask")
    cells = data.get("cells")
    if not isinstance(mask, list) or not isinstance(cells, list):
        raise ValueError("上色文件缺少矩阵")
    clean_mask = _validate_mask(mask, rows=rows, cols=cols)
    clean_cells = validate_coloring_cells(cells, clean_mask, rows=rows, cols=cols)
    return {
        "version": 1,
        "cols": cols,
        "rows": rows,
        "mask": clean_mask,
        "cells": clean_cells,
    }


def render_coloring(grid: dict[str, Any], cell_size: int = 16) -> Image.Image:
    rows = int(grid["rows"])
    cols = int(grid["cols"])
    cell = max(4, min(32, int(cell_size)))
    image = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for row in range(rows):
        for col in range(cols):
            value = grid["cells"][row][col]
            if value is None:
                continue
            x0 = col * cell
            y0 = row * cell
            draw.rectangle((x0, y0, x0 + cell - 1, y0 + cell - 1), fill=hex_to_rgb(value) + (255,))
    return image


def render_line_art(grid: dict[str, Any], cell_size: int = 16) -> Image.Image:
    """Render a model-friendly white shape with dark cell and silhouette lines."""

    rows = int(grid["rows"])
    cols = int(grid["cols"])
    cell = max(6, min(32, int(cell_size)))
    image = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    mask = grid["mask"]
    minor = (197, 194, 199, 255)
    outline = (42, 38, 45, 255)
    for row in range(rows):
        for col in range(cols):
            if not mask[row][col]:
                continue
            x0 = col * cell
            y0 = row * cell
            x1 = x0 + cell - 1
            y1 = y0 + cell - 1
            draw.rectangle((x0, y0, x1, y1), fill=(248, 246, 242, 255), outline=minor, width=1)
            if row == 0 or not mask[row - 1][col]:
                draw.line((x0, y0, x1, y0), fill=outline, width=2)
            if row == rows - 1 or not mask[row + 1][col]:
                draw.line((x0, y1, x1, y1), fill=outline, width=2)
            if col == 0 or not mask[row][col - 1]:
                draw.line((x0, y0, x0, y1), fill=outline, width=2)
            if col == cols - 1 or not mask[row][col + 1]:
                draw.line((x1, y0, x1, y1), fill=outline, width=2)
    return image


def sample_model_colors(
    model_image: Image.Image,
    grid: dict[str, Any],
    palette: list[BeadColor],
) -> dict[str, Any]:
    """Take only colors from a model result while retaining the saved shape."""

    rows = int(grid["rows"])
    cols = int(grid["cols"])
    sampled = np.asarray(model_image.convert("RGB").resize((cols, rows), Image.Resampling.LANCZOS))
    matcher = PaletteMatcher(palette)
    lookup = palette_as_lookup(palette)
    cells: list[list[str | None]] = []
    for row in range(rows):
        values: list[str | None] = []
        for col in range(cols):
            if not grid["mask"][row][col]:
                values.append(None)
                continue
            code = matcher.nearest(sampled[row, col])
            values.append(lookup[code].hex)
        cells.append(values)
    return {**grid, "cells": cells}


def coloring_to_pattern(grid: dict[str, Any], palette: list[BeadColor]) -> PatternResult:
    rows = int(grid["rows"])
    cols = int(grid["cols"])
    matcher = PaletteMatcher(palette)
    lookup = palette_as_lookup(palette)
    counts: Counter[str] = Counter()
    matrix: list[list[str | None]] = []
    raster_rgb = np.full((rows, cols, 3), 255, dtype=np.uint8)
    raster_mask = np.zeros((rows, cols), dtype=bool)

    for row in range(rows):
        code_row: list[str | None] = []
        for col in range(cols):
            value = grid["cells"][row][col]
            if value is None or not grid["mask"][row][col]:
                code_row.append(None)
                continue
            code = matcher.nearest(np.asarray(hex_to_rgb(value), dtype=np.uint8))
            code_row.append(code)
            counts[code] += 1
            raster_mask[row, col] = True
            raster_rgb[row, col] = lookup[code].rgb
        matrix.append(code_row)

    if not counts:
        raise ValueError("上色画布还是空的，请先涂上颜色")
    return PatternResult(
        matrix=matrix,
        counts=dict(sorted(counts.items())),
        rows=rows,
        cols=cols,
        bead_count=sum(counts.values()),
        colors_used=len(counts),
        raster_rgb=raster_rgb,
        raster_mask=raster_mask,
    )


def _validate_mask(mask: Sequence[Sequence[Any]], *, rows: int, cols: int) -> list[list[bool]]:
    if len(mask) != rows:
        raise ValueError("轮廓矩阵高度无效")
    clean: list[list[bool]] = []
    for row in mask:
        if not isinstance(row, list) or len(row) != cols:
            raise ValueError("轮廓矩阵宽度无效")
        clean.append([bool(value) for value in row])
    if not any(any(row) for row in clean):
        raise ValueError("轮廓中没有可上色方格")
    return clean
