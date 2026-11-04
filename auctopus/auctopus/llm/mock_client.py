"""Offline stand-in for every model role, used by the dry run and the tests (no keys, no network, no cost).

Replies are deterministic and carry exactly the machine-readable lines the prompts ask for (KEEP, SELECTION, BEST SEED,
VERDICT, FIGURE(S), FEASIBILITY, LAB-DECISION, SAFETY, RERUN-DECISION, FILE blocks), so every branch of the pipeline
can be exercised. The replies depend on the stage and the attached files, never on the prompts' wording. Scenarios:
    win-first          the first batch produces a selection
    revision-then-win  the first batch is rejected with a best seed; its revision batch wins (default)
    never-win          nothing is ever selected (the run must stop after proposals.max_batches)
    lab-redo           the PI's triage says NO-GO, the manager's design is approved, the safety agent asks for one
                       correction, and the first acquisition fails and is repeated with amendments
"""
from __future__ import annotations

import re
import threading
import time

from ..attachments import content_text
from ..config import RoleCfg
from .base import LLMCancelled, LLMReply, StartedHook

FILLER = ("The construction rests on a single exact identity whose consequences can be tested on the instrument, "
          "and every step from the definition to the prediction is stated so that a referee can check it. ")

MOCK_TEX = r"""\documentclass{article}
\title{Exact Calibration Laws for Disordered Spin Ensembles (mock)}
\begin{document}
\maketitle
\begin{abstract}
A mock manuscript produced by the dry run of the pipeline.
\end{abstract}
\section{Introduction}
This file exists so that every downstream stage has a paper to work on.
\section{Theory}
Exactly $L^2+1$ calibrations determine every sequence of at most $L$ pulses.
\end{document}
"""


MOCK_MD = """# Exact Calibration Laws for Disordered Spin Ensembles (mock)

## Abstract
A mock Markdown manuscript produced by the dry run of the pipeline.

## Precommitted predictions
Exactly L^2+1 calibrations determine every sequence of at most L pulses.
"""


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))


