"""Assemble the proposers' brief and the PI's selection prompt from the prompt templates and the domain pack.

- proposer prompt  = prompts/proposer.md, with {PHYSICAL_ANCHOR} (sample card + proposer rule) and {EXCLUSIONS} (the
                     pack's exclusions.md plus any exclusions the manager adds during the run)
- revision brief   = the same prompt with no exclusion list (a revision may develop a seed from an excluded family)
- PI selection     = prompts/pi-select.md (relaxed: the PI selects the strongest proposal, strengthened) or
                     prompts/pi-select-strict.md (strict: the PI may reject the whole batch), with {PHYSICAL_ANCHOR}
                     (sample card + PI rule)
{PHYSICAL_ANCHOR} is a paragraph of its own and {EXCLUSIONS} sits inside the exclusions sentence, just before its final
full stop. A placeholder with nothing to fill disappears; domain content without its placeholder is an error, so an
edited template fails loudly instead of silently losing the anchor or the exclusions.

prompt_problems() lists the prompt and domain files a run would read that are missing or still have [insert: ...] parts.
"""
from __future__ import annotations

import re
from pathlib import Path

from .config import DOMAIN_FILES, Config

ANCHOR = "{PHYSICAL_ANCHOR}"
EXCLUSIONS = "{EXCLUSIONS}"


class PromptError(ValueError):
    pass


