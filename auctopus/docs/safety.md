# Safety and operational responsibilities

Before connecting an instrument, check the remote agents' execution permissions and the enabled approval requirements. Your laboratory maintains the instrument's technical limits and decides whether a proposed protocol is suitable for the apparatus.

## Control remote execution

> [!WARNING]
> The default Codex command bypasses interactive approvals and its sandbox. The default Claude Code command bypasses permission checks. Use dedicated machines and accounts, and review the access available to them.

These commands define Auctopus's default permission policy for unattended tasks:

```bash
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check {model_flag}"$(cat {prompt_file})"
claude -p --dangerously-skip-permissions --output-format text {model_flag}"$(cat {prompt_file})"
```

Codex is the default computational researcher; Claude Code is the default experimentalist. To restrict execution, replace the launch command through `hpc.agent_command` or `lab.agent_command`. These overrides accept `{model_flag}`, `{prompt_file}` and `{model}`. Set `agent = "custom"` in the relevant section when substituting another agent. See [Remote agents](remote-agents.md).

## Check laboratory approvals

Inspect the active configuration before relying on either checkpoint. Both requirements are enabled by default and can be disabled:

| Setting | Requirement when enabled |
|---|---|
| `lab.safety_review = true` | The safety agent must approve the packet before instrument hand-off. |
| `lab.require_approval = true` | A person must approve the design with `auctopus approve <run>` before instrument hand-off. |

Each safety review starts a fresh conversation with the packet's README, protocol and raw-data schema, the instrument specification and laboratory safety rules. An explicit `SAFETY: APPROVE` is required; missing or unreadable decisions count as rejection. Rejection leads to correction and another review. Continued rejection after `lab.safety_fix_rounds` corrections, default `1`, stops the run before hand-off. [Prompts](prompts.md) specifies the decision-line contract.

At the human checkpoint, read the packet and its safety review, if enabled, before approving. A model's approval does not establish that an experiment is safe.

To decline the design, `auctopus resume <run> --from lab` restarts the laboratory stage from feasibility review, with new triage and a new packet in a new round. Edits to the old packet are not carried over. If you instead edit packet files and run `auctopus approve <run>`, your edited files are sent without a new safety review: the safety agent reviewed the earlier version. See [Running](running.md) for the approval procedure.

## Maintain instrument rules and limits

Write and maintain `domain/lab-safety.md` and `domain/lab-agent-instructions.md` for your apparatus and operating conditions. The experimentalist is instructed to follow them. Keep `domain/instrument.md` current, with capabilities first and limiting numbers accompanied by units and dates. [Domain packs](domain-packs.md) explains these files.

Your laboratory must maintain the technical limits enforced by the instrument's own tools. Model instructions and review do not replace those controls or your assessment of the protocol.

For manual hand-off, give the laboratory safety rules to the receiving person or agent separately. The inbox contains `LAB_AGENT_INSTRUCTIONS.md`, but excludes `domain/lab-safety.md`; over SSH, Auctopus appends those rules to the experimentalist's prompt.

## Handle interruptions and repeat acquisitions

Remote jobs run detached by default. **Ctrl-C, a crash or a reboot of the orchestrator's computer leaves those jobs running.** Handle an active job or acquisition on its host under your laboratory's procedures.

Infrastructure recovery never relaunches a physical acquisition. SSH retries reconnect; ordinary resume waits for the existing job or collects its result.

After an acquisition returns a status other than `done`, the principal investigator (PI) agent can authorise a repeat through `RERUN-DECISION`, bounded by `chain.lab_reruns`, default `1`:

- `APPROVE` repeats the unchanged packet without a new safety review or human approval; any existing approvals stand.
- `AMEND` asks the computational researcher to change the packet, then repeats the enabled safety and human approval checks.
- `REJECT`, or an exhausted repeat allowance, means no further acquisition. The computational researcher still analyses the last acquisition's `RUN-RESULT.json`, data and deviations, and the PI reviews that analysis once.

## Protect credentials and publication control

Environment variables take precedence over keys in the git-ignored `config.toml`. Remote setup writes the agent's key to its configured `env_file` with mode `600`; transfer uses the SSH session, without putting the key on a command line.

Both remote agents receive a standing no-publish instruction. This is an instruction to a model, not a technical access restriction. **Keep publishing credentials off agent hosts.** [Prompts](prompts.md) describes the instructions added to agent tasks.

## Control API costs and execution limits

Choose limits before starting paid work:

- Proposal search: `proposals.max_batches`, `proposals.proposers`, `proposals.revision_proposers` and `proposals.assess_after`, the reply threshold for early assessment and cancellation of remaining requests.
- Model calls: `max_output_tokens`, `timeout_s` and `max_attempts` in each `[roles.NAME]` section.
- Later stages: `chain.review_mode`, `chain.lab_reruns` and optional stages.

[Configuration](configuration.md) gives defaults and interactions. Ordinary resume reuses completed replies. Only OpenAI background responses resume in-flight requests by response ID; other in-flight requests are sent again and can incur another charge.

## Inspect run records

Read `decisions-journal.md` alongside the packet, acquisition records and analysis. [Outputs](outputs.md) explains the evidence and completion records. For software vulnerability reporting, see [Security](../SECURITY.md).
