"""MLR-Bench adapter (team_project/data/mlr-bench).

Mapping of the benchmark's four research stages onto the Auctopus workflow:

    idea        proposals stage: proposers write ideas for the workshop call (the task.md is the sample card), the
                PI rejects or selects strictly; the selected proposal plus the PI's verdict is idea.md
    proposal    theory stage: 02-proofs (method and precommitted predictions), 02b-positioning (related_work.md),
                03-write (proposal.md and the manuscript skeleton main.md), 04-exp (experiment.md)
    experiment  verify stage: the API coding agent runs the experiments (results/results.md, code/) and the PI
                reviews them once (verify-review, one revision)
    paper       reviewers stage: two independent referees, the PI's triage, one revision, the final PI review;
                main.md is the paper

Evaluation uses the benchmark's own reviewers (mlrbench/evals): review_idea, review_proposal, review_experiment,
review_writeup and the hallucination check (eval_hallucination.overall_review), each with its unchanged rubric.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from ..util import read_json, write_json
from .base import BENCHMARKS, Benchmark, Paths, TaskSpec

CODE_EXT = {".py", ".sh", ".yaml", ".yml", ".toml", ".cfg", ".txt", ".json", ".csv", ".log"}


class MLRBench(Benchmark):
    name = "mlr"
    label = "MLR-Bench"
    data_subdir = "mlr-bench"
    coder_budget_s = 5400

    def tasks(self, paths: Paths) -> list[TaskSpec]:
        out = []
        for f in sorted((self.data_dir(paths) / "tasks").glob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.strip()), f.stem)
            out.append(TaskSpec(f.stem, title, text, {"task_file": str(f)}))
        return out

    def variables(self, task: TaskSpec, paths: Paths, project: Path) -> dict[str, str]:
        v = super().variables(task, paths, project)
        v["TASK_CARD"] = task.description.strip()      # the benchmark's task file verbatim, never shortened
        return v

    def extra_instructions(self, task: TaskSpec, paths: Paths) -> str:
        return ("This machine has Python with numpy, pandas, scipy, scikit-learn and matplotlib; install other "
                "packages with pip when needed (torch, transformers, datasets). There may be no GPU: check with "
                "`python -c \"import torch; print(torch.cuda.is_available())\"` and size the experiments so they "
                "finish on CPU within the time budget (small models, subsets, few epochs).")

    # ------------------------------------------------------------- evaluation
    def layout(self, task: TaskSpec, paths: Paths, project: Path, run_dir: Path) -> tuple[Path, list[str]]:
        """Arrange the run's outputs the way mlrbench/evals expects: task.md, idea.md, related_work.md,
        proposal.md, results/results.md, results/paper.md, claude_code/, experiment_log.json."""
        out = paths.eval_dir(self.name, task.id) / "mlr_layout"
        if out.exists():
            shutil.rmtree(out)
        (out / "results").mkdir(parents=True)
        (out / "claude_code").mkdir()
        missing: list[str] = []
        shutil.copyfile(task.extra["task_file"], out / "task.md")
        proposal, verdict = self.selected_proposal(run_dir)
        (out / "idea.md").write_text((proposal or "(no proposal selected)") + "\n\n---\n\n## Principal "
                                     "investigator's assessment\n\n" + verdict, encoding="utf-8")
        if not proposal:
            missing.append("idea (no selected proposal)")
        package = run_dir / "package"
        for name, fallback in (("related_work.md", "02b-positioning-reply.md"), ("proposal.md", "03-write-reply.md")):
            src = package / name
            if not src.exists():
                src = run_dir / fallback
            if src.exists():
                shutil.copyfile(src, out / name)
            else:
                (out / name).write_text("(not produced)\n", encoding="utf-8")
                missing.append(name)
        work = self.workdir(project, run_dir)
        if work is None:
            missing.append("working folder (no computational round)")
            return out, missing
        results = work / "results" / "results.md"
        if results.exists():
            shutil.copyfile(results, out / "results" / "results.md")
        else:
            parts = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(work.glob("RESULTS-*.md"))]
            if parts:
                (out / "results" / "results.md").write_text("\n\n".join(parts), encoding="utf-8")
            else:
                missing.append("results/results.md")
                (out / "results" / "results.md").write_text("(no results file)\n", encoding="utf-8")
        paper = next((work / n for n in ("main.md", "paper.md", "manuscript.md") if (work / n).exists()), None)
        if paper is None:
            missing.append("paper (main.md)")
            (out / "results" / "paper.md").write_text("(no paper)\n", encoding="utf-8")
        else:
            shutil.copyfile(paper, out / "results" / "paper.md")
            for sub in ("figures", "images", "results/figures", "report/images", "plots"):
                d = work / sub
                if d.is_dir():
                    shutil.copytree(d, out / "results" / sub, dirs_exist_ok=True)
            for png in work.glob("*.png"):
                shutil.copyfile(png, out / "results" / png.name)
        n_code = 0
        for p in sorted(work.rglob("*")):
            if (p.is_file() and p.suffix.lower() in CODE_EXT and ".auctopus" not in p.parts
                    and p.stat().st_size < 400_000 and p.name not in ("ROUND-DONE.json",)):
                rel = p.relative_to(work)
                dst = out / "claude_code" / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dst)
                n_code += 1
        if n_code == 0:
            missing.append("code")
        log: list[dict] = []
        for t in sorted((work / ".auctopus" / "coder").glob("*.json")):
            data = read_json(t, default={}) or {}
            log.append({"role": "system", "content": f"=== coding-agent session {t.stem} ==="})
            for m in data.get("messages", []):
                if m.get("role") == "tool":
                    log.append({"role": "assistant", "content": f"[tool {m.get('name')}] "
                                                                f"{json.dumps(m.get('input'), ensure_ascii=False)}"})
                    log.append({"role": "user", "content": f"[tool output]\n{m.get('output', '')}"})
                else:
                    log.append({"role": m.get("role", "assistant"), "content": m.get("content", "")})
        if not log:
            missing.append("experiment log (no coder transcript)")
        write_json(out / "experiment_log.json", log)
        return out, missing

    def evaluate(self, task: TaskSpec, paths: Paths, project: Path, run_dir: Path, judge: str, dry: bool) -> dict:
        layout, missing = self.layout(task, paths, project, run_dir)
        result = {"judge": judge, "layout": str(layout), "missing": missing, "scores": {}, "details": {}}
        if dry:
            result["note"] = "dry evaluation: layout only, the judge was not called"
            return result
        sys.path.insert(0, str(self.data_dir(paths)))
        from mlrbench.evals.eval_hallucination import overall_review
        from mlrbench.evals.review_experiments import review_experiment
        from mlrbench.evals.review_idea import review_idea
        from mlrbench.evals.review_proposal import review_proposal
        from mlrbench.evals.review_writeup import review_writeup
        from .judges import mlr_multimodal_judge, mlr_text_judge
        text_judge = mlr_text_judge(judge)
        lmm_judge = mlr_multimodal_judge(judge)
        task_file = str(layout / "task.md")
        scores, details = result["scores"], result["details"]

        def overall(review: dict | None) -> float | None:
            try:
                return float(review["OverallAssessment"]["score"])
            except (TypeError, KeyError, ValueError):
                return None

        r = review_idea(str(layout / "idea.md"), text_judge, task_file)
        details["idea"] = r
        scores["idea_overall"] = overall(r)
        r = review_proposal(str(layout / "proposal.md"), text_judge, task_file, str(layout / "idea.md"),
                            str(layout / "related_work.md"))
        details["proposal"] = r
        scores["proposal_overall"] = overall(r)
        r = review_experiment(str(layout / "experiment_log.json"), text_judge)
        details["experiment"] = r
        scores["experiment_overall"] = overall(r)
        try:
            scores["experiment_hallucination"] = bool(r["Hallucination"]["has_hallucination"])
        except (TypeError, KeyError):
            scores["experiment_hallucination"] = None
        r = review_writeup(str(layout / "results" / "paper.md"), lmm_judge, task_file, str(layout / "idea.md"),
                           str(layout / "related_work.md"), str(layout / "proposal.md"),
                           str(layout / "results" / "results.md"))
        details["writeup"] = r
        scores["paper_overall"] = overall(r)
        h = overall_review(str(layout / "results" / "paper.md"), lmm_judge, task_file,
                           code_path=str(layout / "claude_code"))
        h = h[0] if isinstance(h, tuple) else h
        details["hallucination"] = h
        scores["paper_hallucination"] = bool(h.get("has_hallucination")) if isinstance(h, dict) else None
        scores["paper_hallucination_count"] = len(h.get("hallucinations") or []) if isinstance(h, dict) else None
        for name, data in details.items():
            write_json(layout.parent / f"review_{name}.json", data)
        return result


BENCHMARKS["mlr"] = MLRBench
