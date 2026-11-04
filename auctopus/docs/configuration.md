# Configuration reference

Use this reference to look up settings, defaults and interactions in `config.toml`. Follow [Getting started](getting-started.md) for the setup sequence.

## Configuration location and values

Commands that operate on an existing project read `config.toml` in the current folder, or the file supplied with the global `--config PATH` option. After `auctopus init my-lab`, change into `my-lab`, or specify the configuration explicitly:

```bash
auctopus --config my-lab/config.toml doctor
```

`auctopus init` creates a project and copies the shipped example configuration. The offline demo can also run without a project: `auctopus dry-run` creates one under `auctopus-dry-run/<stamp>/` in the current folder.

Relative local paths are resolved from the folder containing `config.toml`. Remote paths such as `remote_root` and `env_file` identify locations on the corresponding host.

A string starting with `insert` counts as unset. Unknown keys produce warnings, so check them for misspelt settings. The project configuration is git-ignored; keep credentials out of shared excerpts.

The tables compare code defaults with [auctopus/resources/config.example.toml](../auctopus/resources/config.example.toml). **Same** means the example explicitly sets the code default. **Not set** means the example omits the setting and uses its default.

## Project paths and history

These settings belong to `[project]`.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `name` | Project name. | `"auctopus"` | Same |
| `runs_dir` | Folder containing runs. | `"runs"` | Same |
| `prompts_dir` | Folder containing authored stage prompts. | `"prompts"` | Same |
| `domain_dir` | Folder containing the domain pack. | `"domain"` | Same |
| `log_level` | Logging level. | `"INFO"` | Same |
| `max_history_chars` | Principal investigator (PI) conversation size that triggers compaction, in characters. | `900000` | Same |

The prompt and domain folders may be outside the project. When PI history exceeds `max_history_chars`, earlier turns become a summary, the latest exchange stays verbatim, and old turns are archived beside the conversation. See [Workflow](workflow.md) for conversation boundaries.

## API keys and required roles

These settings belong to `[keys]`.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `openai_api_key` | OpenAI credential; `OPENAI_API_KEY` takes precedence. | `"insert OpenAI API key here"` | Same |
| `anthropic_api_key` | Anthropic credential; `ANTHROPIC_API_KEY` takes precedence. | `"insert Anthropic API key here"` | Same |

Both default values count as unset. For model-role API calls, only the roles below need a model and their provider's key. `doctor` reports model placeholders for these roles, and `doctor --online` tests only their models. Remote coding agents have separate key requirements; see [Remote agents](remote-agents.md).

| Role | Required when |
|---|---|
| `proposer`, `pi`, `pi_review` | Always. |
| `dedup` | `proposals.dedup = true`. |
| `manager` | `proposals.manager_exclusions_after > 0`, or both `chain.lab` and `chain.manager_redesign` are enabled. |
| `feasibility` | `chain.lab = true`. |
| `safety` | Both `chain.lab` and `lab.safety_review` are enabled. |
| Every role in `chain.reviewers` | The role appears in that list. |

Use `auctopus models` to list the model names available to your keys. Any model role can use OpenAI's Responses API or Anthropic's Messages API; a name such as `reviewer_gpt` does not restrict its provider.

## Role defaults and overrides

Each `[roles.NAME]` starts with the generic defaults, then its built-in defaults below, then values from `config.toml`. A role table overrides individual keys; an absent table retains the built-in defaults. A reviewer named in `chain.reviewers` without built-in defaults uses the generic defaults directly.

The provider and model defaults below are also explicitly set in the shipped example.

| Role | Provider | Model |
|---|---|---|
| `proposer` | `"openai"` | `"insert OpenAI model for the proposers"` |
| `dedup` | `"openai"` | `"insert OpenAI model for deduplication"` |
| `pi` | `"openai"` | `"insert OpenAI model for the principal investigator"` |
| `pi_review` | `"openai"` | `"insert OpenAI model for the PI's reviews"` |
| `feasibility` | `"openai"` | `"insert OpenAI model for the feasibility reviewer"` |
| `reviewer_gpt` | `"openai"` | `"insert OpenAI model for the GPT reviewer"` |
| `reviewer_claude` | `"anthropic"` | `"claude-opus-5-5"` |
| `manager` | `"anthropic"` | `"claude-opus-5-5"` |
| `safety` | `"anthropic"` | `"claude-opus-5-5"` |

