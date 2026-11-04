import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from auctopus.config import ConfigError, LabCfg, RemoteCfg
from auctopus.remote.transport import (LocalTransport, SSHTransport, bash_quote_path, select_for_pull)

from helpers import TempDirMixin

HERE = Path(__file__).resolve().parent


def wait_done(t, handle, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        status, code = t.job_status(handle)
        if status == "done":
            return code
        time.sleep(0.3)
    raise AssertionError("job did not finish")


class Selection(unittest.TestCase):
    def test_include_list_caps_and_priority(self):
        entries = [("main.pdf", 1000), ("data/raw.npz", 10), ("big.zip", 30 * 2**20), ("notes.md", 5),
                   (".auctopus/jobs/x/stdout.log", 5), (".git/HEAD", 5)] + \
                  [(f"figs/f{i}.png", 10) for i in range(50)]
        sel, skipped = select_for_pull(entries, [".git", ".auctopus"])
        self.assertEqual(sel[0], "main.pdf")
        self.assertNotIn("data/raw.npz", sel)
        self.assertNotIn("big.zip", sel)
        self.assertEqual(sum(1 for s in sel if s.startswith("figs/")), 40)
        self.assertTrue(any("big.zip" in s for s in skipped))
        sel_all, _ = select_for_pull(entries, [".git", ".auctopus"], include_all=True)
        self.assertIn("data/raw.npz", sel_all)


class Local(TempDirMixin, unittest.TestCase):
    def make(self):
        return LocalTransport(RemoteCfg(transport="local", local_root=str(self.tmp / "remote"), remote_root="work"),
                              "hpc")

    def test_files_and_dirs(self):
        t = self.make()
        t.write_text("work/a/b.txt", "hello")
        self.assertEqual(t.read_text("work/a/b.txt"), "hello")
        self.assertIsNone(t.read_text("work/none.txt"))
        self.assertTrue(t.exists("work/a"))
        t.move("work/a/b.txt", "work/c/d.txt")
        self.assertFalse(t.exists("work/a/b.txt"))
        src = self.tmp / "src"
        (src / "sub").mkdir(parents=True)
        (src / "main.tex").write_text("x")
        (src / "sub" / "r.csv").write_text("1,2")
        (src / "w.bin").write_bytes(b"\x00\x01")
        t.push_dir(src, "work/pkg")
        n = t.pull_dir("work/pkg", self.tmp / "back")
        self.assertEqual(n, 2)                                  # w.bin is not on the include list
        self.assertTrue((self.tmp / "back" / "sub" / "r.csv").exists())
        t.pull_dir("work/pkg", self.tmp / "all", include_all=True)
        self.assertTrue((self.tmp / "all" / "w.bin").exists())

    def test_paths_cannot_escape(self):
        t = self.make()
        with self.assertRaises(Exception):
            t.write_text("../outside.txt", "x")

    def test_detached_job(self):
        t = self.make()
        t.mkdirs("work/job")
        cmd = f'"{sys.executable}" -c "import sys; print(\'out\'); sys.exit(3)"'
        h = t.start_job("j1", "work/job", cmd)
        self.assertEqual(wait_done(t, h), 3)
        self.assertIn("out", t.job_log(h))


class SSHCommandLine(unittest.TestCase):
    def test_placeholder_host_refused(self):
        with self.assertRaises(ConfigError):
            SSHTransport(RemoteCfg(), "hpc")

    def test_argv(self):
        t = SSHTransport(RemoteCfg(host="cluster-alias", user="insert username here", port=2222), "hpc")
        argv = t.ssh_argv("bash -s")
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertNotIn("-i", argv)                              # identity placeholder: use agent / ssh config
        self.assertEqual(argv[-2:], ["cluster-alias", "bash -s"])  # no user: the ~/.ssh/config alias decides
        t2 = SSHTransport(RemoteCfg(host="h.example.org", user="me", identity_file="~/.ssh/id_ed25519",
                                    ssh_options=["-J", "gw"]), "lab")
        argv2 = t2.ssh_argv("x")
        self.assertIn("me@h.example.org", argv2)
        self.assertIn("-J", argv2)
        self.assertEqual(argv2[argv2.index("-i") + 1], os.path.expanduser("~/.ssh/id_ed25519"))

    def test_quoting(self):
        self.assertEqual(bash_quote_path("~/a b"), "\"$HOME\"/'a b'")
        with self.assertRaises(Exception):
            bash_quote_path("bad'path")


def _bash_flavour():
    bash = shutil.which("bash")
    if not bash:
        return None, None
    try:
        out = subprocess.run([bash, "-c", "uname -s"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, None
    return bash, out


def _posix(path: Path, flavour: str) -> str:
    p = path.resolve().as_posix()
    if flavour.startswith(("MINGW", "MSYS", "CYGWIN")) and p[1:3] == ":/":
        return "/" + p[0].lower() + p[2:]
    if flavour == "Linux" and os.name == "nt" and p[1:3] == ":/":
        return "/mnt/" + p[0].lower() + p[2:]
    return p


@unittest.skipUnless(_bash_flavour()[0], "bash is not available")
class SSHThroughFakeClient(TempDirMixin, unittest.TestCase):
    """The real SSH transport, with `ssh` replaced by a local fake that runs commands with bash."""

    def make(self, retries=3):
        bash, flavour = _bash_flavour()
        root = self.tmp / "remote"
        root.mkdir()
        cfg = RemoteCfg(host="fake-host", user="tester", ssh_binary=[sys.executable, str(HERE / "fake_ssh.py")],
                        remote_root=_posix(root, flavour), retries=retries)
        os.environ["FAKE_SSH_BASH"] = bash
        return SSHTransport(cfg, "hpc"), root

    def test_scripts_files_and_tar(self):
        t, root = self.make()
        self.assertIn("ok", t.run("echo ok").stdout)
        t.write_text(f"{t.root}/sub/hello.txt", "héllo 'quoted' $HOME")
        self.assertEqual(t.read_text(f"{t.root}/sub/hello.txt").strip(), "héllo 'quoted' $HOME")
        src = self.tmp / "pkg"
        src.mkdir()
        (src / "main.tex").write_text("\\documentclass{article}")
        (src / "raw.npz").write_bytes(b"\x01\x02")
        t.push_dir(src, f"{t.root}/pkg")
        self.assertTrue(t.exists(f"{t.root}/pkg/raw.npz"))
        back = self.tmp / "back"
        self.assertEqual(t.pull_dir(f"{t.root}/pkg", back), 1)
        self.assertTrue((back / "main.tex").exists())

    def test_detached_job_and_idempotent_start(self):
        t, root = self.make()
        t.mkdirs(f"{t.root}/w")
        h = t.start_job("job1", f"{t.root}/w", "echo started; sleep 1; echo finished; exit 4")
        self.assertEqual(wait_done(t, h, timeout=90), 4)
        self.assertIn("finished", t.job_log(h))
        h2 = t.start_job("job1", f"{t.root}/w", "echo SHOULD-NOT-RUN")   # same id: never started twice
        time.sleep(1)
        self.assertNotIn("SHOULD-NOT-RUN", t.job_log(h2))

    def test_dropped_connection_is_retried(self):
        t, root = self.make(retries=2)
        fail = self.tmp / "fail-count"
        fail.write_text("1")
        os.environ["FAKE_SSH_FAIL_FILE"] = str(fail)
        try:
            import auctopus.remote.transport as tr
            orig = tr.time.sleep
            tr.time.sleep = lambda s: None                        # skip the back-off wait
            try:
                self.assertIn("ok", t.run("echo ok").stdout)
            finally:
                tr.time.sleep = orig
        finally:
            os.environ.pop("FAKE_SSH_FAIL_FILE", None)
        self.assertEqual(fail.read_text(), "0")


class LabConfigDefaults(unittest.TestCase):
    def test_lab_defaults(self):
        lab = LabCfg()
        self.assertEqual(lab.agent, "claude")
        self.assertTrue(lab.require_approval)
        self.assertGreater(lab.max_pull_mb, RemoteCfg().max_pull_mb)


if __name__ == "__main__":
    unittest.main()
