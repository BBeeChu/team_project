# Run and monitor Auctopus

Use this guide to operate a project after [Getting started](getting-started.md). A **run** is one execution of the research workflow. An **acquisition** is one execution of a run packet on the instrument; a run can contain several acquisitions.

## Command reference

Commands for an existing project read `config.toml` in the current folder, or the file named by the global `--config CONFIG` option before the command. A run argument does not select a configuration. Work from your project directory or supply its configuration explicitly. `init` creates a project; `dry-run` also works outside one.

```bash
auctopus --version
auctopus --config config.toml status
```

These commands print the version and display status using the specified configuration. From a clone, `python -m auctopus` works without installation; installing also provides the `auctopus` executable.

Prefix each command below with `auctopus`. Square brackets mark optional arguments. Replace `<run>` with a run folder or name and other labels with your values; quotes keep paths with spaces together.

| Command and arguments | Purpose |
|---|---|
| `init [DIR] [--domain D] [--force]` | Create `config.toml`, 33 prompt templates, a domain pack and `.gitignore`. The shipped domain pack is `template`. |
| `doctor [--online]` | Check required configuration, prompts and domain files. `--online` also tests keys and models for roles used by the configured stages, SSH logins, remote folders and agents. |
| `models` | List the models each configured API key can use. |
| `setup-remote hpc\|lab` | Create the selected remote working folder and store the agent's key in a private file with mode 600. The key travels inside SSH. |
| `new [--until STAGE] [--label L] [--force]` | Start a run, optionally with a label or stage limit. `--force` overrides the readiness check that normally refuses incomplete projects. |
| `resume [<run>]` | Continue a real run at the first unfinished stage and step. Replay, stage-limit and skip options are listed below. |
| `status [<run>]` | Show stage states and the contents of `RUN-BLOCKED.md` when present. |
| `approve <run>` | Record human approval of a real run's laboratory design. The run argument is required; resume separately. |
| `dry-run [--scenario S] [--until STAGE]` | Exercise the workflow offline with mock models, mock coding agents and local folders. |

The options for `resume` are:

- `--from STAGE`: replay the named stage and later enabled stages.
- `--until STAGE`: stop after the named stage; also available on `new` and `dry-run`.
- `--skip a,b`: mark a comma-separated list of stages done without running them.

For `STAGE`, use these names in execution order: `proposals`, `theory`, `verify`, `verify-review`, `lab`, `figures`, `reviewers`, `deliver`.

### Choose the run explicitly

Without a run argument, `status` and `resume` select the latest run folder directly inside `project.runs_dir`. Nested dry runs are excluded. Name the run explicitly when several runs exist.

To inspect a dry run, pass its full printed run-folder path to `status`. That folder sits inside the demo's temporary project; the outer `runs/dry-runs/<stamp>/` or `auctopus-dry-run/<stamp>/` directory is not the run folder.

### Read exit codes and completion markers

| Exit code | Meaning | What to check |
|---|---|---|
| `0` | The command completed normally. | Check which stages ran and whether a final delivery exists. |
| `1` | A blocked run or an error. | Read the terminal message and `RUN-BLOCKED.md` if present. |
| `2` | Waiting for human approval of a laboratory design. | Read `LAB-APPROVAL-REQUIRED.md`, the packet and any safety review. |

`RUN-DONE.json` records that the workflow finished and delivered; it does not establish scientific success. A run can complete after a final decision not to perform the laboratory test or a withdrawal of that test.

The default `review_mode = "once"` gives verification review (`verify-review`) and final manuscript review at most one revision, then continues without requiring a later acceptance. `until-accept` changes those two reviews. Packet, laboratory-analysis and figure reviews allow one review and at most one fix in both modes. See [Workflow](workflow.md) for review limits and decision rules.

## Start a run

After the project passes its readiness checks, begin with the proposal search:

```bash
auctopus new --until proposals
```

Auctopus creates a run under `project.runs_dir` and stops after the proposal stage. Inspect its status and decision journal, then continue the same run:

```bash
auctopus resume "<run>"
```

