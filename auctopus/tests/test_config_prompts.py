"""Configuration loading, placeholders, project scaffolding, the prompt templates and the assembly of the proposer and
PI prompts."""
import os
import unittest
from unittest import mock

from auctopus.cli import RESOURCES, domain_packs, readiness, scaffold
from auctopus.config import DOMAIN_FILES, ConfigError, is_placeholder, load_config
from auctopus.prompt_builder import (PromptError, exclusion_clauses, pi_select_prompt, prompt_problems, prompts_in_use,
                                     proposer_prompts)

from helpers import EXAMPLE_CONFIG, TempDirMixin


class Placeholders(unittest.TestCase):
    def test_placeholder_rules(self):
        for v in (None, "", "  ", "insert OpenAI API key here", "Insert hostname", "insert"):
            self.assertTrue(is_placeholder(v), v)
        for v in ("sk-abc", "gpt-6", "login.example.org", 22):
            self.assertFalse(is_placeholder(v), v)


class ExampleConfig(TempDirMixin, unittest.TestCase):
    def test_example_config_loads_and_reports_every_placeholder(self):
        cfg = load_config(EXAMPLE_CONFIG)
        self.assertEqual(cfg.warnings, [])
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": ""}):
            problems = cfg.problems()
        joined = "\n".join(problems)
        self.assertIn("OpenAI API key missing", joined)
        self.assertIn("Anthropic API key missing", joined)
        self.assertIn("roles.pi.model is a placeholder", joined)
        self.assertIn("roles.proposer.model is a placeholder", joined)
        self.assertIn("hpc.host is a placeholder", joined)
        self.assertIn("lab.remote_root is a placeholder", joined)
        self.assertNotIn("reviewer_claude.model", joined)       # a real model id by default
        self.assertNotIn("safety.model", joined)

    def test_unused_roles_need_no_model(self):
        cfg = load_config(EXAMPLE_CONFIG)
        cfg.chain.lab = False
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x", "ANTHROPIC_API_KEY": "sk-y"}):
            joined = "\n".join(cfg.problems())
        self.assertNotIn("roles.feasibility", joined)
        self.assertIn("roles.pi.model", joined)

    def test_environment_key_wins_over_file(self):
        cfg = load_config(EXAMPLE_CONFIG)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}):
            self.assertEqual(cfg.keys.openai(), "sk-from-env")
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "insert later"}):
            self.assertIsNone(cfg.keys.openai())

    def test_unknown_keys_are_warned_not_fatal(self):
        p = self.tmp / "c.toml"
        p.write_text('[proposals]\nproposers = 3\nproposrs = 4\n[nonsense]\nx = 1\n', encoding="utf-8")
        cfg = load_config(p)
        self.assertEqual(cfg.proposals.proposers, 3)
        self.assertTrue(any("proposrs" in w for w in cfg.warnings))
        self.assertTrue(any("nonsense" in w for w in cfg.warnings))


class Scaffold(TempDirMixin, unittest.TestCase):
    def test_init_creates_a_complete_project_and_refuses_to_overwrite(self):
        cfg_path = scaffold(self.tmp / "lab")
        cfg = load_config(cfg_path)
        for name in DOMAIN_FILES:
            self.assertTrue(cfg.domain(name).exists(), name)
        packaged = sorted(p.name for p in (RESOURCES / "prompts").glob("*.md"))
        self.assertEqual(sorted(p.name for p in cfg.path(cfg.project.prompts_dir).glob("*.md")), packaged)
        self.assertIn("config.toml", (self.tmp / "lab" / ".gitignore").read_text(encoding="utf-8"))
        with self.assertRaises(ConfigError):
            scaffold(self.tmp / "lab")
        scaffold(self.tmp / "lab", force=True)

    def test_the_template_pack_assembles(self):
        self.assertEqual(domain_packs(), ["template"])        # the study's own pack is not part of the release
        cfg = load_config(scaffold(self.tmp / "t", "template"))
        fresh, brief = proposer_prompts(cfg)
        self.assertNotIn("{PHYSICAL_ANCHOR}", fresh + brief)
        self.assertNotIn("{EXCLUSIONS}", fresh + brief)
        pi_select_prompt(cfg, relaxed=True)
        pi_select_prompt(cfg, relaxed=False)


