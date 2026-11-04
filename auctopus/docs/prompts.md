# Prompt templates and response contracts

Use this reference to write prompts that elicit the files and decision lines Auctopus reads; follow [Getting started](getting-started.md) for setup. The study's prompts are not included; write your own from the templates.

## Write a template

1. Replace every `[insert: ...]` instruction used by your configured stages. State the task, evidence to consider and deliverables.
2. Preserve interpolation placeholders, required filenames and response lines. Keep requests for numbered changes.
3. Run `auctopus doctor` to identify missing or unwritten prompt and domain files. `auctopus new` refuses to start with these findings unless you use `--force`; see [Running](running.md).

Templates live in `project.prompts_dir`. This folder and `project.domain_dir` can be outside the repository. See [Configuration](configuration.md) for paths and [Domain packs](domain-packs.md) for the scientific and operational material the prompts use. The offline demo uses mock replies and does not evaluate prompt wording.

## Preserve the five placeholders

| Placeholder | Templates | Replacement and placement rule |
|---|---|---|
| `{PHYSICAL_ANCHOR}` | `proposer.md`, `pi-select-strict.md`, `pi-select.md` | Sample card followed by `proposer-rule.md` for proposers or `pi-rule.md` for the principal investigator (PI). Put it in a paragraph of its own. |
| `{EXCLUSIONS}` | `proposer.md` | Authored exclusions and manager additions as `; or that ...` clauses. Place immediately before the full stop of the sentence listing what to avoid. Empty in revision briefs. |
| `{SEED}` | `17-revision.md` | Seed proposal identifier, for example `proposer-3`. |
| `{TASK_FILE}` | Six computational-researcher templates listed below | Filename holding the task or review, for example `experiment3.md`. |
| `{RUN_ID}` | `lab-run.md` | Acquisition identifier in `inbox/{RUN_ID}/` and `outbox/{RUN_ID}/`. |

`{TASK_FILE}` appears in `05-continue.md`, `07-figure-build.md`, `08-figure-fix.md`, `08-figure-task.md`, `14-lab-twin-packet.md` and `15-lab-analysis.md`. Preserve it when replacing the surrounding authoring instruction.

If a sample card is present, omitting `{PHYSICAL_ANCHOR}` from the relevant prompts is an error. A non-empty exclusion list without `{EXCLUSIONS}` is also an error. Both `doctor` and the run report these omissions.

## Deliver files in response blocks

A file block starts with `===== FILE: relative/path.ext =====`, contains the complete file, and ends with `===== END FILE =====`. Use one block per file. Paths are relative to the paper folder; absolute paths and paths using `..` are skipped.

This schematic two-file example shows the delimiters; replace the angle-bracketed text with complete contents:

```text
===== FILE: protocol.md =====
<complete protocol contents>
===== END FILE =====

===== FILE: results_schema.md =====
<complete results-schema contents>
===== END FILE =====
```

The manager uses the same syntax for `exclusions.md`. An empty block requests no new exclusions.

## Instructions added by Auctopus

For `chain.file_steps`, Auctopus adds file-delivery instructions. The defaults are `03-write` and `03b-redeliver`.

Every computational-researcher task includes its task filename, `hpc.extra_instructions` and standing instructions to keep LaTeX source with its compiled PDF, update `NOTES-RESUME.md` and finish with `ROUND-DONE.json`. It also includes the no-publish instruction described in [Safety](safety.md).

Numbered changes from an accepted review can accompany the next task. After a final `LAB-DECISION: NO-GO` or `LAB-WITHDRAW`, Auctopus supplies the PI's specification for a paragraph describing a later experimental test.

Experimentalist tasks receive the same standing notes and completion instructions, plus `domain/lab-safety.md` and `lab.extra_instructions`. See [Outputs](outputs.md) for completion records and [Remote agents](remote-agents.md) for the separate manual hand-off.

## Template index by stage

The index covers all 33 templates; filenames link to their shipped sources. Inputs are attachments or files in an agent's working folder. After selection, PI tasks retain the continuing PI conversation; [Workflow](workflow.md) describes the context boundaries.

