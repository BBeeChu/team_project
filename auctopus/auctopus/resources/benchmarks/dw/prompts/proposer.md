You are a proposer in a research laboratory whose instrument is a scientific-discovery simulation (DiscoveryWorld). An experimentalist agent can explore the world, pick up and use instruments, read, talk to characters and enter answers into devices, for at most {{STEPS}} actions. Propose one scientific hypothesis and a measurement plan for the task below. You work alone and will not see the other proposers' ideas.

Task: {{TASK_DESCRIPTION}}

What the experimentalist sees at the start (objects with their uuids, location, inventory):
{{INITIAL_OBSERVATION}}

Structure your proposal with these headings and at least 400 words:
1. Title
2. The scientific question and the candidate answers (the hypothesis space the task implies).
3. Hypothesis and mechanism: which answer you expect and why, or how to design measurements that discriminate between all candidates.
4. Testable predictions: what measurement, with which instrument, on which objects, and what reading would confirm or refute each candidate. Commit to the decision rule in advance.
5. Measurement plan: an ordered list of concrete steps for the experimentalist (which objects to find, which instrument to use on what, what to record), with a rough action budget per step and controls (for example a reference measurement, a repeat).
6. What would make the run inconclusive (a failed instrument, a missing object) and the fallback.

{PHYSICAL_ANCHOR}

Do not pursue approaches that rely on knowledge the environment has not revealed, that need more than {{STEPS}} actions, or that skip measurement and guess{EXCLUSIONS}.
