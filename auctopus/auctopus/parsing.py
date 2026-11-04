"""Machine-readable parts of model replies: the dedup KEEP line, the PI's SELECTION and BEST SEED lines, the junk
filter for proposer replies, verdict lines, and files delivered inside a reply as FILE blocks."""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

# ------------------------------------------------------------------------------------------- dedup (KEEP line)

def parse_keep(reply: str, valid: list[str]) -> list[str] | None:
    """The last line that starts with KEEP decides; returns the kept file names in the original order, or None (the
    caller then keeps everything: dedup fails open)."""
    for line in reversed((reply or "").splitlines()):
        if line.strip().lstrip("*#>-• ").upper().startswith("KEEP"):
            kept = set(re.findall(r"proposer-\d+\.md", line)) & set(valid)
            return [v for v in valid if v in kept] or None
    return None


# --------------------------------------------------------------------------------------------- the PI's verdict

NO_SELECTION_RE = re.compile(
    r"no (proposal|proposer|candidate|idea)[^.\n]{0,40}(earns|merits|clears|deserves|is selected|selected)"
    r"|no winner|none (of the|of them|earns|clears|is selected)|\breject(ing)? all\b|would reject all"
    r"|nothing (clears|earns)")
BEST_SEED_RE = re.compile(r"BEST SEED:\s*\**\s*(proposer[-\s]?\d+|none)", re.IGNORECASE)
SELECTION_RE = re.compile(r"^\W*SELECTION\s*:\s*\**\s*(proposer[-\s]?\d+|none)\b", re.IGNORECASE | re.MULTILINE)
SELECT_RE = re.compile(r"\bselect(?:ed|ing)?\s*:?\s*\**\s*(proposer[-\s]?\d+)", re.IGNORECASE)


def _proposer(label: str) -> str:
    return "proposer-" + re.sub(r"\D", "", label)


def pi_selected(verdict: str) -> bool:
    """The last 'SELECTION: proposer-N | none' line decides. A verdict without one selects a proposal unless the
    no-selection pattern appears in its first 1200 characters."""
    hits = SELECTION_RE.findall(verdict or "")
    if hits:
        return hits[-1].strip().lower() != "none"
    return not NO_SELECTION_RE.search((verdict or "")[:1200].lower())


def best_seed(verdict: str) -> str | None:
    """The last 'BEST SEED: proposer-N' line wins; 'none' or no line means no seed. Returns 'proposer-N' or None."""
    hits = BEST_SEED_RE.findall(verdict or "")
    if not hits:
        return None
    last = hits[-1].strip().lower()
    if last == "none":
        return None
    return _proposer(last)


def selected_proposer(verdict: str) -> str | None:
    """Name of the selected proposal: the SELECTION line, else a best-effort 'Select proposer-2: ...'; informational
    only."""
    hits = SELECTION_RE.findall(verdict or "")
    if hits:
        return None if hits[-1].strip().lower() == "none" else _proposer(hits[-1])
    m = SELECT_RE.search((verdict or "")[:1500])
    return _proposer(m.group(1)) if m else None


# ------------------------------------------------------------------------------------------- proposer replies

JUNK_MARKERS = ("message delivery timed out", "please try again", "something went wrong", "network error",
                "you've reached our limit", "an error occurred")


def is_junk_reply(text: str) -> bool:
    """Drop only broken replies; refusals survive and reach dedup and the PI."""
    t = (text or "").strip()
    if len(t) < 400:
        return True
    return len(t) < 600 and any(m in t.lower() for m in JUNK_MARKERS)


def is_proposal(text: str, min_words: int) -> bool:
    """A delivered reply of at least min_words words counts as a proposal (the early-cut counter)."""
    return len((text or "").split()) >= min_words


# ------------------------------------------------------------------------------------------------- verdicts

VERDICT_RE = re.compile(r"^\W*VERDICT\s*[:=]\s*\**\s*([A-Z][A-Z\- ]+?)\b\**\s*$", re.MULTILINE)


def verdict_line(text: str, allowed: tuple[str, ...]) -> str | None:
    """The last 'VERDICT: X' line with X in allowed (case-insensitive); None if there is none."""
    found = None
    for m in VERDICT_RE.finditer(text or ""):
        word = m.group(1).strip().upper().replace(" ", "-")
        for a in allowed:
            if word == a.upper() or word.startswith(a.upper()):
                found = a
                break
    return found


def tagged_line(text: str, tag: str) -> str | None:
    """Value of the last line of the form 'TAG: value' (markdown emphasis tolerated)."""
    pat = re.compile(rf"^\W*{re.escape(tag)}\s*:\s*\**\s*(.+?)\s*\**\s*$", re.MULTILINE | re.IGNORECASE)
    hits = pat.findall(text or "")
    return hits[-1].strip() if hits else None


# ---------------------------------------------------------------------------------------------- file blocks

FILE_PROTOCOL = """
---
How to deliver files in this conversation: there are no attachments or downloads here, so put every file you produce
inside your reply, each one exactly in this form (one block per file, full content, nothing elided):

===== FILE: relative/path/name.ext =====
<the complete file content>
===== END FILE =====

Use paths relative to the paper folder (for example main.tex, references.bib, sections/intro.tex). Files outside such
blocks are not received.
"""

FILE_BLOCK_RE = re.compile(r"^=====\s*FILE:\s*(?P<path>[^\n=]+?)\s*=====\s*\n(?P<body>.*?)^=====\s*END FILE\s*=====\s*$",
                           re.MULTILINE | re.DOTALL)


def safe_relpath(name: str) -> str | None:
    p = PurePosixPath(name.strip().replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts:
        return None
    return p.as_posix()


def extract_files(reply: str) -> dict[str, str]:
    """Files delivered as FILE blocks. Unsafe paths (absolute, '..') are skipped."""
    out: dict[str, str] = {}
    for m in FILE_BLOCK_RE.finditer(reply or ""):
        rel = safe_relpath(m.group("path"))
        if rel:
            out[rel] = m.group("body").rstrip("\n") + "\n"
    return out


def save_files(files: dict[str, str], dest: Path) -> list[Path]:
    written = []
    for rel, body in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        written.append(p)
    return written


def strip_file_blocks(reply: str) -> str:
    """The reply with each FILE block replaced by a one-line note (for compact conversation transcripts)."""
    return FILE_BLOCK_RE.sub(lambda m: f"[file {m.group('path').strip()} delivered]\n", reply or "")
