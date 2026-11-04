"""Configuration: one TOML file (config.toml), with placeholders for every secret and host.

Any string value that starts with "insert" (for example "insert OpenAI API key here") is a placeholder and counts as
unset. API keys may also come from the environment (OPENAI_API_KEY, ANTHROPIC_API_KEY), which wins over the file.
"""
from __future__ import annotations

import dataclasses
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLACEHOLDER_RE = re.compile(r"^\s*insert\b", re.IGNORECASE)


def is_placeholder(value: Any) -> bool:
    """True for unset values: None, empty strings and 'insert ...' placeholders."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == "" or bool(PLACEHOLDER_RE.match(value))
    return False


class ConfigError(ValueError):
    pass


@dataclass
class ProjectCfg:
    name: str = "auctopus"
    runs_dir: str = "runs"
    prompts_dir: str = "prompts"
    domain_dir: str = "domain"          # the domain pack: sample card, instrument specification, rules (see DOMAIN_FILES)
    log_level: str = "INFO"
    max_history_chars: int = 900000     # a conversation is compacted beyond this size (summary + recent turns)


# The files of a domain pack, by fixed name inside project.domain_dir.
DOMAIN_FILES = {
    "sample-card.md": "short description of the system, shown to the proposers and the PI (the physical anchor)",
    "instrument.md": "full specification of the instrument: feasibility, lab design, safety review, run packet",
    "exclusions.md": "idea families fresh proposers must avoid (may be empty)",
    "proposer-rule.md": "the testability rule added to the proposers' physical anchor",
    "pi-rule.md": "the testability veto added to the PI's physical anchor",
    "lab-agent-instructions.md": "standing instructions for the experimentalist on the instrument computer",
    "lab-safety.md": "safety rules for the experimentalist and the safety agent",
}


@dataclass
class KeysCfg:
    openai_api_key: str = "insert OpenAI API key here"
    anthropic_api_key: str = "insert Anthropic API key here"

    def openai(self) -> str | None:
        return _resolve_secret("OPENAI_API_KEY", self.openai_api_key)

    def anthropic(self) -> str | None:
        return _resolve_secret("ANTHROPIC_API_KEY", self.anthropic_api_key)


def _resolve_secret(env_name: str, file_value: str) -> str | None:
    env = os.environ.get(env_name)
    if not is_placeholder(env):
        return env
    if not is_placeholder(file_value):
        return file_value
    return None


@dataclass
class RoleCfg:
    """One agent role served by a model API (proposer, PI, reviewer, ...)."""
    provider: str = "openai"            # "openai", "anthropic" or "mock"
    model: str = "insert model name here"
    effort: str | None = "high"         # reasoning effort; provider- and model-dependent values
    max_output_tokens: int = 64000
    timeout_s: float = 3600.0           # ceiling for one reply (long high-effort replies can run past 30 minutes)
    background: bool = False            # OpenAI only: run as a background response and poll it (survives restarts)
    poll_s: float = 15.0                # polling interval for background responses
    thinking: str = "adaptive"          # Anthropic only: "adaptive" (default) or "omit" to leave the field out
    prompt_cache: bool = True           # Anthropic only: automatic prompt caching of the conversation prefix
    fallbacks: bool = True              # Anthropic only: server-side refusal fallbacks (fallbacks: "default")
    max_attempts: int = 4               # outer retries for transient failures (on top of the SDK's own retries)
    backoff_s: list[float] = field(default_factory=lambda: [60.0, 120.0, 300.0, 600.0])
    web_search: bool = False            # give the model the provider's hosted web-search tool (literature search)
    web_search_type: str = ""           # override the tool type ("" = provider default; see llm clients)
    max_continuations: int = 4          # Anthropic only: resume a turn the server paused (pause_turn) this often


@dataclass
class ProposalsCfg:
    proposers: int = 10                 # proposers per fresh batch
    concurrency: int = 5                # proposer requests in flight at once
    stagger_s: float = 2.0              # delay between launching proposers
    assess_after: int = 5               # the PI assesses a batch as soon as this many proposals are in (0 = wait for all)
    refusal_min_words: int = 600        # a reply shorter than this is a refusal, not a proposal
    dedup: bool = True                  # merge proposals that converged on the same idea before the PI reads them
    max_batches: int = 24               # fresh and revision batches before the run stops
    revision: bool = True               # after a batch without a selection, revise the PI's BEST SEED once
    revision_proposers: int = 6         # proposers in a revision batch
    selection: str = "strict"           # "strict": the PI may reject the whole batch; "relaxed": it selects the strongest
    relax_after: int = 12               # strict selection only: from this batch on the PI selects the strongest (0 = never)
    manager_exclusions_after: int = 6   # batches in a row without a selection before the manager excludes recurring
                                        # rejected idea families from later fresh batches (0 = never)


@dataclass
class ChainCfg:
    """Stages after the selection. The order is fixed (pipeline.stage_table); each optional stage can be switched off."""
    theory_steps: list[str] = field(default_factory=lambda: ["02-proofs", "02b-positioning", "03-write", "04-exp"])
    file_steps: list[str] = field(default_factory=lambda: ["03-write", "03b-redeliver"])  # replies that carry files
    review_mode: str = "once"           # "once": one PI review per experiment, one revision, move on;
                                        # "until-accept": up to max_review_rounds, stop if never accepted
    max_review_rounds: int = 5
    final_review_rounds: int = 2
    verify: bool = True                 # BENCH: run the computational test (verify + verify-review); False skips both
    manuscript: str = "latex"           # BENCH: "latex" (main.tex + PDF) or "markdown" (main.md / report/report.md)
    lab: bool = True                    # test the theory on the instrument (feasibility, packet, safety, run, analysis)
    manager_redesign: bool = True       # after a laboratory NO-GO, the manager proposes a design and the PI rules once
    lab_reruns: int = 1                 # repeat an acquisition that failed or aborted (same pre-registered criteria)
    figures: bool = True               # figure plan, figure 1 build and review, then all figures
    reviewers: list[str] = field(default_factory=lambda: ["reviewer_claude", "reviewer_gpt"])
    review_max_files: int = 9           # attachments per review
    review_max_mb: float = 18.0


@dataclass
class RemoteCfg:
    """A remote machine reached over SSH (HPC or instrument computer), or a local stand-in."""
    transport: str = "ssh"              # "ssh", "local" (a local folder plays the remote) or "manual" (lab only)
    host: str = "insert hostname here"
    user: str = "insert username here"
    port: int = 22
    identity_file: str = "insert path to SSH private key here"
    ssh_binary: str | list[str] = "ssh"  # the OpenSSH client; a list runs a wrapper (e.g. [python, fake_ssh.py])
    ssh_options: list[str] = field(default_factory=list)
    connect_timeout_s: int = 20
    retries: int = 5                    # reconnect attempts for a dropped connection (exit code 255)
    remote_root: str = "insert remote working directory here"
    local_root: str = ""                # transport "local": folder that plays the remote file system
    env_file: str = "~/.auctopus/env"   # remote file that exports the agent's API key (written by `setup-remote`)
    path_prepend: str = "$HOME/.local/bin"
    agent: str = "codex"                # "codex", "claude", "mock" or "custom"
    agent_model: str = "insert model name here"
    agent_command: str = ""             # empty = the default command for `agent` (see remote/agents.py)
    job_timeout_h: float = 24.0
    poll_s: float = 60.0
    detach: bool = True                 # run agent jobs detached (nohup) and poll; False = hold the SSH session open
    pull_exclude: list[str] = field(default_factory=lambda: [".git", "__pycache__", "*.ckpt", "*.pt"])
    max_pull_mb: float = 500.0
    extra_instructions: str = ""        # site notes added to every agent prompt (scheduler, modules, quotas)
    inputs: list[str] = field(default_factory=list)  # BENCH: "local/path:remote/rel" pairs pushed into the working
                                        # folder when it is created (benchmark data, reference papers, ...)


@dataclass
class LabCfg(RemoteCfg):
    agent: str = "claude"
    max_pull_mb: float = 5000.0         # raw data come back in full (up to this size)
    safety_review: bool = True          # the safety agent must approve the run packet before the instrument runs it
    safety_fix_rounds: int = 1          # packet corrections after a safety rejection before the run stops
    require_approval: bool = True       # a person also approves the design before the instrument runs it
    exchange_dir: str = "lab-exchange"  # transport "manual": packets go to inbox/, reports come back in outbox/


@dataclass
class BenchCfg:
    """BENCH: which benchmark task this project runs; read by auctopus.bench, ignored by the pipeline itself."""
    name: str = ""                      # "mlr", "rcb" or "dw"
    task: str = ""                      # task identifier inside the benchmark
    data_dir: str = ""                  # the benchmark's checkout (team_project/data/<benchmark>)
    judge_model: str = ""               # model for the benchmark's own evaluator
    agent_name: str = "auctopus"        # label recorded in the benchmark's result files
    mock: bool = False                  # offline smoke run: mock models and mock agents
    extra: dict = field(default_factory=dict)


@dataclass
class MockCfg:
    scenario: str = "revision-then-win"  # "win-first", "revision-then-win", "never-win", "lab-redo"
    agent_delay_s: float = 0.0


@dataclass
class Config:
    root: Path
    project: ProjectCfg
    keys: KeysCfg
    roles: dict[str, RoleCfg]
    proposals: ProposalsCfg
    chain: ChainCfg
    hpc: RemoteCfg
    lab: LabCfg
    mock: MockCfg
    bench: BenchCfg = field(default_factory=BenchCfg)
    warnings: list[str] = field(default_factory=list)

    def path(self, rel: str) -> Path:
        p = Path(rel).expanduser()
        return p if p.is_absolute() else (self.root / p)

    def domain(self, name: str) -> Path:
        """A file of the domain pack (see DOMAIN_FILES)."""
        return self.path(self.project.domain_dir) / name

    def role(self, name: str) -> RoleCfg:
        if name not in self.roles:
            raise ConfigError(f"role '{name}' is not configured (add a [roles.{name}] table)")
        return self.roles[name]

    def used_roles(self) -> set[str]:
        """The roles the configured stages call (an unused role needs no key or model)."""
        ch, lab = self.chain, self.lab
        used = {"proposer", "pi", "pi_review"}
        if self.proposals.dedup:
            used.add("dedup")
        if self.proposals.manager_exclusions_after > 0:
            used.add("manager")
        if ch.lab:
            used.add("feasibility")
            if ch.manager_redesign:
                used.add("manager")
            if lab.safety_review:
                used.add("safety")
        used.update(ch.reviewers)
        return used

    def problems(self, *, need_remote: bool = True) -> list[str]:
        """Everything that would stop a real (non-mock) run. Empty list = ready."""
        out: list[str] = []
        used = {n: r for n, r in self.roles.items() if n in self.used_roles()}
        for name in sorted(self.used_roles() - set(self.roles)):
            out.append(f"role '{name}' is used but not configured (add a [roles.{name}] table)")
        providers = {r.provider for r in used.values()}
        if "openai" in providers and self.keys.openai() is None:
            out.append("OpenAI API key missing: set OPENAI_API_KEY or keys.openai_api_key")
        if "anthropic" in providers and self.keys.anthropic() is None:
            out.append("Anthropic API key missing: set ANTHROPIC_API_KEY or keys.anthropic_api_key")
        for name, r in used.items():
            if r.provider not in ("openai", "anthropic", "mock"):
                out.append(f"roles.{name}.provider must be openai, anthropic or mock (got {r.provider!r})")
            if r.provider != "mock" and is_placeholder(r.model):
                out.append(f"roles.{name}.model is a placeholder")
        if self.proposals.selection not in ("strict", "relaxed"):
            out.append(f"proposals.selection must be strict or relaxed (got {self.proposals.selection!r})")
        if self.chain.manuscript not in ("latex", "markdown"):
            out.append(f"chain.manuscript must be latex or markdown (got {self.chain.manuscript!r})")
        if need_remote:
            for label, rc in (("hpc", self.hpc), ("lab", self.lab)):
                if label == "lab" and not self.chain.lab:
                    continue
                out += remote_problems(label, rc)
        return out


def remote_problems(label: str, rc: RemoteCfg) -> list[str]:
    out = []
    if rc.transport == "ssh":
        for key in ("host", "remote_root"):           # user may stay unset when host is a ~/.ssh/config alias
            if is_placeholder(getattr(rc, key)):
                out.append(f"{label}.{key} is a placeholder")
        if rc.agent not in ("mock",) and is_placeholder(rc.agent_model) and rc.agent != "custom":
            out.append(f"{label}.agent_model is a placeholder")
    elif rc.transport == "local":
        if not rc.local_root:
            out.append(f"{label}.local_root must be set for transport 'local'")
    elif rc.transport == "manual":
        if label != "lab":
            out.append(f"{label}.transport 'manual' is only supported for the lab")
    else:
        out.append(f"{label}.transport must be ssh, local or manual (got {rc.transport!r})")
    return out


# ---------------------------------------------------------------------------------------------------------- loading

DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    "proposer": dict(provider="openai", model="insert OpenAI model for the proposers", effort="xhigh",
                     max_output_tokens=0, background=True, web_search=True),
    "dedup": dict(provider="openai", model="insert OpenAI model for deduplication", effort="medium",
                  max_output_tokens=0),
    "pi": dict(provider="openai", model="insert OpenAI model for the principal investigator", effort="high",
               max_output_tokens=0, background=True, web_search=True),
    # the PI's reviews run in the PI's own conversation, possibly at another model or effort
    "pi_review": dict(provider="openai", model="insert OpenAI model for the PI's reviews", effort="xhigh",
                      max_output_tokens=0, background=True),
    "feasibility": dict(provider="openai", model="insert OpenAI model for the feasibility reviewer",
                        effort="xhigh", max_output_tokens=0, background=True),
    "reviewer_gpt": dict(provider="openai", model="insert OpenAI model for the GPT reviewer", effort="high",
                         max_output_tokens=0, background=True, web_search=True),
    "reviewer_claude": dict(provider="anthropic", model="claude-opus-5-5", effort="high", web_search=True),
    "manager": dict(provider="anthropic", model="claude-opus-5-5", effort="high"),
    "safety": dict(provider="anthropic", model="claude-opus-5-5", effort="high"),
}


def _build(cls, data: dict[str, Any] | None, where: str, warnings: list[str]):
    data = dict(data or {})
    names = {f.name for f in dataclasses.fields(cls)}
    unknown = sorted(set(data) - names)
    for k in unknown:
        warnings.append(f"unknown key {where}.{k} (ignored)")
        data.pop(k)
    return cls(**data)


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"config file not found: {path} (create a project with `auctopus init`)")
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    warnings: list[str] = []
    roles_raw = raw.get("roles", {})
    roles: dict[str, RoleCfg] = {}
    for name in sorted(set(DEFAULT_ROLES) | set(roles_raw)):
        merged = {**DEFAULT_ROLES.get(name, {}), **(roles_raw.get(name) or {})}
        roles[name] = _build(RoleCfg, merged, f"roles.{name}", warnings)
    known = {"project", "keys", "roles", "proposals", "chain", "hpc", "lab", "mock", "bench"}
    for k in sorted(set(raw) - known):
        warnings.append(f"unknown table [{k}] (ignored)")
    cfg = Config(
        root=path.parent,
        project=_build(ProjectCfg, raw.get("project"), "project", warnings),
        keys=_build(KeysCfg, raw.get("keys"), "keys", warnings),
        roles=roles,
        proposals=_build(ProposalsCfg, raw.get("proposals"), "proposals", warnings),
        chain=_build(ChainCfg, raw.get("chain"), "chain", warnings),
        hpc=_build(RemoteCfg, raw.get("hpc"), "hpc", warnings),
        lab=_build(LabCfg, raw.get("lab"), "lab", warnings),
        mock=_build(MockCfg, raw.get("mock"), "mock", warnings),
        bench=_build(BenchCfg, raw.get("bench"), "bench", warnings),
        warnings=warnings,
    )
    return cfg


def mock_overrides(cfg: Config, sandbox: Path) -> Config:
    """Turn a config into a fully offline dry run: mock models, a local folder as each 'remote', mock agents."""
    for r in cfg.roles.values():
        r.provider = "mock"
        r.background = False
        r.max_attempts = 1
    cfg.proposals.stagger_s = 0.0
    for label, rc in (("hpc", cfg.hpc), ("lab", cfg.lab)):
        rc.transport = "local"
        rc.local_root = str(sandbox / f"remote-{label}")
        rc.remote_root = "work"
        rc.agent = "mock"
        rc.poll_s = 0.2
        rc.job_timeout_h = 0.05
        rc.env_file = ""
    cfg.lab.require_approval = False
    return cfg
