"""M1–M9 — what does a score mean? Model-free sensitivity of the official formula.

The ground truth of the 12 validation cubes is degraded in nine intuitive
ways, each from a trivial strength upward, and every degraded cube is scored
against the original per region (full, object, table, background) with
src/score.py. Every degraded cube is clipped at 0 (SID's logarithm needs
non-negative spectra), never at 1: the ground truth itself exceeds 1 on the
white sheet.

  M1 dropped pixels   random pixels replaced by the mean of their 4 neighbours
                      (1 in 100, 1 in 10, 1 in 2); then 2/4/8× average
                      pooling, upsampled back bilinearly
  M2 dropped bands    every 10th / 4th / 2nd band replaced by the linear
                      interpolation of its two kept neighbours
  M3 low-rank         spectra projected onto the top-k principal components
                      of the training set (k = 30, 12, 8, 4, 2)
  M4 added noise      iid Gaussian, σ = 0.001 … 0.05 (reflectance units)
  M5 smoothing        spatial Gaussian blur of every band, σ = 0.5 … 4 px
  M6 destriping       the per-band column profile, high-passed across
                      columns (σ = 8), subtracted: the ground truth minus its
                      own stripes
  M7 gain error       ×(1+ε) globally (ε = ±1, ±3, ±10 %) and per band with
                      random signs (|ε| = 1, 3, 10 %)
  M8 zero-clamping    values below t set to 0 (t = 0.001 … 0.02), and
                      floored at t (t = 0.005, 0.02)
  M9 constant cubes   zeros, the training-mean spectrum, ones

Reads   /root/data/cache/<split>/cube/<stem>.npy, data/split/{train,val}.txt,
        data/masks/regions.npz
Writes  logs/metric_study.csv               one line per (row, knob, image, region)
        logs/metric_study_mean.csv          the same averaged over the 12 images
        logs/metric_study_noise_decile.csv  M4 at σ = 0.01: SAM and SID by
                                            ground-truth brightness decile
        figs/metric_study.png               metrics and SSC vs knob, one panel
                                            per row and metric, one line per region
Usage: python src/metric_study.py [cache_root]
"""
import csv, sys, time
from pathlib import Path
import numpy as np, torch, torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent))
import score

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/data/cache")
DEV = "cuda"
REGIONS = ("full", "object", "table", "background")
COLS = score.METRICS + score.SCORES


def path(stem):                                              # "train/Category-1_a_0030" -> cache file
    split, name = stem.split("/")
    return CACHE / split / "cube" / f"{name}.npy"


def load(stem):
    return torch.from_numpy(np.load(path(stem))).to(DEV)


def train_stats(stems):
    """Mean spectrum and PCA basis of the training set (every 8th row of every cube, fp64)."""
    n, s, ss = 0, torch.zeros(61, dtype=torch.float64, device=DEV), torch.zeros(61, 61, dtype=torch.float64, device=DEV)
    for stem in stems:
        x = torch.from_numpy(np.ascontiguousarray(np.load(path(stem), mmap_mode="r")[::8])).to(DEV).reshape(-1, 61).double()
        n += len(x); s += x.sum(0); ss += x.T @ x
    mean = s / n
    cov = ss / n - mean[:, None] * mean[None, :]
    evals, evecs = torch.linalg.eigh(cov)                     # ascending
    explained = evals.flip(0).cumsum(0) / evals.sum()
    return mean.float(), evecs.flip(1).float(), explained.cpu().numpy()


# ---------------------------------------------------------------- degradations, (H, W, 61) -> (H, W, 61)
def chw(x): return x.permute(2, 0, 1)[None]                  # (1, 61, H, W) for the conv/pool ops
def hwc(x): return x[0].permute(1, 2, 0)


def drop_pixels(x, frac, gen):
    keep = torch.rand(x.shape[:2], generator=gen, device=DEV) >= frac
    p = F.pad(chw(x), (1, 1, 1, 1), mode="reflect")[0]
    nb = (p[:, :-2, 1:-1] + p[:, 2:, 1:-1] + p[:, 1:-1, :-2] + p[:, 1:-1, 2:]).permute(1, 2, 0) / 4
    return torch.where(keep[..., None], x, nb)


