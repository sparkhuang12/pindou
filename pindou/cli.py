from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .palette import extract_palette_from_chart, load_palette, save_palette
from .quantize import image_to_pattern
from .render import render_pattern, render_preview, save_mask, save_pattern_data
from .segmentation import make_subject_mask


DEFAULT_COLS = 36
DEFAULT_ROWS = 35


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _parse_grid_size(value: str) -> tuple[int, int]:
    normalized = value.strip().lower().replace("*", "x").replace("×", "x").replace(",", "x")
    parts = normalized.split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("must use COLSxROWS, for example 50x60")
    cols = _positive_int(parts[0].strip())
    rows = _positive_int(parts[1].strip())
    return cols, rows


def _resolve_grid_size(args: argparse.Namespace) -> tuple[int, int]:
    cols, rows = args.size if args.size else (DEFAULT_COLS, DEFAULT_ROWS)
    if args.cols is not None:
        cols = args.cols
    if args.rows is not None:
        rows = args.rows
    return cols, rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pindou", description="Generate labeled pin-bead patterns from images.")
    subparsers = parser.add_subparsers(dest="command")

    generate = subparsers.add_parser("generate", help="Generate a pattern from one image.")
    generate.add_argument("image", help="Input image path.")
    generate.add_argument("--output-dir", "-o", default=None, help="Output directory. Defaults to outputs/<image-stem>.")
    generate.add_argument(
        "--size",
        type=_parse_grid_size,
        default=None,
        metavar="COLSxROWS",
        help=f"Grid size, for example 50x60 or 50*60. Defaults to {DEFAULT_COLS}x{DEFAULT_ROWS}.",
    )
    generate.add_argument("--cols", "--width", type=_positive_int, default=None, help="Grid columns; overrides --size.")
    generate.add_argument("--rows", "--height", type=_positive_int, default=None, help="Grid rows; overrides --size.")
    generate.add_argument("--palette", default=None, help="Palette JSON previously produced by extract-palette.")
    generate.add_argument("--palette-chart", default=None, help="221-color chart image to sample before quantization.")
    generate.add_argument("--coverage", type=float, default=0.32, help="Minimum foreground coverage for an occupied cell.")
    generate.add_argument("--padding", type=float, default=0.04, help="Subject padding inside the grid, 0 to 0.45.")
    generate.add_argument("--sample-size", type=int, default=14, help="Supersampling pixels per bead cell.")
    generate.add_argument("--smooth-cells", type=int, default=0, help="Binary closing iterations on occupied cells.")
    generate.add_argument("--mask-method", default="auto", choices=["auto", "alpha", "grabcut", "background"])
    generate.add_argument("--grabcut-iterations", type=int, default=5)
    generate.add_argument("--cell-size", type=int, default=28, help="Rendered output cell size in pixels.")
    generate.add_argument("--major-every", type=int, default=5, help="Major red guide line spacing.")
    generate.add_argument("--title", default=None, help="Optional title text on the pattern image.")
    generate.set_defaults(func=cmd_generate)

    extract = subparsers.add_parser("extract-palette", help="Extract a 221-code palette from a chart image.")
    extract.add_argument("chart", help="Color chart image path.")
    extract.add_argument("--output", "-o", default="palette.json", help="Output palette JSON.")
    extract.add_argument("--sample-radius", type=int, default=None, help="Sampling radius in pixels.")
    extract.set_defaults(func=cmd_extract_palette)

    list_palette = subparsers.add_parser("list-palette", help="Print the built-in palette.")
    list_palette.set_defaults(func=cmd_list_palette)
    return parser


def cmd_generate(args: argparse.Namespace) -> int:
    input_path = Path(args.image)
    output_dir = Path(args.output_dir) if args.output_dir else Path("outputs") / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    cols, rows = _resolve_grid_size(args)

    if args.palette_chart:
        palette = extract_palette_from_chart(args.palette_chart)
        save_palette(palette, output_dir / "extracted_palette.json", source=str(args.palette_chart))
    else:
        palette = load_palette(args.palette)

    image = Image.open(input_path)
    mask_result = make_subject_mask(
        image,
        method=args.mask_method,
        grabcut_iterations=args.grabcut_iterations,
    )
    pattern = image_to_pattern(
        image,
        mask_result.mask,
        palette,
        cols=cols,
        rows=rows,
        coverage_threshold=args.coverage,
        sample_size=args.sample_size,
        padding=args.padding,
        smooth_cells=args.smooth_cells,
    )

    pattern_image = render_pattern(
        pattern,
        palette,
        cell_size=args.cell_size,
        major_every=args.major_every,
        title=args.title,
    )
    preview_image = render_preview(pattern, palette, cell_size=max(8, args.cell_size // 2))

    pattern_image.save(output_dir / "pattern.png")
    preview_image.save(output_dir / "preview.png")
    save_mask(mask_result.mask, output_dir / "mask.png")
    save_pattern_data(
        pattern,
        palette,
        output_json=output_dir / "pattern.json",
        output_csv=output_dir / "matrix.csv",
        source_image=str(input_path),
    )

    print(f"Generated {pattern.cols}x{pattern.rows} pattern")
    print(f"Mask method: {mask_result.method}")
    print(f"Beads: {pattern.bead_count}")
    print(f"Colors used: {pattern.colors_used}")
    print(f"Output: {output_dir}")
    return 0


def cmd_extract_palette(args: argparse.Namespace) -> int:
    palette = extract_palette_from_chart(args.chart, sample_radius=args.sample_radius)
    save_palette(palette, args.output, source=str(args.chart))
    print(f"Extracted {len(palette)} colors to {args.output}")
    return 0


def cmd_list_palette(args: argparse.Namespace) -> int:
    for color in load_palette():
        print(f"{color.code}\t{color.hex}\t{color.rgb[0]},{color.rgb[1]},{color.rgb[2]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
