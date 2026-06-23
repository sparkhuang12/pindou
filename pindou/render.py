from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .palette import BeadColor, palette_as_lookup, text_color_for_rgb
from .quantize import PatternResult


def render_pattern(
    result: PatternResult,
    palette: list[BeadColor],
    cell_size: int = 28,
    major_every: int = 5,
    title: str | None = None,
) -> Image.Image:
    lookup = palette_as_lookup(palette)
    title_text = title or f"{result.cols}x{result.rows} / {result.colors_used} colors / {result.bead_count} beads"

    font_label = _load_font(max(8, int(cell_size * 0.34)), bold=False)
    font_header = _load_font(max(9, int(cell_size * 0.36)), bold=False)
    font_title = _load_font(24, bold=True)
    font_legend = _load_font(18, bold=True)
    font_legend_small = _load_font(15, bold=False)

    left_gutter = max(34, int(cell_size * 1.35))
    right_gutter = max(30, int(cell_size * 1.15))
    header_h = max(24, int(cell_size * 0.9))
    title_h = 44
    bottom_header_h = header_h
    legend_h = _legend_height(result.counts, font_legend, cell_size, result.cols * cell_size)

    grid_w = result.cols * cell_size
    grid_h = result.rows * cell_size
    width = left_gutter + grid_w + right_gutter
    height = title_h + header_h + grid_h + bottom_header_h + legend_h

    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)

    grid_x = left_gutter
    grid_y = title_h + header_h

    draw.text((width // 2, 14), title_text, fill=(20, 20, 20), font=font_title, anchor="ma")
    _draw_headers(draw, result.cols, result.rows, cell_size, grid_x, grid_y, header_h, font_header)
    _draw_cells(draw, result.matrix, lookup, cell_size, grid_x, grid_y, font_label)
    _draw_grid(draw, result.cols, result.rows, cell_size, grid_x, grid_y, major_every)
    _draw_legend(
        draw,
        result.counts,
        palette,
        x=grid_x,
        y=grid_y + grid_h + bottom_header_h + 14,
        max_width=grid_w,
        font_code=font_legend,
        font_count=font_legend_small,
    )
    return image


def render_preview(result: PatternResult, palette: list[BeadColor], cell_size: int = 18) -> Image.Image:
    lookup = palette_as_lookup(palette)
    image = Image.new("RGB", (result.cols * cell_size, result.rows * cell_size), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for row, row_codes in enumerate(result.matrix):
        for col, code in enumerate(row_codes):
            if code is None:
                continue
            color = lookup[code].rgb
            x0 = col * cell_size
            y0 = row * cell_size
            draw.rectangle((x0, y0, x0 + cell_size, y0 + cell_size), fill=color)
    return image


def save_pattern_data(
    result: PatternResult,
    palette: list[BeadColor],
    output_json: str | Path,
    output_csv: str | Path,
    source_image: str | None = None,
) -> None:
    lookup = palette_as_lookup(palette)
    payload = {
        "source_image": source_image,
        "rows": result.rows,
        "cols": result.cols,
        "bead_count": result.bead_count,
        "colors_used": result.colors_used,
        "counts": result.counts,
        "matrix": [["" if code is None else code for code in row] for row in result.matrix],
        "palette": {
            code: {"hex": lookup[code].hex, "rgb": list(lookup[code].rgb)}
            for code in result.counts
        },
    }
    Path(output_json).write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    csv_lines = [",".join("" if code is None else code for code in row) for row in result.matrix]
    Path(output_csv).write_text("\n".join(csv_lines) + "\n", encoding="utf-8")


def save_mask(mask: np.ndarray, output_path: str | Path) -> None:
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(output_path)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _legend_height(counts: dict[str, int], font: ImageFont.ImageFont, cell_size: int, max_width: int) -> int:
    if not counts:
        return 60
    item_w = max(96, cell_size * 4)
    per_row = max(1, max_width // item_w)
    rows = (len(counts) + per_row - 1) // per_row
    return max(72, rows * 34 + 30)


def _draw_headers(
    draw: ImageDraw.ImageDraw,
    cols: int,
    rows: int,
    cell: int,
    grid_x: int,
    grid_y: int,
    header_h: int,
    font: ImageFont.ImageFont,
) -> None:
    grid_w = cols * cell
    grid_h = rows * cell
    header_fill = (226, 229, 232)
    line = (185, 190, 195)
    draw.rectangle((grid_x, grid_y - header_h, grid_x + grid_w, grid_y), fill=header_fill)
    draw.rectangle((grid_x, grid_y + grid_h, grid_x + grid_w, grid_y + grid_h + header_h), fill=header_fill)

    for col in range(cols):
        x = grid_x + col * cell
        center = x + cell / 2
        text = str(col + 1)
        draw.text((center, grid_y - header_h / 2), text, fill=(40, 40, 40), font=font, anchor="mm")
        draw.text((center, grid_y + grid_h + header_h / 2), text, fill=(40, 40, 40), font=font, anchor="mm")
        draw.line((x, grid_y - header_h, x, grid_y + grid_h + header_h), fill=line)

    left_x = grid_x - cell
    right_x = grid_x + grid_w
    draw.rectangle((left_x, grid_y, grid_x, grid_y + grid_h), fill=header_fill)
    draw.rectangle((right_x, grid_y, right_x + cell, grid_y + grid_h), fill=header_fill)
    for row in range(rows):
        y = grid_y + row * cell
        center = y + cell / 2
        text = str(row + 1)
        draw.text((left_x + cell / 2, center), text, fill=(40, 40, 40), font=font, anchor="mm")
        draw.text((right_x + cell / 2, center), text, fill=(40, 40, 40), font=font, anchor="mm")
        draw.line((left_x, y, right_x + cell, y), fill=line)


def _draw_cells(
    draw: ImageDraw.ImageDraw,
    matrix: Sequence[Sequence[str | None]],
    lookup: dict[str, BeadColor],
    cell: int,
    grid_x: int,
    grid_y: int,
    font: ImageFont.ImageFont,
) -> None:
    for row, row_codes in enumerate(matrix):
        for col, code in enumerate(row_codes):
            x0 = grid_x + col * cell
            y0 = grid_y + row * cell
            x1 = x0 + cell
            y1 = y0 + cell
            if code is None:
                draw.rectangle((x0, y0, x1, y1), fill=(255, 255, 255))
                continue
            bead = lookup[code]
            draw.rectangle((x0, y0, x1, y1), fill=bead.rgb)
            draw.text((x0 + cell / 2, y0 + cell / 2), code, fill=text_color_for_rgb(bead.rgb), font=font, anchor="mm")


def _draw_grid(
    draw: ImageDraw.ImageDraw,
    cols: int,
    rows: int,
    cell: int,
    grid_x: int,
    grid_y: int,
    major_every: int,
) -> None:
    grid_w = cols * cell
    grid_h = rows * cell
    minor = (196, 199, 203)
    major = (232, 60, 60)
    for col in range(cols + 1):
        x = grid_x + col * cell
        fill = major if major_every and col % major_every == 0 else minor
        width = 2 if fill == major else 1
        draw.line((x, grid_y, x, grid_y + grid_h), fill=fill, width=width)
    for row in range(rows + 1):
        y = grid_y + row * cell
        fill = major if major_every and row % major_every == 0 else minor
        width = 2 if fill == major else 1
        draw.line((grid_x, y, grid_x + grid_w, y), fill=fill, width=width)


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    counts: dict[str, int],
    palette: list[BeadColor],
    x: int,
    y: int,
    max_width: int,
    font_code: ImageFont.ImageFont,
    font_count: ImageFont.ImageFont,
) -> None:
    lookup = palette_as_lookup(palette)
    ordered_codes = [color.code for color in palette if color.code in counts]
    item_w = 104
    item_h = 26
    gap = 10
    cursor_x = x
    cursor_y = y
    for code in ordered_codes:
        if cursor_x + item_w > x + max_width:
            cursor_x = x
            cursor_y += item_h + gap
        bead = lookup[code]
        draw.rounded_rectangle(
            (cursor_x, cursor_y, cursor_x + item_w, cursor_y + item_h),
            radius=3,
            fill=(255, 255, 255),
            outline=(180, 180, 180),
            width=1,
        )
        draw.rectangle((cursor_x + 4, cursor_y + 4, cursor_x + 42, cursor_y + item_h - 4), fill=bead.rgb)
        draw.text((cursor_x + 23, cursor_y + item_h / 2), code, fill=text_color_for_rgb(bead.rgb), font=font_count, anchor="mm")
        draw.text((cursor_x + 58, cursor_y + item_h / 2), str(counts[code]), fill=(25, 25, 25), font=font_code, anchor="lm")
        cursor_x += item_w + gap

