"""Official ICASSP 2026 Hyper-Object leaderboard scorer, vendored.

Provenance:
- metrics.py, helpers.py: verbatim from github.com/hyper-object/2026-ICASSP-SPGC
  (utils/), except: helpers.py drops an unused matplotlib import; metrics.py
  _filter2d gains a numerically-identical scipy fast path (the original pure-
  python loop takes minutes per image).
- leaderboard_ssc.py: the source was never committed upstream -- reconstructed
  from the committed CPython 3.12 bytecode (utils/__pycache__/), constants and
  control flow verified against `dis` output. See replication/DIAG_FINDINGS.md.
- render.py: the colour-science sRGB fallback extracted from
  utils/visualizations.py (matplotlib-free).

Usage: evaluate_pair_ssc(gt_hwc, pred_hwc, wl_nm) with (H,W,61) cubes and
wl_nm = np.arange(400, 1001, 10). Note the exponential normalizations:
S = exp(-metric/tau), taus: SAM 5deg, SID 0.02, ERGAS 3.0, dE00 3.0; PSNR is
linear 20..50 dB on the sRGB render; final SSC is the weighted GEOMETRIC mean
S_spec^0.5 * S_spat^0.35 * S_color^0.15.
"""
from .leaderboard_ssc import evaluate_pair_ssc  # noqa: F401
