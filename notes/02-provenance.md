# Provenance of ported code

Every file under `src/` that did not originate here lists where it came
from and what, if anything, changed.

| path | from | changes |
|---|---|---|
| `src/official_ssc/` (metrics.py, helpers.py, leaderboard_ssc.py, render.py) | `../report/replication/common/official_ssc/` (August; itself vendored from the organizers' repo `hyper-object/2026-ICASSP-SPGC`, with `leaderboard_ssc.py` reconstructed from committed bytecode) | none — copied verbatim 2026-09-04; see its `__init__.py` docstring for the upstream provenance. August's `gpu.py` was dropped 2026-09-05 (it imported a module that is not here); `src/score.py` replaces it |
| `src/make_regions.py` | written here 2026-09-05 | new; the brightness-threshold object rule and the 2×2-pack grid come from `../report/replication/04-masked-protocol/`; the sheet-bottom line, the table band, the hull rule and the overrides are new |
| `src/build_cache.py` | written here 2026-09-05 | new; the HWC zero-copy layout idea and the "loads are decompression-bound" finding come from `../report/replication/04-masked-protocol/REPORT.md` §6 and `00-baseline-official/REPORT.md` |
| `src/score.py` | written here 2026-09-05 | the official formula in torch, per region; the fp32 conventions and the per-metric masking rules follow `../report/replication/04-masked-protocol/masked_ssc.py`, the torch ΔE00 port `../report/replication/common/ssc.py` |
| `src/metric_study.py` | written here 2026-09-05 | new |
