from __future__ import annotations

from dataclasses import dataclass
from collections import Counter

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import color

from .palette import BeadColor


@dataclass(frozen=True)
class PatternResult:
    matrix: list[list[str | None]]
    counts: dict[str, int]
    rows: int
    cols: int
    bead_count: int
    colors_used: int
    raster_rgb: np.ndarray
    raster_mask: np.ndarray


class PaletteMatcher:
    def __init__(self, palette: list[BeadColor]):
        self.palette = palette
        rgb = np.asarray([color_item.rgb for color_item in palette], dtype=np.float32)
        self.lab = color.rgb2lab((rgb / 255.0).reshape(-1, 1, 3)).reshape(-1, 3)
        self.codes = [color_item.code for color_item in palette]

    def nearest(self, rgb: np.ndarray) -> str:
        lab = color.rgb2lab((rgb.astype(np.float32) / 255.0).reshape(1, 1, 3)).reshape(3)
        distances = np.linalg.norm(self.lab - lab, axis=1)
        return self.codes[int(np.argmin(distances))]


def image_to_pattern(
    image: Image.Image,
    mask: np.ndarray,
    palette: list[BeadColor],
    cols: int = 36,
    rows: int = 35,
    coverage_threshold: float = 0.32,
    sample_size: int = 14,
    padding: float = 0.04,
    smooth_cells: int = 0,
) -> PatternResult:
    if cols <= 0 or rows <= 0:
        raise ValueError("rows and cols must be positive")
    if not 0.0 <= padding < 0.45:
        raise ValueError("padding must be >= 0 and < 0.45")
    if not 0.0 < coverage_threshold <= 1.0:
        raise ValueError("coverage_threshold must be > 0 and <= 1")
    if sample_size < 4:
        raise ValueError("sample_size must be at least 4")

    rgb = np.asarray(image.convert("RGB"))
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != rgb.shape[:2]:
        raise ValueError("mask shape must match image dimensions")
    if not mask.any():
        raise ValueError("mask has no foreground pixels")

    raster_rgb, raster_mask = _fit_subject_to_grid(rgb, mask, cols, rows, sample_size, padding)
    occupancy = _cell_coverage(raster_mask, rows, cols, sample_size) >= coverage_threshold
    if smooth_cells > 0:
        occupancy = _smooth_occupancy(occupancy, smooth_cells)

    matcher = PaletteMatcher(palette)
    matrix: list[list[str | None]] = []
    counts: Counter[str] = Counter()

    for row in range(rows):
        row_codes: list[str | None] = []
        for col in range(cols):
            y0 = row * sample_size
            y1 = (row + 1) * sample_size
            x0 = col * sample_size
            x1 = (col + 1) * sample_size
            if not occupancy[row, col]:
                row_codes.append(None)
                continue
            cell_mask = raster_mask[y0:y1, x0:x1]
            cell_pixels = raster_rgb[y0:y1, x0:x1][cell_mask]
            if cell_pixels.size == 0:
                row_codes.append(None)
                continue
            rgb_value = np.median(cell_pixels.reshape(-1, 3), axis=0)
            code = matcher.nearest(rgb_value)
            row_codes.append(code)
            counts[code] += 1
        matrix.append(row_codes)

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


def _fit_subject_to_grid(
    rgb: np.ndarray,
    mask: np.ndarray,
    cols: int,
    rows: int,
    sample_size: int,
    padding: float,
) -> tuple[np.ndarray, np.ndarray]:
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1

    height, width = rgb.shape[:2]
    pad_x = max(1, int(round((x1 - x0) * 0.02)))
    pad_y = max(1, int(round((y1 - y0) * 0.02)))
    x0 = max(0, x0 - pad_x)
    x1 = min(width, x1 + pad_x)
    y0 = max(0, y0 - pad_y)
    y1 = min(height, y1 + pad_y)

    crop_rgb = rgb[y0:y1, x0:x1]
    crop_mask = mask[y0:y1, x0:x1]
    crop_h, crop_w = crop_rgb.shape[:2]

    target_w = cols * sample_size
    target_h = rows * sample_size
    inner_w = max(1, int(round(target_w * (1.0 - 2.0 * padding))))
    inner_h = max(1, int(round(target_h * (1.0 - 2.0 * padding))))
    scale = min(inner_w / crop_w, inner_h / crop_h)
    resized_w = max(1, int(round(crop_w * scale)))
    resized_h = max(1, int(round(crop_h * scale)))

    crop_image = Image.fromarray(crop_rgb)
    crop_mask_image = Image.fromarray((crop_mask.astype(np.uint8) * 255))
    resized_rgb = np.asarray(crop_image.resize((resized_w, resized_h), Image.Resampling.LANCZOS))
    resized_mask = np.asarray(crop_mask_image.resize((resized_w, resized_h), Image.Resampling.NEAREST)) > 0

    canvas_rgb = np.full((target_h, target_w, 3), 255, dtype=np.uint8)
    canvas_mask = np.zeros((target_h, target_w), dtype=bool)
    left = (target_w - resized_w) // 2
    top = (target_h - resized_h) // 2
    canvas_rgb[top : top + resized_h, left : left + resized_w] = resized_rgb
    canvas_mask[top : top + resized_h, left : left + resized_w] = resized_mask
    return canvas_rgb, canvas_mask


def _cell_coverage(mask: np.ndarray, rows: int, cols: int, sample_size: int) -> np.ndarray:
    trimmed = mask[: rows * sample_size, : cols * sample_size]
    blocks = trimmed.reshape(rows, sample_size, cols, sample_size)
    return blocks.mean(axis=(1, 3))


def _smooth_occupancy(occupancy: np.ndarray, iterations: int) -> np.ndarray:
    result = occupancy.copy()
    for _ in range(iterations):
        result = ndi.binary_closing(result, structure=np.ones((3, 3), dtype=bool))
    return result

