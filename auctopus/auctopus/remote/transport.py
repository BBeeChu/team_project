"""Reach a remote machine (the HPC, the instrument computer) over SSH, or simulate one with a local folder.

SSHTransport uses the system OpenSSH client, so ~/.ssh/config aliases, ProxyJump, keys and agents all work as they do
in a terminal. Commands go to the remote as a script on stdin (`bash -s`), which is immune to the login shell's quoting
rules; directories travel as tar streams. Dropped connections (exit code 255) are retried with back-off.

LocalTransport ("dummy SSH") maps the remote file system into a local folder and runs jobs with a small Python
wrapper. The pipeline code cannot tell the two apart, which is what makes the offline dry run meaningful.
"""
from __future__ import annotations

import fnmatch
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..config import ConfigError, RemoteCfg, is_placeholder
from ..util import LOG, atomic_write_text


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class RemoteError(RuntimeError):
    pass


def check_remote_path(p: str) -> str:
    if not p or "\n" in p or "\x00" in p or "'" in p:
        raise RemoteError(f"unsafe remote path: {p!r}")
    return p


def bash_quote_path(p: str) -> str:
    """Quote a remote path for bash, keeping a leading ~/ expandable."""
    check_remote_path(p)
    if p == "~":
        return '"$HOME"'
    if p.startswith("~/"):
        return '"$HOME"/' + shlex.quote(p[2:])
    return shlex.quote(p)


def remote_join(*parts: str) -> str:
    out = str(PurePosixPath(*[p for p in parts if p]))
    return check_remote_path(out)


def _excluded(rel: str, patterns: list[str]) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat) for pat in patterns)


