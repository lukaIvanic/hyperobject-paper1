"""Figures for notes/sensitivity_analysis/: one family of degradations per page.

For every family: an *example* figure (one validation image degraded at a mild
and at a strong setting — the sRGB render, the per-pixel error map, and the
spectra of one object, one table and one background pixel) and a *results*
figure (the six metrics and the composite score against the setting, one
line per region, averaged over the 12 validation images), plus three extras:
the noise-by-brightness deciles, the stripe template, and the PCA variance.

Reads   logs/metric_study_mean.csv, logs/metric_study_noise_decile.csv, the cache
Writes  notes/sensitivity_analysis/figs/<family>-example.png, <family>-results.png, extras
Usage: python src/metric_study_figs.py [cache_root]
"""
import csv, sys
from pathlib import Path
import numpy as np, torch
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
import score, metric_study as ms

ROOT = ms.ROOT
OUT = ROOT / "notes/sensitivity_analysis/figs"
EXAMPLE = "train/Category-2_a_0013"
COLORS = dict(full="#1f77b4", object="#ff7f0e", table="#2ca02c", background="#d62728")
FAMILIES = {   # row -> (slug, title, example settings)
    "M1": ("dropped-pixels", "Dropped pixels — random pixels refilled from their neighbours, then coarser and coarser pooling", ["drop 0.1", "pool 4"]),
    "M2": ("dropped-bands", "Dropped bands — every n-th wavelength band replaced by the average of its two neighbours", ["every 10", "every 2"]),
    "M3": ("low-rank", "Low-rank spectra — every spectrum rebuilt from only k principal components of the training set", ["k=12", "k=4"]),
    "M4": ("added-noise", "Added noise — independent Gaussian noise of standard deviation σ on every value", ["sigma 0.003", "sigma 0.03"]),
    "M5": ("smoothing", "Smoothing — every band blurred with a Gaussian of width σ pixels", ["sigma 1px", "sigma 4px"]),
    "M6": ("destriping", "Destriping — the vertical stripe pattern subtracted from the ground truth", ["own profile", "train template"]),
    "M7": ("gain-error", "Gain error — every value multiplied by (1 + ε), globally or band by band", ["global +3%", "per band 10%"]),
    "M8": ("zero-clamping", "Zero-clamping — small values set to zero, or lifted to a floor", ["zero <0.01", "floor 0.005"]),
    "M9": ("constant-cubes", "Constant cubes — the same spectrum at every pixel", ["train mean", "ones"]),
}
METRIC_TITLES = dict(SAM="SAM, spectral angle (degrees, lower is better)", SID="SID, spectral divergence (lower is better)",
                     ERGAS="ERGAS, relative band error (lower is better)", PSNR="PSNR of the colour render (dB, higher is better)",
                     SSIM="SSIM of the colour render (higher is better)", DE="ΔE00, colour difference (lower is better)",
                     SSC="Composite score SSC (higher is better)")


def show(ax, rgb, title):
    ax.imshow(np.clip(rgb, 0, 1) ** (1 / 1.6)); ax.set_title(title, fontsize=9); ax.set_xticks([]); ax.set_yticks([])


def example_figure(gt, reg, settings, fns, title, out):
    pts = {n: torch.nonzero(m).float().mean(0).long().tolist() for n, m in reg.items() if m is not None}
    rgb0 = score.render(gt).cpu().numpy()
    fig, axes = plt.subplots(len(settings), 4, figsize=(17, 4.3 * len(settings)))
    for i, (knob, fn) in enumerate(zip(settings, fns)):
        pr = fn(gt).clamp_min(0)
        a = axes[i]
        show(a[0], rgb0, "ground truth (render, brightened)")
        show(a[1], score.render(pr).cpu().numpy(), f"degraded: {knob}")
        d = (pr - gt).abs().mean(-1).cpu().numpy()
        im = a[2].imshow(np.log10(np.maximum(d, 1e-5)), cmap="magma", vmin=-5, vmax=-0.5)
        a[2].set_title("|degraded − truth|, mean over bands (log10)", fontsize=9); a[2].set_xticks([]); a[2].set_yticks([])
        plt.colorbar(im, ax=a[2], fraction=0.046)
        for n, (y, x) in pts.items():
            a[3].plot(score.WL, gt[y, x].cpu(), color=COLORS[n], lw=1.2, label=f"{n} pixel, truth")
            a[3].plot(score.WL, pr[y, x].cpu(), color=COLORS[n], lw=1.2, ls="--", label=f"{n} pixel, degraded")
            for k in (0, 1): a[k].plot(x, y, "+", color=COLORS[n], ms=12, mew=1.5)
        a[3].set_xlabel("wavelength (nm)"); a[3].set_ylabel("reflectance"); a[3].grid(alpha=0.3)
        a[3].set_title("spectra at the three marked pixels", fontsize=9)
        if i == 0: a[3].legend(fontsize=7)
    fig.suptitle(title, fontsize=11); fig.tight_layout(); fig.savefig(out, dpi=100); plt.close(fig)


