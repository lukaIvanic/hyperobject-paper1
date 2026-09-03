# 03 — Experiment plan (draft v1, 2026-09-03, for discussion)

Architecture fixed: official Raw2HSI baseline. Two lengths only: 100 ep
(working) and 1000 ep (official reference). One GPU (RTX 5090); baseline
costs ≈ 4 s/epoch → 100 ep ≈ 7 min, 1000 ep ≈ 66 min, +43 s preload.

## R0 — the fixed recipe

Official baseline recipe verbatim: AdamW 2e-4 cosine, L1 + 0.1·SAM, fp16 AMP,
official batch size, official (repaired) code semantics — on our optimized
pipeline. Two deltas from "as shipped", both from the August audit and both
disclosed: (i) train unclamped, clamp + floor 0.005 at eval (the dead
phase-channel fix); (ii) numerically repaired metrics. Whether (i) is part
of R0 or an ablation arm: **decide** (see Q2).

Data: our split (`data/`), three regions per image (object incl. sheet /
table rail / background). Readout every K epochs on val AND on a fixed train
subset: the six submetrics per region + SSC. Logged to CSV, committed.

## Experiments

| # | question | arms (one change each) | length | readout that decides | cost |
|---|---|---|---|---|---|
| E0 | Did the rewrite preserve the recipe? | R0, *official* split | 1000 | curve in family with exp-00; Kaggle 0.239 if we submit | 66 min |
| E1 | Reference run + split honesty (H3) | R0, our split | 1000 | per-category train-vs-val gap: cats 1/3 ≈ 0, cats 2/4 ≫ 0 | 66 min |
| E2 | What do 1000 epochs buy over 100? (H1) | R0 @100 vs E1 @1000; E1's per-epoch logs | 100 | per-region, per-submetric curves: *where* late gains land (object/table/background) | 7 min |
| E3 | Loss region (H2) | loss over full frame (=E2) / object only / object+table | 100 ×3, object-only @1000 ×1 | object-region submetrics; is the masked gain transient by 1000? | 14 + 66 min |
| E4 | Input: mosaic handled or not | raw mosaic vs mosaic + aligned bilinear demosaic RGB | 100 | all regions; expect render-side metrics move most | 7 min |
| E5 | Is late gain memorized static noise? (H1) | see below | eval-only first | stripe presence in *output* vs epoch, with and without stripes in the input | minutes |
| E6 | Metric sensitivity (H4) | no training; E1 checkpoints | — | multiplier decomposition per region; SAM by brightness decile; tail share (mean vs median, top-5% pixels); ∂SSC/∂metric at operating point; SSC-vs-epoch next to submetric-vs-epoch | minutes |
| E7 | Error bars | R0 @100, seeds ×3 | 100 ×3 | spread of every submetric; sets the noise floor for all 100-ep comparisons | 21 min |
| ENG | The speedup, re-measured | 1 epoch as shipped vs 1 epoch R0 | 1 ep | wall per epoch; August per-fix ladder cited as the record | ≈ 70 min |

Total ≈ 4.5 h of GPU without E5b.

## E5 in detail — the static-noise discriminator

Template T[b, x] = per-(band, column) mean of the high-passed GT over the
train set (the fixed-pattern stripes; August showed it correlates 0.95–0.998
across images).

- **E5a (eval-only, do first).** For E1 checkpoints at ep 10/100/300/1000:
  correlation of the prediction's column profile with T. Then feed the same
  checkpoints an input with T's projection removed from the mosaic. If the
  output stripes vanish → stripes are *copied from the input* (not
  memorized). If they persist and grow with epoch → memorized in weights,
  H1 supported.
- **E5b (training, only if E5a is ambiguous).** Two 1000-ep arms: targets
  with T subtracted (static noise removed) vs targets with a fresh random
  column pattern of the same amplitude per image (noise made non-static).
  If H1 holds, both arms' late-epoch gains vanish. Cost 2 × 66 min.

Also free from E1's logs: train-vs-val gap per region vs epoch. Memorizing
*static* (shared) noise gives no gap; memorizing per-image noise gives a
growing gap. Combined with E5a this separates copy / static-memorize /
per-image-memorize.