def pool(x, p):
    return hwc(F.interpolate(F.avg_pool2d(chw(x), p), scale_factor=p, mode="bilinear", align_corners=False))


def drop_bands(x, every):
    drop = np.arange(every // 2, 61, every); keep = np.setdiff1d(np.arange(61), drop)
    out = x.clone()
    for b in drop:
        lo, hi = keep[keep < b].max(), keep[keep > b].min(); w = (b - lo) / (hi - lo)
        out[..., b] = (1 - w) * x[..., lo] + w * x[..., hi]
    return out


def low_rank(x, k, mean, basis):
    return ((x - mean) @ basis[:, :k]) @ basis[:, :k].T + mean


def gauss1d(sigma):
    r = int(3 * sigma + 0.5); g = torch.exp(-0.5 * (torch.arange(-r, r + 1.0, device=DEV) / sigma) ** 2)
    return g / g.sum(), r


def blur(x, sigma):
    g, r = gauss1d(sigma); c = chw(x).reshape(61, 1, *x.shape[:2])
    c = F.conv2d(F.pad(c, (r, r, 0, 0), mode="reflect"), g[None, None, None, :])
    c = F.conv2d(F.pad(c, (0, 0, r, r), mode="reflect"), g[None, None, :, None])
    return c[:, 0].permute(1, 2, 0)


def destripe(x, sigma=8):
    prof = x.mean(0).T[:, None]                              # (61, 1, W) column profile per band
    g, r = gauss1d(sigma)
    smooth = F.conv1d(F.pad(prof, (r, r), mode="reflect"), g[None, None, :])
    return x - (prof - smooth)[:, 0].T[None]


def rows(mean, basis, gen):
    """(row, name, knob, function) in sweep order."""
    signs = torch.tensor(np.random.default_rng(0).choice([-1.0, 1.0], 61), dtype=torch.float32, device=DEV)
    R = []
    add = lambda row, name, knob, fn: R.append((row, name, knob, fn))
    for f in (0.01, 0.1, 0.5): add("M1", "dropped pixels", f"drop {f:g}", lambda x, f=f: drop_pixels(x, f, gen))
    for p in (2, 4, 8): add("M1", "dropped pixels", f"pool {p}", lambda x, p=p: pool(x, p))
    for e in (10, 4, 2): add("M2", "dropped bands", f"every {e}", lambda x, e=e: drop_bands(x, e))
    for k in (30, 12, 8, 4, 2): add("M3", "low-rank", f"k={k}", lambda x, k=k: low_rank(x, k, mean, basis))
    for s in (0.001, 0.003, 0.01, 0.03, 0.05): add("M4", "added noise", f"sigma {s:g}", lambda x, s=s: x + s * torch.randn(x.shape, generator=gen, device=DEV))
    for s in (0.5, 1, 2, 4): add("M5", "smoothing", f"sigma {s:g}px", lambda x, s=s: blur(x, s))
    add("M6", "destriping", "column profile", destripe)
    for e in (0.01, -0.01, 0.03, -0.03, 0.1, -0.1): add("M7", "gain error", f"global {e:+.0%}", lambda x, e=e: x * (1 + e))
    for e in (0.01, 0.03, 0.1): add("M7", "gain error", f"per band {e:.0%}", lambda x, e=e: x * (1 + e * signs))
    for t in (0.001, 0.003, 0.01, 0.02): add("M8", "zero-clamping", f"zero <{t:g}", lambda x, t=t: torch.where(x < t, torch.zeros_like(x), x))
    for t in (0.005, 0.02): add("M8", "zero-clamping", f"floor {t:g}", lambda x, t=t: x.clamp_min(t))
    add("M9", "constant", "zeros", lambda x: torch.zeros_like(x))
    add("M9", "constant", "train mean", lambda x: torch.zeros_like(x) + mean)
    add("M9", "constant", "ones", lambda x: torch.ones_like(x))
    return R


def noise_deciles(gt, pr, stem, w):
    m = score.maps(gt, pr); bright = gt.mean(-1)
    edges = torch.quantile(bright.flatten()[::7], torch.linspace(0, 1, 11, device=DEV))
    for d in range(10):
        sel = (bright >= edges[d]) & (bright <= edges[d + 1])
        w.writerow([stem, d, f"{edges[d]:.4f}", f"{edges[d + 1]:.4f}", f"{m['SAM'][sel].mean():.4f}", f"{m['SID'][sel].mean():.6f}"])


def figure(mean_rows, out):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    ids = ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8")
    metrics = ("SAM", "SID", "ERGAS", "PSNR", "SSIM", "DE", "SSC")
    fig, axes = plt.subplots(len(ids), len(metrics), figsize=(3.0 * len(metrics), 2.4 * len(ids)))
    for i, row in enumerate(ids):
        sub = [r for r in mean_rows if r["row"] == row]
        knobs = list(dict.fromkeys(r["knob"] for r in sub))
        for j, met in enumerate(metrics):
            ax = axes[i, j]
            for reg in REGIONS:
                ax.plot(range(len(knobs)), [float(r[met]) for r in sub if r["region"] == reg], "o-", ms=3, label=reg)
            ax.set_xticks(range(len(knobs))); ax.set_xticklabels(knobs, rotation=40, ha="right", fontsize=6)
            ax.tick_params(axis="y", labelsize=7); ax.grid(alpha=0.3)
            if i == 0: ax.set_title(met, fontsize=9)
            if j == 0: ax.set_ylabel(f"{row} {sub[0]['name']}", fontsize=8)
    axes[0, 0].legend(fontsize=6)
    fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)