class MockClient:
    provider = "mock"

    def __init__(self, scenario: str = "revision-then-win", delay_s: float = 0.0, markdown: bool = False):
        self.scenario = scenario
        self.delay_s = delay_s
        self.markdown = markdown        # BENCH: deliver main.md instead of main.tex (chain.manuscript = "markdown")

    def complete(self, messages: list[dict], *, system: str | None, role: RoleCfg, stage: str = "",
                 on_started: StartedHook | None = None, resume_id: str | None = None,
                 cancel: threading.Event | None = None) -> LLMReply:
        if on_started:
            on_started(f"mock-{stage}-{len(messages)}")
        if self.delay_s:
            time.sleep(self.delay_s)
        if cancel is not None and cancel.is_set():
            raise LLMCancelled(f"mock:{stage}: cancelled")
        prompt = content_text(messages[-1]["content"]) if messages else ""
        text = self.reply(stage, prompt, messages)
        return LLMReply(text=text, provider="mock", model=f"mock-{role.provider}", stop_reason="end_turn",
                        response_id=f"mock-{stage}")

    # ---------------------------------------------------------------- dispatch
    def reply(self, stage: str, prompt: str, messages: list[dict]) -> str:
        s = self.scenario
        if stage == "proposer":
            revision = "attached file: seed.md" in prompt          # a revision batch carries the seed proposal
            tag = "MOCK-REVISION " if revision else ""
            body = (FILLER * 60).strip()
            return (f"# {tag}Proposal: exact calibration counting for heterogeneous controlled ensembles\n\n"
                    f"{body}\n\nTestable prediction: a signed combination of withheld responses is non-zero.\n")
        if stage == "dedup":
            names = sorted(set(re.findall(r"proposer-\d+\.md", prompt)), key=lambda n: int(re.sub(r"\D", "", n)))
            kept = names[: max(1, len(names) - 1)] if len(names) > 2 else names
            return ("Overlap group: two proposals share the same mechanism; the stronger was kept.\n\n"
                    f"KEEP: {', '.join(kept)}")
        if stage == "selection":
            labels = re.findall(r"attached file: (proposer-\d+)\.md", prompt)
            first = labels[0] if labels else "proposer-1"
            wins = (s == "win-first" or (s in ("revision-then-win", "lab-redo") and "MOCK-REVISION" in prompt))
            if wins:
                return (f"SELECTION: {first}\n\n**Exact calibration counting.** The proposal is the strongest of the "
                        "batch. Its central claim is developed below into a theorem with a proof plan, and its "
                        "testable prediction is a non-zero signed combination of withheld responses.\n")
            return ("SELECTION: none\n\nNo proposal clears the bar: the central mechanisms are known under other "
                    f"names.\n\nBEST SEED: {first}")
        if stage.startswith("manager-exclusions"):
            return ("Two families recur in the verdicts and were rejected each time as already known.\n\n"
                    "===== FILE: exclusions.md =====\n"
                    "; or that restate a known estimator under a new name; or that rest on a generic dimension "
                    "count alone\n===== END FILE =====\n")
        if stage == "02-proofs":
            return "Theorem 1. Exactly L^2+1 calibrations are necessary and sufficient. Proof: dimension count.\n"
        if stage == "02b-positioning":
            return "| reference | what it establishes | what remains ours |\n|---|---|---|\n| A | B | C |\n"
        if stage in ("03-write", "03b-redeliver"):
            if self.markdown:
                return ("The manuscript follows.\n\n===== FILE: main.md =====\n" + MOCK_MD.strip() +
                        "\n===== END FILE =====\n\n===== FILE: proposal.md =====\n# Proposal (mock)\n\nOne "
                        "idea, one prediction.\n===== END FILE =====\n")
            return ("The manuscript follows.\n\n===== FILE: main.tex =====\n" + MOCK_TEX.strip() +
                    "\n===== END FILE =====\n\n===== FILE: references.bib =====\n@article{a, title={A}}\n"
                    "===== END FILE =====\n")
        if stage == "04-exp":
            return ("# Killer experiment\n\nSimulate the ensemble, fit the law on L^2+1 calibrations, predict the "
                    "withheld sequences, and compare with two interpolating rivals.\n")
        if stage.endswith("-compact"):
            return "Summary of the conversation so far: the law, its proof and the experiments."
        if stage == "lab-feasibility":
            return "1. Test: cross-length transfer.\n\nFEASIBILITY: GO"
        if stage == "lab-triage":
            if s == "lab-redo":
                return "The gate's design cannot separate the law from interpolation.\n\nLAB-DECISION: NO-GO"
            return _numbered(["Calibrate counts and the pi pulse.", "Run the ten calibrations and four targets.",
                              "Apply the frozen decision rule."]) + "\n\nLAB-DECISION: GO"
        if stage == "lab-manager-design":
            return "Proposed design: predict a cross-length contrast that every interpolator sets to zero."
        if stage == "lab-redesign":
            return _numbered(["Calibrations first.", "Interleave calibrations and targets.",
                              "Lock the prediction before the targets are read."]) + "\n\nLAB-DECISION: GO"
        if stage.startswith("lab-safety"):
            if s == "lab-redo" and stage == "lab-safety-1":
                return _numbered(["Step 4 sets no laser duty limit: state the duty cycle and keep it within the "
                                  "specification."]) + "\n\nSAFETY: REJECT"
            return "Every step stays inside the standard regime; every exit path leaves the setup idle-safe.\n\n" \
                   "SAFETY: APPROVE"
        if stage.startswith("lab-rerun"):
            return "The run failed its controls; repeat it with one continuous schedule.\n\nRERUN-DECISION: AMEND"
        if stage == "lab-packet-review" or stage == "lab-analysis-review":
            return _numbered(["Keep the thresholds as registered."]) + "\n\nVERDICT: ACCEPT"
        if re.search(r"-round\d+$", stage):
            if stage == "verify-review-round1":
                return _numbered(["State the main result in the abstract.", "Report the error bars."]) + \
                    "\n\nVERDICT: REVISE"
            return _numbered(["Tighten the caption of figure 2."]) + "\n\nVERDICT: ACCEPT"
        if stage == "figure-plan":
            return "Figure 1: one panel showing calibrations versus sequences."
        if stage == "figure-review1":
            return "FIGURE: REVISE\n1. Delete the redundant legend at the top right."
        if stage == "figures-all-review1":
            return "FIGURES: ACCEPT"
        if stage.startswith("reviewer") and stage.endswith("-report"):
            return "Summary. Strengths. Weaknesses.\n\nVerdict: Borderline accept. Confidence: 4."
        if stage == "reviewer-triage":
            return ("| finding | ruling | reason |\n|---|---|---|\n| clarity | ACT | fair |\n\n" +
                    _numbered(["Clarify the abstract.", "Add the missing citation."]))
        return f"Mock reply for stage {stage}."
