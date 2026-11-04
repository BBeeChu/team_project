"""Runs one job for LocalTransport (the dummy remote): python job_wrapper.py <jobdir>.

Reads <jobdir>/run.json ({command, cwd, env}), runs the command through the system shell with stdout/stderr redirected
to stdout.log/stderr.log, and writes the exit code to <jobdir>/exit_code (atomically), mirroring the run.sh that the
SSH transport places on a real remote machine.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    jobdir = Path(sys.argv[1])
    spec = json.loads((jobdir / "run.json").read_text(encoding="utf-8"))
    env = dict(os.environ)
    env.update(spec.get("env") or {})
    with open(jobdir / "stdout.log", "wb") as out, open(jobdir / "stderr.log", "wb") as err:
        try:
            rc = subprocess.run(spec["command"], shell=True, cwd=spec["cwd"], env=env, stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL).returncode
        except Exception as e:  # noqa: BLE001 - report any launch failure as the job's result
            err.write(f"job wrapper: {type(e).__name__}: {e}\n".encode())
            rc = 98
    tmp = jobdir / "exit_code.tmp"
    tmp.write_text(str(rc))
    os.replace(tmp, jobdir / "exit_code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