Use `auctopus new` to start all enabled stages. To stop after computational verification and its PI review, use `--until verify-review`; this stops before the laboratory stage. Choose stages in [Configuration](configuration.md), and review execution permissions and cost controls in [Safety](safety.md).

If readiness checks report incomplete settings or required files, resolve those findings before starting again.

## Monitor a run

Show the latest normal run, or specify one explicitly:

```bash
auctopus status
auctopus status "<run>"
```

Open `<run>/decisions-journal.md` for decisions and `<run>/pipeline.log` for the full log. The console shows the same timestamped log lines. [Outputs](outputs.md) identifies the supporting records and artefacts.

Captured `status` output for the blocked `never-win` dry run, 31 October 2026, with the absolute path shortened:

```text
run …/my-lab/runs/dry-runs/20261031-015749/runs/20261031-015749-dry-run
  ✗ proposals       blocked  24 batch(es); selected: -
  ○ theory          pending  the PI: proofs, positioning, the manuscript, the computational test design
  ○ verify          pending  the computational researcher runs the PI's computational test
  ○ verify-review   pending  the PI reviews the verification; one revision
  ○ lab             pending  feasibility, design, twin and packet, safety agent, instrument run, analysis
  ○ figures         pending  figure plan, figure 1 build and review, the other figures reviewed as a set
  ○ reviewers       pending  independent reviewers, the PI's triage, revision, final review
  ○ deliver         pending  the final paper and its evidence, with checksums

# Run stopped at stage 'proposals'

no proposal selected after 24 batches (proposals.max_batches = 24)

When fixed, resume with:

    auctopus resume …/my-lab/runs/dry-runs/20261031-015749/runs/20261031-015749-dry-run
```

The captured resume instruction does not apply to this dry run: `resume` and `approve` refuse dry-run folders with exit code `1`. Run the scenario again with `dry-run`.

The heading “Run stopped” belongs to `RUN-BLOCKED.md`. The separate `RUN-STOPPED.md` marker prevents resume. Status marks mean done (`✓`), running (`●`), blocked (`✗`) and pending (`○`); terminals without Unicode use `+`, `*`, `x` and `.` respectively.

## Approve or decline a laboratory design

With `lab.require_approval = true`, the default, Auctopus pauses before instrument hand-off and exits with code `2`. If `lab.safety_review = true`, also the default, the safety agent has approved the packet before this pause.

Captured `LAB-APPROVAL-REQUIRED.md`, 31 October 2026. `<run>` replaces the full absolute run-folder path; the round number varies. Use the paths in your own note:

```text
# The experimental design needs your approval

The run packet is in `<run>/hpc-round3/lab_packet` (protocol.md, results_schema.md, analysis/, twin/).
The safety agent's review is `<run>/lab-safety-1-reply.md`.
Nothing has been sent to the instrument. Read the protocol, then approve and continue with:

    auctopus approve <run>
    auctopus resume <run>

To decline, run `auctopus resume <run> --from lab` instead: the laboratory stage starts again from the feasibility review. Edits you make to the packet before approving are sent as they are; the safety review did not see them.
```

### Approve the current packet

1. Read the packet: protocol, expected raw files, analysis code and digital-twin report. If safety review is enabled, read it against your instrument specification and laboratory rules.
2. Check the exact files you intend to send. If you edit the packet before approving, Auctopus sends those edits without a new safety review. When safety review is enabled, its existing review covers the earlier version.
3. Record approval and resume the same run:

   ```bash
   auctopus approve "<run>"
   auctopus resume "<run>"
   ```

Approval is recorded in `state.json`; the note becomes `LAB-APPROVAL-GRANTED.md`. Resume separately, then use `status` and the journal to follow progress.

### Decline the current packet

To decline, replay the laboratory stage:

```bash
auctopus resume "<run>" --from lab
```

