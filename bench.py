#!/usr/bin/env python
"""Entry point for the benchmark runs: `python bench.py <command> ...` from the team_project folder.

Equivalent to `python -m auctopus.bench`, except that this folder is removed from sys.path first: the Auctopus
checkout lives in ./auctopus, and from this folder Python would otherwise import that folder as an empty namespace
package instead of the installed `auctopus` package inside it.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:] = [p for p in sys.path if p and Path(p).resolve() != HERE]
if str(HERE / "auctopus") not in sys.path:
    sys.path.insert(0, str(HERE / "auctopus"))

from auctopus.bench.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
