"""ResearchClawBench adapter (team_project/data/researchclawbench).

The benchmark gives an agent a task description, raw data and reference papers, and asks for code, outputs and a
research report (report/report.md with PNG figures). Mapping onto the Auctopus workflow:

    proposals   proposers propose research questions and hypotheses testable with the given data; strict PI selection
    theory      02-proofs (analysis design, precommitted predictions, acceptance criteria), 02b-positioning
                (positioning against the related work), 03-write (report skeleton report/report.md), 04-exp
                (the analysis protocol, experiment.md)
    verify      the API coding agent runs the analysis in a workspace holding data/ and related_work/ and writes
                code/, outputs/ and report/report.md; one PI review and revision
    reviewers   two independent referees, the PI's triage, one revision, final PI review
    deliver     the workspace is laid out as a ResearchClawBench run and scored by evaluation/score.py (the
                benchmark's multimodal rubric judge; 50 = the published paper's level)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from ..util import read_json, write_json
from .base import BENCHMARKS, Benchmark, Paths, TaskSpec, toml_str


class ResearchClawBench(Benchmark):
    name = "rcb"
    label = "ResearchClawBench"
    data_subdir = "researchclawbench"
    pull_exclude = Benchmark.pull_exclude + ["data", "related_work"]
    coder_budget_s = 5400

    def tasks(self, paths: Paths) -> list[TaskSpec]:
        out = []
        for f in sorted((self.data_dir(paths) / "tasks").glob("*/task_info.json")):
            info = read_json(f, default={}) or {}
            desc = info.get("task", "")
            title = desc.strip().splitlines()[0][:90] if desc.strip() else f.parent.name
            out.append(TaskSpec(f.parent.name, title, desc, {"task_dir": str(f.parent), "data": info.get("data", [])}))
        return out

    @staticmethod
    def data_text(task: TaskSpec) -> str:
        parts = []
        for d in task.extra.get("data", []):
            ws_path = d.get("path", "").lstrip("./")
            type_str = f" [{d.get('type')}]" if d.get("type") else ""
            parts.append(f"- **{d.get('name')}**{type_str} (`{ws_path}`): {d.get('description', '')}")
        return "\n".join(parts) if parts else "No specific data files."

    def variables(self, task: TaskSpec, paths: Paths, project: Path) -> dict[str, str]:
        v = super().variables(task, paths, project)
        v["DATA_FILES"] = self.data_text(task)
        rw = sorted(p.name for p in (Path(task.extra["task_dir"]) / "related_work").glob("*.pdf"))
        v["RELATED_WORK"] = "\n".join(f"- related_work/{n}" for n in rw) or "(none)"
        v["TASK_CARD"] = (task.description.strip()      # the benchmark's task text verbatim, never shortened
                          + "\n\nData files available to the computational researcher:\n" + v["DATA_FILES"])
        return v

    def hpc_inputs(self, task: TaskSpec, paths: Paths) -> list[str]:
        td = Path(task.extra["task_dir"])
        return [f"{td / 'data'}:data", f"{td / 'related_work'}:related_work"]

    def extra_instructions(self, task: TaskSpec, paths: Paths) -> str:
        return ("The workspace holds the task's raw data in data/ (read-only: never modify it) and the reference "
                "papers as PDFs in related_work/ (read them with pymupdf4llm or pypdf). Write analysis code in "
                "code/, intermediate results in outputs/, the report in report/report.md and every figure as a PNG "
                "in report/images/, referenced as images/<name>.png. No web access is needed or expected. Python "
                "has numpy, pandas, scipy, scikit-learn and matplotlib; install more with pip if required.")

    # ------------------------------------------------------------- evaluation
    def layout(self, task: TaskSpec, paths: Paths, project: Path, run_dir: Path) -> tuple[Path, list[str]]:
        """A ResearchClawBench run workspace: workspaces/<run_id>/ with _meta.json, INSTRUCTIONS.md, code/,
        outputs/, report/ (the evaluator reads the report, the images and the instructions)."""
        sys.path.insert(0, str(self.data_dir(paths)))
        from evaluation.instructions_tmpl import INSTRUCTIONS_TEMPLATE
        cfg_task = read_json(project / "task.json", default={}) or {}
        run_id = f"auctopus-{task.id}-{run_dir.name}"[:120]
        ws = self.data_dir(paths) / "workspaces" / run_id
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True)
        missing: list[str] = []
        work = self.workdir(project, run_dir)
        if work is None:
            missing.append("working folder (no computational round)")
        else:
            for sub in ("code", "outputs", "report"):
                if (work / sub).is_dir():
                    shutil.copytree(work / sub, ws / sub, dirs_exist_ok=True)
            if not (ws / "report" / "report.md").exists():
                main = next((work / n for n in ("main.md", "report.md", "paper.md") if (work / n).exists()), None)
                if main is not None:
                    (ws / "report").mkdir(exist_ok=True)
                    shutil.copyfile(main, ws / "report" / "report.md")
                else:
                    missing.append("report/report.md")
            if not (ws / "code").is_dir():
                (ws / "code").mkdir()
                for p in work.glob("*.py"):
                    shutil.copyfile(p, ws / "code" / p.name)
            (ws / "outputs").mkdir(exist_ok=True)
        (ws / "INSTRUCTIONS.md").write_text(INSTRUCTIONS_TEMPLATE.format(workspace=str(ws.resolve()),
                                                                          task_desc=task.description,
                                                                          data_text=self.data_text(task)),
                                            encoding="utf-8")
        write_json(ws / "_meta.json", {"task_id": task.id, "run_id": run_id, "timestamp": time.strftime("%Y%m%d_%H%M%S"),
                                       "status": "completed", "workspace": str(ws),
                                       "agent_name": cfg_task.get("agent_name") or f"auctopus-{cfg_task.get('model', '')}",
                                       "agent_cmd": "auctopus.bench (Auctopus workflow with the API coding agent)",
                                       "model": cfg_task.get("model", ""), "auctopus_run": str(run_dir)})
        return ws, missing

    def evaluate(self, task: TaskSpec, paths: Paths, project: Path, run_dir: Path, judge: str, dry: bool) -> dict:
        ws, missing = self.layout(task, paths, project, run_dir)
        result = {"judge": judge, "layout": str(ws), "missing": missing, "scores": {}, "details": {}}
        if dry:
            result["note"] = "dry evaluation: workspace laid out, the judge was not called"
            return result
        from .judges import rcb_judge_env
        rcb_judge_env(judge)
        sys.path.insert(0, str(self.data_dir(paths)))
        import importlib
        import evaluation.config as ecfg
        importlib.reload(ecfg)                      # it reads JUDGE_MODEL_NAME at import time
        from evaluation import score as score_module
        importlib.reload(score_module)
        data = score_module.score_workspace(ws)
        if "error" in data:
            result["error"] = data["error"]
            return result
        items = data.get("items", [])
        by_type: dict[str, list[float]] = {}
        for it in items:
            by_type.setdefault(it.get("type", "text"), []).append(float(it.get("score", 0)))
        result["scores"] = {"total_score": data.get("total_score"), "n_items": len(items),
                            **{f"mean_{k}": round(sum(v) / len(v), 2) for k, v in by_type.items() if v},
                            "items_at_or_above_paper": sum(1 for it in items if float(it.get("score", 0)) >= 50)}
        result["details"] = data
        write_json(paths.eval_dir(self.name, task.id) / "rcb_score.json", data)
        return result


BENCHMARKS["rcb"] = ResearchClawBench
