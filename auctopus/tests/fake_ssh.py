"""A stand-in for the `ssh` client, for tests: runs the remote command locally with bash.

Accepts the same arguments the SSH transport passes (-p PORT, -o OPT, -i KEY, -J HOST, target, command) and executes
the command with bash, passing stdin and stdout through, so the SSH transport's real code path (scripts on stdin, tar
streams, detached jobs, exit codes) runs end to end without a network. FAKE_SSH_FAIL_FILE names a counter file: while
it holds a positive number, each call decrements it and fails with exit code 255 (a dropped connection).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

WITH_VALUE = {"-p", "-o", "-i", "-J", "-l", "-F", "-L", "-R", "-D", "-E", "-S", "-W", "-b", "-c", "-m"}


def main() -> int:
    args = sys.argv[1:]
    fail_file = os.environ.get("FAKE_SSH_FAIL_FILE")
    if fail_file and Path(fail_file).exists():
        left = int(Path(fail_file).read_text().strip() or 0)
        if left > 0:
            Path(fail_file).write_text(str(left - 1))
            sys.stderr.write("ssh: connect to host fake: Connection reset (simulated)\n")
            return 255
    i = 0
    positional = []
    while i < len(args):
        a = args[i]
        if a in WITH_VALUE:
            i += 2
            continue
        if a.startswith("-") and not positional:
            i += 1
            continue
        positional.append(a)
        i += 1
    if len(positional) < 2:
        sys.stderr.write("fake ssh: need a target and a command\n")
        return 255
    command = positional[1]
    bash = os.environ.get("FAKE_SSH_BASH") or shutil.which("bash")
    proc = subprocess.run([bash, "-c", command], stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                          stderr=sys.stderr.buffer)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
