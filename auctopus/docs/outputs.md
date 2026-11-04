# Run outputs and file contracts

Use this reference to locate a run's evidence and interpret its saved files. Follow [Running](running.md) for commands, approval procedures and recovery.

`<run>` means the workflow's run folder or name. `<run-id>` identifies one acquisition: one execution of the run packet on the instrument. A run can contain several acquisitions, each with its own returned files.

## Open the audit trail first

1. Read `decisions-journal.md` for timestamped decisions, then `pipeline.log` for the full log. The console shows the same log lines with timestamps.
2. Check `state.json` for the saved resume point. Read any `RUN-BLOCKED.md`, `RUN-STOPPED.md`, laboratory approval note or `RUN-DONE.json` present.
3. Read `pi-verdict.md` for the principal investigator's (PI's) selection verdict and `selection.json` for the batch containing the selected proposal. Inspect that batch's proposals and actual brief.
4. Inspect the relevant `hpc-roundN/` snapshot and, for an instrument test, `lab_results/<run-id>/`. Compare the packet, returned files and PI reviews.
5. For a delivered run, open the final paper and `MANIFEST.sha256` in its delivery folder. Use the earlier records to assess how the workflow reached that result.

[Prompts](prompts.md) specifies the response contracts; [Workflow](workflow.md) explains the stages and information boundaries.

## Run-folder map

Numbered batches, rounds and deliveries depend on the path the run takes. Approval, blocked, stopped and completion records appear only when applicable.

```text
<run>/
  state.json
  decisions-journal.md
  pipeline.log
  conversations/
    pi.json
  batches/
    01-fresh/
      prompt.md
      proposer-N.md
      dedup-reply.md
      pi-verdict.md
      manifest.json
    02-revision/
      revision/
        brief.md
        seed.md
        review.md
  manager/
    exclusions-1/
  exclusions-manager.md
  pi-verdict.md
  selection.json
  02-proofs-reply.md
  package/
  hpc-round1/
  lab-*-reply.md
  lab_results/
    <run-id>/
  LAB-APPROVAL-REQUIRED.md
  LAB-APPROVAL-GRANTED.md
  RUN-BLOCKED.md
  RUN-STOPPED.md
  delivery-v1/
    MANIFEST.sha256
  RUN-DONE.json
```

| File or folder | Purpose |
|---|---|
| `state.json` | Saved workflow state and approval records. |
| `decisions-journal.md`, `pipeline.log` | Decisions and the full execution log. |
| `conversations/pi.json` | Continuing PI conversation; other conversation files hold one-shot calls. |
| `batches/NN-fresh/prompt.md` | Actual proposer brief, fixed at batch start and stable across resumes. |
| `brief.md`, `seed.md`, `review.md` in a revision batch | Brief with exclusions removed, verbatim seed and the PI's whole-batch verdict. |
| `pi-verdict.md`, `selection.json` at the run root | PI selection verdict and selection record; each batch also keeps its own verdict. |
| `manager/exclusions-N/`, `exclusions-manager.md` | Manager inputs and reply; accumulated additions for later fresh batches. |
| `02-proofs-reply.md`, `package/` | A theory-step reply and manuscript files extracted from file blocks. |
| `hpc-roundN/` | Local snapshot of the computational researcher's working folder after a task. |
| `lab-*-reply.md` | Feasibility assessments, PI rulings, safety reviews and rerun decisions. |
| `lab_results/<run-id>/` | Returned files for one acquisition. |
| `LAB-APPROVAL-REQUIRED.md`, `LAB-APPROVAL-GRANTED.md` | Design awaiting human approval, or the note renamed after approval. |
| `RUN-BLOCKED.md`, `RUN-STOPPED.md` | Reason continuation is blocked, or a marker preventing resumption. |
| `delivery-vN/`, `RUN-DONE.json` | Final delivery and workflow completion record. |

`selection.json` records the batch and, when readable, the selected proposal identifier. The identifier comes from `SELECTION:`, otherwise a “selected proposer-N” phrase in the reply's first 1,500 characters; otherwise none is recorded. This record is informational: theory continues in the PI conversation that made the selection. Parsing and fallback behaviour are specified in [Prompts](prompts.md#decision-lines-and-fallbacks).

## Computational rounds and task records

Each `hpc-roundN/` snapshot holds the manuscript, reports and deliverables returned after a computational task. `NOTES-RESUME.md` records the agent's notes for later sessions. [Remote agents](remote-agents.md) describes the job files and session behaviour.

The computational researcher is instructed to write `ROUND-DONE.json` with a `done` or `blocked` status, a summary and the deliverables. Experimentalist tasks carry the same completion instruction. This records a task; `RUN-RESULT.json` records an acquisition, and `RUN-DONE.json` records the workflow. Keep LaTeX source and its compiled PDF together when inspecting a round.

Figure-review evidence lives in `figure_review/`. Figure 1 uses `figure1.png` and `page_figure1.png`; every other figure uses `figureN.png` and `page_figureN.png`. The PI reviews Figure 1 separately, then the remaining figures as a set, subject to attachment limits.

