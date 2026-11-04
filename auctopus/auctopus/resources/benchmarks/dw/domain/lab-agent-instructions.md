# Instructions for the experimentalist

You operate the DiscoveryWorld environment. Each run packet gives a protocol to execute, a hypothesis under test and the files to return. Start every run by reading the protocol and the current observation, locate the named objects (teleport to them by uuid), take the control measurement first when the protocol asks for one, record every instrument reading exactly as the environment returns it, and stop when the protocol's stopping rule or the action budget is reached. Enter a final answer into a device only when the protocol's decision rule is satisfied by the readings.

Record every departure from the protocol (an object that could not be found, an action that kept failing, a step skipped) in `deviations.md`, with the step number and the reason.

## The exchange folder

Auctopus places each run packet in the laboratory's working folder and starts the experimentalist with the run id.

```
inbox/<run-id>/        written by Auctopus
    RUN-REQUEST.json   the run id and the packet's files with their SHA-256 hashes
    protocol.md        the protocol
    results_schema.md  the raw files to return, with their format
    analysis/          the analysis code (run by the computational researcher)
outbox/<run-id>/       written by the experimentalist
    RUN-RESULT.json    the outcome (below), written last
    data/              trajectory.jsonl, notes.md, final_knowledge.md, environment.log
    deviations.md      everything that differed from the protocol, with steps and reasons
```

## RUN-RESULT.json

```json
{
  "run_id": "<run-id>",
  "status": "done | aborted | failed",
  "started": "2026-01-01T09:00:00",
  "finished": "2026-01-01T15:30:00",
  "files": ["data/trajectory.jsonl"],
  "deviations": "none | see deviations.md",
  "notes": "one paragraph of plain facts"
}
```

`done` means the protocol ran to its stopping rule or the action budget and every file in `results_schema.md` is present.
