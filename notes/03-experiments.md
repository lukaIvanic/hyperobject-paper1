# 03 — Experiment plan (v2, 2026-09-03 — under discussion)

Architecture fixed: the official Raw2HSI baseline. Two training lengths
only: 100 epochs (working) and 1000 (the official reference). One RTX 5090;
the baseline runs ≈ 4 s/epoch on our pipeline → 100 ep ≈ 7 min, 1000 ep ≈
66 min, plus a 43 s preload.

## Order of work

1. **Data prep** — masks, split, visual audit.
2. **M-series** — the metric study, model-free, before any training.
3. **Quick runs** (100 ep, T1–T3) — the working run, loss region, input.
4. **Long runs** (1000 ep, T4–T6) and the speedup re-measure.
5. **Seeds ×3** (T8) — only after the whole pass, so a change upstream does not cost them twice.

---

## 0. The fixed recipe (R0)

The official baseline recipe verbatim — AdamW 2e-4 cosine, L1 + 0.1·SAM,
fp16 AMP, official batch size, official (repaired) code semantics — on our
optimized pipeline and our split. Two deltas from "as shipped", both from
the August audit, both disclosed: (i) train unclamped, clamp + floor 0.005
at eval (the dead phase-channel fix); (ii) numerically repaired metrics.
Open: whether (i) lives inside R0 or is its own arm (Q1).

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
- Split manifest: val weighted toward categories 2/4 (novel objects); no adjacent
  indices (adjacent = same book, cover/spine); category-4 picks prefer
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

## 3. Training experiments (in execution order)

Every run is R0 on our split unless stated. Each row changes one thing
relative to the row it names.

| # | question | arm | vs | length | readout that decides | cost |
|---|---|---|---|---|---|---|
| T1 | the working run; also: split honesty (H3) | R0 | — | 100 | per-region submetrics; per-category train-vs-val gap: cats 1/3 ≈ 0, cats 2/4 ≫ 0 | 7 min |
| T2 | loss region (H2) | loss on object only; loss on object + table | T1 (full-frame loss) | 100 ×2 | object-region submetrics | 14 min |
| T3 | input: mosaic handled or not | mosaic + aligned bilinear demosaic RGB | T1 | 100 | all regions; expect render-side metrics to move most | 7 min |
| T4 | what do 1000 epochs buy? (H1) | R0 | T1 | 1000 | per-region, per-submetric curves over 1000 ep — *where* late gains land; confirms H3 at length | 66 min |
| T5 | is the masked gain transient? | best T2 loss region | T4 | 1000 | gap to T4 at 1000 vs gap to T1 at 100 | 66 min |
| T6 | did the rewrite preserve the recipe? | R0 on the *official* split | exp-00 record | 1000 | curve in family; Kaggle 0.239 if submitted (Q3) | 66 min |
| T7 | the speedup, re-measured | 1 epoch as shipped vs 1 epoch R0 | — | 1 ep | wall per epoch; the August per-fix ladder cited as the record | ≈ 70 min |
| T8 | error bars — **after the full pass, not before** | T1 config, seeds ×3 | T1 | 100 ×3 | spread of each submetric per region; sets the noise floor for T1–T3 | 21 min |

T1–T3 ≈ 30 min of GPU; T4–T6 ≈ 3.3 h; T8 last, once nothing upstream is
going to change (a change would otherwise cost the seeds again).

## 4. Secondary — needs its own discussion before it is planned

**The static-noise discriminator (H1).** Is the late-epoch gain memorized
static noise? Hard to get right; not on the critical path. Sketch kept for
the discussion: template T[b, x] = per-(band, column) mean of high-passed
train GT (August: correlates 0.95–0.998 across images). Eval-only probe on
T4 checkpoints: stripe presence in the *output* vs epoch, then the same
checkpoints on an input with T projected out — vanish means copied from the
input, persist-and-grow means memorized. Training arms (destriped targets;
per-image randomized stripes) only if the probe is ambiguous. T4's
per-region train-vs-val curves are a free third angle.

## Open questions

- Q1. Unclamped training: inside R0 as a disclosed delta, or its own arm?
- Q2. T3 at 100 ep only, or also at 1000?
- Q3. One Kaggle submission on T6 for the external anchor?
