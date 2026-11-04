"""Shared test helpers: an offline project in a temporary folder."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from auctopus.cli import RESOURCES, scaffold
from auctopus.config import load_config, mock_overrides
from auctopus.llm import reset_clients

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = RESOURCES / "config.example.toml"


def offline_config(tmp: Path, scenario: str = "revision-then-win", **chain):
    """A project created by `auctopus init` inside `tmp`, turned into an offline run (mock models, local folders as
    the remote machines)."""
    cfg = load_config(scaffold(tmp, force=True))
    cfg = mock_overrides(cfg, tmp / "sandbox")
    cfg.mock.scenario = scenario
    cfg.project.runs_dir = str(tmp / "runs")
    for k, v in chain.items():
        setattr(cfg.chain, k, v)
    reset_clients()
    return cfg


class TempDirMixin:
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="auctopus-test-"))

    def tearDown(self):
        import logging
        for h in list(logging.getLogger("auctopus").handlers):   # release pipeline.log before deleting
            h.close()
            logging.getLogger("auctopus").removeHandler(h)
        shutil.rmtree(self.tmp, ignore_errors=True)
