"""Command line of auctopus.bench (see the package docstring)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..config import load_config
from ..util import LOG, setup_logging
from .base import BENCHMARKS, Paths, get_benchmark


def _paths(args) -> Paths:
    p = Paths()
    if getattr(args, "data_root", None):
        p.data_root = Path(args.data_root).resolve()
    if getattr(args, "out_root", None):
        p.out_root = Path(args.out_root).resolve()
    return p


def _options(args) -> dict[str, str]:
    out = {}
    for item in getattr(args, "opt", None) or []:
        k, _, v = item.partition("=")
        out[k.strip()] = v.strip()
    return out


def cmd_list(args) -> int:
    b = get_benchmark(args.bench)
    tasks = b.tasks(_paths(args))
    print(f"{b.label}: {len(tasks)} task(s)")
    for t in tasks:
        print(f"  {t.id:<42} {t.title[:70]}")
    return 0


def cmd_prepare(args) -> int:
    b = get_benchmark(args.bench)
    paths = _paths(args)
    task = b.task(paths, args.task)
    cfg_path = b.prepare(task, paths, args.model, args.judge, args.mock, args.effort, force=args.force,
                         options=_options(args))
    print(f"project: {cfg_path.parent}")
    from ..cli import readiness
    problems = readiness(load_config(cfg_path))
    if problems:
        print("not ready:\n  - " + "\n  - ".join(problems))
        return 1
    print("ready")
    return 0


def cmd_run(args) -> int:
    b = get_benchmark(args.bench)
    paths = _paths(args)
    task = b.task(paths, args.task)
    cfg_path = b.prepare(task, paths, args.model, args.judge, args.mock, args.effort, force=args.force,
                         options=_options(args))
    cfg = load_config(cfg_path)
    for w in cfg.warnings:
        LOG.warning("config: %s", w)
    from ..cli import readiness
    problems = readiness(cfg)
    if problems:
        print("The project is not ready:\n  - " + "\n  - ".join(problems))
        return 1
    from ..llm import reset_clients
    from ..pipeline import Pipeline, new_run_dir
    reset_clients()
    run = b.latest_run(cfg_path.parent) if args.resume else None
    if run is None:
        run = new_run_dir(cfg, task.id[:40])
    print(f"run folder: {run}")
    code = Pipeline(cfg, run, dry_run=args.mock).run(from_stage=args.from_stage, until=args.until)
    from ..cli import _print_status
    _print_status(Pipeline(cfg, run, dry_run=args.mock).status_rows())
    print(f"exit code {code}; decisions in {run / 'decisions-journal.md'}")
    if code == 0 and args.evaluate:
        return cmd_evaluate(args)
    return code


def cmd_evaluate(args) -> int:
    b = get_benchmark(args.bench)
    paths = _paths(args)
    task = b.task(paths, args.task)
    project = paths.project(b.name, task.id)
    cfg_path = project / "config.toml"
    if not cfg_path.exists():
        print(f"no project for {b.name}/{task.id}: run `python -m auctopus.bench run` first")
        return 1
    cfg = load_config(cfg_path)
    run = b.latest_run(project)
    if run is None:
        print("no run to evaluate")
        return 1
    judge = args.judge or cfg.bench.judge_model or "gpt-5-nano"
    result = b.evaluate(task, paths, project, run, judge, args.dry)
    out = b.record(task, paths, run, result)
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=1, ensure_ascii=False))
    print(f"written: {out}")
    return 0


def cmd_summary(args) -> int:
    b = get_benchmark(args.bench)
    paths = _paths(args)
    rows = []
    for ev in sorted((paths.out_root / b.name).glob("*/eval/evaluation.json")):
        data = json.loads(ev.read_text(encoding="utf-8"))
        rows.append({"task": data.get("task"), **(data.get("scores") or {}), **{
            f"run_{k}": v for k, v in (data.get("run_stats") or {}).items() if k in ("model_calls", "input_tokens",
                                                                                      "output_tokens", "done")}})
    if not rows:
        print("no evaluations yet")
        return 1
    keys = list(dict.fromkeys(k for r in rows for k in r))
    out = paths.out_root / b.name / "summary.json"
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    csv = paths.out_root / b.name / "summary.csv"
    with open(csv, "w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(k, "")) for k in keys) + "\n")
    print(f"{len(rows)} task(s); columns: {', '.join(keys)}")
    for r in rows:
        print("  " + "  ".join(f"{k}={r[k]}" for k in keys if k in r))
    print(f"written: {out} and {csv}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m auctopus.bench",
                                 description="Run Auctopus on MLR-Bench, ResearchClawBench or DiscoveryWorld and "
                                             "score with each benchmark's evaluator.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, task=True):
        p.add_argument("--bench", required=True, choices=["mlr", "rcb", "dw"])
        if task:
            p.add_argument("--task", required=True)
        p.add_argument("--data-root", help="folder holding the benchmark checkouts (default team_project/data)")
        p.add_argument("--out-root", help="folder for projects, runs and evaluations (default team_project/runs)")

    def run_opts(p):
        p.add_argument("--model", default="gpt-5-nano", help="model for every Auctopus role and the coding agent")
        p.add_argument("--judge", default="gpt-5-nano", help="model for the benchmark's evaluator")
        p.add_argument("--effort", default="medium", help="reasoning effort for the roles")
        p.add_argument("--mock", action="store_true", help="offline smoke run: mock models and mock agents")
        p.add_argument("--force", action="store_true", help="rewrite the project folder even if it exists")
        p.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE",
                       help="benchmark option (dw: steps=100); repeatable")

    p = sub.add_parser("list", help="list the tasks of a benchmark")
    common(p, task=False)
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("prepare", help="write the project folder for one task and check readiness")
    common(p)
    run_opts(p)
    p.set_defaults(fn=cmd_prepare)
    p = sub.add_parser("run", help="prepare (if needed) and run the pipeline on one task")
    common(p)
    run_opts(p)
    p.add_argument("--until", help="stop after this stage")
    p.add_argument("--from", dest="from_stage", help="run this stage and every later one again")
    p.add_argument("--resume", action="store_true", help="continue the latest run instead of starting a new one")
    p.add_argument("--evaluate", action="store_true", help="score the run with the benchmark's evaluator after it")
    p.add_argument("--dry", action="store_true", help="(with --evaluate) check the layout, do not call the judge")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("evaluate", help="score the latest run of one task with the benchmark's evaluator")
    common(p)
    p.add_argument("--judge", help="judge model (default: the project's bench.judge_model)")
    p.add_argument("--dry", action="store_true", help="lay the outputs out and check them, without calling the judge")
    p.set_defaults(fn=cmd_evaluate)
    p = sub.add_parser("summary", help="aggregate the evaluations of a benchmark")
    common(p, task=False)
    p.set_defaults(fn=cmd_summary)
    args = ap.parse_args(argv)
    if args.cmd != "run":
        setup_logging("INFO")
    try:
        return int(args.fn(args) or 0)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