This matrix gives the remaining built-in values. Each cell is **code default / shipped example**; **omitted** means that key is absent from the example role table.

| Role | `effort` | `max_output_tokens` | `background` | `web_search` | `timeout_s` |
|---|---|---|---|---|---|
| `proposer` | `xhigh` / `xhigh` | `0` / `0` | `true` / `true` | `true` / `true` | `3600` / omitted |
| `dedup` | `medium` / `medium` | `0` / `0` | `false` / omitted | `false` / omitted | `3600` / omitted |
| `pi` | `high` / `high` | `0` / `0` | `true` / `true` | `true` / `true` | `3600` / `14400` |
| `pi_review` | `xhigh` / `xhigh` | `0` / `0` | `true` / `true` | `false` / omitted | `3600` / `7200` |
| `feasibility` | `xhigh` / `xhigh` | `0` / `0` | `true` / `true` | `false` / omitted | `3600` / omitted |
| `reviewer_gpt` | `high` / `xhigh` | `0` / `0` | `true` / `true` | `true` / `true` | `3600` / omitted |
| `reviewer_claude` | `high` / `high` | `64000` / omitted | `false` / omitted | `true` / `true` | `3600` / omitted |
| `manager` | `high` / `high` | `64000` / omitted | `false` / omitted | `false` / omitted | `3600` / omitted |
| `safety` | `high` / `high` | `64000` / omitted | `false` / omitted | `false` / omitted | `3600` / omitted |

### Options available to every role

These keys can appear in any `[roles.NAME]` table. Provider-specific controls apply only to that provider; the chosen model determines which capabilities it supports.

| Setting | Meaning | Generic code default | Shipped example |
|---|---|---|---|
| `provider` | `"openai"` or `"anthropic"`; `"mock"` for the offline demo. | `"openai"` | Role table above |
| `model` | Provider model name. | `"insert model name here"` | Role table above |
| `effort` | Reasoning effort; values depend on provider and model. | `"high"` | Role matrix above |
| `max_output_tokens` | Output-token limit; `0` uses the provider's limit. | `64000` | Role matrix above |
| `timeout_s` | Model-request timeout, in seconds. | `3600` | Role matrix above |
| `background` | OpenAI background response with polling and a saved response id. | `false` | Role matrix above |
| `poll_s` | Background-response polling interval, in seconds. | `15` | Not set |
| `web_search` | Enable the provider's hosted web search. | `false` | Role matrix above |
| `web_search_type` | Hosted search tool type; empty selects the provider default. | `""` | Not set |
| `thinking` | Anthropic thinking setting: `"adaptive"` or `"omit"`. | `"adaptive"` | Not set |
| `prompt_cache` | Enable Anthropic prompt caching. | `true` | Not set |
| `fallbacks` | Enable Anthropic's fallback model for classifier-declined requests. | `true` | Not set |
| `max_attempts` | Total attempts for one model call, including the first. | `4` | Not set |
| `backoff_s` | Waiting intervals before subsequent attempts, in seconds. | `[60, 120, 300, 600]` | Not set |
| `max_continuations` | Maximum continuations of an Anthropic paused turn. | `4` | Not set |

OpenAI effort examples are `low`, `medium`, `high` and `xhigh`; Anthropic values are `low`, `medium`, `high`, `xhigh` and `max`. An empty `web_search_type` selects `web_search` for OpenAI or `web_search_20260209` for Anthropic. Set a different hosted tool type to select another version.

On Anthropic models that support `fallbacks`, a request declined by a safety classifier is rerun on Anthropic's recommended fallback model within the same call. When Anthropic pauses a long turn with stop reason `pause_turn`, Auctopus continues it up to `max_continuations` times. Server-side web search is one situation that can pause a turn.

### Model attempts and interrupted calls

`max_attempts` covers transient failures: rate limits, connection errors, timeouts, server errors and empty replies. The provider SDK's own short retries happen inside each Auctopus attempt.

Before attempt `n + 1`, Auctopus waits `backoff_s[n - 1]` seconds. With the defaults, there are at most four attempts and three waits: 60, 120 and 300 seconds. The fourth interval, 600 seconds, is used only if the attempt limit is increased. If the list is shorter than needed, its last value repeats.

A completed reply is saved immediately. For an unfinished OpenAI background request, the saved response id lets Auctopus resume polling after a restart. Other model requests still in flight when the orchestrator stops are sent again on resume. See [Running](running.md) for continuation procedures.

