from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


FAMILY_COUNTS: dict[str, int] = {
    "A": 26,
    "B": 32,
    "C": 29,
    "D": 26,
    "E": 24,
    "F": 25,
    "G": 21,
    "H": 23,
    "M": 15,
}


# Approximate RGB palette matching the visible 221-code chart families.
# Use --palette-chart with the real chart image when exact swatch sampling is
# required.
FAMILY_HEX: dict[str, list[str]] = {
    "A": [
        "#fff7bf", "#fff1a1", "#fff268", "#ffe84a", "#f7dc35", "#ffaf45",
        "#ff854d", "#ffdf4d", "#ff944f", "#ff6f2f", "#ffe0a5", "#ff9c73",
        "#ffd985", "#ee4640", "#fff58a", "#fff4c2", "#ffdf56", "#ffb67a",
        "#ff7e74", "#ffe877", "#ffe79c", "#efff73", "#d7b69c", "#ffd98d",
        "#ffbf3f", "#ffc735",
    ],
    "B": [
        "#e7f51b", "#53e84d", "#9be95a", "#5fde37", "#32d952", "#65d8aa",
        "#2da678", "#159858", "#124f3d", "#9ed2ca", "#556624", "#0f6f56",
        "#b9e455", "#9df13f", "#244d36", "#a6e5b4", "#879826", "#f3fa29",
        "#25bfa0", "#bfe8cd", "#126878", "#0e5963", "#263e25", "#eff9a7",
        "#4d8074", "#7f7425", "#bfe8b2", "#7fdfc8", "#b4e744", "#d6f7af",
        "#9edc7d", "#9aa64a",
    ],
    "C": [
        "#d6f8f4", "#82e5e7", "#8eddec", "#4bc1dc", "#04add2", "#56a9dc",
        "#2b7ac2", "#1264c8", "#0a5199", "#0c9cbb", "#17c6c6", "#0b2e43",
        "#c4e2e5", "#e6fbfb", "#22a8a0", "#0b3f8e", "#18d7d7", "#133e47",
        "#087b91", "#236c9c", "#d4e9f0", "#a8d0dc", "#c9e4ec", "#69b7e1",
        "#b2e7de", "#2ba4be", "#c9e7ed", "#b5d7df", "#253b91",
    ],
    "D": [
        "#a4aceb", "#7787d4", "#355ba8", "#213f90", "#b536ca", "#9768d6",
        "#7944b5", "#d8c3f1", "#c7a8ea", "#24163f", "#9aa5d6", "#e382ce",
        "#be00a5", "#8733b4", "#2b2f93", "#ecebf1", "#b7c8e9", "#9b4cc3",
        "#cbc0c7", "#9b2aa5", "#a700b0", "#323a9f", "#ddd3ee", "#7182df",
        "#4054c7", "#d1b7f4",
    ],
    "E": [
        "#ffd4d7", "#ff9db8", "#f664a4", "#e94b93", "#e33b79", "#e94369",
        "#98213c", "#ffe0e5", "#e755a2", "#d01972", "#ffd4cc", "#ff91b7",
        "#9b003a", "#ffd9ca", "#ffd5d5", "#fff0eb", "#ffd5d4", "#ffd8dc",
        "#ffd8d1", "#e5d1cf", "#cfb2ae", "#caa5b2", "#866879", "#bd8bb6",
    ],
    "F": [
        "#ff8a70", "#fb353e", "#f83b43", "#ed213e", "#e90034", "#9a302c",
        "#a91636", "#c41136", "#e9677a", "#8c4319", "#4d1e1a", "#ff4d62",
        "#fb6d56", "#ffd6d8", "#ab0034", "#ffc8ae", "#e48766", "#ce7541",
        "#bd344d", "#c79791", "#f4b1c6", "#f7bbce", "#ff725d", "#e999a7",
        "#ee4449",
    ],
    "G": [
        "#ffe4d0", "#ffc4a7", "#f8b08b", "#c67a38", "#f4ba39", "#e9971a",
        "#8e4d2d", "#6b2d2d", "#e7a74d", "#b96613", "#6b3b19", "#b6752a",
        "#9b5624", "#7c3e2d", "#fff5dd", "#f5ddb0", "#673229", "#f2c188",
        "#d65a1f", "#a34920", "#b7864f",
    ],
    "H": [
        "#ffffff", "#f7f7f5", "#aaa9ad", "#88868b", "#404049", "#242225",
        "#050505", "#e8d8dd", "#ededed", "#f6f2e8", "#d8dde6", "#fff3d9",
        "#f3ead3", "#d8e1df", "#58626b", "#111111", "#f0eeeb", "#f9f8f3",
        "#eee7dc", "#b7c6c7", "#d8dfd5", "#d3d2cb", "#747c76",
    ],
    "M": [
        "#a7b2a5", "#80947f", "#526665", "#eadfc9", "#d0ccb8", "#a7a478",
        "#9c8c78", "#b87882", "#9b7d54", "#b5a3a6", "#8e6384", "#4a2e2a",
        "#ba744b", "#b8675c", "#626b68",
    ],
}


