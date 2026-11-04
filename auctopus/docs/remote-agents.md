# Remote-agent setup and jobs

Use this reference to prepare remote agents, inspect their jobs and arrange a manual laboratory hand-off. Follow [Getting started](getting-started.md) for the first-project setup sequence.

## Choose hosts and laboratory transport

The computational researcher works on an HPC or another Linux server, configured in `[hpc]`. The experimentalist works on the instrument computer, configured in `[lab]`. Codex is the default computational agent; Claude Code is the default experimentalist. For an alternative invocation, see [custom commands](#site-notes-and-custom-commands).

Choose the laboratory connection before preparing credentials:

| Route | How work reaches the instrument | What you prepare |
|---|---|---|
| SSH, `lab.transport = "ssh"` | Auctopus transfers the packet and starts the experimentalist remotely. | An SSH account, remote agent and working folder on the instrument computer. |
| Manual, `lab.transport = "manual"` | Auctopus writes an exchange folder and waits for returned files. | A shared folder or a way to carry files, with a person or agent executing the packet. |

The `local` transport uses local folders to simulate remote hosts for tests and the offline demo. For manual laboratory transport, prepare the computational host through SSH and use the hand-off procedure below for the laboratory.

## Default agent commands and permissions

With an empty `agent_command`, Auctopus uses these command templates. Auctopus replaces the braces before launch; do not paste these templates into a terminal unchanged.

```bash
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check {model_flag}"$(cat {prompt_file})"
claude -p --dangerously-skip-permissions --output-format text {model_flag}"$(cat {prompt_file})"
```

These defaults bypass interactive approval prompts. The Codex command also bypasses its sandbox. Use machines and accounts set aside for this work, or change the execution policy through `agent_command` before setup. See [Safety](safety.md) for account preparation, the no-publish instruction and laboratory approval responsibilities.

## Launch requirements and study software

For an SSH launch, the computer running Auctopus needs the system OpenSSH client. The remote machine needs the agent itself, `bash` and `tar`. Auctopus uses OpenSSH in batch mode, so authentication must work without a password prompt.

Install the software and provide the data and access needed by your study: computational libraries, manuscript-building tools and instrument-control software. Describe the computational environment in `hpc.extra_instructions` and the instrument computer's environment in `lab.extra_instructions`. Put the instrument specification, operating instructions and safety rules in the domain files described in [Domain packs](domain-packs.md).

The following installation commands require Node.js and npm on the relevant machine.

On the computational host:

```bash
npm install -g @openai/codex
```

On the instrument computer, when using the default SSH experimentalist:

```bash
npm install -g @anthropic-ai/claude-code
```

Set the machine's `path_prepend` if the agent binary is outside the non-interactive job's `PATH`. The shipped example uses `$HOME/.local/bin`.

## SSH connections and remote credentials

For each SSH machine, set `host` and `remote_root` in `config.toml`. A host can be an alias from `~/.ssh/config`. If that alias sets the user, `user` may remain a placeholder: Auctopus connects to `host` alone. Otherwise, supply the username.

SSH keys, `ssh-agent`, aliases and `ProxyJump` work through the system client as they do in a terminal. Use `port`, `identity_file` and `ssh_options` where needed. A placeholder `identity_file` selects authentication through `ssh-agent` or `~/.ssh/config`. See [Configuration](configuration.md) for path handling and placeholder rules.

Remote coding agents need their own provider key regardless of the providers chosen for model roles. The default Codex agent needs the OpenAI key; the default Claude Code agent needs the Anthropic key.

From the project folder containing `config.toml`, or with the global `--config PATH` option:

1. Configure the keys and choose `hpc.agent`, `hpc.agent_model`, `lab.agent` and `lab.agent_model` for the machines you use.
2. Prepare the computational host:

   ```bash
   auctopus setup-remote hpc
   ```

3. For an SSH laboratory connection, prepare the instrument computer:

   ```bash
   auctopus setup-remote lab
   ```

Each setup command creates `remote_root` and writes the agent's API key to `env_file`, with mode 600. Codex receives the OpenAI key, also as `CODEX_API_KEY`; Claude Code receives the Anthropic key. Keys travel inside the SSH session and do not appear on the command line. The default remote key file is `~/.auctopus/env`.

## Readiness checks

Run these checks from the same project folder:

```bash
auctopus doctor
auctopus doctor --online
```

Resolve the local findings before the online check. For model-role calls, `doctor` reports placeholders only for roles used by the configured stages; `doctor --online` tests only those models and their keys. [Configuration](configuration.md) lists the role-selection rules.

For SSH machines, the online check tests the login, whether `remote_root` is writable, whether `tar` and the selected agent can be found, and whether the key file exists. Test your task-specific libraries, manuscript build and instrument-control software separately.

## Site notes and custom commands

Use `hpc.extra_instructions` for scheduler, module, GPU and quota information. Use `lab.extra_instructions` for equivalent site notes on the instrument computer. The experimentalist also receives `domain/lab-agent-instructions.md` and the safety rules from `domain/lab-safety.md`; the computational researcher receives the instrument specification for laboratory work.

`agent_command` overrides the selected agent's default invocation. For another agent, set `agent = "custom"` and supply its command. The available substitutions are:

| Substitution | Value or use |
|---|---|
| `{model_flag}` | The model-option fragment for the configured agent and `agent_model`. The supplied commands place it directly before the quoted prompt argument. |
| `{prompt_file}` | The saved prompt file's path, used by `cat` in the supplied commands. |
| `{model}` | The configured `agent_model`, for a command that supplies its own model-option syntax. |

This complete override reuses the supplied Codex invocation:

```toml
[hpc]
agent = "codex"
agent_command = 'codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check {model_flag}"$(cat {prompt_file})"'
```

Keep the quoted `"$(cat {prompt_file})"` expression to pass the prompt text as one argument, and preserve the position of `{model_flag}`. For other command syntax, provide the shell quoting and spacing it requires. Write literal braces as `{{` and `}}`.

The agent must read the task, write deliverables in its working folder, update `NOTES-RESUME.md` and write `ROUND-DONE.json`. [Prompts](prompts.md) describes the task instructions; [Outputs](outputs.md) describes the completion records.

## Detached jobs, job files and saved notes

Each task starts a fresh, non-interactive agent session in its working folder. With `detach = true`, Auctopus starts the job with `nohup`, in its own session, and polls for completion. Job timeouts and polling intervals are listed in [Configuration](configuration.md).

The job files have this layout. `<workdir>` is the agent's working folder and `<job>` identifies the job.

```text
<workdir>/
  .auctopus/
    prompts/<job>.md
    jobs/<job>/
      run.sh
      started
      pid
      stdout.log
      stderr.log
      exit_code
```

The prompt file contains the task and standing rules. `run.sh` sources `env_file`, extends `PATH` and invokes the agent. The `started` marker prevents a retried launch from starting the same job twice. `exit_code` appears when the agent exits; the logs record its output.

Files remain available to later sessions. The computational researcher and experimentalist update `NOTES-RESUME.md` and leave earlier reports in the working folder; they do not retain a conversation between tasks.

For the first computational task, Auctopus sends the manuscript package and `experiment.md` to a new folder under `hpc.remote_root`. Each returned `hpc-roundN/` folder is a local snapshot after a task. [Outputs](outputs.md) explains the returned files and how to identify omitted files; [Configuration](configuration.md) lists transfer budgets and exclusions.

## Recovery from SSH, job and acquisition failures

| Failure | What Auctopus does |
|---|---|
| SSH connection failure, exit code 255 | Makes up to `retries` additional attempts, waiting between them. Other failures are not retried by this mechanism. |
| Computational process disappears without an exit code, or exceeds `job_timeout_h` | Starts that task once more. A second failure blocks the run and writes `RUN-BLOCKED.md`. |
| Orchestrator stops through Ctrl-C, a crash or a local reboot | Detached jobs continue. On resume, Auctopus waits for the running job or collects its finished result. |
| Acquisition returns a status other than `done` | Asks the principal investigator (PI) agent for a rerun ruling, subject to `chain.lab_reruns`. |

To continue after the orchestrator stops, run this from the project folder. `<run>` is the workflow's run folder or name.

```bash
auctopus resume <run>
```

Dry runs cannot be resumed or approved. Repeat an offline scenario with `auctopus dry-run`.

SSH reconnection and ordinary resume do not repeat an acquisition. Only the PI's `RERUN-DECISION` can do so. `RERUN-DECISION: APPROVE` repeats the unchanged packet without new safety review or human approval. `RERUN-DECISION: AMEND` asks the computational researcher to change the packet and repeats the enabled safety and human approval checks.

If the PI rejects a repeat or the allowance is exhausted, the computational researcher still analyses the last acquisition's returned status, data and deviations. The PI reviews that analysis once. See [Prompts](prompts.md) for the decision contract and [Running](running.md) for approval checkpoints and stage replay.

## Manual laboratory hand-off

Set `lab.transport = "manual"` and choose `lab.exchange_dir`. Auctopus writes `<exchange_dir>/inbox/<run-id>/` and waits for `<exchange_dir>/outbox/<run-id>/RUN-RESULT.json`. Here, `<run-id>` identifies one acquisition.

1. After the configured approvals, carry or share the acquisition's inbox folder. It contains the packet, `RUN-REQUEST.json` and `LAB_AGENT_INSTRUCTIONS.md`, copied from `domain/lab-agent-instructions.md`.
2. Give `domain/lab-safety.md` to the person or agent separately. The manual inbox does not contain these safety rules.
3. Have the experimentalist execute the protocol under the operating instructions and safety rules.
4. Return the files required by `results_schema.md` and the `deviations.md` report to the matching outbox. Write `RUN-RESULT.json` last, with status `done`, `aborted` or `failed`.

Use `done` only when every protocol step ran and every file in `results_schema.md` is present. [Outputs](outputs.md) gives the exchange layouts and the supplied result template.

Over SSH, Auctopus places the packet in `lab.remote_root/inbox/<run-id>/` and `LAB_AGENT_INSTRUCTIONS.md` at `lab.remote_root` itself. It appends the safety rules to the experimentalist's prompt.