## Proposal search limits

These settings belong to `[proposals]`.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `proposers` | Number of proposers in each fresh batch. | `10` | Same |
| `concurrency` | Maximum proposer requests in flight. | `5` | Same |
| `stagger_s` | Delay between proposer requests, in seconds. | `2.0` | Same |
| `assess_after` | Number of sufficiently long replies that triggers early assessment; `0` waits for all. | `5` | Same |
| `refusal_min_words` | Minimum reply length counted towards `assess_after`, in words. | `600` | Same |
| `dedup` | Deduplicate proposals in fresh batches with at least two replies. | `true` | Same |
| `max_batches` | Total fresh and revision batches allowed before stopping without selection. | `24` | Same |
| `revision` | Allow one revision batch for a rejected fresh batch with a best seed. | `true` | Same |
| `revision_proposers` | Number of proposers in a revision batch. | `6` | Same |
| `selection` | `"strict"` permits rejection of every proposal; `"relaxed"` asks for the strongest. | `"strict"` | Same |
| `relax_after` | In strict mode, use relaxed selection from this batch number; `0` never relaxes. | `12` | Same |
| `manager_exclusions_after` | Number of consecutive unselected batches since the manager's last update that triggers new exclusions; `0` disables. | `6` | Same |

Once `assess_after` qualifying replies arrive, Auctopus cancels the remaining proposer requests and sends the batch for assessment. A reply below `refusal_min_words` still reaches the PI but does not count towards this threshold. Despite its name, this setting is a length rule, not semantic refusal detection. A separate junk filter drops replies under 400 characters, or under 600 characters with an error phrase.

A rejected fresh batch with a readable best seed can receive one revision batch when `revision` is enabled. That revision batch is not revised again. Both kinds of batch count towards `max_batches`; the run also stops immediately if every proposer in one batch fails.

The manager updates exclusions before the next fresh batch once `manager_exclusions_after` unselected batches have accumulated since its last update. These additions affect later fresh batches. `relax_after` changes the PI's selection instruction: the default switches at batch 12 from permitting complete rejection to asking for the strongest proposal. See [Workflow](workflow.md) for the search branches and [Prompts](prompts.md) for selection parsing.

## Stage switches and review settings

These settings belong to `[chain]`.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `theory_steps` | Ordered prompt steps in the continuing PI conversation. | `["02-proofs", "02b-positioning", "03-write", "04-exp"]` | Same |
| `file_steps` | Steps receiving engine-added file-delivery instructions. | `["03-write", "03b-redeliver"]` | Not set |
| `lab` | Enable the laboratory stage. | `true` | Same |
| `figures` | Enable figure preparation and review. | `true` | Same |
| `reviewers` | Manuscript-referee roles; `[]` skips the reviewers stage. | `["reviewer_claude", "reviewer_gpt"]` | Same |
| `review_mode` | Review policy for verification and final PI review: `"once"` or `"until-accept"`. | `"once"` | Same |
| `max_review_rounds` | Verification-review limit in `"until-accept"` mode. | `5` | Same |
| `final_review_rounds` | Final PI-review limit after the reviewers' revision, in `"until-accept"` mode. | `2` | Same |
| `manager_redesign` | Request a manager design and one PI ruling after the PI declines the laboratory test. | `true` | Same |
| `lab_reruns` | Maximum additional acquisitions authorised by the PI's rerun ruling. | `1` | Same |
| `review_max_files` | Maximum number of files attached to one PI review. | `9` | Same |
| `review_max_mb` | Total attachment size in one message, in MB. | `18.0` | Same |

Setting `lab = false` or `figures = false` skips that stage. An empty `reviewers` list skips the reviewers stage. These configuration choices are separate from the agents' decisions within an enabled stage.

For verification and final PI review, `"once"` permits one review and at most one revision. `"until-accept"` requires acceptance within the corresponding review-round limit. Packet, laboratory-analysis and figure reviews keep their single-review, single-fix policy in either mode. [Prompts](prompts.md) gives the complete review-policy and decision-line tables, including the laboratory decisions.

`review_max_mb` applies to every message carrying attachments, not only PI reviews. Files beyond its total budget are skipped with a warning. `review_max_files` separately caps the files attached to each PI review, including the images for the remaining-figure review. See [Outputs](outputs.md) when auditing the evidence retained locally.

## SSH and remote-agent settings

