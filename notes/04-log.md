# Running log

Dated entries, newest last. What was done, what was found, what changed.

## 2026-09-04 — environment

- Private GitHub repo `lukaIvanic/hyperobject-paper1` created; Mac pushes,
  box pulls/pushes with its own deploy key (read-write, revocable on GitHub).
- vast.ai instance 49861988 rented: RTX 5090 32 GB, 128 cores, 251 GB RAM,
  600 GB disk (measured 3.8 GB/s write, 4.3 GB/s read), Utah, ≈$0.82/h.
  Image `pytorch/pytorch:2.8.0-cuda12.8-cudnn9-devel`, torch 2.8.0+cu128.
  A first attempt on another host (49859256) never provisioned and was
  destroyed.
- Repo cloned to `/root/hyperobject-paper1`; data root `/root/data`.
- Next: Kaggle token on the box → download the official archive → extract
  → build the per-image `.npy` cache → `02-provenance.md` as code is ported.

## 2026-09-04 — data on the box

- Official archive downloaded with the Kaggle API: 37.1 GB in 281 s
  (≈132 MB/s), `/root/data/track1.zip`. Extracted in 182 s to `/root/data/raw/`.
- Layout: `train/{hsi_61,mosaic}` 167 pairs (34 GB of HDF5); `test-public/
  {hsi_61,mosaic}` 11 pairs (ground truth included); `test-private/mosaic`
  4 mosaics, no ground truth. So 178 cubes, 182 mosaics.
- Formats: cube `.h5` with datasets `cube` (1024, 1024, 61) float32 HWC and
  `wavelengths` (61,) float32; mosaic `.npy` (1024, 1024) float32 in [0, 1].
- Next: `src/build_cache.py` — one uncompressed `.npy` per cube (HWC
  contiguous, so it pins zero-copy as a channels-last tensor), verified
  against the HDF5 read; then regions and split.

## 2026-09-05 — box lost and re-created

- Restarting the stopped instance 49861988 failed: its GPU had been rented
  by someone else in the meantime ("required resources unavailable",
  queued indefinitely). Same failure mode as the August box. Lesson:
  vast.ai keeps the disk on stop, not the GPU. Policy from now on:
  instances are disposable — rent when working, destroy when done; the
  repo holds everything that matters; re-setup is ≈10 min.
- New instance 49952327 (California): RTX 5090, 48 cores, 137 GB RAM,
  600 GB disk (1.2 GB/s write, 390 MB/s read), ≈$0.72/h. New deploy key;
  the old key was removed from GitHub; the old instance was destroyed
  after the data was verified here.
- Data re-downloaded (37.1 GB in 315 s) and extracted (116 s). Verified:
  167 + 11 cubes, 167 + 11 + 4 mosaics, cube (1024, 1024, 61) float32,
  wavelengths 400…1000 nm — identical to yesterday.
- Cache built with `src/build_cache.py`: 178 cubes + 182 mosaics → 46.3 GB
  in 28 s wall (4.4 s per cube in-worker, 32 workers); every file read back
  and compared bit-for-bit. Disk at 116 GB of 600 used.
- Split manifests copied from August (`data/split/`): 166 train incl. the 11
  public-test images, 12 val (1 apple, 1 glass, 5 books, 5 misc).
- Regions built with `src/make_regions.py` (26 s for 178 images): object =
  brightness > 0.09 on the 2×2-pack grid, open 1, close 20, fill, largest
  component, dilate 3 blocks; sheet bottom = last row at ≥ 50 % of the mask's
  max width (a first version used the mask's lowest row, which the bright
  clamp under the tabletop pulled ~60 px too low); table = 80 px band below
  the sheet bottom; background = rest. Sheet bottom lands at 826–850 px on
  172 of 178 images; outliers: the three convex-hull overrides (874–880),
  `Category-1_a_0027` (864), `Category-3_a_0042` (884), and the glass sliver
  `Category-3_a_0054` (988). Object 1–74 % of the frame, table 3–8 %.
- Audit material on the Mac: `data/audit/images/<stem>.png` (178, one per
  image, git-ignored) and `data/audit/Category-*.png` (contact sheets,
  committed). Luka audits every image and flags those needing adjustment.
- Audit round 1 (Luka, all 178 figures). Category 1 and 3 clean; Category-
  3_a_0054 (glass sliver, no table) removed from the split → 165 train.
  Category 2: dark books 0029–0032 clipped → convex hull override (a book
  is a rectangle). Category 4: images up to a_0010 have a tilted tabletop →
  the sheet bottom is now a per-image fitted line (robust to the clamp
  bump), not a row; dark objects 0005 (headset), 0026/0029 (sunglasses) →
  hand-drawn polygon overrides replace August's hull, which had swallowed
  large background triangles and dragged the table band ~50 px down.
  Sheet bottom now 818–850 px on all but the glass sliver. Second audit
  round pending.
