# 01 — Decisions

Frozen choices. Each has a date and a one-line reason. Change = new dated entry, not an edit.

## Data

- **2026-09-03 · Regions.** Three per image: *object*, *table/rig*, *background*.
  The white paper sheet the object stands on stays inside *object* — masking it
  out is messy and it is a small pixel fraction. Consequence: the August
  table cut (`y_cut` at the object/paper contact, exp-04 §19) must be redrawn
  at the paper/rail boundary; *table* = the dark rail + clamp below the sheet.
- **2026-09-03 · Official public-test images fold into training.** Simpler;
  all experiments run on our own split anyway. (Noted: keeping them separate
  would allow extra analysis; rejected for simplicity.)
- **2026-09-03 · Split.** Our own train/val split, val weighted toward
  categories 2 and 4 (novel objects); categories 1 and 3 are re-posed copies of a
  few objects. Exact manifest to be produced in `data/`.

## Training

- **2026-09-03 · Architecture.** Official Raw2HSI baseline only. No variants.
- **2026-09-03 · Training length.** Simplify: one working length plus the
  official 1000-epoch reference. Working length provisionally 100 epochs;
  no intermediate rungs unless an experiment needs one. (Luka: "get the point
  across as simply as possible".)

## Code

- **2026-09-03 · One file if possible.** New trainer written minimal, clean,
  and small, taking inspiration from exp-00 (baseline model, speedups) and
  exp-04 (masks, split, per-region official-formula evaluator). Not a merge
  of the two — a rewrite that contains only what Paper 1's experiments need.
  The 1000-epoch baseline number (Kaggle 0.23888, local proxy curve) is the
  parity check that the port preserved the recipe.

## Reporting

- **2026-09-03 · Readout.** Six submetrics per region are primary; SSC
  secondary. Scorer deployment on Kaggle is unresolved and stated as such.
