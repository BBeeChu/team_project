"""Small shared helpers: logging, atomic file writes, JSON state, time stamps, word counts."""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

LOG = logging.getLogger("auctopus")


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    """Log to stderr (and optionally to a file). Replies and results never go through the logger."""
    root = logging.getLogger("auctopus")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for h in list(root.handlers):
        root.removeHandler(h)
        if isinstance(h, logging.FileHandler):
            h.close()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(fmt)
    root.addHandler(h)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        root.addHandler(fh)


def now_stamp() -> str:
    """Run-folder style time stamp, e.g. 20261020-213045."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def atomic_write_text(path: Path, text: str) -> None:
    """Write text so that a crash never leaves a half-written file (write to a temp file, then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(Path(path), json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-").lower()
    return (s[:max_len].rstrip("-")) or "run"


def sleep_with_log(seconds: float, why: str) -> None:
    if seconds > 0:
        LOG.info("waiting %.0f s (%s)", seconds, why)
        time.sleep(seconds)


def truncate_middle(text: str, limit: int) -> str:
    """Keep the head and tail of a long text (for logs and prompts that quote command output)."""
    if len(text) <= limit:
        return text
    half = max(limit // 2 - 20, 0)
    return text[:half] + f"\n... [{len(text) - 2 * half} characters omitted] ...\n" + text[-half:]
