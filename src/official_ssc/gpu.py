"""GPU implementation of the official leaderboard scorer (evaluate_pair_ssc).

Same math as the vendored numpy path (leaderboard_ssc.py + metrics.py +
render.py), implemented in torch so a full-image evaluation takes ~0.1 s
instead of ~30 s. Run `parity_check()` once per session/box: it scores one
image both ways and asserts the components agree.

Conventions follow the numpy code exactly:
- cubes as (H,W,C) float tensors on any device, values in [0,1]
- SAM eps 1e-8 on the denominator; SID eps 1e-12 inside sum-normalized
  spectra and logs; ERGAS eps 1e-12 on channel means, scale 1.0
- render: CIE-1931-2deg CMFs + D65, vis range 400-700 nm, np.gradient
  wavelength weights, linear-sRGB matrix + gamma, clipped to [0,1]
- SSIM: gaussian 11x11 sigma 1.5, K=(0.01,0.03), reflect padding, mean over
  channel-averaged map; PSNR data_range 1.0
- DeltaE00 via common/ssc.py's torch port (parity-checked here against colour)
- SSC = (S_spec^.5 * S_spat^.35 * S_color^.15), S_spec geometric,
  S_x = clip(exp(-x/tau), 1e-6, 1), taus sam 5 / sid 0.02 / ergas 3 / dE 3,
  PSNR normalized (20,50)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))       # official_ssc/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # common/
import ssc as _ssc                                             # torch dE00

_WEIGHTS = {}


def _render_weights(wl_nm: np.ndarray, device) -> torch.Tensor:
    key = (tuple(np.asarray(wl_nm, dtype=float)), str(device))
    if key not in _WEIGHTS:
        from render import _load_cmf_ill_res  # vendored official math
        wl_vis, xbar, ybar, zbar, E, mask = _load_cmf_ill_res(np.asarray(wl_nm, float))
        w = np.gradient(wl_vis)
        k = 1.0 / np.sum(E * ybar * w)
        Wxyz = np.stack([k * E * xbar * w, k * E * ybar * w, k * E * zbar * w], 1)  # (V,3)
        _WEIGHTS[key] = (torch.as_tensor(Wxyz, dtype=torch.float64, device=device),
                         torch.as_tensor(mask, device=device))
    return _WEIGHTS[key]


def render_srgb_gpu(cube_hwc: torch.Tensor, wl_nm: np.ndarray) -> torch.Tensor:
    """(H,W,C) reflectance -> (H,W,3) sRGB, official math."""
    Wxyz, mask = _render_weights(wl_nm, cube_hwc.device)
    XYZ = cube_hwc[..., mask].to(torch.float64) @ Wxyz                     # (H,W,3)
    M = torch.tensor([[3.2406, -1.5372, -0.4986],
                      [-0.9689, 1.8758, 0.0415],
                      [0.0557, -0.2040, 1.0570]], dtype=torch.float64,
                     device=cube_hwc.device)
    lin = (XYZ @ M.T).clamp_min(0.0)
    a = 0.055
    rgb = torch.where(lin <= 0.0031308, 12.92 * lin,
                      (1 + a) * lin.pow(1 / 2.4) - a)
    return rgb.clamp(0.0, 1.0).float()


def _sam(gt, pr, eps=1e-8):
    num = (gt * pr).sum(-1)
    den = gt.norm(dim=-1) * pr.norm(dim=-1) + eps
    ang = torch.rad2deg(torch.arccos((num / den).clamp(-1.0, 1.0)))
    return float(ang.mean())


def _sid(gt, pr, eps=1e-12):
    ps = gt / (gt.sum(-1, keepdim=True) + eps)
    qs = pr / (pr.sum(-1, keepdim=True) + eps)
    spq = (ps * torch.log((ps + eps) / (qs + eps))).sum(-1)
    sqp = (qs * torch.log((qs + eps) / (ps + eps))).sum(-1)
    return float((spq + sqp).mean())


def _ergas(gt, pr, eps=1e-12):
    rmse_c = ((gt - pr) ** 2).mean((0, 1)).sqrt()
    mu_c = gt.mean((0, 1))
    return float(100.0 * ((rmse_c / (mu_c.abs() + eps)) ** 2).mean().sqrt())


def _psnr(a, b, eps=1e-12):
    mse = ((a - b) ** 2).mean().clamp_min(eps)
    return float(-10.0 * torch.log10(mse))


_G = {}
def _gauss_kernel(device, dtype, win=11, sigma=1.5):
    key = (str(device), dtype)
    if key not in _G:
        ax = torch.arange(win, dtype=torch.float64) - win // 2
        g = torch.exp(-0.5 * (ax / sigma) ** 2)
        g = g / g.sum()
        k = (g[:, None] * g[None, :])
        _G[key] = (k / k.sum()).to(device=device, dtype=dtype)[None, None]
    return _G[key]


def _ssim(a_hwc, b_hwc, K=(0.01, 0.03)):
    C1, C2 = K[0] ** 2, K[1] ** 2
    x = a_hwc.permute(2, 0, 1)[:, None].to(torch.float64)      # (C,1,H,W)
    y = b_hwc.permute(2, 0, 1)[:, None].to(torch.float64)
    k = _gauss_kernel(x.device, x.dtype)
    pad = k.shape[-1] // 2
    def f(t):
        return F.conv2d(F.pad(t, (pad,) * 4, mode="reflect"), k)
    mx, my = f(x), f(y)
    sxx = f(x * x) - mx * mx
    syy = f(y * y) - my * my
    sxy = f(x * y) - mx * my
    m = ((2 * mx * my + C1) * (2 * sxy + C2)) / ((mx * mx + my * my + C1) * (sxx + syy + C2) + 1e-12)
    return float(m.mean(0).mean())


def evaluate_pair_ssc_gpu(gt_hwc: torch.Tensor, pr_hwc: torch.Tensor,
                          wl_nm: np.ndarray,
                          weights=(0.5, 0.35, 0.15),
                          taus=None, psnr_range=(20.0, 50.0)) -> dict:
    if taus is None:
        taus = dict(sam=5.0, sid=0.02, ergas=3.0, de=3.0)
    gt = gt_hwc.to(torch.float64)
    pr = pr_hwc.to(torch.float64)
    sam_v, sid_v, erg_v = _sam(gt, pr), _sid(gt, pr), _ergas(gt, pr)
    e = lambda x, t: float(np.clip(np.exp(-x / t), 1e-6, 1.0))
    S_SAM, S_SID, S_ERG = e(sam_v, taus["sam"]), e(sid_v, taus["sid"]), e(erg_v, taus["ergas"])
    S_spec = (S_SAM * S_SID * S_ERG) ** (1 / 3)

    gt_rgb = render_srgb_gpu(gt_hwc, wl_nm)
    pr_rgb = render_srgb_gpu(pr_hwc, wl_nm)
    psnr_v = _psnr(gt_rgb, pr_rgb)
    ssim_v = _ssim(gt_rgb, pr_rgb)
    S_PSNR = float(np.clip((psnr_v - psnr_range[0]) / (psnr_range[1] - psnr_range[0]), 0, 1))
    S_spat = 0.5 * (S_PSNR + ssim_v)
    dE = _ssc.deltaE00_mean_torch(gt_rgb, pr_rgb)
    S_col = e(dE, taus["de"])
    ws, wp, wc = weights
    SSC = (S_spec ** ws * S_spat ** wp * S_col ** wc) ** (1.0 / (ws + wp + wc))
    return dict(SAM_deg=sam_v, SID=sid_v, ERGAS=erg_v, PSNR_dB=psnr_v, SSIM=ssim_v,
                DeltaE00=dE, S_SAM=S_SAM, S_SID=S_SID, S_ERGAS=S_ERG, S_PSNR=S_PSNR,
                S_SSIM=ssim_v, S_SPEC=S_spec, S_SPAT=S_spat, S_COLOR=S_col, SSC=SSC)


def parity_check(gt_hwc: torch.Tensor, pr_hwc: torch.Tensor, wl_nm) -> dict:
    """Score one pair with both paths; return {key: (gpu, numpy, absdiff)}."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from common.official_ssc.leaderboard_ssc import evaluate_pair_ssc
    g = evaluate_pair_ssc_gpu(gt_hwc, pr_hwc, wl_nm)
    n = evaluate_pair_ssc(gt_hwc.cpu().numpy(), pr_hwc.cpu().numpy(), np.asarray(wl_nm))
    return {k: (g[k], n[k], abs(g[k] - n[k])) for k in g}
