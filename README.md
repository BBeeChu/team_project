# team_project: Auctopus on three end-to-end AI-scientist benchmarks

This folder runs the [Auctopus](https://github.com/E-zClap/auctopus) workflow (the harness of *Collaborative AI
agents for autonomous experimental research with solid-state quantum spins*) on MLR-Bench, ResearchClawBench and
DiscoveryWorld, and scores every run with the benchmark's own evaluator.

```
team_project/
  auctopus/            the Auctopus checkout, with the benchmark layer added (auctopus/bench/) and a few core edits
  data/                benchmark checkouts (mlr-bench, researchclawbench, discoveryworld, ...; not in git)
  runs/                projects, runs and evaluations, one folder per benchmark and task (not in git)
  bench.py             entry point (python bench.py ...), equivalent to python -m auctopus.bench
  environment.yml      the conda environment
```

## Setup

```bash
conda env create -f environment.yml          # creates the env "team_project" (Python 3.11)
conda activate team_project
pip install -e auctopus                       # Auctopus with the benchmark layer
export OPENAI_API_KEY=sk-...                  # every role, the coding agent and the judges use OpenAI models
```

The benchmark checkouts in `data/` were made with:

```bash
git clone --depth 1 https://github.com/chchenhui/mlrbench data/mlr-bench
git clone --depth 1 https://github.com/InternScience/ResearchClawBench data/researchclawbench
git clone --depth 1 https://github.com/allenai/discoveryworld data/discoveryworld
```

## Run a task

```bash
python bench.py list --bench mlr                       # 201 tasks; rcb: 40; dw: 120 (8 themes x 3 levels x 5 seeds)
python bench.py run  --bench rcb --task Astronomy_000 --model gpt-5-nano --evaluate
python bench.py run  --bench mlr --task iclr2025_dl4c  --model gpt-5-nano --evaluate
python bench.py run  --bench dw  --task plant-nutrients-easy-s0 --model gpt-5-nano --evaluate
python bench.py evaluate --bench rcb --task Astronomy_000 --judge gpt-5-nano   # score the latest run again
python bench.py summary  --bench rcb                                           # runs/rcb/summary.{json,csv}
```

`run` writes the project (`runs/<bench>/<task>/project/`: config.toml, prompts/, domain/), starts an Auctopus run
under `project/runs/<stamp>/` and, with `--evaluate`, lays the outputs out for the benchmark's evaluator and scores
them into `runs/<bench>/<task>/eval/evaluation.json`. Ordinary Auctopus commands work on the project too
(`auctopus --config runs/rcb/Astronomy_000/project/config.toml status`, `resume`, `resume --from reviewers`).