`PULL-SKIPPED.txt` in a pulled folder lists files left behind by the transfer limit. Check it before treating a local round or returned acquisition as a complete copy of the remote files. [Configuration](configuration.md) defines the per-pull budgets and exclusion patterns.

## Laboratory packet and approval records

The computational researcher prepares the digital twin and run packet before acquisition. The packet lives in its working folder and the corresponding round snapshot:

```text
lab_packet/
  README.md
  protocol.md
  results_schema.md
  analysis/
  twin/
    report.md
```

`protocol.md` contains numbered executable steps. `results_schema.md` specifies the raw files to return and their formats. `analysis/` contains analysis code tested on twin data; `twin/` contains the twin and its report.

When human approval is required, `LAB-APPROVAL-REQUIRED.md` identifies the packet and safety review for that run. It gives `auctopus approve <run>` and `auctopus resume <run>` with the same run folder. Approval is recorded in `state.json`, and the note is renamed `LAB-APPROVAL-GRANTED.md`.

The note also explains declining the design with `auctopus resume <run> --from lab`. This repeats the laboratory stage from feasibility review and builds a new packet in a new round; edits to the old packet are not carried over. If you instead edit the packet and approve it, Auctopus sends those edited files without another safety review. Follow [Running](running.md) for the procedure and [Safety](safety.md) for approval responsibilities.

## Instrument inbox and outbox

SSH transport uses `lab.remote_root` as the exchange root; manual transport uses the local `lab.exchange_dir`. Both carry the packet and acquisition records in this layout:

```text
<exchange root>/
  inbox/<run-id>/
    RUN-REQUEST.json
    README.md
    protocol.md
    results_schema.md
    analysis/
    twin/
  outbox/<run-id>/
    RUN-RESULT.json
    data/
    deviations.md
```

`RUN-REQUEST.json` records the acquisition identifier and SHA-256 hashes of the packet files. Acquisition identifiers have the form `<run name>-<YYYYmmdd-HHMMSS>-run<N>`.

The location of the standing instructions depends on transport:

| Transport | `LAB_AGENT_INSTRUCTIONS.md` | Laboratory safety rules |
|---|---|---|
| SSH | In `lab.remote_root`, alongside `inbox/` and `outbox/`. | Auctopus appends `domain/lab-safety.md` to the experimentalist's prompt. |
| Manual | Inside `inbox/<run-id>/`, copied from `domain/lab-agent-instructions.md`. | Not included in the inbox; supply `domain/lab-safety.md` separately to the person or agent performing the acquisition. |

The experimentalist writes raw data, acquisition logs, instrument settings and calibration runs under `data/`. It records deviations from the protocol, with times and reasons, in `deviations.md`. Return the files required by `results_schema.md` and the deviations report, then write `RUN-RESULT.json` last. See [Remote agents](remote-agents.md) for the manual hand-off procedure.

## Acquisition result template

The [lab-agent-instructions.md](../auctopus/resources/domains/template/lab-agent-instructions.md) template contains this `RUN-RESULT.json` format. Replace `<run-id>`, select one status, and fill the record with the acquisition's actual details:

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

| Field | Template content |
|---|---|
| `run_id` | String identifying the acquisition. |
| `status` | One string: `done`, `aborted` or `failed`. |
| `started`, `finished` | Timestamp strings; the template shows `YYYY-MM-DDTHH:MM:SS`. |
| `files` | Array of file-path strings, illustrated by `data/run.log` inside the acquisition's outbox. |
| `deviations` | String reporting `none` or referring to `deviations.md`. |
| `notes` | String containing one paragraph of plain facts. |

`done` means every protocol step ran and every file listed in `results_schema.md` is present. Returned files are copied to `<run>/lab_results/<run-id>/`, subject to the transfer budget. [Prompts](prompts.md#laboratory-decisions-and-acquisition-repeats) specifies how the PI decides whether to repeat an acquisition.

## Delivery and stop records

The delivery stage copies the final paper, source, reports and figures from the latest round into `delivery-vN/`. `MANIFEST.sha256` contains their SHA-256 checksums. The final paper's filename varies.

`RUN-DONE.json` means the workflow finished and delivered, not that every scientific claim was accepted. A run can deliver after a final `LAB-DECISION: NO-GO` or `LAB-WITHDRAW`, with a paragraph describing the experimental signature a later experiment could test. No acquisition takes place on that branch. Delivery can also follow the single requested revision in `review_mode = "once"`, without another acceptance review; see [Prompts](prompts.md#review-policy-by-task).

`RUN-BLOCKED.md` gives the reason a run cannot continue and a resume command. `RUN-STOPPED.md` prevents resumption. Dry-run folders cannot be resumed or approved, including a blocked `never-win` demo whose note still prints a resume command. Repeat the scenario with `auctopus dry-run` instead. [Running](running.md) explains how to act on these records.
