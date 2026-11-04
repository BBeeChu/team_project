"""Coding agents on remote machines: the computational researcher (Codex on the HPC) and the experimentalist (Claude
Code on the instrument computer), each started over SSH in a working folder.

Each task is one non-interactive agent run (`codex exec`, `claude -p`) launched as a detached job; it is finished when the process
exits (exit-code marker), and the agent is asked to leave ROUND-DONE.json with its own status. Agents authenticate with
API keys that the remote reads from a private env file (see `setup-remote`).
"""
from __future__ import annotations

import re
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Config, RemoteCfg, is_placeholder
from ..util import LOG, iso_now, truncate_middle

NO_PUBLISH_RULE = (
    "STANDING RULE (binding on every task): never publish anything outside this folder. Do not create, "
    "push to or change any remote repository (GitHub or any other host), do not create releases, do not upload or "
    "deposit files to any external service (Zenodo, Software Heritage, figshare, OSF, arXiv or any other), and do "
    "not request archival or identifiers. Releases are local files in this folder only. If a task asks for a public "
    "identifier or deposition, record it as pending for the people running this laboratory and continue.")

CONTINUITY_RULE = (
    "Working memory: this folder is your only memory between tasks. Before starting, read NOTES-RESUME.md (if it "
    "exists) and your previous reports in this folder. Keep NOTES-RESUME.md current as you work: what was done, "
    "where the results are, and what remains, so a later session can continue without you.")

MANUSCRIPT_RULE = (
    "Manuscript: keep the paper's LaTeX source and its compiled PDF together in this folder (main.tex and main.pdf, "
    "or the paper's own names) and rebuild the PDF whenever you change the source; the reviewers read the PDF.")

MARKDOWN_RULE = (   # BENCH: used instead of MANUSCRIPT_RULE when chain.manuscript = "markdown"
    "Manuscript: the paper is a Markdown document in this folder (main.md, or report/report.md where the task says "
    "so); keep it current whenever results change, with figures saved as PNG files and referenced by relative path. "
    "The reviewers read that Markdown file; no LaTeX or PDF is needed.")

COMPLETION_RULE = (
    "When the task is complete (or cannot be completed), write ROUND-DONE.json in this folder as your last action: "
    '{"status": "done" or "blocked", "summary": "<one paragraph of plain facts>", "deliverables": ["<paths>"]}. '
    "Do not write it before the work is finished.")

DEFAULT_COMMANDS = {
    # `codex exec` is the non-interactive form of the Codex agent.
    "codex": 'codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check {model_flag}'
             '"$(cat {prompt_file})"',
    # The experimentalist is Claude Code on the instrument computer; `-p` runs one task headless.
    "claude": 'claude -p --dangerously-skip-permissions --output-format text {model_flag}"$(cat {prompt_file})"',
    "mock": '"{python}" -m auctopus.remote.mock_agent --role {label} --prompt "{prompt_file}" --scenario {scenario}',
    # BENCH: an API coding agent (OpenAI Responses API with shell and file tools), so no CLI agent is needed
    "api": '"{python}" -m auctopus.bench.coder {model_flag}--prompt "{prompt_file}"',
}


def strip_goal(prompt: str) -> str:
    """Codex TUI prompts start with '/goal'; a non-interactive run takes the text itself."""
    return re.sub(r"^\s*/goal\s+", "", prompt, count=1)


def agent_command(rc: RemoteCfg, label: str, prompt_file: str, scenario: str) -> str:
    template = rc.agent_command or DEFAULT_COMMANDS.get(rc.agent)
    if not template:
        raise ValueError(f"{label}.agent '{rc.agent}' needs {label}.agent_command (no default for it)")
    model_flag = ""
    if not is_placeholder(rc.agent_model):
        flag = "-m" if rc.agent == "codex" else "--model"
        model_flag = f"{flag} {shlex.quote(rc.agent_model)} "
    return template.format(model_flag=model_flag, model=rc.agent_model, prompt_file=prompt_file,
                           python=sys.executable, label=label, scenario=scenario)


@dataclass
class AgentResult:
    exit_code: int | None
    status: str          # "done" (process ended) / "timeout" / "lost"
    log_tail: str
    handle: dict