def results_figure(rows, title, out):
    knobs = list(dict.fromkeys(r["knob"] for r in rows))
    fig, axes = plt.subplots(2, 4, figsize=(17, 8))
    for ax, met in zip(axes.ravel(), ("SAM", "SID", "ERGAS", "PSNR", "SSIM", "DE", "SSC")):
        for reg in ms.REGIONS:
            ax.plot(range(len(knobs)), [float(r[met]) for r in rows if r["region"] == reg], "o-", color=COLORS[reg], ms=4, label=reg)
        ax.set_xticks(range(len(knobs))); ax.set_xticklabels(knobs, rotation=30, ha="right", fontsize=8)
        ax.set_title(METRIC_TITLES[met], fontsize=9); ax.grid(alpha=0.3)
        if met == "SSC": ax.set_ylim(-0.02, 1.02)
    ax = axes[1, 3]
    for comp, ls in (("S_SPEC", "-"), ("S_SPAT", "--"), ("S_DE", ":")):
        ax.plot(range(len(knobs)), [float(r[comp]) for r in rows if r["region"] == "full"], ls, color=COLORS["full"], marker="o", ms=4, label=f"{comp} (full frame)")
    ax.set_xticks(range(len(knobs))); ax.set_xticklabels(knobs, rotation=30, ha="right", fontsize=8); ax.set_ylim(-0.02, 1.02)
    ax.set_title("the three factors of SSC, full frame", fontsize=9); ax.grid(alpha=0.3); ax.legend(fontsize=7)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle(f"{title}\nmean over the 12 validation images; one line per region", fontsize=11)
    fig.tight_layout(); fig.savefig(out, dpi=100); plt.close(fig)


def extras(template, explained):
    dec = {}
    for r in csv.DictReader(open(ROOT / "logs/metric_study_noise_decile.csv")):
        dec.setdefault(int(r["decile"]), []).append((float(r["bright_lo"]), float(r["bright_hi"]), float(r["SAM"]), float(r["SID"])))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    x = [np.mean([v[1] for v in dec[d]]) for d in range(10)]
    for ax, j, name in ((axes[0], 2, "SAM (degrees)"), (axes[1], 3, "SID")):
        ax.plot(range(10), [np.mean([v[j] for v in dec[d]]) for d in range(10)], "o-")
        ax.set_xticks(range(10)); ax.set_xticklabels([f"{b:.2f}" for b in x], fontsize=8)
        ax.set_xlabel("decile of ground-truth brightness (upper edge, mean reflectance)"); ax.set_ylabel(name); ax.set_yscale("log"); ax.grid(alpha=0.3, which="both")
    fig.suptitle("The same noise (σ = 0.01) scored by pixel brightness: dark pixels pay almost all of it", fontsize=11)
    fig.tight_layout(); fig.savefig(OUT / "added-noise-by-brightness.png", dpi=100); plt.close(fig)

    t = template.cpu().numpy()                               # (W, 61)
    fig, axes = plt.subplots(2, 1, figsize=(14, 6), gridspec_kw=dict(height_ratios=[2, 1]))
    im = axes[0].imshow(t.T, aspect="auto", cmap="RdBu_r", vmin=-0.004, vmax=0.004)
    axes[0].set_ylabel("band"); axes[0].set_title("the stripe template: per-column offset of every band, averaged over 165 training cubes", fontsize=10)
    axes[0].set_yticks([0, 20, 40, 60]); axes[0].set_yticklabels(["400 nm", "600 nm", "800 nm", "1000 nm"]); plt.colorbar(im, ax=axes[0], fraction=0.02)
    axes[1].plot(t[:, 30], lw=0.7); axes[1].set_xlim(0, 1023); axes[1].set_xlabel("column"); axes[1].set_ylabel("offset at 700 nm"); axes[1].grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(OUT / "destriping-template.png", dpi=100); plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.semilogy(range(1, 62), 1 - explained + 1e-9, "o-", ms=3); ax.set_xlabel("number of principal components k"); ax.set_ylabel("fraction of variance NOT explained")
    ax.grid(alpha=0.3, which="both"); ax.set_title("How much of the training spectra k components leave out", fontsize=10)
    fig.tight_layout(); fig.savefig(OUT / "low-rank-variance.png", dpi=100); plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    train = (ROOT / "data/split/train.txt").read_text().split()
    mean, basis, explained, template = ms.train_stats(train)
    R = ms.rows(mean, basis, template, torch.Generator(device=ms.DEV).manual_seed(0))
    gt = ms.load(EXAMPLE); reg = score.regions(np.load(ROOT / "data/masks/regions.npz")[EXAMPLE.split("/")[1]], ms.DEV)
    means = list(csv.DictReader(open(ROOT / "logs/metric_study_mean.csv")))
    for row, (slug, title, settings) in FAMILIES.items():
        fns = [next(fn for r, _, k, fn in R if r == row and k == s) for s in settings]
        example_figure(gt, reg, settings, fns, title, OUT / f"{slug}-example.png")
        results_figure([r for r in means if r["row"] == row], title, OUT / f"{slug}-results.png")
    extras(template, explained)
    print(f"figures in {OUT}")
