"""auctopus.bench: run the Auctopus workflow on public AI-scientist benchmarks and score the outputs with each
benchmark's own evaluator.

    python -m auctopus.bench list     --bench mlr|rcb|dw
    python -m auctopus.bench prepare  --bench mlr --task <id> [--model gpt-5-nano] [--mock]
    python -m auctopus.bench run      --bench mlr --task <id> [--model gpt-5-nano] [--mock] [--until STAGE]
    python -m auctopus.bench evaluate --bench mlr --task <id> [--judge gpt-5-nano] [--dry]
    python -m auctopus.bench summary  --bench mlr

Benchmarks:
    mlr  MLR-Bench          (team_project/data/mlr-bench)         idea -> proposal -> experiments -> paper
    rcb  ResearchClawBench  (team_project/data/researchclawbench) raw data -> analysis -> report
    dw   DiscoveryWorld     (team_project/data/discoveryworld)    hypothesis -> protocol -> environment run -> analysis

The pipeline itself is unchanged in its stage order and decision contracts; each benchmark is a project folder
(config.toml, prompts/, domain/) written by its adapter, plus a collector that lays the run's outputs out the way the
benchmark's evaluator expects them.
"""
from .base import BENCHMARKS, Benchmark, Paths, TaskSpec, get_benchmark  # noqa: F401
