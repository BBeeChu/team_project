Design the computational experiment that the computational researcher will run unattended. Your reply becomes experiment.md, its first task. Specify:

1. Datasets: public datasets (name the loader, for example Hugging Face datasets) or a synthetic generator with its parameters; subset sizes so that everything runs on a CPU, or one GPU if available, within about one hour.
2. Models and baselines: small open models or classical methods; list each run (configuration, seeds).
3. Metrics and the exact decision rule for each precommitted prediction, copied verbatim from the plan.
4. Controls: the control runs and what a failed control means for the conclusion (inconclusive, not negative).
5. Deliverables: `code/` with every script, `results/results.md` with the tables of real numbers and the exact commands used, figures as PNG under `figures/`, and the completed manuscript `main.md` with Abstract, Results (tables and figures with provenance) and Discussion that compares each precommitted prediction with the observed result and says confirmed, refuted or inconclusive.
6. A fallback: the smallest experiment that still tests H1 if the full plan does not fit the time budget.
