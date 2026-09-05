"""The official leaderboard formula on the GPU, reduced per region.

The organizers' scorer (`src/official_ssc`, numpy, ~30 s per image) is the
reference. This file is the same mathematics in torch fp32 (~30 ms per image)
with one addition: every metric can be reduced over a region mask.

For a pair of (H, W, 61) cubes the per-pixel maps are computed once —
SAM (deg), SID, and on the sRGB render ΔE00, the channel-averaged SSIM map
and the squared error — and each region reduces them:

  SAM, SID, ΔE00, SSIM   mean of the map over the region's pixels
  PSNR                   −10·log10 of the mean squared RGB error over the region
  ERGAS                  per-band RMSE and per-band GT mean over the region's
                         pixels: 100 · sqrt(mean_b (RMSE_b / mean_b)²)

SSIM windows at a region's boundary still see pixels outside it — the same
rule as the organizers' own (unused) mask argument. mask=None is the full
frame and reproduces the reference scorer.

Scores: S_x = clip(exp(−x/τ), 1e-6, 1) with τ = 5° SAM, 0.02 SID, 3 ERGAS,
3 ΔE00; S_PSNR = clip((PSNR − 20)/30, 0, 1); S_spec = geometric mean of the
three spectral scores; S_spat = (S_PSNR + SSIM)/2; S_col = S_ΔE00;
SSC = S_spec^0.5 · S_spat^0.35 · S_col^0.15.

`python src/score.py` is the parity check: one val cube against a noisy copy,
full frame, this file against the numpy reference, every value within 1e-4
(relative for the raw metrics, absolute for the scores).
"""
import sys
from pathlib import Path
import numpy as np, torch, torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent))
from official_ssc.render import _load_cmf_ill_res

WL = np.arange(400, 1001, 10, dtype=np.float32)
torch.backends.cudnn.allow_tf32 = torch.backends.cuda.matmul.allow_tf32 = False   # true fp32, like the reference
METRICS = ("SAM", "SID", "ERGAS", "PSNR", "SSIM", "DE")
SCORES = ("S_SAM", "S_SID", "S_ERGAS", "S_PSNR", "S_DE", "S_SPEC", "S_SPAT", "SSC")
_C = {}


def _consts(device):
    if device not in _C:
        wl_vis, xb, yb, zb, E, vis = _load_cmf_ill_res(WL)          # official CMF/D65 tables
        w = np.gradient(wl_vis); k = 1 / np.sum(E * yb * w)
        g = torch.exp(-0.5 * ((torch.arange(11.0) - 5) / 1.5) ** 2); g /= g.sum()
        t = lambda a: torch.tensor(np.asarray(a), dtype=torch.float32, device=device)
        _C[device] = dict(
            Wxyz=t(np.stack([k * E * xb * w, k * E * yb * w, k * E * zb * w], 1)), vis=torch.tensor(vis, device=device),
            xyz2rgb=t([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]]),
            rgb2xyz=t([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]),
            white=t([0.95047, 1.0, 1.08883]), gauss=(g[:, None] * g[None, :]).to(device)[None, None])
    return _C[device]


def render(cube):
    """(H, W, 61) reflectance -> (H, W, 3) sRGB in [0, 1], the official render."""
    c = _consts(cube.device)
    lin = ((cube[..., c["vis"]] @ c["Wxyz"]) @ c["xyz2rgb"].T).clamp_min(0)
    return torch.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin.pow(1 / 2.4) - 0.055).clamp(0, 1)


def _lab(rgb):
    c = _consts(rgb.device)
    lin = torch.where(rgb > 0.04045, ((rgb + 0.055) / 1.055).pow(2.4), rgb / 12.92)
    t = (lin @ c["rgb2xyz"].T) / c["white"]
    d = 6 / 29
    f = torch.where(t > d ** 3, t.pow(1 / 3), t / (3 * d * d) + 4 / 29)
    return 116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])


