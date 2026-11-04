"""File attachments for model calls.

A message's content is either a string or a list of provider-neutral parts:
    {"type": "text", "text": "..."}
    {"type": "file", "path": "<absolute path>", "name": "<shown name>", "kind": "pdf" | "image"}
Text files are inlined as text parts when the message is built. PDFs and images stay as file parts (paths, so the saved
conversation stays small) and each client turns them into its own binary content blocks when it sends the request.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from .util import LOG

PDF_EXT = {".pdf"}
IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp"}
TEXT_EXT = {".md", ".txt", ".tex", ".bib", ".json", ".csv", ".py", ".yaml", ".yml", ".toml", ".log", ".sty", ".bst",
            ".cls", ".bbl", ".tsv"}
MAX_TEXT_CHARS = 400_000     # per inlined text file; longer files are cut in the middle with a marker


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in PDF_EXT:
        return "pdf"
    if ext in IMAGE_EXT:
        return "image"
    if ext in TEXT_EXT or path.name in ("Makefile", "README"):
        return "text"
    return None


def inline_text_file(path: Path, name: str | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_TEXT_CHARS:
        half = MAX_TEXT_CHARS // 2
        text = text[:half] + f"\n[... {len(text) - 2 * half} characters omitted ...]\n" + text[-half:]
    shown = name or path.name
    return f"----- attached file: {shown} -----\n{text}\n----- end of attached file: {shown} -----"


def build_content(prompt: str, files: list[Path] | None = None, names: list[str] | None = None,
                  note: str | None = None, max_mb: float = 18.0) -> str | list[dict]:
    """The prompt plus attached files, as one message content. Returns a plain string if every file is text."""
    files = [Path(f) for f in (files or [])]
    if not files:
        return prompt
    names = names or [f.name for f in files]
    parts: list[dict] = [{"type": "text", "text": prompt + (("\n\n" + note) if note else "")}]
    total = 0
    for f, shown in zip(files, names):
        if not f.is_file():
            LOG.warning("attachment missing, skipped: %s", f)
            continue
        size = f.stat().st_size
        k = kind_of(f)
        if k is None:
            LOG.warning("attachment type not supported, skipped: %s", f.name)
            continue
        if total + size > max_mb * 1024 * 1024:
            LOG.warning("attachment budget (%.0f MB) reached; skipped %s", max_mb, f.name)
            continue
        total += size
        if k == "text":
            parts.append({"type": "text", "text": inline_text_file(f, shown)})
        else:
            parts.append({"type": "file", "path": str(f.resolve()), "name": shown, "kind": k})
    if all(p["type"] == "text" for p in parts):
        return "\n\n".join(p["text"] for p in parts)
    return parts


def _b64(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")


def to_openai_content(content: str | list[dict], role: str) -> str | list[dict]:
    """Responses API input content. Assistant turns are plain text."""
    if isinstance(content, str) or role != "user":
        return content if isinstance(content, str) else "\n\n".join(p.get("text", "") for p in content)
    out: list[dict] = []
    for p in content:
        if p["type"] == "text":
            out.append({"type": "input_text", "text": p["text"]})
        elif p["kind"] == "pdf":
            out.append({"type": "input_file", "filename": p["name"],
                        "file_data": "data:application/pdf;base64," + _b64(p["path"])})
        elif p["kind"] == "image":
            mime = IMAGE_EXT.get(Path(p["path"]).suffix.lower(), "image/png")
            out.append({"type": "input_text", "text": f"(image: {p['name']})"})
            out.append({"type": "input_image", "image_url": f"data:{mime};base64," + _b64(p["path"])})
    return out


def to_anthropic_content(content: str | list[dict], role: str) -> str | list[dict]:
    """Messages API content. Documents and images go before the text that refers to them."""
    if isinstance(content, str) or role != "user":
        return content if isinstance(content, str) else "\n\n".join(p.get("text", "") for p in content)
    files: list[dict] = []
    texts: list[dict] = []
    for p in content:
        if p["type"] == "text":
            texts.append({"type": "text", "text": p["text"]})
        elif p["kind"] == "pdf":
            files.append({"type": "document", "title": p["name"],
                          "source": {"type": "base64", "media_type": "application/pdf", "data": _b64(p["path"])}})
        elif p["kind"] == "image":
            mime = IMAGE_EXT.get(Path(p["path"]).suffix.lower(), "image/png")
            files.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": _b64(p["path"])}})
    return files + texts


INLINE_RE = re.compile(r"----- attached file: (?P<n>.+?) -----\n.*?\n----- end of attached file: (?P=n) -----",
                       re.DOTALL)


def strip_attachments(content: str | list[dict]) -> str | list[dict]:
    """The same turn with its attachments replaced by short notes. Used for the older turns of a long conversation,
    so each request carries only the current attachments (the replies keep what the model concluded from them)."""
    note = r"[attached file \g<n>: sent with this earlier turn, not repeated]"
    if isinstance(content, str):
        return INLINE_RE.sub(note, content)
    out = []
    for p in content:
        if p["type"] == "text":
            out.append({"type": "text", "text": INLINE_RE.sub(note, p["text"])})
        else:
            out.append({"type": "text", "text": f"[attached {p['kind']} {p['name']}: sent with this earlier turn, "
                                                f"not repeated]"})
    return "\n\n".join(p["text"] for p in out)


def content_text(content: str | list[dict]) -> str:
    """Plain-text view of a content (for the mock model, logs and size accounting)."""
    if isinstance(content, str):
        return content
    out = []
    for p in content:
        out.append(p["text"] if p["type"] == "text" else f"[attached {p['kind']}: {p['name']}]")
    return "\n\n".join(out)
