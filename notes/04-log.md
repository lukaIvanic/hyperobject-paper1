# Log

Dated, newest last. Only what changed the work; recipes live in the code
docstrings, choices in `01-decisions.md`.

## 2026-09-04 — environment

Private repo `lukaIvanic/hyperobject-paper1`; the box pulls and pushes with
its own deploy key. vast.ai RTX 5090, image `pytorch/pytorch:2.8.0-cuda12.8-
cudnn9-devel`; repo at `/root/hyperobject-paper1`, data at `/root/data`.

## 2026-09-05 — box policy

A stopped instance cannot be restarted once its GPU is re-rented (happened
twice). Instances are disposable: rent when working, destroy when done; the
repo holds everything that matters; re-setup ≈ 10 min (download 37 GB ≈ 5 min,
extract 2 min, cache 30 s). Current box 49952327: RTX 5090, 48 cores, 137 GB
RAM, 600 GB disk.

## 2026-09-05 — data

Official archive: `train` 167 cube/mosaic pairs, `test-public` 11 pairs (with
ground truth), `test-private` 4 mosaics. Cube (1024, 1024, 61) float32 HWC,
wavelengths 400…1000 nm step 10; mosaic (1024, 1024) float32 in [0, 1].
Cache: `src/build_cache.py` → 46 GB of `.npy`, every file read back bit-for-bit.
Split: August manifest reused — 165 train (the 11 public-test images folded
in; `Category-3_a_0054` dropped: a sliver of the glass at the frame edge, no
table) / 12 val.

## 2026-09-05 — regions, locked

Three audit rounds by Luka over all 178 figures. Recipe in
`src/make_regions.py`, six hand-drawn polygon overrides with reasons in
`data/masks/overrides.yaml`. What the audit changed: the sheet bottom is a
per-image fitted line (tilted tabletop in Category-4 up to a_0010); convex
hull for every book (dark covers fall below the brightness threshold);
polygons for the headset, the two sunglasses and three book tops; August's
hull overrides for dark objects were dropped (they swallowed background).
Result: object 1–75 % of the frame, table 4–8 %, sheet bottom 818–850 px on
every image in the split. Data prep done.

Next: the metric study (M1–M9).