Options: `--model` (every Auctopus role and the coding agent), `--judge` (the benchmark's evaluator), `--effort`
(low, medium, high), `--until STAGE`, `--resume`, `--opt steps=100` (DiscoveryWorld action budget; the benchmark's
defaults are 100 for Easy and 1000 for Normal and Challenge).

Offline check without any API key (mock models and mock agents, the DiscoveryWorld environment still runs):

```bash
python bench.py run --bench dw --task plant-nutrients-easy-s0 --mock --out-root runs-mock
python bench.py evaluate --bench dw --task plant-nutrients-easy-s0 --dry --out-root runs-mock
cd auctopus && python -m unittest tests.test_bench -v
```

## How each benchmark maps onto the workflow

| Stage | MLR-Bench | ResearchClawBench | DiscoveryWorld |
|---|---|---|---|
| proposals | ideas for the workshop call; strict PI selection | research questions testable with the data | hypotheses and a measurement plan |
| theory | method, precommitted predictions, related_work.md, proposal.md, main.md, experiment.md | analysis plan, positioning, report/report.md skeleton, protocol | hypotheses, decision rule, notebook main.md, protocol draft |
| verify + review | API coding agent runs the experiments, PI review, one revision | coding agent runs the analysis in a workspace with data/ and related_work/ | off |
| lab | off | off | feasibility, PI GO/NO-GO, manager redesign, run packet, PI packet review, experimentalist in the environment, rerun ruling, analysis, PI review |
| reviewers | two referees, triage, revision, final review | same | same |
| evaluator | mlrbench/evals: idea, proposal, experiment (+hallucination), paper (+hallucination), 1 to 10 | evaluation/score.py: weighted rubric, 0 to 100, 50 = the paper | environment scorecard (completion, procedure) + scripts/knowledgeScorer.py (critical questions) |

## What was kept and what was changed in Auctopus

Kept unchanged: the stage order and resumable state, the PI's persistent conversation, proposal batches with
deduplication, strict selection, revision batches and manager exclusions, every decision-line contract
(SELECTION, VERDICT, FEASIBILITY, LAB-DECISION, SAFETY, RERUN-DECISION), the remote job model (jobs, ROUND-DONE.json,
rounds pulled after each task), the laboratory stage logic, the referee stage and the delivery.

Changed in the core (every edit is marked `BENCH` in the source; `git diff` in `auctopus/` lists them):

| File | Change |
|---|---|
| `config.py` | `chain.verify` (skip the computational test), `chain.manuscript = "latex" \| "markdown"`, `hpc.inputs` (data pushed into the working folder), a `[bench]` table |
| `pipeline.py` | verify and verify-review are optional stages |
| `stages/chain.py` | `main_doc()` finds a Markdown manuscript; `ensure_hpc_dir()` creates the working folder on first use and pushes `hpc.inputs` |
| `stages/front.py` | the theory stage accepts a Markdown manuscript instead of requiring a `.tex` file |
| `stages/experiments.py`, `stages/lab.py` | share `ensure_hpc_dir()`; the lab stage can assess the PI's manuscript when no computational round exists |
| `stages/reviewers.py`, `stages/deliver.py` | reviewers receive and the delivery keeps the Markdown manuscript |
| `remote/agents.py` | the `api` agent (an OpenAI tool-loop coding agent, no Codex or Claude Code needed); a Markdown manuscript rule |
| `llm/mock_client.py`, `llm/__init__.py` | the mock PI delivers `main.md` when the manuscript is Markdown |

Added: `auctopus/bench/` (adapters, the API coding agent `coder.py`, the DiscoveryWorld experimentalist
`dw_agent.py`, judge-client shims `judges.py`, the CLI) and `auctopus/resources/benchmarks/<mlr|rcb|dw>/`
(prompt templates and domain packs written for each benchmark). Switched off per benchmark rather than changed:
figures (all), the laboratory stage (MLR, RCB), the safety agent and human approval (DiscoveryWorld, a simulation),
hosted web search and background responses (gpt-5-nano).

The benchmark evaluators run unchanged; `judges.py` only builds their judge clients for gpt-5 models (which take
`max_completion_tokens`) and, for ResearchClawBench, sets the `JUDGE_*` environment its scorer reads.

## Notes and limits

- Costs: gpt-5-nano for every role keeps a task at a few dollars; the coding agent's shell tool runs whatever the
  model asks, in the project's working folder, so use a dedicated machine or container for real runs.
- MLR-Bench experiments run on CPU unless the machine has a GPU; the prompts ask for small models and subsets.
- The DiscoveryWorld oracle scorecard is written to `project/remote-lab/work/scores/` and never enters the outbox,
  so no agent sees it; evaluation reads it afterwards.
- `runs-mock/` and `runs/` are not in git; `data/` is several GB and is re-created with the clone commands above.

## Provenance

`auctopus/` is a modified copy of https://github.com/E-zClap/auctopus (MIT), upstream commit `bbb98e3`
("Auctopus 1.0.0"). `docs/auctopus-core-changes.patch` is the diff of the modified upstream files, and
`docs/auctopus-added-files.txt` lists the folders added on top (the `bench` package, the benchmark prompt
packs and their tests). Benchmark checkouts under `data/` are not in this repository; re-download them with
the commands above.