## Data prep (gating; small)

1. Region masks for all 178 images: object mask = August recipe (background
   threshold + morphology, CFA-pack aligned); table region = rows below a
   **single fixed y cut** — the rig is identical across images (paper stack
   y≈800–840, rail y≈840–880), so one constant, verified on contact sheets,
   should do; per-image overrides only if the sheets show it fails.
2. Split manifest: val weighted to cats 2/4, no adjacent indices, single-shot
   cat-4 objects preferred; public-test 11 folded into train.
3. Contact sheets for a visual sign-off before any run.

## Open questions

- Q1. Is E5b worth 2.2 h up front, or wait for E5a?
- Q2. Unclamped training: inside R0 (disclosed delta) or a separate arm?
- Q3. E4 at 100 ep only, or also at 1000 (66 min)?
- Q4. Do we spend one Kaggle submission on E0 for the external anchor?

---

# v2 amendments (2026-09-03, after discussion)

## Ordering

1. Data prep (masks, split, visual audit — the table cut is per-image where
   the rig moved; a constant row is only the starting guess).
2. **M-series: the metric study, model-free, before any training.**
3. Quick runs (100 ep): E7 seeds, E2-100, E3 (three arms), E4.
4. 1000-ep runs last: E1 (reference), E0 (parity), E3 object-only long.
   E2's "where late gains land" and E5a's epoch sweep wait for E1;
   E5a can be piloted on the 100-ep checkpoints.

Split honesty (H3) is read from the 100-ep run's per-category train-vs-val
readout already; E1 only confirms it at length.

## M-series — what does a score mean? (synthetic predictors)

Idea (Luka): take the GT, degrade it in a controlled, intuitive way, score
the degraded cube against the original with the recovered formula, and
read off what "actual performance" each score level corresponds to, per
metric and per region. Precedent: the August resolution ladder (pooled GT
upsampled: 512² → 0.535, 256² → 0.307, 128² → 0.136) and the degenerate
Kaggle submissions (floor 0.14). Cost: minutes; no model.

Each row is a degradation with a knob swept wide enough to span the scale:

| id | degradation ("synthetic predictor") | knob | what it isolates |
|---|---|---|---|
| M1 | keep every k-th band, linearly interpolate the rest | k = 2, 3, 4, 6 | spectral detail vs the smooth low-rank prior; SAM/SID/ERGAS sensitivity to fine spectral structure |
| M2 | project each spectrum onto top-k PCA components of train | k = 2, 4, 8, 12 | score of a perfect low-rank predictor (4 PCs = 99.3% variance) |
| M3 | spatial pool p then bilinear upsample | p = 2, 4, 8 | spatial component; redo of the August ladder under regions |
| M4 | iid Gaussian noise σ on every value | σ = 0.002 … 0.05 | brightness dependence: same σ → SAM by decile; how dark pixels dominate |
| M5 | spatial smoothing (box/Gaussian, w = 3, 5, 11) | w | how much the score *penalizes a cleaner prediction* — the stripes are in the GT, a denoised prediction loses; August: SAM(GT, destriped GT) ≈ 8° |
| M6 | column-template removal (destripe) | — | M5's targeted version: perfect prediction minus the static stripes |
| M7 | global / per-band gain (1+ε) | ε = ±1 … ±10% | what SAM ignores (scale) and what ERGAS/PSNR punish |
| M8 | clamp values below t to 0 | t = 0.005, 0.02 | SID's log blow-up on zeros; the floor lever |
| M9 | constant cubes (zeros, train mean, ones) | — | floor; cross-check against the Kaggle 0.140 / 0.140 / 0.091 |

Every row: six submetrics + SSC, full frame and per region (object / table /
background), on the val images. Two derived views: (a) SSC vs knob, all rows
on one axis — the "ruler"; (b) for M4, SAM by brightness decile at one σ —
the dark-pixel mechanism in one figure. Plus the analytic part: formula,
∂SSC/∂metric at a few operating points, and the exponential's knee.

Caution on knobs: dropping 1 pixel in 100 and interpolating is too mild to
register (spectra are smooth, 4 PCs ≈ 99%); sweep until the row spans
~0.14 → ~1.0 so each metric's knee is visible.
