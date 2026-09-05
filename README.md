# Paper 1 — the Hyper-Object challenge, measured on its own baseline

Clean restart (2026-09-03). One architecture (the official Raw2HSI baseline),
one frozen data protocol, one frozen recipe; every claim is a controlled
comparison with the six submetrics as the primary readout.

- `notes/` — thinking, decisions, experiment plan (start with `notes/00-start.md`)
- `data/` — split manifests, region masks + overrides, audit contact sheets (committed, small)
- `src/` — ported code, cleaned; provenance of every file in `notes/02-provenance.md`
- `runs/` — checkpoints on the box (ignored); `logs/` — per-run CSV/log (committed)
- `figs/` — figures; `paper/` — the write-up (Typst)

Old material lives in `../report/` (replication reports, exp-00..04) and is
read-only from here: nothing is trusted until it is re-run under this protocol.
