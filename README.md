# Pindou Pattern Generator

This project converts one input image into a labeled pin-bead pattern like the
reference grid:

- Detect the main subject.
- Crop and fit it into a configurable bead grid, default `36x35`.
- Quantize every occupied cell to a `221` color code palette.
- Render a numbered pattern image with cell labels and a legend.
- Export machine-readable `JSON` and `CSV` matrices.

The built-in palette is an approximate `A/B/C/D/E/F/G/H/M` 221-color set based
on the supplied chart layout. For best color matching, pass the actual color
chart image with `--palette-chart`; the CLI will sample the swatches and use
those measured colors.

## Quick Start

```bash
python3 -m pindou generate input.png --output-dir outputs/demo
```

Typical output files:

- `pattern.png`: final labeled grid.
- `preview.png`: color-only bead preview.
- `mask.png`: extracted subject mask.
- `matrix.csv`: bead code matrix, blank cells empty.
- `pattern.json`: matrix, counts, and palette metadata.

## Use the supplied 221-color chart

If you have the chart image from the prompt saved locally:

```bash
python3 -m pindou generate input.png \
  --palette-chart color_chart.jpg \
  --output-dir outputs/demo
```

You can also extract only the palette:

```bash
python3 -m pindou extract-palette color_chart.jpg --output palette.json
```

Then reuse it:

```bash
python3 -m pindou generate input.png --palette palette.json
```

## Useful Options

```bash
python3 -m pindou generate input.png \
  --size 50x60 \
  --coverage 0.32 \
  --padding 0.04 \
  --sample-size 14 \
  --mask-method auto \
  --cell-size 28 \
  --output-dir outputs/demo
```

- `--size`: output grid size in `columns x rows` format. `50x60`,
  `50*60`, and `50,60` are accepted.
- `--cols` / `--width`: override only the grid columns.
- `--rows` / `--height`: override only the grid rows.
- `--coverage`: lower values keep more edge cells; higher values make cleaner
  edges.
- `--sample-size`: supersampling per bead cell. Larger values reduce edge
  aliasing at the cost of speed.
- `--padding`: subject margin inside the grid.
- `--mask-method`: `auto`, `alpha`, `grabcut`, or `background`.

## Notes

The default pipeline avoids downloading large segmentation models so it can run
offline. It uses alpha masks when available, otherwise OpenCV GrabCut initialized
with background estimation, then keeps the largest foreground component. For
busy backgrounds, supply an image with transparent background or adjust
`--coverage` and `--padding`.
