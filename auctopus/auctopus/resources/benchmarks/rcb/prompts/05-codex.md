You are the computational researcher. This workspace holds the raw data in `data/` (read-only), the reference papers in `related_work/`, the report skeleton `report/report.md`, the positioning note and the analysis design `experiment.md`. Carry out `experiment.md` end to end:

1. Read the design, then inspect the data files (shapes, columns, missing values) and skim the reference papers (pymupdf4llm or pypdf) for the published numbers to compare against.
2. Write the code in `code/` and run it; save intermediate results under `outputs/` as CSV or JSON. Every number you report must come from a run in this workspace.
3. Produce the figures as PNG files under `report/images/` and reference them in the report as `images/<name>.png`.
4. Complete `report/report.md`: Abstract, Introduction, Data, Methods, Results (tables and figures, with means and uncertainty), a comparison of each precommitted prediction with the observed value and its verdict (confirmed, refuted or inconclusive by the decision rule), Discussion against the reference papers, Limitations. Failed controls are reported as failed and make the affected conclusion inconclusive.
5. Update NOTES-RESUME.md and finish with ROUND-DONE.json.

If a step cannot be run, scale down to what can be run, say so in the report, and never fill the gap with invented numbers.