if __name__ == "__main__":
    t0 = time.time()
    train = [l.strip() for l in (ROOT / "data/split/train.txt").read_text().split()]
    val = [l.strip() for l in (ROOT / "data/split/val.txt").read_text().split()]
    lbl = np.load(ROOT / "data/masks/regions.npz")
    mean, basis, explained = train_stats(train)
    print(f"train stats from {len(train)} cubes in {time.time() - t0:.0f}s; PCA variance explained: "
          + ", ".join(f"k={k} {explained[k - 1]:.5f}" for k in (2, 4, 8, 12, 30)))
    gen = torch.Generator(device=DEV).manual_seed(0)
    R = rows(mean, basis, gen)
    (ROOT / "logs").mkdir(exist_ok=True); (ROOT / "figs").mkdir(exist_ok=True)
    rows_out = []
    with open(ROOT / "logs/metric_study_noise_decile.csv", "w", newline="") as fd:
        wd = csv.writer(fd); wd.writerow(["stem", "decile", "bright_lo", "bright_hi", "SAM", "SID"])
        for stem in val:
            gt = load(stem); reg = score.regions(lbl[stem.split("/")[1]], DEV)
            for row, name, knob, fn in R:
                pr = fn(gt).clamp_min(0)
                for region, r in score.score(gt, pr, reg).items():
                    rows_out.append(dict(row=row, name=name, knob=knob, stem=stem, region=region, **r))
            noise_deciles(gt, (gt + 0.01 * torch.randn(gt.shape, generator=gen, device=DEV)).clamp_min(0), stem, wd)
            print(f"{stem}  {len(R)} rows  {time.time() - t0:.0f}s")
    with open(ROOT / "logs/metric_study.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["row", "name", "knob", "stem", "region", *COLS]); w.writeheader()
        for r in rows_out: w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})
    mean_rows = []
    for row, name, knob, _ in R:
        for region in REGIONS:
            sub = [r for r in rows_out if r["row"] == row and r["knob"] == knob and r["region"] == region]
            mean_rows.append(dict(row=row, name=name, knob=knob, region=region, **{c: f"{np.mean([r[c] for r in sub]):.6g}" for c in COLS}))
    with open(ROOT / "logs/metric_study_mean.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["row", "name", "knob", "region", *COLS]); w.writeheader(); w.writerows(mean_rows)
    figure(mean_rows, ROOT / "figs/metric_study.png")
    print(f"{len(R)} rows × {len(val)} images × {len(REGIONS)} regions in {time.time() - t0:.0f}s")
    for r in mean_rows:
        if r["region"] == "object": print(f"{r['row']} {r['knob']:>16s}  SAM {float(r['SAM']):6.2f}  SID {float(r['SID']):8.5f}  ERGAS {float(r['ERGAS']):6.2f}  "
                                          f"PSNR {float(r['PSNR']):5.1f}  SSIM {float(r['SSIM']):.4f}  dE {float(r['DE']):5.2f}  SSC {float(r['SSC']):.3f}   (object)")