def _de00_map(rgb1, rgb2):
    """Per-pixel CIEDE2000 (Sharma et al. 2005), the formula colour-science implements."""
    (L1, a1, b1), (L2, a2, b2) = _lab(rgb1), _lab(rgb2)
    rad = torch.deg2rad
    C1, C2 = torch.sqrt(a1 * a1 + b1 * b1), torch.sqrt(a2 * a2 + b2 * b2)
    c7 = (0.5 * (C1 + C2)) ** 7
    G = 0.5 * (1 - torch.sqrt(c7 / (c7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = torch.sqrt(a1p * a1p + b1 * b1), torch.sqrt(a2p * a2p + b2 * b2)
    h1p, h2p = torch.rad2deg(torch.atan2(b1, a1p)) % 360, torch.rad2deg(torch.atan2(b2, a2p)) % 360
    zero = (C1p * C2p) == 0
    dh = h2p - h1p
    dh = torch.where(dh > 180, dh - 360, torch.where(dh < -180, dh + 360, dh))
    dh = torch.where(zero, torch.zeros_like(dh), dh)
    dLp, dCp, dHp = L2 - L1, C2p - C1p, 2 * torch.sqrt(C1p * C2p) * torch.sin(rad(dh) / 2)
    Lbp, Cbp, hsum = 0.5 * (L1 + L2), 0.5 * (C1p + C2p), h1p + h2p
    hbp = torch.where((h1p - h2p).abs() <= 180, 0.5 * hsum, torch.where(hsum < 360, 0.5 * (hsum + 360), 0.5 * (hsum - 360)))
    hbp = torch.where(zero, hsum, hbp)
    T = 1 - 0.17 * torch.cos(rad(hbp - 30)) + 0.24 * torch.cos(rad(2 * hbp)) + 0.32 * torch.cos(rad(3 * hbp + 6)) - 0.20 * torch.cos(rad(4 * hbp - 63))
    cb7 = Cbp ** 7
    Rt = -torch.sin(2 * rad(30 * torch.exp(-((hbp - 275) / 25) ** 2))) * 2 * torch.sqrt(cb7 / (cb7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / torch.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    return torch.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def _ssim_map(a, b):
    """(H, W, 3) pair -> (H, W) channel-averaged SSIM map (gaussian 11×11 σ 1.5, reflect padding)."""
    k = _consts(a.device)["gauss"]
    f = lambda t: F.conv2d(F.pad(t, (5,) * 4, mode="reflect"), k)
    x, y = a.permute(2, 0, 1)[:, None], b.permute(2, 0, 1)[:, None]
    mx, my = f(x), f(y)
    sxx, syy, sxy = f(x * x) - mx * mx, f(y * y) - my * my, f(x * y) - mx * my
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    return (((2 * mx * my + C1) * (2 * sxy + C2)) / ((mx * mx + my * my + C1) * (sxx + syy + C2) + 1e-12)).mean(0)[0]


def maps(gt, pr):
    """Per-pixel error maps of a (H, W, 61) pair, fp32 on the pair's device."""
    gt, pr = gt.float(), pr.float()
    sam = torch.rad2deg(torch.arccos(((gt * pr).sum(-1) / (gt.norm(dim=-1) * pr.norm(dim=-1) + 1e-8)).clamp(-1, 1)))
    ps, qs = gt / (gt.sum(-1, keepdim=True) + 1e-12), pr / (pr.sum(-1, keepdim=True) + 1e-12)
    sid = (ps * torch.log((ps + 1e-12) / (qs + 1e-12))).sum(-1) + (qs * torch.log((qs + 1e-12) / (ps + 1e-12))).sum(-1)
    g, p = render(gt), render(pr)
    return dict(SAM=sam, SID=sid, DE=_de00_map(g, p), SSIM=_ssim_map(g, p), MSE=((g - p) ** 2).mean(-1), gt=gt, pr=pr)


def scores(r):
    s = lambda x, tau: float(np.clip(np.exp(-x / tau), 1e-6, 1))
    S = dict(S_SAM=s(r["SAM"], 5), S_SID=s(r["SID"], 0.02), S_ERGAS=s(r["ERGAS"], 3),
             S_PSNR=float(np.clip((r["PSNR"] - 20) / 30, 0, 1)), S_DE=s(r["DE"], 3))
    S["S_SPEC"] = (S["S_SAM"] * S["S_SID"] * S["S_ERGAS"]) ** (1 / 3)
    S["S_SPAT"] = 0.5 * (S["S_PSNR"] + r["SSIM"])
    S["SSC"] = S["S_SPEC"] ** 0.5 * S["S_SPAT"] ** 0.35 * S["S_DE"] ** 0.15
    return S


def reduce(m, mask=None):
    """The six metrics and the scores over one region: a bool (H, W) mask, or None for the full frame."""
    sel = (lambda x: x) if mask is None else (lambda x: x[mask])
    gt, pr = sel(m["gt"]).reshape(-1, 61), sel(m["pr"]).reshape(-1, 61)
    rmse_b = ((gt - pr) ** 2).mean(0).sqrt()
    r = dict(SAM=sel(m["SAM"]).mean(), SID=sel(m["SID"]).mean(), DE=sel(m["DE"]).mean(), SSIM=sel(m["SSIM"]).mean(),
             PSNR=-10 * torch.log10(sel(m["MSE"]).mean().clamp_min(1e-12)),
             ERGAS=100 * ((rmse_b / (gt.mean(0).abs() + 1e-12)) ** 2).mean().sqrt())
    r = {k: float(v) for k, v in r.items()}
    return {**r, **scores(r)}


def regions(lbl512, device):
    """The four regions of one image from its 512² label map (0 background, 1 object, 2 table)."""
    lbl = torch.as_tensor(lbl512, device=device).repeat_interleave(2, 0).repeat_interleave(2, 1)
    return {"full": None, "object": lbl == 1, "table": lbl == 2, "background": lbl == 0}


def score(gt, pr, regions):
    """{region: metrics and scores} for a (H, W, 61) pair; regions = {name: bool mask or None}."""
    m = maps(gt, pr)
    return {name: reduce(m, mask) for name, mask in regions.items()}


if __name__ == "__main__":
    from official_ssc import evaluate_pair_ssc
    gt = np.load("/root/data/cache/train/cube/Category-2_a_0013.npy")
    pr = np.clip(gt + np.random.default_rng(0).normal(0, 0.01, gt.shape).astype(np.float32), 0, 1)
    ref = evaluate_pair_ssc(gt, pr, WL)
    ours = reduce(maps(torch.tensor(gt, device="cuda"), torch.tensor(pr, device="cuda")))
    pairs = dict(SAM="SAM_deg", SID="SID", ERGAS="ERGAS", PSNR="PSNR_dB", SSIM="SSIM", DE="DeltaE00",
                 S_SPEC="S_SPEC", S_SPAT="S_SPAT", S_DE="S_COLOR", SSC="SSC")
    for k, kr in pairs.items():
        d = abs(ours[k] - ref[kr]); tol = 1e-4 * (max(1, abs(ref[kr])) if k in METRICS else 1)
        print(f"{k:7s} torch {ours[k]:12.6f}  numpy {ref[kr]:12.6f}  |diff| {d:.1e}  {'ok' if d <= tol else 'FAIL'}")
        assert d <= tol, k
    print("parity ok")
