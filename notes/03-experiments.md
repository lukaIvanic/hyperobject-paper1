# 03 — Experiment plan (v2, 2026-09-03 — under discussion)

Architecture fixed: the official Raw2HSI baseline. Two training lengths
only: 100 epochs (working) and 1000 (the official reference). One RTX 5090;
the baseline runs ≈ 4 s/epoch on our pipeline → 100 ep ≈ 7 min, 1000 ep ≈
66 min, plus a 43 s preload.

## Order of work

1. **Data prep** — masks, split, visual audit.
2. **M-series** — the metric study, model-free, before any training.
3. **Quick runs** (100 ep) — seeds, training length, loss region, input.
4. **Long runs** (1000 ep) — last; nothing quick depends on them.

---

## 0. The fixed recipe (R0)

The official baseline recipe verbatim — AdamW 2e-4 cosine, L1 + 0.1·SAM,
fp16 AMP, official batch size, official (repaired) code semantics — on our
optimized pipeline and our split. Two deltas from "as shipped", both from
the August audit, both disclosed: (i) train unclamped, clamp + floor 0.005
at eval (the dead phase-channel fix); (ii) numerically repaired metrics.
Open: whether (i) lives inside R0 or is its own arm (Q2).

Every run logs, every K epochs, on val and on a fixed train subset: the six
submetrics per region (object / table / background / full) and SSC. CSV
committed under `logs/`. Every experiment changes exactly one thing.

## 1. Data prep

- Region masks for all 178 images. Object = the August recipe (brightness
  threshold on the GT, morphology, CFA-pack aligned; the white sheet stays
  inside object). Table = the dark rail and clamp below the sheet, cut by a
  row boundary; a single constant row is only the starting guess — the rig
  moves in some images, so the cut is verified per image on contact sheets.
  Background = the rest.
- Split manifest: val weighted toward cats 2/4 (novel objects); no adjacent
  indices (adjacent = same book, cover/spine); cat-4 picks prefer
  single-shot objects; the official public-test 11 fold into train.
- Contact sheets for a visual sign-off before anything runs.

## 2. M-series — what does a score mean? (model-free)

Take the ground truth, degrade it in a controlled and intuitive way, score
the degraded cube against the original with the recovered formula, and
read off what "actual performance" each score level corresponds to, per
metric and per region. No model. Minutes per row.

Precedents: the August resolution ladder (pooled GT upsampled: 512² →
0.535, 256² → 0.307, 128² → 0.136) and the degenerate Kaggle submissions
(floor 0.140).

**The principle of each sweep:** start from an error a person would call
trivial and unimportant — one pixel in a hundred interpolated, one band in
ten — and measure exactly how much the score punishes it. Then make the
error progressively less trivial and follow the response. The curve from
"trivial" to "severe" *is* the result; nothing is pre-judged as too mild
to register.

| id | synthetic predictor | knob, from trivial upward | what it isolates |
|---|---|---|---|
| M1 | drop pixels, interpolate them back (bilinear) | 1 in 100 → 1 in 10 → 1 in 2 → pool 2/4/8 | spatial error; the spatial component and its spectral side-effects |
| M2 | drop bands, interpolate them back (linear) | 1 in 10 → 1 in 4 → every other band | fine spectral structure vs the smooth prior; SAM/SID/ERGAS sensitivity |
| M3 | project spectra onto top-k PCA components (train-fit) | k = 12 → 8 → 4 → 2 | score of a perfect low-rank predictor (4 PCs ≈ 99.3% variance) |
| M4 | add iid Gaussian noise σ | σ = 0.001 → 0.05 | brightness dependence: one σ, SAM by brightness decile — the dark-pixel mechanism |
| M5 | spatial smoothing (box / Gaussian) | w = 3 → 11 | how much the score penalizes a prediction *cleaner* than the GT |
| M6 | remove the static column template (destripe) | — | M5 targeted: a perfect prediction minus the stripes. August: SAM(GT, destriped GT) ≈ 8° |
| M7 | global or per-band gain (1+ε) | ε = ±1% → ±10% | what SAM ignores (scale) vs what ERGAS/PSNR punish |
| M8 | clamp values below t to zero | t = 0.001 → 0.02 | SID's log blow-up on exact zeros; the submission-floor lever |
| M9 | constant cubes: zeros, train-mean spectrum, ones | — | the floor; cross-check vs Kaggle 0.140 / 0.140 / 0.091 |

