"""Standardized sRGB render (D65, CIE 1931 2deg) used by the leaderboard scorer.

Extracted verbatim from the challenge repo's utils/visualizations.py
render_srgb_preview colour-science fallback (the organizers' private
hsi_reflectance_to_srgb is not published; the fallback is the same math the
README documents). Takes a cube in CHW, returns (H,W,3) float32 sRGB in [0,1].
"""
from __future__ import annotations
import numpy as np


def _load_cmf_ill_res(wl_nm, vis_range=(400.0, 700.0),
                      illuminant="D65",
                      observer="CIE 1931 2 Degree Standard Observer",
                      base_shape=(380.0, 780.0, 1.0)):
    import colour
    wl_nm = np.asarray(wl_nm, dtype=float)
    vmin, vmax = vis_range
    vis_mask = (wl_nm >= vmin) & (wl_nm <= vmax)
    wl_vis = wl_nm[vis_mask]
    start, end, step = base_shape
    n_steps = int(np.floor((end - start) / step)) + 1
    wl_base = start + step * np.arange(n_steps)

    cmfs = colour.MSDS_CMFS[observer].copy().align(colour.SpectralShape(start, end, step))
    illu = colour.SDS_ILLUMINANTS[illuminant].copy().align(colour.SpectralShape(start, end, step))

    xbar = np.interp(wl_vis, wl_base, cmfs.values[..., 0])
    ybar = np.interp(wl_vis, wl_base, cmfs.values[..., 1])
    zbar = np.interp(wl_vis, wl_base, cmfs.values[..., 2])
    E = np.interp(wl_vis, wl_base, illu.values)
    return wl_vis, xbar, ybar, zbar, E, vis_mask


def render_srgb_preview(cube, wl, vis_range=(400.0, 700.0), illuminant="D65",
                        observer="CIE 1931 2 Degree Standard Observer",
                        clip=True, title=None):
    """cube: (C,H,W) reflectance in [0,1]; wl: (C,) nm. Returns (H,W,3) sRGB."""
    arr = np.asarray(cube, dtype=np.float32)
    arr = np.transpose(arr, (1, 2, 0))                     # H,W,C
    wl = np.asarray(wl, dtype=float)

    wl_vis, xbar, ybar, zbar, E, mask = _load_cmf_ill_res(wl, vis_range, illuminant, observer)
    Rv = arr[..., mask]
    w = np.gradient(wl_vis)
    k = 1.0 / np.sum(E * ybar * w)
    Wx = k * (E * xbar * w); Wy = k * (E * ybar * w); Wz = k * (E * zbar * w)
    X = np.tensordot(Rv, Wx, axes=([2], [0]))
    Y = np.tensordot(Rv, Wy, axes=([2], [0]))
    Z = np.tensordot(Rv, Wz, axes=([2], [0]))
    M = np.array([[3.2406, -1.5372, -0.4986],
                  [-0.9689, 1.8758, 0.0415],
                  [0.0557, -0.2040, 1.0570]], dtype=np.float64)
    RGB_lin = np.stack([X, Y, Z], axis=-1) @ M.T
    RGB_lin = np.clip(RGB_lin, 0.0, None)
    a = 0.055; threshold = 0.0031308
    RGB = np.where(RGB_lin <= threshold, 12.92 * RGB_lin,
                   (1 + a) * np.power(RGB_lin, 1 / 2.4) - a)
    if clip:
        RGB = np.clip(RGB, 0.0, 1.0)
    return RGB.astype(np.float32)
