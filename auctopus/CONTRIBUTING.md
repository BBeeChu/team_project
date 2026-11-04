# Contributing to Auctopus

Contribute code, tests, templates or documentation using the local setup and review process below. Contributions must not include secrets, the authors' unpublished study prompts or private instrument descriptions. Use minimal synthetic prompts and data, example hostnames and redacted configuration excerpts to explain a change.

## Set up a local checkout

Use Python 3.11 or later. If `python` selects an older interpreter, use the command for your supported interpreter, such as `python3`. From the directory where you want the checkout, run:

```bash
git clone https://github.com/E-zClap/auctopus.git
cd auctopus
python -m venv .venv
```

Activate the virtual environment. On Linux or macOS:

```bash
source .venv/bin/activate
```

On Windows, in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

With the environment active, install the checkout and record its version:

```bash
python -m pip install -e .
auctopus --version
```

The editable installation uses the checked-out package. Keep the environment active and run the checks below from the repository root. Local tests and the offline demo need no API keys or remote machines.

Real remote agents run without interactive approvals by default. Before testing on an HPC, another Linux server or an instrument computer, read [Safety](docs/safety.md) and [Remote agents](docs/remote-agents.md). Use accounts and machines set aside for this work.

## Run the offline tests

From the repository root, run:

```bash
python -m unittest discover -s tests
```

The suite contains 66 offline tests and uses only the Python standard library. It covers decision parsing and fallbacks, prompt assembly, SSH transport through a fake `ssh` client, model clients against fake SDKs, crash recovery and end-to-end scenarios. The [tests](tests/) make no network requests.

## Run the offline smoke test

From the repository root, run:

```bash
auctopus dry-run
```

Without a project, this creates a temporary project beneath `auctopus-dry-run/`, which is git-ignored. The default scenario, `revision-then-win`, rejects the first proposal batch and selects from its revision batch. Success means all eight stages are marked done and the command exits with code 0.

Open `decisions-journal.md` in the run folder printed by the command. Check the recorded decisions when reviewing a workflow change. [Outputs](docs/outputs.md) explains the other saved files.

The demo uses mock models, mock coding agents and local folders in place of remote machines. It exercises workflow decisions and file handling without API keys, authored prompts or SSH. Human approval is skipped. Mock replies depend on the stage and attached files, so the demo does not test prompt wording or physical instrument operation.

Repeat a scenario with `auctopus dry-run`. Dry-run folders cannot be resumed or approved.

For the scenario also used in CI, run:

```bash
auctopus dry-run --scenario lab-redo
```

This exercises laboratory redesign, a safety correction and an amended repeat of a failed mock acquisition. See [Running](docs/running.md) for all four scenarios and their expected outcomes.

## Check the CI requirements

The [tests workflow](.github/workflows/tests.yml) tests all combinations of Ubuntu and Windows with Python 3.11, 3.12 and 3.13. It installs the package, treats `ResourceWarning` as an error during tests, then runs `lab-redo`.

Use the same checks locally before submitting code changes:

```bash
python -W error::ResourceWarning -m unittest discover -s tests
auctopus dry-run --scenario lab-redo
```

Report the commands and results in your pull request. If a check fails, include a short redacted excerpt and explain what remains unresolved.

## Find the relevant package files

Paths below are relative to the repository root. Module names within subdirectories are listed without the `.py` extension.

| Path | Contents |
|---|---|
| `auctopus/` | Core modules: `cli.py`, `config.py`, `pipeline.py`, `conversation.py`, `parsing.py`, `prompt_builder.py`, `attachments.py`, `state.py`, `util.py`, `context.py`. |
| `auctopus/llm/` | Model clients and their base: `openai_client`, `anthropic_client`, `mock_client`, `base`. |
| `auctopus/remote/` | Remote execution support: `transport`, `agents`, `job_wrapper`, `mock_agent`. |
| `auctopus/stages/` | Workflow modules: `front`, `experiments`, `lab`, `figures`, `reviewers`, `deliver`, `chain`. |
| `auctopus/resources/` | `config.example.toml`, 33 templates in `prompts/`, seven files in `domains/template/`. |
| `tests/` | `test_config_prompts`, `test_conversation`, `test_llm_clients`, `test_parsing`, `test_pipeline`, `test_transport`, plus `fake_ssh.py` and `helpers.py`. |
| `docs/` | User guides and references; start at the [Documentation index](docs/README.md). |

Read the surrounding implementation and its tests before editing. [Workflow](docs/workflow.md) explains stages and information boundaries; [Prompts](docs/prompts.md) describes response contracts.

## Report a useful bug

Search existing issues, then use the bug-report form. Include:

- The result of `auctopus --version`, or the version you tried or checkout commit if the command cannot run.
- Your Python version and operating system.
- The command and the relevant stage or dry-run scenario.
- Minimal steps to reproduce the problem, plus expected and actual behaviour.
- A short redacted log excerpt around the failure and any relevant exit code.

State whether the problem occurs in an offline dry run, through manual laboratory hand-off or with live services. If an offline scenario reproduces it, identify that scenario. Do not attach a whole project or run folder: saved prompts, conversations and logs can contain private material.

Remove API keys, credentials, private host details and confidential research material. Use minimal synthetic prompts and data, example hostnames and redacted configuration excerpts for reproduction. For a suspected vulnerability, follow [Security](SECURITY.md) and keep the problem details out of public issues.

## Propose and prepare a change

For a larger change, start with a feature request. Describe the task you cannot complete, the proposed behaviour and where it belongs in the research workflow. Identify effects on configuration, decision handling, saved files or recovery. This gives maintainers enough context to assess the change before implementation.

Prepare the contribution in this order:

1. Fork the [repository](https://github.com/E-zClap/auctopus) and use your fork as the push destination for your checkout.
2. Create a branch from `main` for the change. Keep the commits focused on one problem and run the relevant checks.
3. Push the branch to your fork and open a pull request against `E-zClap/auctopus`, targeting `main`.
4. Complete the pull-request template, link relevant issues and respond to review comments by updating the same branch.

Explain the resulting behaviour and record your checks. Mark documentation or checks as “Not applicable” when they do not apply. Follow the [Code of conduct](CODE_OF_CONDUCT.md) in issues and reviews.

## Follow code, test and documentation conventions

Match the surrounding code style. No linter or formatter is configured. Keep unrelated edits out of the change and explain behaviour that is not apparent from the code.

Add or update offline tests when changing behaviour. Use the existing mocks and fake clients; tests must not need provider credentials, SSH hosts or an instrument. For a bug fix, cover the failing case. For decision or recovery changes, check the affected fallback and continuation behaviour as well as the successful path.

Update documentation and shipped templates when commands, settings, response contracts or file handling change. Keep template placeholders and machine-readable decision lines consistent with the implementation. Use synthetic examples; keep private authored material outside the repository through `project.prompts_dir` and `project.domain_dir`.

Write documentation in direct, precise language with British spelling and sentence-case headings. Give each page one main task. Use relative links, copyable commands without shell prompts, and separate output blocks. Use tables for lookup and numbered lists for procedures.

Quote observed output accurately; do not invent logs or model replies. Keep outcome words lowercase in prose and exact response lines in code. Distinguish defaults from configurable policy, model instructions from technical restrictions, and workflow completion from scientific success. Use “run” for one workflow execution and “acquisition” for one execution of a run packet on the instrument.