CHART_X_RATIOS: dict[str, float] = {
    "A": 0.075,
    "B": 0.181,
    "C": 0.288,
    "D": 0.394,
    "E": 0.501,
    "F": 0.607,
    "G": 0.713,
    "H": 0.819,
    "M": 0.925,
}
CHART_TOP_Y_RATIO = 178.0 / 1380.0
CHART_STEP_Y_RATIO = 39.0 / 1380.0


@dataclass(frozen=True)
class BeadColor:
    code: str
    hex: str
    rgb: tuple[int, int, int]
    family: str


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid hex color: {value!r}")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: Iterable[int]) -> str:
    r, g, b = [int(round(v)) for v in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def build_default_palette() -> list[BeadColor]:
    palette: list[BeadColor] = []
    for family, count in FAMILY_COUNTS.items():
        colors = FAMILY_HEX[family]
        if len(colors) != count:
            raise ValueError(f"Family {family} has {len(colors)} colors, expected {count}")
        for idx, hex_value in enumerate(colors, start=1):
            palette.append(
                BeadColor(
                    code=f"{family}{idx}",
                    hex=hex_value.lower(),
                    rgb=hex_to_rgb(hex_value),
                    family=family,
                )
            )
    if len(palette) != 221:
        raise ValueError(f"Default palette has {len(palette)} colors, expected 221")
    return palette


def load_palette(path: str | Path | None = None) -> list[BeadColor]:
    if path is None:
        return build_default_palette()

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("colors", [])
    else:
        items = data

    palette: list[BeadColor] = []
    for item in items:
        code = str(item["code"])
        hex_value = str(item["hex"]).lower()
        palette.append(
            BeadColor(
                code=code,
                hex=hex_value,
                rgb=hex_to_rgb(hex_value),
                family=code[0],
            )
        )
    validate_palette(palette)
    return palette


def validate_palette(palette: list[BeadColor]) -> None:
    codes = [color.code for color in palette]
    if len(codes) != len(set(codes)):
        raise ValueError("Palette contains duplicate bead codes")
    expected = [f"{family}{idx}" for family, count in FAMILY_COUNTS.items() for idx in range(1, count + 1)]
    missing = sorted(set(expected) - set(codes))
    if missing:
        raise ValueError(f"Palette is missing codes: {', '.join(missing[:10])}")


def save_palette(palette: list[BeadColor], path: str | Path, source: str | None = None) -> None:
    payload = {
        "source": source or "custom",
        "colors": [
            {"code": color.code, "hex": color.hex, "rgb": list(color.rgb), "family": color.family}
            for color in palette
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def extract_palette_from_chart(chart_path: str | Path, sample_radius: int | None = None) -> list[BeadColor]:
    """Sample a standard 221-color chart image.

    The supplied chart has stable family columns and row spacing. This function
    samples each swatch near its center and uses the median color, which is
    robust against the printed black label text.
    """

    image = Image.open(chart_path).convert("RGB")
    arr = np.asarray(image)
    height, width = arr.shape[:2]
    radius = sample_radius or max(5, int(min(width, height) * 0.008))

    colors: list[BeadColor] = []
    for family, count in FAMILY_COUNTS.items():
        x = int(round(CHART_X_RATIOS[family] * width))
        for idx in range(1, count + 1):
            y = int(round((CHART_TOP_Y_RATIO + CHART_STEP_Y_RATIO * (idx - 1)) * height))
            x0 = max(0, x - radius)
            x1 = min(width, x + radius + 1)
            y0 = max(0, y - radius)
            y1 = min(height, y + radius + 1)
            patch = arr[y0:y1, x0:x1, :].reshape(-1, 3)

            # Drop very dark label pixels when possible. For black swatches,
            # keep all pixels so the median remains near black.
            luminance = 0.2126 * patch[:, 0] + 0.7152 * patch[:, 1] + 0.0722 * patch[:, 2]
            if np.median(luminance) > 60:
                patch = patch[luminance > 30]
            rgb = tuple(int(v) for v in np.median(patch, axis=0))
            colors.append(BeadColor(code=f"{family}{idx}", hex=rgb_to_hex(rgb), rgb=rgb, family=family))

    validate_palette(colors)
    return colors


def palette_as_lookup(palette: list[BeadColor]) -> dict[str, BeadColor]:
    return {color.code: color for color in palette}


def text_color_for_rgb(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b = [v / 255.0 for v in rgb]
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (255, 255, 255) if luminance < 0.42 else (18, 18, 18)