The stage restarts at feasibility review, with new triage and a new packet built in a new round. Old packet edits do not carry forward. Later enabled stages also replay; see [Rerun from a stage](#rerun-from-a-stage). If the replay reaches another approval checkpoint, review the new packet. To end the investigation, [stop the run for good](#stop-a-run-for-good).

## Resume after a stop

1. Return to the project directory, or select its configuration with `--config`.
2. If `RUN-BLOCKED.md` exists, read its reason and correct the underlying problem.
3. Continue the intended run:

   ```bash
   auctopus resume "<run>"
   ```

Ordinary resume continues at the first unfinished stage and, within it, the first unfinished step. Check `status` and new journal entries for progress, a block or an approval pause.

For a run that has not passed `verify-review`, continue only through that stage with:

```bash
auctopus resume "<run>" --until verify-review
```

After an orchestrator interruption, Auctopus waits for a running remote job or collects its finished result. See [When the orchestrator or a remote process stops](#when-the-orchestrator-or-a-remote-process-stops) for each failure case.

## Rerun from a stage

Use `--from` to repeat work, for example computational verification:

```bash
auctopus resume "<run>" --from verify
```

The selected stage and later enabled stages run again. Auctopus discards their saved state, PI turns and one-shot conversations; earlier stages are retained. This repeats work, and replaying the laboratory stage can lead to another acquisition. For interrupted work, use [ordinary resume](#resume-after-a-stop).

## Skip stages

To omit figures and independent manuscript reviewers when continuing a run:

```bash
auctopus resume "<run>" --skip figures,reviewers
```

Skipped stages are marked done without executing their work. For a project-wide choice, configure `chain.lab`, `chain.figures` or an empty `chain.reviewers` list in [Configuration](configuration.md).

## Stop a run for good

1. Stop the local orchestrator with Ctrl-C if it is running.
2. Handle ongoing remote jobs or an acquisition separately on their hosts, using your laboratory's operating procedures.
3. Create `RUN-STOPPED.md` in the run folder and record why the investigation ended.

Leave the marker in place. Its presence prevents the run from being resumed.

> [!WARNING]
> Ctrl-C and `RUN-STOPPED.md` do not stop detached remote jobs or an acquisition already underway. The marker prevents future resume; it is not an instrument stop control.

## When the orchestrator or a remote process stops

### SSH connections

After an SSH connection failure with exit code `255`, `retries` allows up to five more attempts by default, with a wait between them. Other failures are not retried at this boundary. Reconnection does not restart a task or authorise another acquisition.

### Computational tasks

If a computational process disappears without an exit code or exceeds `job_timeout_h`, Auctopus starts that task once more automatically. A second failure blocks the run and writes `RUN-BLOCKED.md`. Inspect `stdout.log`, `stderr.log` and `exit_code` when present; [Remote agents](remote-agents.md) gives their locations.

### The orchestrator and detached jobs

Remote jobs run detached by default. Ctrl-C, a crash or reboot of the orchestrator's computer leaves them running. Ordinary resume waits for the job or collects its result. The `started` marker prevents a second launch.

### Physical acquisitions

Infrastructure retries never relaunch an acquisition. If an acquisition returns a status other than `done`, the PI agent issues a `RERUN-DECISION`, within the `chain.lab_reruns` limit, default `1`:

- `RERUN-DECISION: APPROVE` repeats the unchanged packet. The existing safety and human approvals stand; neither check is repeated.
- `RERUN-DECISION: AMEND` asks the computational researcher to amend the packet. The amended packet goes through the configured safety and human approval checks again.
- `RERUN-DECISION: REJECT`, or an exhausted rerun limit, means no further acquisition.

The computational researcher still analyses the last acquisition's `RUN-RESULT.json`, data and deviations when no further acquisition is authorised. The PI reviews that analysis once.

### Model requests

Replies are saved when they arrive; completed calls are not sent again during ordinary resume. An in-flight OpenAI background response can resume by its response ID. Other requests still in flight when the orchestrator stops are sent again on resume.

## Run the offline scenarios

Offline demos use mock models and coding agents, with local folders standing in for remote machines. They need no API keys or SSH, do not require your own prompts and skip human approval. Mock replies depend on stages and attached files, so they do not evaluate prompt wording.

From a clone, use `python -m auctopus` without installing the package. After installation, the `auctopus` executable accepts the same commands:

```bash
python -m auctopus dry-run --scenario lab-redo
```

Expected outcomes for complete scenario runs with the shipped settings:

| Scenario | Expected outcome | Exit code |
|---|---|---|
| `win-first` | The first batch produces a selection; the workflow reaches delivery. | `0` |
| `revision-then-win` | The first batch is rejected with a best seed; its revision batch is selected and the workflow reaches delivery. This is the default. | `0` |
| `never-win` | No proposal is selected; the run blocks at `proposals.max_batches`, default `24`. | `1` |
| `lab-redo` | The manager's redesign is accepted; safety requests a correction; a failed acquisition is followed by an amended packet and another acquisition; the workflow reaches delivery. | `0` |

Inside a project, demos are created under `runs/dry-runs/<stamp>/`; outside a project, under `auctopus-dry-run/<stamp>/`. Inspect a demo with `status` and its printed inner run-folder path. Dry runs cannot be resumed or approved: both commands refuse with exit code `1`. To repeat a scenario, start it again with `dry-run`.

Captured `decisions-journal.md` excerpt from the `lab-redo` dry run, 31 October 2026, using mock models:

```text
- 2026-10-31T03:13:34 proposals: batch 01-fresh ended without a selection (none-selected; best seed: proposer-1)
- 2026-10-31T03:13:34 proposals: the PI selected proposer-1 in batch 02-revision
- 2026-10-31T03:13:35 lab: LAB-DECISION NO-GO
- 2026-10-31T03:13:35 lab: after the manager's design, LAB-DECISION GO
- 2026-10-31T03:13:36 lab: SAFETY REJECT (review 1)
- 2026-10-31T03:13:36 lab: SAFETY APPROVE (review 2)
- 2026-10-31T03:13:37 lab: acquisition 20261031-031334-dry-run-20261031-031336-run1 returned status failed
- 2026-10-31T03:13:37 lab: RERUN-DECISION AMEND for acquisition 20261031-031334-dry-run-20261031-031336-run1
- 2026-10-31T03:13:37 lab: SAFETY APPROVE (review 3)
- 2026-10-31T03:13:37 lab: acquisition 20261031-031334-dry-run-20261031-031337-run2 returned status done
- 2026-10-31T03:13:40 deliver: delivery-v1 assembled (final paper: main.pdf)
```

The two acquisition identifiers are `<run-id>` values belonging to one workflow run.

## Troubleshoot a blocked run

Start with `status` and `RUN-BLOCKED.md`. Bypassing readiness checks does not resolve the causes below.

| Symptom | Inspect | Next action |
|---|---|---|
| `doctor` reports an incomplete project | Configuration placeholders and required prompt/domain files | Fill the reported values or text, then run `doctor` again. |
| API or model checks fail; every proposer fails | Provider keys and role model names | Use `models` and `doctor --online` to check access and correct the configuration. |
| No proposal is selected before the batch limit in a real run | PI verdicts, sample card, prompts and exclusions | Reconsider the brief and search limit. Replay `proposals` after changing the brief to assemble fresh batch inputs. |
| Verification exhausts `max_review_rounds` in `until-accept` mode | PI reviews and computational reports | Check the requested changes, review policy and limits before continuing. |
| Safety still rejects after the correction allowance | Packet, safety reviews, instrument specification and laboratory rules | Replay `lab` from feasibility and review the new packet and safety decision. |
| A computational task fails again after its automatic restart | Remote job logs, process status and timeout setting | Correct the host or task problem before following the resume instruction in `RUN-BLOCKED.md`. |
| An acquisition returns `failed` or `aborted` | `RUN-RESULT.json`, deviations and the PI's rerun decision | Follow the PI's ruling and required checks; do not independently relaunch the acquisition. |
| Resume is prevented by `RUN-STOPPED.md` | The recorded reason for ending the run | Keep the marker in place for an investigation you have ended. |
| `resume` or `approve` refuses a dry run | The run folder you supplied | Repeat the scenario with `dry-run`. |

If files are missing from a pulled folder, inspect `PULL-SKIPPED.txt` for the files left on the remote host. [Outputs](outputs.md) describes the artefacts, and [Configuration](configuration.md) defines the transfer limits.