class Templates(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.cfg = load_config(scaffold(self.tmp))
        self.prompts = self.cfg.path(self.cfg.project.prompts_dir)

    def test_every_template_belongs_to_a_stage(self):
        packaged = {p.name for p in (RESOURCES / "prompts").glob("*.md")}
        self.assertEqual(set(prompts_in_use(self.cfg)), packaged)    # the default config runs every stage

    def test_unwritten_prompts_are_reported_and_stop_a_real_run(self):
        joined = "\n".join(prompt_problems(self.cfg))
        self.assertIn("prompts still to write", joined)
        self.assertIn("proposer.md", joined)
        self.assertIn("domain/sample-card.md still has", joined)
        self.assertIn("prompts still to write", "\n".join(readiness(self.cfg)))
        for p in list(self.prompts.glob("*.md")) + list(self.cfg.path(self.cfg.project.domain_dir).glob("*.md")):
            p.write_text(p.read_text(encoding="utf-8").replace("[insert:", "Written:"), encoding="utf-8")
        self.assertEqual(prompt_problems(self.cfg), [])
        (self.prompts / "06-review.md").unlink()
        self.assertIn("06-review.md", "\n".join(prompt_problems(self.cfg)))

    def test_only_the_prompts_of_the_configured_stages_are_needed(self):
        self.cfg.chain.lab = False
        self.cfg.chain.figures = False
        self.cfg.chain.reviewers = []
        self.cfg.proposals.relax_after = 0
        used = prompts_in_use(self.cfg)
        self.assertIn("pi-select-strict.md", used)
        for name in ("pi-select.md", "12-feasibility-gate.md", "lab-run.md", "07-figure-plan.md", "10-cold-referee.md"):
            self.assertNotIn(name, used)
        self.cfg.chain.lab = True
        self.cfg.lab.transport = "manual"
        self.assertNotIn("lab-run.md", prompts_in_use(self.cfg))
        self.assertIn("14s-safety-review.md", prompts_in_use(self.cfg))


class Prompts(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.cfg = load_config(scaffold(self.tmp))
        self.cfg.domain("exclusions.md").write_text("# a comment\n; or that rely on a lookup table\n",
                                                    encoding="utf-8")

    def test_proposer_prompt_has_anchor_and_exclusions_but_revision_brief_has_no_exclusions(self):
        fresh, brief = proposer_prompts(self.cfg)
        self.assertIn("**Physical anchor.**", fresh)
        self.assertIn("**Physical anchor.**", brief)
        self.assertIn("[insert: what the proposers must avoid]; or that rely on a lookup table.", fresh)
        self.assertIn("[insert: what the proposers must avoid].", brief)
        self.assertNotIn("a comment", fresh)

    def test_manager_exclusions_extend_the_list(self):
        fresh, _ = proposer_prompts(self.cfg, "; or that restate a known estimator")
        self.assertIn("; or that rely on a lookup table; or that restate a known estimator.", fresh)
        self.assertEqual(exclusion_clauses("; or that a.", "or that b"), "; or that a; or that b")

    def test_pi_prompt_relaxed_and_strict(self):
        relaxed = pi_select_prompt(self.cfg, relaxed=True)
        strict = pi_select_prompt(self.cfg, relaxed=False)
        for text in (relaxed, strict):
            self.assertIn("**Physical anchor.**", text)
            self.assertIn("SELECTION: proposer-N", text)
            self.assertIn("BEST SEED: proposer-N", text)
        self.assertIn("relaxed selection", relaxed)
        self.assertNotIn("relaxed selection", strict)

    def test_a_template_without_its_placeholder_fails_loudly(self):
        prompt = self.cfg.path(self.cfg.project.prompts_dir) / "proposer.md"
        prompt.write_text(prompt.read_text(encoding="utf-8").replace("{PHYSICAL_ANCHOR}", ""), encoding="utf-8")
        with self.assertRaises(PromptError):
            proposer_prompts(self.cfg)


if __name__ == "__main__":
    unittest.main()
