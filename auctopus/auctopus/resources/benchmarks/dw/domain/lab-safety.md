# Safety rules

The instrument is a simulation; there is no physical hazard. The rules protect the integrity of the experiment:
- Never exceed the run's action budget of {{STEPS}} actions.
- Never read or write files outside `outbox/<run-id>/`, and never consult the environment's scorecard or oracle data.
- Record readings exactly as the environment returns them; never edit or invent a reading.
- Enter a final answer into a device only when the protocol's decision rule is met; otherwise leave the answer unentered and report the run as inconclusive in deviations.md.
