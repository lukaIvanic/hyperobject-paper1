# Experiment plan (v3, 2026-09-04 — under discussion)

Referencing convention: number *and* name, e.g. "T2 (the clamp ablation)",
"M8 (zero-clamping)". M = metric-study rows, T = training runs.

One architecture: the official Raw2HSI baseline. Two training lengths:
**100 epochs** (the working length) and **1000 epochs** (the official
reference). One RTX 5090. The baseline runs ≈ 4 s/epoch on our pipeline,
so a 100-epoch run is ≈ 7 min and a 1000-epoch run ≈ 66 min, plus a 43 s
preload.

## Order of work

1. Data prep — masks, split, visual audit.
2. The metric study (M1–M9) — model-free, before any training.
3. The quick runs (T1–T4) — 100 epochs each, ≈ 40 min of GPU in total.
4. The long runs (T5–T8) — 1000 epochs each, ≈ 3.3 h in total, plus the speedup
   re-measure.
5. Seeds (T9) — three repeats of the working run, only after the whole pass,
   so that a change upstream does not cost them twice.

---

## The recipe

The official baseline recipe **exactly as shipped**: AdamW 2e-4 with cosine
decay, loss L1 + 0.1·SAM, fp16 mixed precision, official batch size, and
the model's output clamped to [0, 1] during training. It runs on our
optimized pipeline (same mathematics, ≈1000× faster) and on our split. The
only delta is the August code repairs without which the shipped script
does not run (an undefined variable, a wrong reduction axis in the
metrics).

The clamp is the one thing we already know is problematic (August found
output channels that drift negative die permanently under it). It is *not*
folded into the recipe by decision. It gets its own quick run — T2,
the clamp ablation — and the metric study first tells us how to read
that run's result.

Every run logs, every few epochs, on the validation images and on a fixed
subset of training images: the six submetrics (SAM, SID, ERGAS, PSNR,
SSIM, ΔE00) for each region (object, table, background, full frame) and the
composite score. Logs are CSV, committed. Every experiment changes exactly
one thing against a named comparison run.

## Data prep

- Region masks for all 178 images. *Object* = the August recipe
  (brightness threshold on the ground truth, morphology, aligned to the
  2×2 filter pattern); the white sheet stays inside the object. *Table* =
  the dark rail and clamp below the sheet, cut by a row boundary — a
  single constant row is only the starting guess, the rig moves in some
  images, so each cut is checked on contact sheets. *Background* = the
  rest.
- Split manifest: validation weighted toward categories 2 and 4 (the novel
  objects); never two adjacent indices (adjacent = the same book, cover and
  spine); category-4 picks prefer single-shot objects; the 11 official
  public-test images fold into training.
- Contact sheets for a visual sign-off before anything runs.

## The metric study (M1–M9) — what does a score mean?

Model-free. Take the ground truth, degrade it in a controlled, intuitive
way, score the degraded cube against the original with the recovered
formula, and read off what actual performance each score level corresponds
to — per metric and per region. Minutes per row.

Precedents: the August resolution ladder (pooled ground truth upsampled
back: 512² scored 0.535, 256² scored 0.307, 128² scored 0.136) and the
degenerate Kaggle submissions (floor 0.140).

**The principle of every sweep:** start from an error a person would call
trivial and unimportant — one pixel in a hundred interpolated, one band in
ten — and measure exactly how much the score punishes it. Then make the
error progressively less trivial and follow the response. The curve from
trivial to severe *is* the result; nothing is pre-judged as too mild to
register.

| # | synthetic predictor | knob, from trivial upward | what it isolates |
|---|---|---|---|
| M1 | **dropped pixels**, interpolated back (bilinear) | 1 in 100 → 1 in 10 → 1 in 2 → pool 2, 4, 8 | spatial error: the spatial component and its spectral side-effects |
| M2 | **dropped bands**, interpolated back (linear) | 1 in 10 → 1 in 4 → every other band | fine spectral structure vs the smooth prior; SAM/SID/ERGAS sensitivity |
| M3 | **low-rank spectra** (projection onto the top-k principal components of the training set) | k = 12 → 8 → 4 → 2 | the score of a perfect predictor that knows only the low-dimensional structure (4 components ≈ 99.3% of variance) |
| M4 | **added noise** (iid Gaussian, one σ everywhere) | σ = 0.001 → 0.05 | brightness dependence: the same σ, SAM by brightness decile — the dark-pixel mechanism |
| M5 | **smoothing** (box or Gaussian) | width 3 → 11 | how much the score penalizes a prediction *cleaner* than the ground truth |
| M6 | **destriping** (the static column template removed) | — | smoothing, targeted: a perfect prediction minus the stripes. August: SAM between the ground truth and its own destriped version ≈ 8° |
| M7 | **gain error** (multiply by 1+ε, global or per band) | ε = ±1% → ±10% | what SAM ignores (scale) vs what ERGAS and PSNR punish |
| M8 | **zero-clamping** (values below t set to 0) | t = 0.001 → 0.02 | SID's logarithm blowing up on exact zeros; the submission-floor lever; the eval-side half of the clamp question (T2) |
| M9 | **constant cubes** (zeros, training-mean spectrum, ones) | — | the floor; cross-check against Kaggle 0.140 / 0.140 / 0.091 |

