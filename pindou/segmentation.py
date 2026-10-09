from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import color, filters, measure, morphology


@dataclass(frozen=True)
class MaskResult:
    mask: np.ndarray
    method: str


def make_subject_mask(
    image: Image.Image,
    method: str = "auto",
    grabcut_iterations: int = 5,
    max_processing_side: int = 1000,
) -> MaskResult:
    method = method.lower()
    if method not in {"auto", "alpha", "grabcut", "background"}:
        raise ValueError("method must be one of: auto, alpha, grabcut, background")

    if method in {"auto", "alpha"}:
        alpha = _alpha_mask(image)
        if alpha is not None and alpha.mean() < 0.98:
            return MaskResult(mask=_clean_mask(alpha), method="alpha")
        if method == "alpha":
            raise ValueError("Image does not contain a usable alpha channel")

    rgb = np.asarray(image.convert("RGB"))

    if method in {"auto", "grabcut"}:
        try:
            mask = _grabcut_mask(rgb, grabcut_iterations, max_processing_side)
            if mask.sum() > 0:
                return MaskResult(mask=_clean_mask(mask), method="grabcut")
        except cv2.error:
            if method == "grabcut":
                raise

    mask = _background_difference_mask(rgb)
    return MaskResult(mask=_clean_mask(mask), method="background")


def make_subject_mask_from_box(
    image: Image.Image,
    box: tuple[int, int, int, int],
    grabcut_iterations: int = 6,
    max_processing_side: int = 1400,
) -> MaskResult:
    """Extract a foreground object using a user-drawn bounding box.

    ``box`` uses Pillow coordinates: ``(left, top, right, bottom)``. Pixels
    outside the box are treated as definite background while GrabCut refines
    the foreground inside it. This mirrors the rectangular selection workflow
    used by desktop image editors and produces a full-resolution mask.
    """

    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    left, top, right, bottom = [int(value) for value in box]
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))

    if right - left < 3 or bottom - top < 3:
        raise ValueError("Selection must be at least 3 pixels wide and high")

    small, scale = _resize_for_processing(rgb, max_processing_side)
    scaled_left = int(round(left * scale))
    scaled_top = int(round(top * scale))
    scaled_right = int(round(right * scale))
    scaled_bottom = int(round(bottom * scale))
    small_height, small_width = small.shape[:2]

    scaled_left = max(0, min(scaled_left, small_width - 2))
    scaled_top = max(0, min(scaled_top, small_height - 2))
    scaled_right = max(scaled_left + 2, min(scaled_right, small_width))
    scaled_bottom = max(scaled_top + 2, min(scaled_bottom, small_height))
    rect = (
        scaled_left,
        scaled_top,
        scaled_right - scaled_left,
        scaled_bottom - scaled_top,
    )

    mask = np.zeros((small_height, small_width), dtype=np.uint8)
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    try:
        cv2.grabCut(
            bgr,
            mask,
            rect,
            bgd_model,
            fgd_model,
            grabcut_iterations,
            cv2.GC_INIT_WITH_RECT,
        )
    except cv2.error:
        fallback = _background_difference_mask(rgb)
        selection_mask = np.zeros((height, width), dtype=bool)
        selection_mask[top:bottom, left:right] = True
        cleaned_fallback = _clean_mask(fallback & selection_mask)
        if cleaned_fallback.any():
            return MaskResult(mask=cleaned_fallback, method="selection-background")
        return MaskResult(mask=selection_mask, method="selection-box")
    result = np.logical_or(mask == cv2.GC_FGD, mask == cv2.GC_PR_FGD)

    if scale < 1.0:
        result = cv2.resize(
            result.astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        ) > 0

    # GrabCut can occasionally keep a disconnected background island. The
    # existing cleanup keeps the largest coherent subject and fills pinholes.
    cleaned = _clean_mask(result)
    if not cleaned.any():
        # A simple rectangular mask is a predictable fallback for very flat or
        # low-contrast images where GrabCut cannot infer a foreground model.
        cleaned = np.zeros((height, width), dtype=bool)
        cleaned[top:bottom, left:right] = True
        return MaskResult(mask=cleaned, method="selection-box")
    return MaskResult(mask=cleaned, method="selection-grabcut")


def apply_mask_edits(
    mask: np.ndarray,
    keep_points: list[tuple[int, int]],
    remove_points: list[tuple[int, int]],
    *,
    radius: int = 32,
) -> np.ndarray:
    """Apply user brush edits to a full-resolution boolean subject mask."""
    result = np.asarray(mask, dtype=bool)
    if result.ndim != 2:
        raise ValueError("mask must be a two-dimensional array")
    if radius < 2 or radius > 256:
        raise ValueError("brush radius must be between 2 and 256 pixels")
    height, width = result.shape
    editable = result.astype(np.uint8, copy=True)
    for x, y in keep_points:
        if 0 <= x < width and 0 <= y < height:
            cv2.circle(editable, (int(x), int(y)), radius, 1, thickness=-1)
    for x, y in remove_points:
        if 0 <= x < width and 0 <= y < height:
            cv2.circle(editable, (int(x), int(y)), radius, 0, thickness=-1)
    result = editable.astype(bool)
    if not result.any():
        raise ValueError("修正后没有保留任何主体区域")
    return result


