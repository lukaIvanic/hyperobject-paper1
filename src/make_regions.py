"""Three regions per image — object, table, background — from the ground truth.

Every image is the same rig: the object stands on a white paper sheet on a
dark tabletop, black background. Regions are decided on the 512×512 grid of
2×2 Bayer packs (one cell = one RGGB pack), so a region boundary can never
split a pack; they are expanded ×2 at load time.

  brightness  = cube.mean(bands), 2×2 block-averaged                (512×512)
  object      = brightness > THRESH  →  open r1  →  close r20  →  fill holes
                →  largest component  →  [convex hull]  →  dilate MARGIN
                (the object together with the sheet it stands on)
  sheet bottom = the last row where the object mask is at least half its
                widest row (the sheet is wide; the bright clamp under the
                tabletop forms a narrow bump below it and must not count)
  object      = the mask above the sheet bottom
  table       = the full-width band of TABLE_H rows below the sheet bottom
                (the dark tabletop and the clamp)
  background  = everything else

Labels: 0 background, 1 object, 2 table (uint8, 512×512).

Reads   /root/data/cache/<split>/cube/<stem>.npy
Writes  data/masks/regions.npz          {stem: uint8 (512, 512)}, compressed
        data/masks/stats.csv            per-image fractions and the object's bottom row
        data/audit/images/<stem>.png    per-image audit figure: render + log-brightness, region contours
        data/audit/<category>.png       contact sheets of the same
Per-image exceptions (dark objects that the threshold clips) are in
data/masks/overrides.yaml, each with a reason.

Usage: python src/make_regions.py [cache_root]
"""
import csv, sys, time
from multiprocessing import Pool
from pathlib import Path
import numpy as np, yaml
from scipy import ndimage as ndi
from scipy.spatial import ConvexHull, Delaunay

sys.path.insert(0, str(Path(__file__).parent))
from official_ssc.render import render_srgb_preview

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/data/cache")
THRESH, R_OPEN, R_CLOSE, MARGIN, TABLE_H = 0.09, 1, 20, 3, 40   # block units; TABLE_H = 80 px
WL = np.arange(400, 1001, 10, dtype=np.float32)


def disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def convex_hull(m):
    pts = np.column_stack(np.nonzero(m))
    hull = Delaunay(pts[ConvexHull(pts).vertices])
    yy, xx = np.mgrid[:m.shape[0], :m.shape[1]]
    return hull.find_simplex(np.column_stack([yy.ravel(), xx.ravel()])).reshape(m.shape) >= 0


def regions(b512, thresh=THRESH, convex=False):
    m = b512 > thresh
    m = ndi.binary_opening(m, disk(R_OPEN))
    m = ndi.binary_closing(m, disk(R_CLOSE))
    m = ndi.binary_fill_holes(m)
    lab, n = ndi.label(m)
    assert n >= 1
    m = lab == (np.argmax(ndi.sum_labels(m, lab, range(1, n + 1))) + 1)
    if convex:
        m = convex_hull(m)
    m = ndi.binary_dilation(m, disk(MARGIN))
    width = m.sum(axis=1)
    y_bottom = np.flatnonzero(width >= 0.5 * width.max())[-1]          # sheet bottom
    lbl = np.zeros(m.shape, np.uint8)
    lbl[y_bottom + 1:y_bottom + 1 + TABLE_H, :] = 2
    lbl[:y_bottom + 1][m[:y_bottom + 1]] = 1
    return lbl, int(y_bottom)


def one(item):
    split, stem, override = item
    cube = np.load(CACHE / split / "cube" / f"{stem}.npy", mmap_mode="r")
    b512 = np.asarray(cube).mean(axis=2).reshape(512, 2, 512, 2).mean(axis=(1, 3))
    lbl, y_bottom = regions(b512, **override)
    rgb = render_srgb_preview(np.transpose(cube, (2, 0, 1)), WL)[::2, ::2]   # 512² preview
    audit_figure(stem, lbl, y_bottom, rgb, b512, ROOT / f"data/audit/images/{stem}.png")
    return stem, lbl, y_bottom, rgb[::2, ::2]


def contours(ax, lbl):
    ax.contour(lbl == 1, levels=[0.5], colors="lime", linewidths=0.8)
    ax.contour(lbl == 2, levels=[0.5], colors="red", linewidths=0.8)


def audit_figure(stem, lbl, y_bottom, rgb, b512, out):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, (a, b) = plt.subplots(1, 2, figsize=(13, 6.6))
    a.imshow(np.clip(rgb, 0, 1) ** (1 / 1.8)); contours(a, lbl)
    a.set_title(f"{stem}   object {100 * (lbl == 1).mean():.1f}%   table {100 * (lbl == 2).mean():.1f}%   y_bottom={2 * y_bottom}")
    b.imshow(np.log10(np.maximum(b512, 1e-4)), cmap="gray"); contours(b, lbl)
    b.set_title(f"log10 block brightness (thresh {THRESH})")
    for ax in (a, b):
        ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout(); fig.savefig(out, dpi=100); plt.close(fig)


def contact_sheet(category, rows, out):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    n = len(rows); cols = 6; nr = -(-n // cols)
    fig, axes = plt.subplots(nr, cols, figsize=(cols * 3.2, nr * 3.4))
    for ax, (stem, lbl, y_bottom, rgb) in zip(axes.ravel(), rows):
        ax.imshow(np.clip(rgb, 0, 1) ** (1 / 1.8))
        contours(ax, lbl[::2, ::2])
        ax.set_title(f"{stem[-6:]}  obj {100 * (lbl == 1).mean():.0f}%  y={2 * y_bottom}", fontsize=8)
    for ax in axes.ravel():
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(f"{category}: green = object (incl. sheet), red = table", fontsize=11)
    fig.tight_layout(); fig.savefig(out, dpi=90); plt.close(fig)


if __name__ == "__main__":
    t0 = time.time()
    overrides = yaml.safe_load((ROOT / "data/masks/overrides.yaml").read_text()) or {}
    items = [(p.parent.parent.name, p.stem, {k: v for k, v in overrides.get(p.stem, {}).items() if k != "reason"})
             for p in sorted(CACHE.glob("*/cube/*.npy"))]
    assert len(items) == 178, len(items)
    (ROOT / "data/audit/images").mkdir(parents=True, exist_ok=True)
    with Pool(32) as pool:
        results = pool.map(one, items, chunksize=1)
    np.savez_compressed(ROOT / "data/masks/regions.npz", **{stem: lbl for stem, lbl, _, _ in results})
    with open(ROOT / "data/masks/stats.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["stem", "object_frac", "table_frac", "y_bottom_px"])
        for stem, lbl, y_bottom, _ in results:
            w.writerow([stem, f"{(lbl == 1).mean():.4f}", f"{(lbl == 2).mean():.4f}", 2 * y_bottom])
    for cat in ("Category-1", "Category-2", "Category-3", "Category-4"):
        contact_sheet(cat, [r for r in results if r[0].startswith(cat)], ROOT / f"data/audit/{cat}.png")
    fr = np.array([[(lbl == 1).mean(), (lbl == 2).mean()] for _, lbl, _, _ in results])
    print(f"{len(results)} images in {time.time() - t0:.0f}s; object {100 * fr[:, 0].min():.0f}–{100 * fr[:, 0].max():.0f}%, "
          f"table {100 * fr[:, 1].min():.0f}–{100 * fr[:, 1].max():.0f}%; overrides: {sorted(overrides)}")