Every row: six submetrics plus the composite, full frame and per region, on
the validation images. Derived views: the "ruler" (composite score vs knob,
all rows on one axis); the noise row at one σ, SAM by brightness decile;
and the analytic part — the formula, the slope of the composite against
each submetric at a few operating points, the exponential's knee. Outcome:
a table a reader can use to translate any score, ours or the leaderboard's,
into a concrete kind and size of error.

## The quick runs (T1–T4, 100 epochs each)

Every run is the recipe on our split unless stated. Each changes one thing
against the run it names.

| # | run | question | what changes | compared against | readout that decides | cost |
|---|---|---|---|---|---|---|
| T1 | **the working run** | the reference for everything at 100 epochs; also *split honesty*: is the train/val gap real once the split is honest? | nothing | — | per-region submetrics; per-category train-vs-val gap: categories 1 and 3 ≈ 0, categories 2 and 4 ≫ 0 | 7 min |
| T2 | **the clamp ablation** | what does the training-time clamp do? | output unclamped during training; clamped and floored at 0.005 for evaluation | T1 the working run | dead output channels (fraction of exact zeros per band); SID and ERGAS; M8 (zero-clamping) says how to read it | 7 min |
| T3 | **the loss region** | does masking help, and how much? | loss over the object only; loss over object + table | T1 the working run (full-frame loss) | object-region submetrics | 14 min |
| T4 | **the input** | does handling the mosaic help? | mosaic + an aligned bilinear color interpolation as extra input planes | T1 the working run | all regions; the render-side metrics are expected to move most | 7 min |

Decision point after these: whichever clamp setting wins becomes the
setting for the long runs. If that is the unclamped one, T3 and T4 are repeated under it (≈ 30 min) so the long runs and the
quick runs share one recipe.

## The long runs (T5–T8, 1000 epochs each)

| # | run | question | what changes | compared against | readout that decides | cost |
|---|---|---|---|---|---|---|
| T5 | **the long reference** | what do 1000 epochs buy over 100? | nothing but length | T1 the working run | per-region, per-submetric curves over 1000 epochs — *where* the late gains land; confirms split honesty at length | 66 min |
| T6 | **the long masked run** | is the masking gain transient? | the winning loss region from T3 | T5 the long reference | the gap at 1000 epochs vs the gap at 100 | 66 min |
| T7 | **the parity run** | did the rewrite preserve the recipe? | the *official* split instead of ours | the August exp-00 record | curve in family with exp-00; Kaggle 0.239 if we submit | 66 min |
| T8 | **the speedup re-measure** | is the ≈1000× real? | one epoch as shipped vs one epoch on our pipeline | — | wall time per epoch; the August per-fix ladder is cited as the record | ≈ 70 min |

## Seeds (T9)

Three repeats of the working run (T1) with different seeds, run last. They set
the noise floor for every quick-run comparison. ≈ 21 min.

## Secondary — needs its own discussion before it is planned

**The static-noise question.** Is the late-epoch gain memorized static
noise (the column stripes shared across the dataset)? Hard to get right;
not on the critical path. Sketch for the discussion: estimate the
per-(band, column) stripe template from the training ground truth; probe
T5's (the long reference's) checkpoints for stripe presence in the *output*
across epochs, then feed the same checkpoints an input with the template
projected out — stripes vanish means copied from the input, stripes persist
and grow means memorized. Training arms (destriped targets, per-image
randomized stripes) only if that probe is ambiguous. T5's
per-region train-vs-val curves are a free third angle.

## Open decisions

- Should T4 (the input) also be run at 1000 epochs (another 66 min)?
- Do we spend one Kaggle submission on T7 (the parity run) for the external
  anchor?