def _alpha_mask(image: Image.Image) -> np.ndarray | None:
    if image.mode not in {"RGBA", "LA"} and "transparency" not in image.info:
        return None
    alpha = np.asarray(image.convert("RGBA"))[:, :, 3]
    return alpha > 16


def _resize_for_processing(rgb: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    height, width = rgb.shape[:2]
    scale = min(1.0, max_side / float(max(height, width)))
    if scale >= 1.0:
        return rgb, 1.0
    resized = cv2.resize(rgb, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA)
    return resized, scale


def _grabcut_mask(rgb: np.ndarray, iterations: int, max_side: int) -> np.ndarray:
    small, scale = _resize_for_processing(rgb, max_side)
    height, width = small.shape[:2]
    bg_seed = _background_difference_mask(small)

    mask = np.full((height, width), cv2.GC_PR_BGD, dtype=np.uint8)
    border = max(3, int(round(min(height, width) * 0.035)))
    mask[:border, :] = cv2.GC_BGD
    mask[-border:, :] = cv2.GC_BGD
    mask[:, :border] = cv2.GC_BGD
    mask[:, -border:] = cv2.GC_BGD

    if bg_seed.mean() > 0.005:
        mask[bg_seed] = cv2.GC_PR_FGD
        confident_fg = morphology.binary_erosion(bg_seed, morphology.disk(max(1, border // 2)))
        mask[confident_fg] = cv2.GC_FGD
    else:
        mx = max(1, int(round(width * 0.08)))
        my = max(1, int(round(height * 0.08)))
        mask[my : height - my, mx : width - mx] = cv2.GC_PR_FGD

    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)
    bgr = cv2.cvtColor(small, cv2.COLOR_RGB2BGR)
    cv2.grabCut(bgr, mask, None, bgd_model, fgd_model, iterations, cv2.GC_INIT_WITH_MASK)

    result = np.logical_or(mask == cv2.GC_FGD, mask == cv2.GC_PR_FGD)
    if scale < 1.0:
        original_h, original_w = rgb.shape[:2]
        result = cv2.resize(result.astype(np.uint8), (original_w, original_h), interpolation=cv2.INTER_NEAREST) > 0
    return result


def _background_difference_mask(rgb: np.ndarray) -> np.ndarray:
    height, width = rgb.shape[:2]
    border = max(2, int(round(min(height, width) * 0.04)))
    border_pixels = np.concatenate(
        [
            rgb[:border, :, :].reshape(-1, 3),
            rgb[-border:, :, :].reshape(-1, 3),
            rgb[:, :border, :].reshape(-1, 3),
            rgb[:, -border:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    lab = color.rgb2lab(rgb / 255.0)
    bg_lab = color.rgb2lab(np.median(border_pixels, axis=0).reshape(1, 1, 3) / 255.0)[0, 0]
    distance = np.linalg.norm(lab - bg_lab, axis=2)

    try:
        threshold = float(filters.threshold_otsu(distance))
    except ValueError:
        threshold = 12.0
    threshold = max(10.0, min(threshold, 32.0))
    mask = distance > threshold

    # If the background is near white, low-saturation foreground can be missed.
    gray = color.rgb2gray(rgb / 255.0)
    try:
        gray_threshold = float(filters.threshold_otsu(gray))
        if np.median(border_pixels) > 210:
            mask |= gray < max(0.08, gray_threshold - 0.08)
    except ValueError:
        pass
    return mask


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    if mask.size == 0 or not mask.any():
        return mask

    area = mask.size
    min_size = max(12, int(area * 0.0007))
    close_radius = max(1, int(round(min(mask.shape) * 0.004)))

    mask = morphology.remove_small_objects(mask, min_size=min_size)
    mask = morphology.binary_closing(mask, morphology.disk(close_radius))
    mask = ndi.binary_fill_holes(mask)
    mask = _largest_component(mask)
    mask = morphology.remove_small_holes(mask, area_threshold=max(32, int(area * 0.0008)))
    return mask.astype(bool)


def _largest_component(mask: np.ndarray) -> np.ndarray:
    labels = measure.label(mask, connectivity=2)
    if labels.max() == 0:
        return mask
    regions = measure.regionprops(labels)
    largest = max(regions, key=lambda region: region.area)
    return labels == largest.label
