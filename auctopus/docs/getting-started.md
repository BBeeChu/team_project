# Getting started

This guide prepares your first real run with Auctopus, the Python package and command-line tool for orchestrating research agents. The release supplies the engine and templates ([The paper](paper.md)); you configure your study, prompts and machines below. For offline scenarios, see [Running](running.md#run-the-offline-scenarios).

## 1. Choose providers, machines and stages

Make these choices before preparing services or credentials:

| Choice | Available options |
|---|---|
| Model roles | OpenAI or Anthropic for each role. Choose accessible models in step 3. |
| Computational researcher | Codex by default on an HPC system or Linux server, reached over SSH. |
| Laboratory work | Enabled by default; set `chain.lab = false` to omit it. Later enabled stages still run. |
| Laboratory transport, if enabled | Claude Code by default on the instrument computer over SSH, or a manual exchange folder with an agent or person handling the packet. |
| Figures | Enabled by default; set `chain.figures = false` to omit them. |
| Manuscript reviewers | Enabled by default; set `chain.reviewers = []` to omit them. |

Model roles and remote coding agents are configured separately. For custom coding agents, see [Remote agents](remote-agents.md); for stage behaviour, see [Workflow](workflow.md).

> [!WARNING]
> Remote coding agents run without interactive approvals by default. Use dedicated machines and accounts, and keep publishing credentials off them. Read [Safety](safety.md) before preparing machines or connecting an instrument.

**Check:** you have chosen role providers, a computational host and enabled stages. If laboratory work is enabled, you have chosen how its files reach the instrument.

## 2. Install the command and create a project

These commands assume an activated Python 3.11 or later virtual environment. From the repository clone used for the offline demo:

```bash
python -m pip install -e .
auctopus init my-lab
cd my-lab
```

If `python` does not select Python 3.11 or later, use the appropriate interpreter, such as `python3`, in the installation command. Installation adds `auctopus` and its provider dependencies.

Edit the project's copies of the configuration, prompts and domain pack. The remaining project commands read `config.toml` in your current folder, or the file supplied with the global `--config PATH` option. Relative configuration paths resolve from that file's folder.

**Check:** `my-lab` contains `config.toml`, `prompts/`, `domain/` and `.gitignore`; your terminal is in that folder.

## 3. Set stages, keys and models

Apply your stage choices in `[chain]`. For manual laboratory exchange, set `transport = "manual"` and `exchange_dir` in `[lab]`.

The configured stages and settings determine which model roles need values:

| Condition | Required roles |
|---|---|
| Always | `proposer`, `pi`, `pi_review` |
| `proposals.dedup = true` | `dedup` |
| `proposals.manager_exclusions_after > 0`, or both `chain.lab` and `chain.manager_redesign` are true | `manager` |
| `chain.lab = true` | `feasibility` |
| Both `chain.lab` and `lab.safety_review` are true | `safety` |
| Roles named in `chain.reviewers` | Every role in that list |

For model-role calls, only these roles need a model and their provider's key. Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the environment, or use `openai_api_key` and `anthropic_api_key` under `[keys]`. Environment variables take precedence; the generated `config.toml` is git-ignored.

The default remote coding agents have separate key requirements: OpenAI for Codex and Anthropic for Claude Code. You need both provider keys if you use both agents, even when all model roles use one provider.

```bash
auctopus models
```

Use the accessible model names to set `provider` and `model` for each required `[roles.NAME]`. See [Configuration](configuration.md) for effort, output limits and timeouts. A later `--until` pause does not narrow readiness requirements; they follow the configured stages.

**Check:** model discovery lists available choices, and each required role has a provider and model name without an `insert` placeholder.

## 4. Write the domain pack and prompts

Complete the files in `domain/`:

1. Describe the physical system, controls, measurements and key parameters in `sample-card.md`.
2. Define testability in `proposer-rule.md` and `pi-rule.md`, and excluded idea families in `exclusions.md`.
3. If laboratory work is enabled, complete `instrument.md`, `lab-agent-instructions.md` and `lab-safety.md`. Put current instrument capabilities first, with limiting numbers, units and dates.

[Domain packs](domain-packs.md) explains each file. Then replace the `[insert: ...]` parts in the required `prompts/` files, preserving interpolation placeholders and machine-readable reply lines. [Prompts](prompts.md) identifies each template's recipient, attachments and reply contract.

```bash
auctopus doctor
```

**Check:** the report no longer lists missing or unwritten prompt and domain files for the configured stages. Remote settings may still need attention in step 5.

## 5. Prepare the remote agents

SSH uses the system OpenSSH client in batch mode. Prepare key-based login without password prompts; aliases, keys, agents and ProxyJump settings in `~/.ssh/config` are supported.

Each SSH host needs `bash`, `tar` and its coding agent. The following installs also require Node.js and npm on that host.

On the computational host, install the default Codex agent:

```bash
npm install -g @openai/codex
```

When laboratory work is enabled and uses SSH, install the default experimentalist on the instrument computer:

```bash
npm install -g @anthropic-ai/claude-code
```

Set `host`, `user` and `remote_root` in `[hpc]`. Set them in `[lab]` when laboratory work is enabled and uses SSH. The `user` placeholder may remain if `host` is an SSH alias that supplies the user; `host` and `remote_root` are required. Leaving `identity_file` at its placeholder uses your SSH agent or configuration. Set `path_prepend` if the agent is outside the default PATH. See [Remote agents](remote-agents.md) for custom commands and scheduler instructions.

Back in the local project folder:

```bash
auctopus setup-remote hpc
```

When laboratory work is enabled and uses SSH, also run:

```bash
auctopus setup-remote lab
```

Each command creates `remote_root` and writes the agent's key to `env_file` with mode 600 over SSH.

For manual transport, omit laboratory SSH setup. Identify the operator and agree on the inbox/outbox contract in [Outputs](outputs.md). The inbox includes the packet, `RUN-REQUEST.json` and `LAB_AGENT_INSTRUCTIONS.md`; give `domain/lab-safety.md` to the operator separately because it is not included.

**Check:** each SSH host has its working directory and private environment file for the API key. For manual exchange, the operator has the safety rules and knows where to collect packets and return results.

## 6. Check readiness and connectivity

```bash
auctopus doctor
```

Resolve the offline checklist until the report says `Ready.`. `auctopus new` normally refuses to start while that list is non-empty.

Real runs use paid APIs and can last many hours. Review the cost controls in [Safety](safety.md) before testing services or starting a run.

```bash
auctopus doctor --online
```

The online check tests keys and models for the required roles, plus configured SSH connections and remote setup. It checks writable remote roots, availability of `tar` and the agent, and presence of the key file.

**Check:** the offline report says `Ready.`, and online checks show no remaining key, model or remote-setup failures.

## 7. Inspect proposals before continuing

Start with the proposal search:

```bash
auctopus new --until proposals
auctopus status
```

Note the reported run folder and open its `decisions-journal.md` to inspect the search decisions. After selection, read `pi-verdict.md` for the PI's assessment. [Outputs](outputs.md) maps the other artefacts. If the run is blocked, read `RUN-BLOCKED.md` and follow [Running](running.md#monitor-a-run).

After inspecting the proposal results, continue through the theory, computational verification and PI review. Replace `<run>` with the intended run folder or name:

```bash
auctopus resume "<run>" --until verify-review
auctopus status "<run>"
```

This second pause is before laboratory work. Inspect the computational reports and journal before continuing.

**Check:** `status` marks `proposals` done after the first pause, then stages through `verify-review` done after the second. Resolve any recorded block before proceeding.

## 8. Continue and review the laboratory packet

```bash
auctopus resume "<run>"
```

With laboratory work enabled, safety-agent review and human approval are required by default. At the human checkpoint, the run writes `LAB-APPROVAL-REQUIRED.md` and exits with code 2. Read the protocol, raw-data schema, analysis and twin material in the packet, plus the safety review identified in the note. Under these defaults, the packet has not reached the instrument.

Before declining or editing a packet, follow [Running](running.md#approve-or-decline-a-laboratory-design). To approve:

```bash
auctopus approve "<run>"
auctopus resume "<run>"
```

If laboratory work is disabled, resuming proceeds to the later enabled stages.

**Check:** approval renames the note to `LAB-APPROVAL-GRANTED.md` and records it in `state.json`. Follow subsequent progress with `status`; interpret exit codes and completion markers in [Running](running.md#read-exit-codes-and-completion-markers).
