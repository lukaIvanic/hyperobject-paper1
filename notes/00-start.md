# 00 — Starting notes (2026-09-03)

Status: thought stream from the kickoff conversation, lightly organized.
Nothing here is decided until it is moved to `01-decisions.md`.

## Why a clean restart

The August work (`../report/`) produced five experiment reports, a 14-page
draft, and a lot of results that contradict each other across protocols
(full-frame vs masked, official split vs val12, pooled vs full-res). It is
hard to say what is new, what is old, and what to trust. Paper 1 fixes the
architecture to the official baseline and rebuilds the story bottom-up on
one protocol, so every effect is attributable.

## Deliverable and deadline

Prof. Štajduhar (email, early Sept): document only the essentials —
experimental methodology, dataset, learning methods, most important results;
skip the obvious. Report due ≈ 11–13 Sept 2026, then ≤30 min presentation
incl. discussion. Plan: write 2–3 paper-like pieces, then condense. English.
Part II (self-distillation) dropped. Slides last.

## Scope of Paper 1

In: dataset overhaul (census, honest split, region masks: object / table /
background), the metric (formula, floor, sensitivity), the engineering note
(≈1000× baseline speedup, one table), and controlled experiments on the
baseline architecture only: loss region, input type, training length, split
honesty, the static-noise hypothesis, seeds.

Out: any architecture change (MST++, UNet, ensembles) — that is Paper 2.

## Luka's hypotheses (as stated, to be tested — not conclusions)

H1. *Everyone trains absurdly long* (baseline 1000 ep, winner 3000 ep) and the
    score keeps rising with epochs. Suspected cause: static noise in the GT
    (vertical column stripes and other fixed-pattern noise) is shared across
    the whole dataset incl. train and test-private; small conv nets cannot
    memorize it fast (huge output per tiny input, translation-invariant), but
    they slowly capture it, and that is what late epochs buy.
H2. Masking out background + table should therefore help most in the short
    regime (100 ep target instead of 1000), because the model spends capacity
    on the object instead of on noise.
H3. Train and val losses showed no difference — concerning; suspected to be
    an artifact of the official split (categories 1/3 are re-posed copies of the
    same few objects).
H4. The SSC score is doubly sensitive: submetrics (SAM, SID, ERGAS) blow up
    on low-intensity pixels and outliers (which may just be the unlearnable
    stripes), and the aggregate is exponential on top of that. Small real
    differences become large score differences, so it is unclear what a
    "good" architecture or method even is under this metric; leaderboard
    score may correlate with raw epoch count as much as with modeling.

## What the old evidence already says (to be re-verified here)

- H3: **supported.** exp-04 §18.2/§19.5 — on cats 2/4 val SAM is 2–3× train
  at matched brightness; on cats 1/3 there is no gap. The official split
  validated only on the repetitive categories.
- H2: **supported in the short regime, transient later.** exp-04 §8/§14 —
  masked loss 3.3× at 100 ep (UNet), tie by ~300 ep (MST).
- H1: **evidence leans against the memorization reading**, so it needs a
  discriminating experiment rather than a narrative:
  - the model's output already contains the stripes and they are present in
    the mosaic *input* (template correlates 0.996 with GT and with pred, 0.002
    with residual) — copied locally, not memorized (exp-03);
  - SAM vs stripe amplitude dose-response is flat (exp-04 §18.3);
  - the long-training gains behaved like update starvation (exp-04 §14:
    1000 ep × 167 images at small batch ≈ tens of thousands of steps).
  Counter-point (Luka): each image is ~64M output values, so "steps" is not
  the whole story either. Both readings are live.
  Discriminators to run: (a) train on targets with the static column
  template removed / stripes randomized per image — do late gains vanish?
  (b) per-region (object/table/background) train-vs-val curves over 1000 ep
  — where do late gains land, and do they appear on train only?
  (c) stripe presence in the *output* vs epoch, and with stripes removed
  from the input.
- H4: **partly measured.** Formula recovered from bytecode (validated 0.558
  vs 0.571 on a published anchor); floor 0.14 from degenerate submissions;
  SID log blows up on zeros; per-pixel SAM p95 ≈ 17° vs median 4.4°;
  SSC = product of five per-metric multipliers (exp-04 §17.1) — a clean
  sensitivity analysis is still to be done on the baseline.
  Deployment of the scorer on Kaggle is NOT settled: the "2× pooled cubes"
  hypothesis fits two anchors but is not in their eval code; Luka is
  skeptical. State it as unresolved.

## Conventions (proposed)

- Primary readout: the six submetrics (SAM, SID, ERGAS, PSNR, SSIM, ΔE00)
  per region; SSC secondary (near the floor at 100 ep it is uninformative).
- Three regions per image: object, table/rig, background. Train masks must
  be redone: August masks excluded background only, table was left in.
- Our own train/val split, val weighted toward cats 2/4 (novel objects).
- One recipe; every experiment changes exactly one thing; ≥3 seeds on the
  config that carries a headline claim. Runs <10 min where possible; 1000-ep
  baseline (66 min) is the reference, run rarely.
- Every ported file gets a provenance line; every number in the paper traces
  to a committed log.

## Next

1. Freeze decisions → `01-decisions.md` (regions, split, recipe, epochs).
2. Data prep: masks with table region for all images; manifests in `data/`.
3. Port code (`02-provenance.md`): trainer, evaluator, mask tools, speedups.
4. Experiment plan with budgets → `03-experiments.md`.