class RemoteAgent:
    """Runs agent tasks in one remote working folder and waits for them, resumable from a saved job handle."""

    def __init__(self, cfg: Config, label: str, transport, workdir: str):
        self.cfg = cfg
        self.label = label
        self.rc: RemoteCfg = cfg.hpc if label == "hpc" else cfg.lab
        self.t = transport
        self.workdir = workdir

    def compose_prompt(self, prompt: str, extra_rules: list[str] | None = None) -> str:
        text = strip_goal(prompt).rstrip()
        rules = [CONTINUITY_RULE, COMPLETION_RULE]
        if self.label == "hpc":
            manuscript = MARKDOWN_RULE if self.cfg.chain.manuscript == "markdown" else MANUSCRIPT_RULE
            rules[0:0] = [NO_PUBLISH_RULE, manuscript]
        if self.rc.extra_instructions.strip():
            rules.append("Site notes: " + self.rc.extra_instructions.strip())
        rules += list(extra_rules or [])
        for r in rules:
            if r not in text:
                text += "\n\n" + r
        return text + "\n"

    def start(self, job_id: str, prompt: str, extra_rules: list[str] | None = None) -> dict:
        prompt_rel = f".auctopus/prompts/{job_id}.md"
        self.t.write_text(f"{self.workdir}/{prompt_rel}", self.compose_prompt(prompt, extra_rules))
        self.t.write_text(f"{self.workdir}/.auctopus/prompts/{job_id}.started", iso_now())
        cmd = agent_command(self.rc, self.label, prompt_rel, self.cfg.mock.scenario)
        LOG.info("%s: starting %s agent job %s in %s", self.label, self.rc.agent, job_id, self.workdir)
        return self.t.start_job(job_id, self.workdir, cmd, env_file=self.rc.env_file,
                                path_prepend=self.rc.path_prepend, detach=self.rc.detach,
                                timeout_s=self.rc.job_timeout_h * 3600)

    def wait(self, handle: dict) -> AgentResult:
        deadline = handle.get("started", time.time()) + self.rc.job_timeout_h * 3600
        polls = 0
        lost_streak = 0
        while True:
            status, code = self.t.job_status(handle)
            if status == "done":
                tail = self.t.job_log(handle, 30)
                LOG.info("%s: job %s finished (exit %s)", self.label, handle["job_id"], code)
                return AgentResult(code, "done", tail, handle)
            if status == "lost":
                lost_streak += 1
                if lost_streak >= 3:      # three checks in a row: the process is gone without an exit code
                    tail = self.t.job_log(handle, 60)
                    LOG.error("%s: job %s is gone without an exit code", self.label, handle["job_id"])
                    return AgentResult(None, "lost", tail, handle)
            else:
                lost_streak = 0
            if time.time() > deadline:
                self.t.kill_job(handle)
                tail = self.t.job_log(handle, 60)
                LOG.error("%s: job %s timed out after %.1f h", self.label, handle["job_id"], self.rc.job_timeout_h)
                return AgentResult(None, "timeout", tail, handle)
            polls += 1
            if polls % 20 == 0:
                LOG.info("%s: job %s still running; recent output:\n%s", self.label, handle["job_id"],
                         truncate_middle(self.t.job_log(handle, 8), 1500))
            time.sleep(max(0.1, self.rc.poll_s))

    def round_done(self) -> dict | None:
        """The agent's own completion record, if it left one."""
        import json
        text = self.t.read_text(f"{self.workdir}/ROUND-DONE.json")
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return {"status": "unreadable", "raw": text[:2000]}

    def clear_round_marker(self) -> None:
        """Archive the previous task's ROUND-DONE.json so the next task's marker is unambiguous."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.t.move(f"{self.workdir}/ROUND-DONE.json", f"{self.workdir}/.auctopus/ROUND-DONE.{stamp}.json")


def push_inputs(transport, inputs: list[tuple[Path, str]]) -> None:
    """Push local files or folders (local path, remote path) before a task starts."""
    for local, remote in inputs:
        local = Path(local)
        if local.is_dir():
            transport.push_dir(local, remote)
        elif local.is_file():
            transport.push_file(local, remote)
        else:
            LOG.warning("input missing, not pushed: %s", local)
