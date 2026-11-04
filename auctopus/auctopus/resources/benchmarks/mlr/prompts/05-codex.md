You are the computational researcher. This folder holds the manuscript skeleton `main.md`, the proposal `proposal.md`, the literature review `related_work.md` and the experiment design `experiment.md`. Carry out `experiment.md` end to end:

1. Read every file, then plan the runs and the time budget (about one hour of computation; use subsets and small models rather than exceeding it).
2. Write the code in `code/` and run it. Every reported number must come from a run in this folder; save raw outputs (CSV or JSON) under `results/`.
3. Write `results/results.md`: the exact commands, the configurations, the tables of results with means and variability over seeds, the figures (PNG files under `figures/`, referenced by relative path), and for every precommitted prediction a line stating the locked threshold, the observed value, and the verdict (confirmed, refuted or inconclusive by the decision rule). Report failed controls as failed; do not reinterpret the decision rule.
4. Complete `main.md` into the full paper: Abstract, Introduction, Related Work, Method, Experimental Setup, Results (the same tables and figures), Discussion (predictions versus observations, controls, limitations), References. Keep every number identical to `results/results.md`.
5. Update NOTES-RESUME.md and finish with ROUND-DONE.json.

If something cannot be run (a missing dataset, an impossible dependency), scale the experiment down to what can be run, say so in results.md and main.md, and never fill the gap with invented numbers.
