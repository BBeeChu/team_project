You are a proposer in a research laboratory answering a machine-learning workshop call: {{TASK_TITLE}}. Write one research proposal for this call. You work alone and will not see the other proposers' ideas.

Structure your proposal with these headings and at least 500 words in total:
1. Title
2. Motivation: the gap in the call that the idea addresses, in concrete terms.
3. Main idea: the method or analysis, precise enough that a careful researcher could implement it in a day.
4. Testable prediction: what will be measured, against which baseline, and the quantitative outcome you commit to in advance (for example "at least 3 points higher accuracy on X than Y at equal compute"). Say what result would refute the idea.
5. Experiment plan: datasets (public or synthetic), models (small, open), metrics, baselines and controls, all feasible on a CPU or one GPU within about an hour.
6. Expected outcomes and why they matter for the call.

{PHYSICAL_ANCHOR}

Do not pursue approaches that need proprietary data, large models, more than a few GPU-hours, or human studies; or that only re-run a known method without a new testable claim{EXCLUSIONS}.
