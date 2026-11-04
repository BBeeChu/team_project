# Instructions for the experimentalist

[insert: your standing instructions for the experimentalist: how to run a packet on this instrument, which calibrations start every run, and how to report deviations and failed controls.]

## The exchange folder

Auctopus places each run packet in the laboratory's working folder (`lab.remote_root`) and starts the experimentalist with the run id. In manual mode (`lab.transport = "manual"`) the same layout lives in a shared folder (`lab.exchange_dir`) and is carried by hand.

```
inbox/<run-id>/        written by Auctopus
    RUN-REQUEST.json   the run id and the packet's files with their SHA-256 hashes
    protocol.md        the protocol
    results_schema.md  the raw files to return, with their format
    analysis/          the analysis code (run by the computational researcher)
outbox/<run-id>/       written by the experimentalist
    RUN-RESULT.json    the outcome (below), written last
    data/              the raw data, run logs, instrument settings and calibration runs
    deviations.md      everything that differed from the protocol, with times and reasons
```

## RUN-RESULT.json

```json
{
  "run_id": "<run-id>",
  "status": "done | aborted | failed",
  "started": "2026-01-01T09:00:00",
  "finished": "2026-01-01T15:30:00",
  "files": ["data/run.log"],
  "deviations": "none | see deviations.md",
  "notes": "one paragraph of plain facts"
}
```

`done` means every protocol step ran and every file in `results_schema.md` is present.