def _read(path: Path) -> str:
    if not path.exists():
        raise PromptError(f"missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def card_text(path: Path) -> str:
    lines = [l for l in _read(path).splitlines() if not l.startswith("#")]
    return " ".join(l.strip() for l in lines if l.strip())


def fill_anchor(template: str, block: str | None, where: str) -> str:
    """Put the physical-anchor paragraph where the {PHYSICAL_ANCHOR} paragraph stands (or drop that paragraph)."""
    paras = re.split(r"\n\s*\n", template.strip())
    idx = [i for i, p in enumerate(paras) if p.strip() == ANCHOR]
    if not idx:
        if ANCHOR in template:
            raise PromptError(f"{where}: {ANCHOR} must stand alone as its own paragraph")
        if block:
            raise PromptError(f"{where}: the domain pack has a sample card but the prompt has no {ANCHOR} paragraph")
        return "\n\n".join(paras) + "\n"
    if len(idx) > 1:
        raise PromptError(f"{where}: {ANCHOR} appears {len(idx)} times")
    if block:
        paras[idx[0]] = block
    else:
        paras.pop(idx[0])
    return "\n\n".join(paras) + "\n"


def exclusion_clauses(*parts: str) -> str:
    """Join exclusion texts written as continuations of 'Do not pursue approaches that ...' ('; or that ...')."""
    out = ""
    for part in parts:
        t = (part or "").strip().rstrip(".").rstrip()
        if not t:
            continue
        if not t.startswith(";"):
            t = "; " + t
        out += t
    return out


def _anchor_block(cfg: Config, rule_name: str) -> str | None:
    card_path = cfg.domain("sample-card.md")
    if not card_path.exists():
        return None
    rule_path = cfg.domain(rule_name)
    rule = rule_path.read_text(encoding="utf-8").strip() if rule_path.exists() else ""
    return f"**Physical anchor.** {card_text(card_path)} {rule}".rstrip()


def domain_exclusions(cfg: Config) -> str:
    """The pack's exclusion list; lines that start with # are comments."""
    path = cfg.domain("exclusions.md")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def proposer_prompts(cfg: Config, extra_exclusions: str = "") -> tuple[str, str]:
    """(prompt for fresh batches, brief for revision batches). `extra_exclusions` are the manager's additions."""
    base = fill_anchor(_read(cfg.path(cfg.project.prompts_dir) / "proposer.md"),
                       _anchor_block(cfg, "proposer-rule.md"), "proposer prompt")
    clauses = exclusion_clauses(domain_exclusions(cfg), extra_exclusions)
    count = base.count(EXCLUSIONS)
    if count > 1:
        raise PromptError(f"proposer prompt: {EXCLUSIONS} appears {count} times")
    if count == 0:
        if clauses:
            raise PromptError(f"proposer prompt: there are exclusions to add but no {EXCLUSIONS} placeholder")
        return base, base
    return base.replace(EXCLUSIONS, clauses), base.replace(EXCLUSIONS, "")


def pi_select_prompt(cfg: Config, relaxed: bool = True) -> str:
    name = "pi-select.md" if relaxed else "pi-select-strict.md"
    return fill_anchor(_read(cfg.path(cfg.project.prompts_dir) / name), _anchor_block(cfg, "pi-rule.md"),
                       f"PI selection prompt ({name})")


def load_prompt(cfg: Config, name: str, **subs: str) -> str:
    """A prompt file from prompts/, with {KEY} placeholders replaced (unknown braces are left alone)."""
    text = _read(cfg.path(cfg.project.prompts_dir) / name)
    for k, v in subs.items():
        text = text.replace("{" + k + "}", v)
    return text


# ------------------------------------------------------------------------------------------- what still to write

UNFILLED = "[insert"        # the templates mark every part still to be written as [insert: ...]


def prompts_in_use(cfg: Config) -> list[str]:
    """The prompt files the configured stages read, in the order the run reaches them."""
    pc, ch = cfg.proposals, cfg.chain
    names = ["proposer.md"]
    if pc.dedup:
        names.append("dedup.md")
    if pc.selection != "relaxed":
        names.append("pi-select-strict.md")
    if pc.selection == "relaxed" or pc.relax_after > 0:
        names.append("pi-select.md")
    if pc.revision:
        names.append("17-revision.md")
    if pc.manager_exclusions_after > 0:
        names.append("manager-exclusions.md")
    names += [f"{s}.md" for s in ch.theory_steps] + ["03b-redeliver.md", "05-codex.md", "05-continue.md",
                                                     "06-review.md"]
    if ch.lab:
        names += ["12-feasibility-gate.md", "13-feasibility-triage.md"]
        if ch.manager_redesign:
            names += ["16m-manager-design.md", "16-lab-redesign.md"]
        names += ["14-lab-twin-packet.md", "14r-lab-packet-review.md"]
        if cfg.lab.safety_review:
            names.append("14s-safety-review.md")
        if cfg.lab.transport != "manual":
            names.append("lab-run.md")
        if ch.lab_reruns > 0:
            names.append("18-lab-rerun.md")
        names.append("15-lab-analysis.md")
    if ch.figures:
        names += ["07-figure-plan.md", "07-figure-build.md", "08-figure-review.md", "08-figure-fix.md",
                  "09-figures-render.md", "08-figure-task.md", "09-figures-all.md"]
    if ch.reviewers:
        names += ["10-cold-referee.md", "11-referee-triage.md"]
    return list(dict.fromkeys(names))


def domain_files_in_use(cfg: Config) -> list[str]:
    """The domain-pack files the configured stages read (the instrument files only when the lab stage runs)."""
    lab_only = ("instrument.md", "lab-agent-instructions.md", "lab-safety.md")
    return [n for n in DOMAIN_FILES if cfg.chain.lab or n not in lab_only]


def prompt_problems(cfg: Config) -> list[str]:
    """Missing prompt and domain files, and files that still carry [insert: ...] parts. Empty list = all written."""
    out: list[str] = []
    prompts_dir = cfg.path(cfg.project.prompts_dir)
    names = prompts_in_use(cfg)
    missing = [n for n in names if not (prompts_dir / n).exists()]
    if missing:
        out.append(f"missing in {prompts_dir}: " + ", ".join(missing))
    todo = [n for n in names if n not in missing and UNFILLED in (prompts_dir / n).read_text(encoding="utf-8")]
    if todo:
        out.append(f"prompts still to write ({UNFILLED}: ...] parts): " + ", ".join(todo))
    for name in domain_files_in_use(cfg):
        path = cfg.domain(name)
        if not path.exists():
            if name != "exclusions.md":
                out.append(f"domain/{name} is missing ({DOMAIN_FILES[name]})")
        elif UNFILLED in path.read_text(encoding="utf-8"):
            out.append(f"domain/{name} still has {UNFILLED}: ...] parts to fill in ({DOMAIN_FILES[name]})")
    return out
