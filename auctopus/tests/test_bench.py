"""Offline smoke tests of auctopus.bench: each adapter prepares a project, runs the whole pipeline with mock models
and mock agents, and lays its outputs out for the benchmark's evaluator (dry evaluation, no judge call).

They need the benchmark checkouts under team_project/data (see team_project/README.md); each test is skipped when
its checkout is absent. The DiscoveryWorld test also needs pygame (the environment runs headless)."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from auctopus.bench import Paths, get_benchmark
from auctopus.bench.base import TEAM_ROOT
from auctopus.config import load_config
from auctopus.pipeline import Pipeline, new_run_dir
from auctopus.util import read_json

from helpers import TempDirMixin

DATA = TEAM_ROOT / "data"


def run_mock(bench_name: str, task_id: str, tmp: Path) -> tuple:
    b = get_benchmark(bench_name)
    paths = Paths(data_root=DATA, out_root=tmp)
    task = b.task(paths, task_id)
    cfg_path = b.prepare(task, paths, "gpt-5-nano", "gpt-5-nano", mock=True, force=True)
    cfg = load_config(cfg_path)
    from auctopus.llm import reset_clients
    reset_clients()
    run = new_run_dir(cfg, "test")
    with contextlib.redirect_stdout(io.StringIO()):
        code = Pipeline(cfg, run, dry_run=True).run()
    return b, paths, task, cfg_path.parent, run, code


class BenchSmoke(TempDirMixin, unittest.TestCase):
    @unittest.skipUnless((DATA / "mlr-bench" / "tasks").is_dir(), "MLR-Bench checkout not present")
    def test_mlr_mock_pipeline_and_layout(self):
        b, paths, task, project, run, code = run_mock("mlr", "iclr2025_dl4c", self.tmp)
        self.assertEqual(code, 0)
        state = read_json(run / "state.json")
        for name in ("proposals", "theory", "verify", "verify-review", "reviewers", "deliver"):
            self.assertEqual(state["stages"][name]["status"], "done", name)
        self.assertTrue((run / "package" / "main.md").exists())        # Markdown manuscript accepted
        layout, missing = b.layout(task, paths, project, run)
        self.assertEqual(missing, [])
        for rel in ("task.md", "idea.md", "related_work.md", "proposal.md", "results/results.md",
                    "results/paper.md", "experiment_log.json"):
            self.assertTrue((layout / rel).exists(), rel)

    @unittest.skipUnless((DATA / "researchclawbench" / "tasks").is_dir(), "ResearchClawBench checkout not present")
    def test_rcb_mock_pipeline_pushes_data_and_lays_out_workspace(self):
        b, paths, task, project, run, code = run_mock("rcb", "Astronomy_000", self.tmp)
        self.assertEqual(code, 0)
        work = b.workdir(project, run)
        self.assertTrue((work / "data").is_dir() and (work / "related_work").is_dir())   # hpc.inputs pushed
        self.assertFalse((run / "hpc-round1" / "data").exists())                         # and not pulled back
        ws, missing = b.layout(task, paths, project, run)
        try:
            self.assertEqual(missing, [])
            self.assertTrue((ws / "_meta.json").exists() and (ws / "INSTRUCTIONS.md").exists())
            self.assertTrue((ws / "report" / "report.md").exists())
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    @unittest.skipUnless((DATA / "discoveryworld" / "discoveryworld").is_dir(), "DiscoveryWorld checkout not present")
    def test_dw_mock_pipeline_runs_the_environment(self):
        try:
            import pygame  # noqa: F401
        except ImportError:
            self.skipTest("pygame not installed")
        b, paths, task, project, run, code = run_mock("dw", "plant-nutrients-easy-s0", self.tmp)
        self.assertEqual(code, 0)
        state = read_json(run / "state.json")
        self.assertNotIn("verify", state["stages"])                      # chain.verify = false
        self.assertEqual(state["stages"]["lab"]["decision"], "GO")
        final = state["stages"]["lab"]["result_final"]
        traj = run / "lab_results" / final["run_id"] / "data" / "trajectory.jsonl"
        self.assertTrue(traj.exists() and traj.read_text().count("\n") >= 1)
        oracle = read_json(project / "remote-lab" / "work" / "scores" / f"{final['run_id']}.json")
        self.assertIn("scoreNormalized", oracle["scorecard"][0])
        result = b.evaluate(task, paths, project, run, "gpt-5-nano", dry=True)
        self.assertIn("procedure_score", result["scores"])
        self.assertTrue((b.workdir(project, run) / "knowledge.md").exists())


if __name__ == "__main__":
    unittest.main()
