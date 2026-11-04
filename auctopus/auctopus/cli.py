"""Command line: auctopus <command> (or python -m auctopus <command>).

  init [DIR] [--domain D]  create a project: config.toml, the prompt templates and a domain pack (default template)
  doctor [--online]        check the project and list what is still to write; --online also tests the API keys, the
                           models and the SSH hosts
  models                   list the models each API key can use
  setup-remote hpc|lab     create the remote working folder and store the agent's API key there (private file)
  new [--until STAGE]      start a new run
  resume [RUN] [--from STAGE] [--until STAGE] [--skip a,b]
                           continue a run (the latest by default) at its first unfinished stage
  status [RUN]             show the stages of a run
  approve RUN              approve the experimental design so the instrument may run it
  dry-run [--scenario S]   run the whole pipeline offline (mock models, local folders as the remote machines)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import Config, ConfigError, load_config, mock_overrides
from .util import LOG, now_stamp, setup_logging

RESOURCES = Path(__file__).resolve().parent / "resources"
TAGLINE = "a PI-centred laboratory of AI agents"
SCENARIOS = ["win-first", "revision-then-win", "never-win", "lab-redo"]


# ------------------------------------------------------------------------------------------------------ output

def _unicode_ok() -> bool:
    try:
        "✓○●✗".encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _color_ok() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ and (os.name != "nt" or "WT_SESSION" in os.environ
                                                                      or "TERM" in os.environ)


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _color_ok() else text


MARKS = {"done": ("✓", "+", "32"), "running": ("●", "*", "36"), "blocked": ("✗", "x", "31"),
         "pending": ("○", ".", "2")}


def _mark(status: str) -> str:
    uni, ascii_, code = MARKS.get(status, MARKS["pending"])
    return _paint(uni if _unicode_ok() else ascii_, code)


def _banner() -> None:
    print(_paint(f"Auctopus {__version__}", "1") + f" - {TAGLINE}")


def _print_status(rows: list[tuple[str, str, str]], notes: dict[str, str] | None = None) -> None:
    for name, status, note in rows:
        detail = note or (notes or {}).get(name, "")
        print(f"  {_mark(status)} {name:<15} {status:<8} {_paint(detail, '2') if not note else detail}")


# ------------------------------------------------------------------------------------------------------ helpers

def _config_path(arg: str | None) -> Path:
    return Path(arg) if arg else Path.cwd() / "config.toml"


def _load(args) -> Config:
    path = _config_path(args.config)
    if not path.exists():
        raise ConfigError(f"no config.toml in {path.parent} (create a project with `auctopus init`, or pass "
                          "--config)")
    cfg = load_config(path)
    for w in cfg.warnings:
        LOG.warning("config: %s", w)
    return cfg


def _run_dir(cfg: Config, run: str | None) -> Path:
    from .pipeline import latest_run
    if run:
        p = Path(run)
        if not p.is_absolute() and not p.exists():
            p = cfg.path(cfg.project.runs_dir) / run
        if not (p / "state.json").exists():
            raise ConfigError(f"not a run folder (no state.json): {p}")
        return p.resolve()
    p = latest_run(cfg)
    if p is None:
        raise ConfigError("no run yet: start one with `auctopus new`")
    return p


def domain_packs() -> list[str]:
    return sorted(p.name for p in (RESOURCES / "domains").iterdir() if p.is_dir())


def readiness(cfg: Config, report: bool = False) -> list[str]:
    """Everything that would stop a real run: configuration, prompt assembly, missing or unwritten prompt and domain
    files."""
    from .prompt_builder import PromptError, pi_select_prompt, prompt_problems, prompts_in_use, proposer_prompts
    problems = cfg.problems() + prompt_problems(cfg)
    prompts_dir = cfg.path(cfg.project.prompts_dir)
    present = [n for n in prompts_in_use(cfg) if (prompts_dir / n).exists()]
    try:
        if "proposer.md" in present:
            proposer_prompts(cfg)
        if "pi-select-strict.md" in present:
            pi_select_prompt(cfg, relaxed=False)
        if "pi-select.md" in present:
            pi_select_prompt(cfg, relaxed=True)
        if report and "proposer.md" in present:
            print("  prompts: the proposer and PI prompts assemble")
    except PromptError as e:
        problems.append(f"prompts: {e}")
    return problems


def scaffold(dest: Path, domain: str = "template", force: bool = False) -> Path:
    """A project folder: config.toml, prompts/ and domain/ copied from the packaged resources."""
    if domain not in domain_packs():
        raise ConfigError(f"unknown domain pack {domain!r} (available: {', '.join(domain_packs())})")
    dest.mkdir(parents=True, exist_ok=True)
    targets = [dest / "config.toml", dest / "prompts", dest / "domain"]
    existing = [t.name for t in targets if t.exists()]
    if existing and not force:
        raise ConfigError(f"{dest} already has {', '.join(existing)} (use --force to overwrite)")
    shutil.copyfile(RESOURCES / "config.example.toml", dest / "config.toml")
    shutil.copytree(RESOURCES / "prompts", dest / "prompts", dirs_exist_ok=True)
    shutil.copytree(RESOURCES / "domains" / domain, dest / "domain", dirs_exist_ok=True)
    ignore = dest / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# API keys and run data stay out of version control\nconfig.toml\nruns/\nlab-exchange/\n",
                          encoding="utf-8")
    return dest / "config.toml"


# ------------------------------------------------------------------------------------------------------- commands

def cmd_init(args) -> int:
    dest = Path(args.dir).resolve()
    cfg_path = scaffold(dest, args.domain, args.force)
    _banner()
    print(f"\nCreated the project {dest}")
    print(f"  config.toml   settings, models and hosts (fill in every 'insert ...' value)")
    print(f"  prompts/      the stage prompt templates (write each '[insert: ...]' part)")
    print(f"  domain/       the domain pack '{args.domain}'")
    where = "" if dest == Path.cwd() else f"cd {dest}\n  "
    print(f"\nNext:\n  {where}auctopus dry-run           # the whole pipeline offline, no keys or prompts needed\n"
          f"  auctopus doctor            # what is still to fill in: {cfg_path.name}, prompts/, domain/\n"
          f"  auctopus doctor --online   # then test the keys, the models and the SSH hosts\n"
          f"  auctopus new               # start a real run")
    return 0


def cmd_doctor(args) -> int:
    cfg = _load(args)
    print(f"config: {_config_path(args.config)}")
    for w in cfg.warnings:
        print(f"  warning: {w}")
    problems = readiness(cfg, report=True)
    if args.online:
        problems += _online_checks(cfg)
    if problems:
        print("\nNot ready:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nReady." + ("" if args.online else " (run with --online to test the keys, models and SSH hosts)"))
    return 0


def _online_checks(cfg: Config) -> list[str]:
    out: list[str] = []
    providers: dict[str, set[str]] = {}
    for name, role in cfg.roles.items():
        if name in cfg.used_roles():
            providers.setdefault(role.provider, set()).add(role.model)
    if "openai" in providers and cfg.keys.openai():
        try:
            import openai
            client = openai.OpenAI(api_key=cfg.keys.openai())
            for model in sorted(providers["openai"]):
                try:
                    client.models.retrieve(model)
                    print(f"  openai: model {model} is available")
                except Exception as e:  # noqa: BLE001
                    out.append(f"openai: model {model}: {type(e).__name__}: {str(e)[:200]}")
        except ImportError:
            out.append("the openai package is not installed (pip install auctopus)")
    if "anthropic" in providers and cfg.keys.anthropic():
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=cfg.keys.anthropic())
            for model in sorted(providers["anthropic"]):
                try:
                    client.models.retrieve(model)
                    print(f"  anthropic: model {model} is available")
                except Exception as e:  # noqa: BLE001
                    out.append(f"anthropic: model {model}: {type(e).__name__}: {str(e)[:200]}")
        except ImportError:
            out.append("the anthropic package is not installed (pip install auctopus)")
    from .remote.transport import bash_quote_path, make_transport
    for label, rc in (("hpc", cfg.hpc), ("lab", cfg.lab)):
        if label == "lab" and (not cfg.chain.lab or rc.transport == "manual"):
            continue
        try:
            t = make_transport(rc, label)
            binary = {"codex": "codex", "claude": "claude"}.get(rc.agent, "")
            env = rc.env_file
            root = bash_quote_path(rc.remote_root)
            res = t.run(f"echo AUCTOPUS_OK\nmkdir -p {root} && test -w {root} && echo WRITABLE\n"
                        f"command -v tar >/dev/null && echo TAR\n"
                        + (f"export PATH=\"{rc.path_prepend}:$PATH\"; command -v {binary} >/dev/null && echo AGENT\n"
                           if binary else "")
                        + (f"test -f {bash_quote_path(env)} && echo ENVFILE\n" if env else ""), timeout=60,
                        check=False)
            got = set(res.stdout.split())
            if "AUCTOPUS_OK" not in got:
                out.append(f"{label}: cannot run commands over SSH ({res.stderr.strip()[-200:]})")
                continue
            print(f"  {label}: SSH works")
            if "WRITABLE" not in got:
                out.append(f"{label}: remote_root {rc.remote_root} is not writable")
            if "TAR" not in got:
                out.append(f"{label}: tar is missing on the remote")
            if binary and "AGENT" not in got:
                out.append(f"{label}: '{binary}' not found on the remote PATH (install it or set {label}.agent_command)")
            if env and "ENVFILE" not in got:
                out.append(f"{label}: no API-key file at {env} (run `auctopus setup-remote {label}`)")
        except Exception as e:  # noqa: BLE001
            out.append(f"{label}: {type(e).__name__}: {e}")
    return out


def cmd_setup_remote(args) -> int:
    cfg = _load(args)
    rc = cfg.hpc if args.target == "hpc" else cfg.lab
    from .remote.transport import make_transport
    t = make_transport(rc, args.target)
    t.mkdirs(rc.remote_root)
    if rc.env_file:
        if rc.agent == "codex":
            key, var = cfg.keys.openai(), "OPENAI_API_KEY"
        elif rc.agent == "claude":
            key, var = cfg.keys.anthropic(), "ANTHROPIC_API_KEY"
        else:
            key, var = None, ""
        if var and not key:
            print(f"no {var} configured: fill in the keys in config.toml (or the environment) first")
            return 1
        if var:
            safe = key.replace("'", "'\"'\"'")
            lines = f"export {var}='{safe}'\n"
            if rc.agent == "codex":
                lines += f"export CODEX_API_KEY='{safe}'\n"      # codex exec also reads CODEX_API_KEY
            t.write_text(rc.env_file, lines, private=True)
            print(f"{args.target}: wrote {var} to {rc.env_file} (mode 600); the key travelled on the SSH channel only")
    print(f"{args.target}: {rc.remote_root} is ready")
    return 0


def cmd_models(args) -> int:
    cfg = _load(args)
    if cfg.keys.openai():
        import openai
        ids = sorted(m.id for m in openai.OpenAI(api_key=cfg.keys.openai()).models.list())
        print("OpenAI models:\n  " + "\n  ".join(ids))
    if cfg.keys.anthropic():
        import anthropic
        ids = [m.id for m in anthropic.Anthropic(api_key=cfg.keys.anthropic()).models.list()]
        print("Anthropic models:\n  " + "\n  ".join(ids))
    if not cfg.keys.openai() and not cfg.keys.anthropic():
        print("no API keys configured")
        return 1
    return 0


def cmd_new(args) -> int:
    cfg = _load(args)
    problems = readiness(cfg)
    if problems and not args.force:
        print("The project is not ready (see `auctopus doctor`):\n  - " + "\n  - ".join(problems))
        return 1
    from .pipeline import Pipeline, new_run_dir
    run = new_run_dir(cfg, args.label or "")
    print(f"run folder: {run}")
    return Pipeline(cfg, run).run(until=args.until)


def _refuse_dry_run(run: Path) -> bool:
    """A dry run's history comes from mock models: continuing it with a real configuration would send that history to
    paid models. Dry runs are played again from the start instead."""
    from .state import RunState
    if not RunState(run).get("dry_run"):
        return False
    print(f"error: {run.name} is a dry run (mock models, local folders); it cannot be resumed or approved. "
          "Run `auctopus dry-run` again instead.", file=sys.stderr)
    return True


def cmd_resume(args) -> int:
    cfg = _load(args)
    from .pipeline import Pipeline
    run = _run_dir(cfg, args.run)
    if _refuse_dry_run(run):
        return 1
    skip = [s for s in (args.skip or "").split(",") if s]
    print(f"run folder: {run}")
    return Pipeline(cfg, run).run(from_stage=args.from_stage, until=args.until, skip=skip)


def cmd_status(args) -> int:
    cfg = _load(args)
    from .pipeline import STAGE_NOTES, Pipeline
    run = _run_dir(cfg, args.run)
    p = Pipeline(cfg, run)
    print(f"run {run}")
    _print_status(p.status_rows(), STAGE_NOTES)
    blocked = run / "RUN-BLOCKED.md"
    if blocked.exists():
        print("\n" + blocked.read_text(encoding="utf-8"))
    return 0


def cmd_approve(args) -> int:
    cfg = _load(args)
    from .state import RunState
    run = _run_dir(cfg, args.run)
    if _refuse_dry_run(run):
        return 1
    st = RunState(run)
    st.stage("lab")["approved"] = True
    st.stage("lab")["approved_at"] = now_stamp()
    st.save()
    note = run / "LAB-APPROVAL-REQUIRED.md"
    if note.exists():
        note.replace(run / "LAB-APPROVAL-GRANTED.md")
    print(f"approved the experimental design of {run.name}; continue with `auctopus resume {run}`")
    return 0


def cmd_dry_run(args) -> int:
    path = _config_path(args.config)
    stamp = now_stamp()
    if path.exists():
        cfg = load_config(path)
        sandbox = cfg.path(cfg.project.runs_dir) / "dry-runs" / stamp
    else:                                     # no project here: play the packaged one in a folder of its own
        sandbox = Path.cwd() / "auctopus-dry-run" / stamp
        cfg = load_config(scaffold(sandbox / "project"))
    sandbox.mkdir(parents=True, exist_ok=True)
    cfg = mock_overrides(cfg, sandbox)
    cfg.mock.scenario = args.scenario
    cfg.project.runs_dir = str(sandbox / "runs")
    from .llm import reset_clients
    from .pipeline import Pipeline, new_run_dir
    reset_clients()
    _banner()
    run = new_run_dir(cfg, "dry-run")
    from .state import RunState
    marker = RunState(run)
    marker.set("dry_run", True)                  # `resume` and `approve` refuse this run (see _refuse_dry_run)
    marker.save()
    print(f"dry run, scenario '{args.scenario}': mock models, local folders as the HPC and the instrument computer\n"
          f"run folder: {run}\n")
    code = Pipeline(cfg, run, dry_run=True).run(until=args.until)
    p = Pipeline(cfg, run, dry_run=True)
    print()
    _print_status(p.status_rows())
    print(f"\nexit code {code}; every decision is in {run / 'decisions-journal.md'}")
    return code


# ----------------------------------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="auctopus", description=f"Auctopus {__version__}: {TAGLINE}.")
    ap.add_argument("--version", action="version", version=f"Auctopus {__version__}")
    ap.add_argument("--config", help="path to config.toml (default: ./config.toml)")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="command")
    p = sub.add_parser("init", help="create a project folder")
    p.add_argument("dir", nargs="?", default=".", help="project folder (default: the current folder)")
    p.add_argument("--domain", default="template", help=f"domain pack ({', '.join(domain_packs())})")
    p.add_argument("--force", action="store_true", help="overwrite an existing project's files")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("doctor", help="check the project")
    p.add_argument("--online", action="store_true", help="also test the keys, the models and the SSH hosts")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("models", help="list the models your API keys can use")
    p.set_defaults(fn=cmd_models)
    p = sub.add_parser("setup-remote", help="prepare the HPC or the instrument computer")
    p.add_argument("target", choices=["hpc", "lab"])
    p.set_defaults(fn=cmd_setup_remote)
    p = sub.add_parser("new", help="start a new run")
    p.add_argument("--until", help="stop after this stage")
    p.add_argument("--label", help="suffix for the run folder name")
    p.add_argument("--force", action="store_true", help="start even if doctor reports problems")
    p.set_defaults(fn=cmd_new)
    p = sub.add_parser("resume", help="continue a run")
    p.add_argument("run", nargs="?", help="run folder or name (default: the latest run)")
    p.add_argument("--from", dest="from_stage", help="run this stage and every later one again")
    p.add_argument("--until", help="stop after this stage")
    p.add_argument("--skip", help="comma-separated stages to mark done")
    p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("status", help="show the stages of a run")
    p.add_argument("run", nargs="?")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("approve", help="approve the experimental design of a run")
    p.add_argument("run")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("dry-run", help="run the whole pipeline offline")
    p.add_argument("--scenario", default="revision-then-win", choices=SCENARIOS)
    p.add_argument("--until", help="stop after this stage")
    p.set_defaults(fn=cmd_dry_run)
    args = ap.parse_args(argv)
    if args.cmd not in ("new", "resume", "dry-run"):
        setup_logging("INFO")
    try:
        return int(args.fn(args) or 0)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