`[hpc]` configures the computational researcher on an HPC or another Linux server. `[lab]` configures the experimentalist on the instrument computer. The following settings are shared; paired defaults are HPC / lab.

Read [Safety](safety.md) before preparing the hosts. [Remote agents](remote-agents.md) gives installation, default commands, custom-command substitutions and recovery behaviour.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `transport` | `"ssh"`; `"local"` simulates a remote host with a local folder. Lab also accepts `"manual"`. | `"ssh"` | Same |
| `host` | SSH hostname or `~/.ssh/config` alias. | Unset placeholder | Host placeholders |
| `user` | SSH username; may remain unset when the SSH alias supplies it. | Unset placeholder | Username placeholders |
| `port` | SSH port. | `22` | Same |
| `identity_file` | SSH private-key path; unset uses ssh-agent or SSH configuration. | Unset placeholder | Unset placeholder |
| `ssh_options` | Additional SSH arguments, for example `["-J", "gateway.example.org"]`. | `[]` | Same |
| `connect_timeout_s` | SSH connection timeout, in seconds. | `20` | Not set |
| `retries` | Additional attempts after an SSH connection failure with exit code 255. | `5` | Not set |
| `remote_root` | Working directory on the corresponding host. | Unset placeholder | Working-directory placeholders |
| `env_file` | Remote credentials file sourced by the job launcher. | `"~/.auctopus/env"` | Same |
| `path_prepend` | Path prepended for agent discovery in the unattended job. | `"$HOME/.local/bin"` | Same |
| `agent` | `"codex"`, `"claude"` or `"custom"`. | `"codex"` / `"claude"` | Same |
| `agent_model` | Model passed to the remote coding agent. | Unset placeholder / `"claude-opus-5-5"` | HPC placeholder; lab same |
| `agent_command` | Agent-command override; empty uses the command for `agent`. | `""` | Same |
| `job_timeout_h` | Remote task timeout, in hours. | `24` / `72` | `24.0` / `72.0` |
| `poll_s` | Remote-job polling interval, in seconds. | `60` / `300` | `60.0` / `300.0` |
| `detach` | Launch with `nohup` in its own session, then poll. | `true` | Same |
| `pull_exclude` | Patterns excluded from folder pulls. | `[".git", "__pycache__", "*.ckpt", "*.pt"]` | Not set |
| `max_pull_mb` | Total size of one pull of a remote folder, in MB. | `500` / `5000` | HPC `200.0`; lab not set |
| `extra_instructions` | Agent site notes: scheduler, modules, GPUs or quotas. | `""` | HPC same; lab not set |

For SSH transport, `host` and `remote_root` are required. If an alias in `~/.ssh/config` sets the username, `user` may stay a placeholder and Auctopus connects to `host` alone.

The default `retries = 5` allows the initial SSH attempt plus up to five more attempts, with waits between them. Only SSH exit code 255 triggers this retry mechanism; it does not retry other failures. [Remote agents](remote-agents.md) distinguishes reconnection, job restart and acquisition repeats.

`hpc.max_pull_mb` and `lab.max_pull_mb` each apply to the aggregate files in one folder pull. [Outputs](outputs.md) explains how to find files omitted from a pull.

## Laboratory checks and manual exchange

These additional settings belong to `[lab]`.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `safety_review` | Require safety-agent approval before instrument hand-off. | `true` | Same |
| `safety_fix_rounds` | Packet correction passes allowed after safety rejection. | `1` | Same |
| `require_approval` | Require a human to approve the experimental design. | `true` | Same |
| `exchange_dir` | Local exchange root for `transport = "manual"`. | `"lab-exchange"` | Same |

See [Safety](safety.md) for approval responsibilities, [Prompts](prompts.md) for rejection and rerun decisions, and [Running](running.md) for approving or replaying a laboratory stage. [Remote agents](remote-agents.md) describes the manual hand-off; [Outputs](outputs.md) specifies its inbox and outbox.

## Offline scenario setting

This setting belongs to `[mock]` and is used only by `auctopus dry-run`.

| Setting | Meaning | Code default | Shipped example |
|---|---|---|---|
| `scenario` | `"win-first"`, `"revision-then-win"`, `"never-win"` or `"lab-redo"`. | `"revision-then-win"` | Same |

Dry-run folders cannot be resumed or approved. Repeat a scenario with `auctopus dry-run`; see [Running](running.md) for scenario outcomes.