Every row: six submetrics + SSC, full frame and per region, on the val
images. Derived views: (a) SSC vs knob for all rows on one axis — the
"ruler"; (b) M4 at one σ, SAM by brightness decile; (c) the analytic part:
the formula, ∂SSC/∂metric at a few operating points, the exponential's
knee. Outcome: a table a reader can use to translate any score, ours or the
leaderboard's, into a concrete kind and size of error.

## 3. Training experiments

| # | question | arms (one change each) | length | readout that decides | cost |
|---|---|---|---|---|---|
| E7 | error bars | R0, seeds ×3 | 100 | spread of each submetric per region — the noise floor for every 100-ep comparison | 21 min |
| E2 | what do 1000 epochs buy over 100? (H1) | R0 @100 vs E1 @1000 | 100 | per-region, per-submetric; later, E1's curves: *where* late gains land | 7 min |
| E3 | loss region (H2) | full frame (= E2) / object only / object + table | 100 ×3 | object-region submetrics | 14 min |
| E4 | input: mosaic handled or not | raw mosaic vs mosaic + aligned bilinear demosaic RGB | 100 | all regions; expect render-side metrics to move most | 7 min |
| H3 | split honesty | read from any 100-ep run | — | per-category train-vs-val gap: cats 1/3 ≈ 0, cats 2/4 ≫ 0 | free |
| E5 | is late gain memorized static noise? (H1) | see below | eval-only first | stripe presence in the *output*, with and without stripes in the input | minutes |
| E1 | 1000-ep reference on our split | R0 | 1000 | per-region curves over 1000 ep; confirms H3 at length; checkpoints for E5 | 66 min |
| E3L | is the masked gain transient? | object-only loss | 1000 | vs E1 at 1000: gap gone or not | 66 min |
| E0 | did the rewrite preserve the recipe? | R0, *official* split | 1000 | curve in family with exp-00; Kaggle 0.239 if submitted (Q4) | 66 min |
| ENG | the speedup, re-measured | 1 epoch as shipped vs 1 epoch R0 | 1 ep | wall per epoch; the August per-fix ladder cited as the record | ≈ 70 min |

Total ≈ 4.5 h of GPU, quick runs ≈ 50 min of it.

### E5 — the static-noise discriminator

Template T[b, x] = per-(band, column) mean of high-passed GT over the train
set (the fixed-pattern stripes; August: correlates 0.95–0.998 across
images).

- **E5a, eval-only (do first; pilot on 100-ep checkpoints, sweep on E1's).**
  Correlation of the prediction's column profile with T, per epoch. Then
  the same checkpoints on an input with T's projection removed from the
  mosaic. Stripes vanish → copied from the input, not memorized. Stripes
  persist and grow with epoch → memorized in weights; H1 supported.
- **E5b, training (only if E5a is ambiguous).** Two 1000-ep arms: targets
  with T subtracted (static noise removed) vs targets with a fresh random
  column pattern of the same amplitude per image (noise made non-static).
  If H1 holds, both arms' late-epoch gains vanish. 2 × 66 min.
- Free from E1's logs: train-vs-val gap per region vs epoch. Memorizing
  *static* (shared) noise gives no gap; memorizing per-image noise gives a
  growing gap. With E5a this separates copy / static-memorize /
  per-image-memorize.

## Open questions

- Q1. E5b: commit 2.2 h now, or wait for E5a?
- Q2. Unclamped training: inside R0 as a disclosed delta, or its own arm?
- Q3. E4 at 100 ep only, or also at 1000?
- Q4. One Kaggle submission on E0 for the external anchor?
