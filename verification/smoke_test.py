from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pindou.cli import _parse_grid_size
from pindou.palette import load_palette
from pindou.quantize import image_to_pattern
from pindou.render import render_pattern, render_preview, save_mask, save_pattern_data
from pindou.segmentation import make_subject_mask


def main() -> int:
    artifact_dir = Path("verification/artifacts")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    input_path = artifact_dir / "synthetic_input.png"

    image = Image.new("RGB", (320, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((55, 35, 265, 255), fill=(30, 30, 30))
    draw.ellipse((105, 95, 143, 133), fill=(245, 245, 240))
    draw.ellipse((178, 95, 216, 133), fill=(245, 245, 240))
    draw.polygon([(120, 185), (160, 130), (202, 185)], fill=(255, 210, 65))
    draw.rectangle((55, 225, 265, 292), fill=(232, 65, 70))
    image.save(input_path)

    palette = load_palette()
    mask_result = make_subject_mask(image)
    pattern = image_to_pattern(image, mask_result.mask, palette, cols=36, rows=35)
    custom_pattern = image_to_pattern(image, mask_result.mask, palette, cols=24, rows=20)

    assert pattern.rows == 35
    assert pattern.cols == 36
    assert custom_pattern.rows == 20
    assert custom_pattern.cols == 24
    assert _parse_grid_size("42x31") == (42, 31)
    assert _parse_grid_size("42*31") == (42, 31)
    assert pattern.bead_count > 300
    assert pattern.colors_used >= 3

    render_pattern(pattern, palette).save(artifact_dir / "synthetic_pattern.png")
    render_preview(pattern, palette).save(artifact_dir / "synthetic_preview.png")
    save_mask(mask_result.mask, artifact_dir / "synthetic_mask.png")
    save_pattern_data(
        pattern,
        palette,
        output_json=artifact_dir / "synthetic_pattern.json",
        output_csv=artifact_dir / "synthetic_matrix.csv",
        source_image=str(input_path),
    )
    print(f"mask_method={mask_result.method}")
    print(f"beads={pattern.bead_count}")
    print(f"colors_used={pattern.colors_used}")
    print(f"artifacts={artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
