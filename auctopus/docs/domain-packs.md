# Domain files and authoring rules

Use this page to describe your research system, testability rules, instrument and laboratory procedures in the seven domain files. Follow [Getting started](getting-started.md) for the project setup sequence and [Prompts](prompts.md) for the stage templates that use this material.

## Choose the files your stages need

The domain pack is a folder of plain Markdown, separate from the stage prompts. The default pack is `template`; replace its authoring instructions with your own material. Its project location defaults to `domain/`. Set `project.domain_dir` to use another folder, including one outside the repository; see [Configuration](configuration.md).

| File | Purpose | Readers | Required when |
|---|---|---|---|
| [sample-card.md](../auctopus/resources/domains/template/sample-card.md) | Scientific system and measurements. | Every proposer, each principal investigator (PI) batch assessment, feasibility reviewer. | Always. |
| [proposer-rule.md](../auctopus/resources/domains/template/proposer-rule.md) | Testability rule for proposals. | Proposers. | Always. |
| [pi-rule.md](../auctopus/resources/domains/template/pi-rule.md) | Matching rule for assessing proposals. | PI during batch assessment. | Always. |
| [exclusions.md](../auctopus/resources/domains/template/exclusions.md) | Idea families excluded from fresh proposals. | Fresh proposers and manager through the current brief. | Always; may be empty. |
| [instrument.md](../auctopus/resources/domains/template/instrument.md) | Capabilities, limits and returned measurements. | Feasibility reviewer, PI, computational researcher, manager, safety agent. | Laboratory stage enabled. |
| [lab-agent-instructions.md](../auctopus/resources/domains/template/lab-agent-instructions.md) | Operating a packet and returning results. | Experimentalist. | Laboratory stage enabled. |
| [lab-safety.md](../auctopus/resources/domains/template/lab-safety.md) | Safety limits and responses to unsafe steps. | Experimentalist and safety agent. | Laboratory stage enabled. |

With `chain.lab = false`, only the first four files are required. Enabling the laboratory stage also requires the instrument description, operating instructions and safety rules, including for manual transport. Filenames above link to the shipped templates.

## Describe the system in the sample card

The `sample-card.md` template recommends one paragraph of about 120 words as authoring guidance. Explain what the system is, what it can measure and control, its key parameters, and what one measurement returns. Focus on the scientific system and observable quantities. Put instrument models, detailed capabilities and operating limits in `instrument.md`.

The orchestrator leaves out lines starting with `#` when it constructs the sample card. Use those lines for headings or authoring comments, and put the substantive description on ordinary text lines. Replace the template's `[insert: ...]` part with the description.

The sample card becomes the physical anchor supplied to proposers and each PI batch assessment. For proposers, the anchor also includes `proposer-rule.md`; for PI assessment, it includes `pi-rule.md`. The feasibility reviewer also receives the sample card alongside the manuscript and instrument specification.

The proposer and PI selection prompts receive the anchor through `{PHYSICAL_ANCHOR}`. [Prompts](prompts.md) specifies its placement and the errors reported when a required placeholder is missing.

## Define matching testability rules

Use `proposer-rule.md` to say what makes a proposed prediction testable on your system. Use `pi-rule.md` to give the PI the matching assessment rule, including when inability to test a prediction requires rejection.

Write both rules against the capabilities you describe. Compare the proposers' requirements with the PI's rejection criteria so they apply compatible constraints. Later, the feasibility reviewer assesses the manuscript against the instrument specification, and the PI decides whether to proceed with a laboratory test. See [Workflow](workflow.md) for those decisions.

## Specify exclusions as sentence clauses

`exclusions.md` contains idea families that fresh proposers must avoid. Each exclusion continues the prompt's sentence, “Do not pursue approaches that ...”, and starts with `; or that`. For example, an authored exclusion could be:

```text
; or that require unavailable pulse control
```

Inserted into an avoidance sentence, this example reads:

```text
Do not pursue approaches that cannot be tested on this system; or that require unavailable pulse control.
```

Write a complete predicate after `; or that`, so it continues the sentence grammatically. Lines starting with `#` are comments and are ignored. To specify no exclusions, leave the non-comment content empty.

In `proposer.md`, retain `{EXCLUSIONS}` immediately before the full stop of the sentence listing what to avoid. Revision proposers receive the brief with exclusions removed, the seed proposal and the PI's verdict on its batch.

During a run, the manager can identify recurring rejected families after the configured number of batches without selection. Its additions are saved to `exclusions-manager.md` in the run and appended to the exclusions used by later fresh batches. These additions do not require you to rewrite the project's `exclusions.md`. The trigger is `proposals.manager_exclusions_after`; see [Configuration](configuration.md).

## Document current instrument capabilities

`instrument.md` is the reference against which the agents design and check the laboratory test. Start with a “Current capabilities” section containing the operative specification. Give limiting numbers with units, measurement dates and calibration validity conditions. Keep historical measurements in clearly labelled background sections, and update or remove conflicting operating instructions.

Cover the hardware, calibration at the working point, operating regime, hard limits and control-software capabilities. Describe how long an acquisition may take, which raw files return, and what the instrument cannot do. Where relevant to your system, document timing grids, shortest pulses, power and count-rate limits, coherence, contrast, noise and drift. Supply your own measurements and limits; the template supplies no instrument values.

Describe capabilities precisely enough for the computational researcher to build a digital twin, a simulation of the proposed experiment, and an executable run packet. Distinguish an available control from a proposed extension, and a calibrated working point from an older measurement. Check these descriptions against the instrument's present operation before using the pack.

## Operating instructions and safety rules

In `lab-agent-instructions.md`, tell the experimentalist how to run a packet on this instrument. Specify the calibrations that begin each acquisition, how to report failed controls, and how to record deviations with times and reasons. Preserve the template's exchange instructions and `RUN-RESULT.json` format. [Outputs](outputs.md) provides that template and the returned-file contract.

In `lab-safety.md`, specify the laboratory's hard limits, what the experimentalist must do when a protocol step would exceed them, and how to leave the instrument safe on every exit path. The safety agent reads these rules with the packet and instrument specification. Keep the instructions consistent with the instrument's own tool-enforced limits. See [Remote agents](remote-agents.md) for supplying the instructions and safety rules through SSH or manual hand-off, and [Safety](safety.md) for operational responsibilities.

## Check the authored pack

Replace every required `[insert: ...]` part and retain the prompt placeholders that route the domain material. `auctopus doctor` lists missing or unwritten files used by the configured stages. `auctopus new` refuses to start until that list is empty, unless you use `--force`.

These checks identify missing and unwritten files. Before a real run, review the sample card, testability rules and current instrument specification together for scientific and operational consistency.