Decision names below refer to the [decision-line table](#decision-lines-and-fallbacks). Remote tasks also receive the standing instructions above.

### Proposal search (`proposals`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [proposer.md](../auctopus/resources/prompts/proposer.md) | Each proposer | Rendered prompt alone, with anchor and exclusions | One proposal. |
| [dedup.md](../auctopus/resources/prompts/dedup.md) | Deduplication role | Fresh-batch `proposer-N.md` files | `KEEP` list for assessment; used with at least two replies. |
| [pi-select-strict.md](../auctopus/resources/prompts/pi-select-strict.md) | PI, fresh assessment | Kept proposals and PI anchor | Begin with `SELECTION`; if none, end with `BEST SEED`. May reject the batch. |
| [pi-select.md](../auctopus/resources/prompts/pi-select.md) | PI, fresh assessment | Kept proposals and PI anchor | Same lines; asks for the strongest proposal, strengthened. |
| [17-revision.md](../auctopus/resources/prompts/17-revision.md) | Revision proposers | `brief.md` without exclusions, verbatim `seed.md`, whole-batch verdict in `review.md` | One revised proposal. |
| [manager-exclusions.md](../auctopus/resources/prompts/manager-exclusions.md) | Manager | `verdict-<batch>.md` files and current `proposer-brief.md` | `exclusions.md` file block of clauses; additions saved in `exclusions-manager.md`. |

### Theory and manuscript (`theory`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [02-proofs.md](../auctopus/resources/prompts/02-proofs.md) | PI | Continuing conversation | Results and proofs. |
| [02b-positioning.md](../auctopus/resources/prompts/02b-positioning.md) | PI | Continuing conversation | Comparison with closest prior work. |
| [03-write.md](../auctopus/resources/prompts/03-write.md) | PI | Continuing conversation | LaTeX manuscript file blocks, saved to `package/`. |
| [03b-redeliver.md](../auctopus/resources/prompts/03b-redeliver.md) | PI | Continuing conversation after a reply without `.tex` | Redelivered source blocks; requested once when needed. |
| [04-exp.md](../auctopus/resources/prompts/04-exp.md) | PI | Continuing conversation | Computational test design, saved as `experiment.md`. |

### Computational verification (`verify`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [05-codex.md](../auctopus/resources/prompts/05-codex.md) | Computational researcher | Manuscript source and `experiment.md` | Verification deliverables and completion record. |

### Verification review and revision (`verify-review`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [06-review.md](../auctopus/resources/prompts/06-review.md) | PI through `roles.pi_review` | Latest manuscript and results: main PDF first, then source and reports | Numbered changes and `VERDICT`. |
| [05-continue.md](../auctopus/resources/prompts/05-continue.md) | Computational researcher | Review or changes in `{TASK_FILE}`, existing working files | Revised deliverables and completion record. |

These shared templates also support later analysis and manuscript reviews and revisions. Attachment budgets are specified in [Configuration](configuration.md).

### Laboratory design, acquisition and analysis (`lab`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [12-feasibility-gate.md](../auctopus/resources/prompts/12-feasibility-gate.md) | Feasibility reviewer | Manuscript, `instrument.md`, `sample-card.md` | Report ending with `FEASIBILITY`, recorded in the journal. |
| [13-feasibility-triage.md](../auctopus/resources/prompts/13-feasibility-triage.md) | PI | Feasibility report, instrument specification, manuscript | `LAB-DECISION`; packet brief or specification for a replacement paragraph. |
| [16m-manager-design.md](../auctopus/resources/prompts/16m-manager-design.md) | Manager | Manuscript, instrument specification, PI ruling, feasibility report | Design separating the prediction from its rivals. |
| [16-lab-redesign.md](../auctopus/resources/prompts/16-lab-redesign.md) | PI | Manager's design | `LAB-DECISION`; approval replaces the earlier packet brief. |
| [14-lab-twin-packet.md](../auctopus/resources/prompts/14-lab-twin-packet.md) | Computational researcher | Brief in `{TASK_FILE}`; `hardware/instrument.md` | `lab_packet/` with README, protocol, schema, analysis code and twin report. |
| [14r-lab-packet-review.md](../auctopus/resources/prompts/14r-lab-packet-review.md) | PI | Manuscript; packet README, protocol, schema and twin report | Numbered changes and `VERDICT`, or `LAB-WITHDRAW` with a replacement-paragraph specification. |
| [14s-safety-review.md](../auctopus/resources/prompts/14s-safety-review.md) | Safety agent | Packet README, protocol, schema; `instrument.md`, `lab-safety.md` | `SAFETY`; numbered corrections if rejected. |
| [lab-run.md](../auctopus/resources/prompts/lab-run.md) | Experimentalist | `LAB_AGENT_INSTRUCTIONS.md`; `inbox/{RUN_ID}/` packet; appended safety rules | Raw files, `deviations.md`, then `RUN-RESULT.json` in `outbox/{RUN_ID}/`. |
| [18-lab-rerun.md](../auctopus/resources/prompts/18-lab-rerun.md) | PI | Acquisition's `RUN-RESULT.json` and `deviations.md` | `RERUN-DECISION`, with changes for amendment. |
| [15-lab-analysis.md](../auctopus/resources/prompts/15-lab-analysis.md) | Computational researcher | Returned files in `lab_results/`; status in `{TASK_FILE}` | Analysis deliverables and completion record. |

### Figure preparation and review (`figures`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [07-figure-plan.md](../auctopus/resources/prompts/07-figure-plan.md) | PI | Manuscript | Figure 1 plan, used as the researcher's brief. |
| [07-figure-build.md](../auctopus/resources/prompts/07-figure-build.md) | Computational researcher | Plan in `{TASK_FILE}` | `figure_review/figure1.png` at 600 dpi and `figure_review/page_figure1.png`. |
| [08-figure-review.md](../auctopus/resources/prompts/08-figure-review.md) | PI | Figure 1 and its manuscript-page preview | Numbered changes and `FIGURE`. |
| [08-figure-fix.md](../auctopus/resources/prompts/08-figure-fix.md) | Computational researcher | Review in `{TASK_FILE}` | Changes and new renders of changed figures. |
| [09-figures-render.md](../auctopus/resources/prompts/09-figures-render.md) | Computational researcher | Text saved as the task file for `08-figure-task.md` | Every figure except Figure 1 as `figure_review/figureN.png` at 600 dpi and `figure_review/page_figureN.png`. |
| [08-figure-task.md](../auctopus/resources/prompts/08-figure-task.md) | Computational researcher | Task in `{TASK_FILE}` | Task deliverables and completion record. |
| [09-figures-all.md](../auctopus/resources/prompts/09-figures-all.md) | PI | Remaining figures and their manuscript-page previews, within attachment limits | Numbered changes and `FIGURES`. |

For the figure set, Auctopus writes the text of `09-figures-render.md` to a task file, then sends `08-figure-task.md` with `{TASK_FILE}` naming it. Figure 1 is reviewed separately; the later set excludes it.

Both figure reviews attach only images and page previews, with no full manuscript or source. The PI retains its earlier conversation. `chain.review_max_files` caps attached files, and `chain.review_max_mb` caps their total size; see [Configuration](configuration.md).

### Manuscript refereeing (`reviewers`)

| Template | Recipient | Inputs | Response and engine use |
|---|---|---|---|
| [10-cold-referee.md](../auctopus/resources/prompts/10-cold-referee.md) | Each role in `chain.reviewers` | Manuscript PDF and main LaTeX source only | Referee report with recommendation and confidence score; no decision line is parsed. |
| [11-referee-triage.md](../auctopus/resources/prompts/11-referee-triage.md) | PI | Referee reports and manuscript | Numbered changes used as the researcher's revision brief. |

Each referee receives a fresh conversation without analysis code, data or earlier exchanges. The PI's triage turns the reports into a revision task.

The `deliver` stage has no prompt template; see [Outputs](outputs.md).

## Decision lines and fallbacks

For each decision-line contract, the engine reads the **last matching line**. Keep the requested placement: selection at the beginning, closing decisions at the end. `LAB-WITHDRAW` is a separate marker recognised anywhere in the packet review.

| Contract | Missing or unreadable response |
|---|---|
| `KEEP: proposer-1.md, ...` | Keep every proposal. |
| `SELECTION: proposer-N` or `SELECTION: none` | Count as a selection unless no-selection wording, such as “no winner” or “reject all”, appears in the first 1,200 characters. |
| `BEST SEED: proposer-N` or `BEST SEED: none` | No seed, so no revision batch. |
| `VERDICT: ACCEPT` or `VERDICT: REVISE` | Treat as `VERDICT: REVISE`. |
| `FEASIBILITY: GO` or `FEASIBILITY: NO-GO` | Record as unreadable; the PI's triage decides whether to proceed. |
| `LAB-DECISION: GO` or `LAB-DECISION: NO-GO` | Treat as `LAB-DECISION: NO-GO`. |
| `LAB-WITHDRAW` | No withdrawal; remaining checks still apply. |
| `SAFETY: APPROVE` or `SAFETY: REJECT` | Reject unless approval is explicit. |
| `RERUN-DECISION: APPROVE`, `RERUN-DECISION: AMEND` or `RERUN-DECISION: REJECT` | Reject the repeat. |
| `FIGURE: ACCEPT` or `FIGURE: REVISE` | Request a fix pass. |
| `FIGURES: ACCEPT` or `FIGURES: REVISE` | Request a fix pass. |

Selection and identifying a proposal are separate operations. A prose verdict can therefore count as a selection without a readable proposal identifier. `selection.json` records the batch and identifies the proposal from `SELECTION:`, else a “selected proposer-N” phrase in the first 1,500 characters, else no identifier. This record is informational: theory continues in the PI conversation that made the selection.

## Review policy by task

Parsing a line determines the decision. The policy below determines the correction and when the workflow continues.

| Review | `review_mode = "once"` (default) | `review_mode = "until-accept"` |
|---|---|---|
| Computational verification (`verify-review`) | One review; a revision request gets one revision task, then the workflow continues. | Repeat until accepted, at most `chain.max_review_rounds`; stop if none accepts. |
| Run packet (`lab`) | One review and at most one fix pass. | Same. |
| Laboratory analysis (`lab`) | One review and at most one fix pass. | Same. |
| Figure 1 (`figures`) | One review and at most one fix pass. | Same. |
| Remaining figure set (`figures`) | One review and at most one fix pass. | Same. |
| Final PI review after the reviewers' revision (`reviewers`) | One review and at most one revision, then the workflow continues. | Repeat until accepted, at most `chain.final_review_rounds`; stop if none accepts. |
| Safety review (`lab`, when enabled) | Explicit approval required; correct and re-review up to `lab.safety_fix_rounds` corrections, then stop if rejected again. | Same. |

The packet, analysis and two figure reviews continue after a requested fix without another acceptance review. Packet withdrawal follows the laboratory branch below. [Configuration](configuration.md) lists the limits; [Safety](safety.md) explains human approval and safety responsibilities.

## Laboratory decisions and acquisition repeats

`FEASIBILITY` is advisory; the PI's `LAB-DECISION` controls the laboratory branch. If `chain.manager_redesign` is enabled, a declined test receives a manager design and one further PI ruling.

After a final `LAB-DECISION: NO-GO` or packet-review `LAB-WITHDRAW`, no acquisition takes place. The PI specifies an experimental-signature paragraph: a short description of the observable signature by which a later experiment could test the theory. The computational researcher adds it to the manuscript in place of the laboratory test.

After an acquisition that did not end `done`, the PI agent can authorise a repeat within `chain.lab_reruns`:

- `RERUN-DECISION: APPROVE` repeats the unchanged packet. Earlier safety and human approvals stand; neither is requested again.
- `RERUN-DECISION: AMEND` sends the listed changes to the computational researcher. The amended packet needs safety review and human approval again when each is enabled.
- `RERUN-DECISION: REJECT`, or an exhausted repeat allowance, means no further acquisition.

With no further acquisition, the computational researcher still analyses the last acquisition's result record, data and deviations. The PI reviews that analysis once. [Remote agents](remote-agents.md) distinguishes these PI decisions from connection and job recovery.

## Proposal revisions

A rejected fresh batch with a readable best seed can receive one revision batch when `proposals.revision` is enabled. The revision brief has its exclusions removed. A revision batch is not revised again; [Workflow](workflow.md) describes the subsequent search branches.