def make_tar(local_dir: Path, exclude: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for path in sorted(Path(local_dir).rglob("*")):
            rel = path.relative_to(local_dir).as_posix()
            if any(_excluded("/".join(rel.split("/")[: i + 1]), exclude) for i in range(rel.count("/") + 1)):
                continue
            if path.is_file():
                tf.add(path, arcname=rel, recursive=False)
    return buf.getvalue()


PULL_EXT = {".tex", ".bib", ".bbl", ".pdf", ".md", ".json", ".csv", ".txt", ".png", ".svg", ".sty", ".bst", ".cls",
            ".zip", ".py", ".yaml", ".yml", ".toml", ".tsv", ".log"}
PULL_NAMES = {"Makefile", "README", "LICENSE"}
PRIORITY_RE = ("main.pdf", "main.tex", "manuscript", "paper", "report", "audit", "response", "round-done",
               "notes-resume", "run-result", "deviations", "protocol", "results_schema", "delivery", "manifest")


def select_for_pull(entries: list[tuple[str, int]], exclude: list[str], max_file_mb: float = 20.0,
                    max_total_mb: float = 200.0, per_family: int = 40,
                    include_all: bool = False) -> tuple[list[str], list[str]]:
    """Choose which remote files come back after a round: documents and results with size caps, so a round never
    drags gigabytes of raw data back. Returns (selected, skipped)."""
    keep: list[tuple[tuple, str, int]] = []
    skipped: list[str] = []
    families: dict[tuple[str, str], int] = {}
    for rel, size in entries:
        parts = rel.split("/")
        if any(_excluded("/".join(parts[: i + 1]), exclude) for i in range(len(parts))):
            continue
        name = parts[-1]
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if not include_all and ext not in PULL_EXT and name not in PULL_NAMES:
            continue
        if not include_all and size > max_file_mb * 1024 * 1024:
            skipped.append(f"{rel} ({size / 1048576:.1f} MB, over the {max_file_mb:.0f} MB per-file cap)")
            continue
        fam = ("/".join(parts[:-1]), ext)
        families[fam] = families.get(fam, 0) + 1
        if not include_all and families[fam] > per_family and len(parts) > 1:
            skipped.append(f"{rel} (more than {per_family} {ext or 'plain'} files in {fam[0]})")
            continue
        low = name.lower()
        prio = next((i for i, key in enumerate(PRIORITY_RE) if key in low), len(PRIORITY_RE))
        keep.append(((len(parts) > 1, prio, size), rel, size))
    keep.sort()
    selected, total = [], 0
    for _, rel, size in keep:
        if total + size > max_total_mb * 1024 * 1024:
            skipped.append(f"{rel} (total pull cap of {max_total_mb:.0f} MB reached)")
            continue
        total += size
        selected.append(rel)
    return selected, skipped


def tar_single(path: Path, arcname: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        tf.add(path, arcname=arcname, recursive=False)
    return buf.getvalue()


def extract_tar(data: bytes, local_dir: Path) -> int:
    local_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        members = [m for m in tf.getmembers() if m.isfile() or m.isdir()]
        tf.extractall(local_dir, members=members, filter="data")   # 'data' filter blocks absolute and ../ paths
        n = sum(1 for m in members if m.isfile())
    return n


# ================================================================================================= SSH (real)

class SSHTransport:
    kind = "ssh"

    def __init__(self, cfg: RemoteCfg, label: str):
        if is_placeholder(cfg.host):
            raise ConfigError(f"{label}.host is a placeholder: fill it in config.toml (or use transport='local' for a "
                              f"dry run)")
        self.cfg = cfg
        self.label = label
        self.root = cfg.remote_root

    # ---------------------------------------------------------------- plumbing
    def _target(self) -> str:
        return self.cfg.host if is_placeholder(self.cfg.user) else f"{self.cfg.user}@{self.cfg.host}"

    def ssh_argv(self, remote_command: str) -> list[str]:
        binary = self.cfg.ssh_binary
        base = [binary] if isinstance(binary, str) else list(binary)   # a list allows a wrapper (tests, jump scripts)
        argv = base + ["-p", str(self.cfg.port),
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={self.cfg.connect_timeout_s}",
                "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=6",
                "-o", "StrictHostKeyChecking=accept-new"]
        if not is_placeholder(self.cfg.identity_file):
            argv += ["-i", os.path.expanduser(self.cfg.identity_file)]
        argv += list(self.cfg.ssh_options)
        argv += [self._target(), remote_command]
        return argv

    def _exec(self, remote_command: str, stdin: bytes | None, timeout: float) -> subprocess.CompletedProcess:
        delays = [5, 15, 30, 60, 120]
        attempt = 0
        while True:
            try:
                proc = subprocess.run(self.ssh_argv(remote_command), input=stdin, capture_output=True,
                                      timeout=timeout)
            except subprocess.TimeoutExpired as e:
                raise RemoteError(f"{self.label}: ssh command timed out after {timeout:.0f} s") from e
            except FileNotFoundError as e:
                raise RemoteError(f"{self.label}: ssh client '{self.cfg.ssh_binary}' not found") from e
            if proc.returncode != 255 or attempt >= self.cfg.retries:
                return proc
            delay = delays[min(attempt, len(delays) - 1)]
            LOG.warning("%s: ssh connection failed (%s); retry %d/%d in %d s", self.label,
                        proc.stderr.decode(errors="replace").strip()[-200:], attempt + 1, self.cfg.retries, delay)
            time.sleep(delay)
            attempt += 1

    # ------------------------------------------------------------------ public
    def resolve(self, rel: str) -> str:
        if rel.startswith("/") or rel.startswith("~"):
            return check_remote_path(rel)
        return remote_join(self.root, rel)

    def run(self, script: str, *, timeout: float = 600, check: bool = True) -> CmdResult:
        """Run a bash script on the remote (sent on stdin, so no quoting problems with the login shell)."""
        proc = self._exec("bash -s", ("set -o pipefail\n" + script + "\n").encode(), timeout)
        res = CmdResult(proc.returncode, proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace"))
        if check and not res.ok:
            raise RemoteError(f"{self.label}: remote command failed ({res.returncode}): "
                              f"{res.stderr.strip()[-500:] or res.stdout.strip()[-500:]}")
        return res

    def mkdirs(self, rdir: str) -> None:
        self.run(f"mkdir -p {bash_quote_path(rdir)}", timeout=120)

    def write_text(self, rpath: str, text: str, private: bool = False) -> None:
        q = bash_quote_path(rpath)
        parent = bash_quote_path(str(PurePosixPath(rpath).parent))
        marker = "AUCTOPUS_EOF_7f3a"
        if marker in text:
            raise RemoteError("text contains the heredoc marker")
        umask = "umask 077\n" if private else ""
        self.run(f"{umask}mkdir -p {parent}\ncat > {q} <<'{marker}'\n{text}\n{marker}\n", timeout=300)

    def read_text(self, rpath: str) -> str | None:
        q = bash_quote_path(rpath)
        res = self.run(f"if [ -f {q} ]; then cat {q}; else echo '__AUCTOPUS_MISSING__'; fi", timeout=300)
        return None if res.stdout.strip() == "__AUCTOPUS_MISSING__" else res.stdout

    def exists(self, rpath: str) -> bool:
        q = bash_quote_path(rpath)
        return self.run(f"[ -e {q} ] && echo yes || echo no", timeout=120).stdout.strip() == "yes"

    def push_dir(self, local_dir: Path, rdir: str, exclude: list[str] | None = None) -> None:
        self._push_tar(make_tar(Path(local_dir), exclude or []), rdir)

    def push_file(self, local_file: Path, rpath: str) -> None:
        self._push_tar(tar_single(Path(local_file), PurePosixPath(rpath).name), str(PurePosixPath(rpath).parent))

    def _push_tar(self, data: bytes, rdir: str) -> None:
        q = bash_quote_path(rdir)
        proc = self._exec(f"bash -c {shlex.quote(f'mkdir -p {q} && tar -xf - -C {q}')}", data, timeout=3600)
        if proc.returncode != 0:
            raise RemoteError(f"{self.label}: push to {rdir} failed: {proc.stderr.decode(errors='replace')[-500:]}")

    def move(self, src: str, dst: str) -> None:
        d = bash_quote_path(str(PurePosixPath(dst).parent))
        self.run(f"mkdir -p {d} && if [ -e {bash_quote_path(src)} ]; then mv -f {bash_quote_path(src)} "
                 f"{bash_quote_path(dst)}; fi", timeout=120)

    def pull_dir(self, rdir: str, local_dir: Path, exclude: list[str] | None = None,
                 max_mb: float = 200.0, include_all: bool = False) -> int:
        q = bash_quote_path(rdir)
        listing = self.run(f"cd {q} && find . -type f -printf '%s\\t%P\\n'", timeout=600).stdout
        entries = []
        for line in listing.splitlines():
            size, _, rel = line.partition("\t")
            if rel and size.isdigit():
                entries.append((rel, int(size)))
        selected, skipped = select_for_pull(entries, list(exclude or []) + [".auctopus"], max_total_mb=max_mb,
                                            include_all=include_all)
        n = 0
        if selected:
            proc = self._exec(f"bash -c {shlex.quote(f'cd {q} && tar -cf - -T -')}",
                              ("\n".join(selected) + "\n").encode(), timeout=3600)
            if proc.returncode != 0:
                raise RemoteError(f"{self.label}: pull of {rdir} failed: "
                                  f"{proc.stderr.decode(errors='replace')[-500:]}")
            n = extract_tar(proc.stdout, Path(local_dir))
        _note_skipped(Path(local_dir), skipped)
        return n

    # -------------------------------------------------------------------- jobs
    def start_job(self, job_id: str, workdir: str, command: str, env_file: str = "",
                  path_prepend: str = "", detach: bool = True, timeout_s: float = 86400) -> dict:
        jobdir = remote_join(workdir, ".auctopus", "jobs", job_id)
        wq, jq = bash_quote_path(workdir), bash_quote_path(jobdir)
        env_line = ""
        if env_file:
            eq = bash_quote_path(env_file)
            env_line = f"if [ -f {eq} ]; then . {eq}; fi\n"
        path_line = f'export PATH="{path_prepend}:$PATH"\n' if path_prepend else ""
        script = (f"#!/usr/bin/env bash\ncd {wq} || exit 97\n{env_line}{path_line}"
                  f"( {command} ) > {jq}/stdout.log 2> {jq}/stderr.log < /dev/null\n"
                  f"rc=$?\necho \"$rc\" > {jq}/exit_code.tmp && mv {jq}/exit_code.tmp {jq}/exit_code\n")
        self.write_text(f"{jobdir}/run.sh", script)
        handle = {"transport": "ssh", "job_id": job_id, "workdir": workdir, "jobdir": jobdir,
                  "started": time.time(), "detach": detach}
        # Idempotent launch: job ids are unique, and a 'started' marker means a retried launch (after a dropped SSH
        # connection) never starts the same job twice.
        if detach:
            self.run(f"cd {jq} || exit 1\nif [ -f started ]; then echo ALREADY_STARTED; exit 0; fi\ntouch started\n"
                     f"if command -v setsid >/dev/null; then setsid nohup bash run.sh > /dev/null 2>&1 < /dev/null & "
                     f"else nohup bash run.sh > /dev/null 2>&1 < /dev/null & fi\necho $! > pid\n", timeout=120)
        else:
            # hold the session open for the whole job (any shell; fragile for very long jobs)
            self.run(f"cd {jq} && touch started", timeout=120)
            self._exec(f"bash {jq}/run.sh", None, timeout=timeout_s)
        return handle

    def job_status(self, handle: dict) -> tuple[str, int | None]:
        jq = bash_quote_path(handle["jobdir"])
        out = self.run(f"if [ -f {jq}/exit_code ]; then echo DONE $(cat {jq}/exit_code); "
                       f"elif [ -f {jq}/pid ] && kill -0 $(cat {jq}/pid) 2>/dev/null; then echo RUNNING; "
                       f"else echo LOST; fi", timeout=120).stdout.split()
        if out and out[0] == "DONE":
            return "done", int(out[1]) if len(out) > 1 and out[1].lstrip("-").isdigit() else None
        return ("running", None) if out and out[0] == "RUNNING" else ("lost", None)

    def job_log(self, handle: dict, tail_lines: int = 40) -> str:
        jq = bash_quote_path(handle["jobdir"])
        res = self.run(f"tail -n {int(tail_lines)} {jq}/stdout.log 2>/dev/null; echo '--- stderr ---'; "
                       f"tail -n {int(tail_lines)} {jq}/stderr.log 2>/dev/null", timeout=120, check=False)
        return res.stdout

    def kill_job(self, handle: dict) -> None:
        jq = bash_quote_path(handle["jobdir"])
        self.run(f"if [ -f {jq}/pid ]; then p=$(cat {jq}/pid); kill -TERM -- -$p 2>/dev/null || kill -TERM $p "
                 f"2>/dev/null; fi; true", timeout=120, check=False)


# ===================================================================================== Local folder (dummy SSH)

class LocalTransport:
    """A local folder plays the remote machine. Used for the dry run and the tests (no network, no keys)."""
    kind = "local"

    def __init__(self, cfg: RemoteCfg, label: str):
        if not cfg.local_root:
            raise ConfigError(f"{label}.local_root must be set for transport 'local'")
        self.cfg = cfg
        self.label = label
        self.base = Path(cfg.local_root).resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = cfg.remote_root or "work"

    def _p(self, rpath: str) -> Path:
        check_remote_path(rpath)
        rel = rpath
        if rel.startswith("~/"):
            rel = "home/" + rel[2:]
        elif rel == "~":
            rel = "home"
        rel = rel.lstrip("/")
        p = (self.base / rel).resolve()
        if p != self.base and self.base not in p.parents:
            raise RemoteError(f"path escapes the local remote root: {rpath}")
        return p

    def resolve(self, rel: str) -> str:
        if rel.startswith("/") or rel.startswith("~"):
            return check_remote_path(rel)
        return remote_join(self.root, rel)

    def run(self, script: str, *, timeout: float = 600, check: bool = True) -> CmdResult:
        proc = subprocess.run(script, shell=True, cwd=self.base, capture_output=True, text=True, timeout=timeout)
        res = CmdResult(proc.returncode, proc.stdout, proc.stderr)
        if check and not res.ok:
            raise RemoteError(f"{self.label}: local command failed ({res.returncode}): {res.stderr[-500:]}")
        return res

    def mkdirs(self, rdir: str) -> None:
        self._p(rdir).mkdir(parents=True, exist_ok=True)

    def write_text(self, rpath: str, text: str, private: bool = False) -> None:
        atomic_write_text(self._p(rpath), text)

    def read_text(self, rpath: str) -> str | None:
        p = self._p(rpath)
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def exists(self, rpath: str) -> bool:
        return self._p(rpath).exists()

    def push_dir(self, local_dir: Path, rdir: str, exclude: list[str] | None = None) -> None:
        extract_tar(make_tar(Path(local_dir), exclude or []), self._p(rdir))

    def push_file(self, local_file: Path, rpath: str) -> None:
        dst = self._p(rpath)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_file, dst)

    def move(self, src: str, dst: str) -> None:
        s, d = self._p(src), self._p(dst)
        if s.exists():
            d.parent.mkdir(parents=True, exist_ok=True)
            s.replace(d)

    def pull_dir(self, rdir: str, local_dir: Path, exclude: list[str] | None = None,
                 max_mb: float = 200.0, include_all: bool = False) -> int:
        src = self._p(rdir)
        if not src.is_dir():
            raise RemoteError(f"{self.label}: {rdir} does not exist")
        entries = [(p.relative_to(src).as_posix(), p.stat().st_size) for p in src.rglob("*") if p.is_file()]
        selected, skipped = select_for_pull(entries, list(exclude or []) + [".auctopus"], max_total_mb=max_mb,
                                            include_all=include_all)
        dest = Path(local_dir)
        for rel in selected:
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src / rel, target)
        _note_skipped(dest, skipped)
        return len(selected)

    def start_job(self, job_id: str, workdir: str, command: str, env_file: str = "",
                  path_prepend: str = "", detach: bool = True, timeout_s: float = 86400) -> dict:
        wdir = self._p(workdir)
        jobdir = wdir / ".auctopus" / "jobs" / job_id
        jobdir.mkdir(parents=True, exist_ok=True)
        for f in ("exit_code", "pid"):
            (jobdir / f).unlink(missing_ok=True)
        env = {"AUCTOPUS_REMOTE_ROOT": str(self.base)}
        pkg_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = pkg_root + os.pathsep + os.environ.get("PYTHONPATH", "")
        atomic_write_text(jobdir / "run.json", json.dumps({"command": command, "cwd": str(wdir), "env": env}))
        wrapper = Path(__file__).with_name("job_wrapper.py")
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen([sys.executable, str(wrapper), str(jobdir)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        _CHILDREN.append(proc)                  # keep a reference: the job outlives this call by design
        (jobdir / "pid").write_text(str(proc.pid))
        if not detach:
            proc.wait(timeout=timeout_s)
        return {"transport": "local", "job_id": job_id, "workdir": workdir,
                "jobdir": str(jobdir), "started": time.time(), "detach": detach}

    def job_status(self, handle: dict) -> tuple[str, int | None]:
        _reap()
        jobdir = Path(handle["jobdir"])
        ec = jobdir / "exit_code"
        if ec.exists():
            txt = ec.read_text().strip()
            return "done", int(txt) if txt.lstrip("-").isdigit() else None
        pid_file = jobdir / "pid"
        if pid_file.exists() and _pid_alive(int(pid_file.read_text().strip() or 0)):
            return "running", None
        # the wrapper may have finished between the two checks
        if ec.exists():
            return self.job_status(handle)
        return "lost", None

    def job_log(self, handle: dict, tail_lines: int = 40) -> str:
        jobdir = Path(handle["jobdir"])
        out = []
        for name in ("stdout.log", "stderr.log"):
            p = jobdir / name
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_lines:] if p.exists() else []
            out.append("\n".join(lines))
        return out[0] + "\n--- stderr ---\n" + out[1]

    def kill_job(self, handle: dict) -> None:
        pid_file = Path(handle["jobdir"]) / "pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(pid, 15)
            except (OSError, ValueError):
                pass


_CHILDREN: list[subprocess.Popen] = []


def _reap() -> None:
    """Collect finished job wrappers (they are detached on purpose; this only releases their handles)."""
    for p in list(_CHILDREN):
        if p.poll() is not None:
            _CHILDREN.remove(p)


def _note_skipped(local_dir: Path, skipped: list[str]) -> None:
    if skipped:
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "PULL-SKIPPED.txt").write_text(
            "Files left on the remote machine by the pull caps:\n" + "\n".join(skipped) + "\n", encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def make_transport(cfg: RemoteCfg, label: str):
    if cfg.transport == "ssh":
        return SSHTransport(cfg, label)
    if cfg.transport == "local":
        return LocalTransport(cfg, label)
    raise ConfigError(f"{label}.transport {cfg.transport!r} has no SSH transport (manual exchange is handled by the "
                      f"lab stage)")
