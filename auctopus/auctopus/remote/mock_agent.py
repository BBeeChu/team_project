"""Offline stand-in for the remote agents (codex on the HPC, Claude Code on the instrument computer).

Run in the agent's working folder by the job runner, exactly where the real agent would run:
    auctopus.remote.mock_agent --role hpc|lab --prompt <prompt file> --scenario <name>
It writes the files the real agent is asked to produce (manuscript, PDF, lab packet, figures, RUN-RESULT.json, ...)
and finishes with ROUND-DONE.json, so every pipeline stage downstream has real files to handle. What it produces
depends on the task's job name (the prompt file is .auctopus/prompts/<job id>.md), never on the prompt's wording.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path


def tiny_png(width: int = 1200, height: int = 600) -> bytes:
    """A valid grayscale PNG (white page with a dark diagonal) without any imaging library."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        row = bytearray([255]) * width
        x = int(y * width / height)
        for dx in range(-2, 3):
            if 0 <= x + dx < width:
                row[x + dx] = 40
        rows += row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + \
        chunk(b"IEND", b"")


def tiny_pdf(title: str) -> bytes:
    """A valid one-page PDF with one line of text."""
    text = title.replace("(", "[").replace(")", "]")[:80]
    stream = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def task_key(job_id: str) -> str:
    """The pipeline step of an HPC job: job ids are '<step>-<round>-<timestamp>[-r<restart>]',
    e.g. 'lab-packet-4-20261029T101500' or 'verify-1-20261029T101500-r1'."""
    return re.sub(r"-\d+-\d{8}T\d{6}(-r\d+)?$", "", job_id)


def hpc(key: str, here: Path) -> list[str]:
    made: list[str] = []
    tex = here / "main.tex"
    if not tex.exists():
        tex.write_text("\\documentclass{article}\n\\begin{document}\nMock manuscript.\n\\end{document}\n",
                       encoding="utf-8")
    body = tex.read_text(encoding="utf-8")
    if key == "lab-packet":
        lp = here / "lab_packet"
        (lp / "analysis").mkdir(parents=True, exist_ok=True)
        (lp / "twin").mkdir(parents=True, exist_ok=True)
        (lp / "README.md").write_text("# Run packet\n\nprotocol.md, results_schema.md, analysis/, twin/\n")
        (lp / "protocol.md").write_text("1. Calibrate counts and the pi pulse.\n2. Run every sequence.\n"
                                        "3. Thresholds: S/SE > 3.09.\n")
        (lp / "results_schema.md").write_text("- data/run.log: text log\n- data/sweep.csv: counts per sequence\n")
        (lp / "analysis" / "analyze.py").write_text("print('decision quantity')\n")
        (lp / "twin" / "report.md").write_text("Twin: the protocol reaches its thresholds in 8 hours.\n")
        (lp / "completion_manifest.json").write_text(json.dumps({"complete": True}))
        made.append("lab_packet/")
    elif key == "lab-analysis":
        rr = here / "lab_results" / "RUN-RESULT.json"
        status = json.loads(rr.read_text())["status"] if rr.exists() else "missing"
        verdict = "SURVIVED" if status == "done" else "INCONCLUSIVE"
        (here / "LAB_ANALYSIS.md").write_text(f"# Laboratory analysis\n\nRun status: {status}\nVerdict: {verdict}\n")
        body = body.replace("\\end{document}", "\\section{Experiment}\nLaboratory test: " + verdict +
                            ".\n\\end{document}")
        made.append("LAB_ANALYSIS.md")
    elif key.startswith("figure"):                # figure-build, figure1-fix, figures-render, figures-all-fix
        fr = here / "figure_review"
        fr.mkdir(exist_ok=True)
        png = tiny_png()
        for name in ("figure1.png", "page_figure1.png", "figure2.png", "page_figure2.png"):
            (fr / name).write_bytes(png)
        made.append("figure_review/")
    else:
        n = len(list(here.glob("RESULTS-*.md"))) + 1
        (here / f"RESULTS-{n}.md").write_text(f"# Results of task {n}\n\nThe experiment ran end to end.\n")
        body = body.replace("\\end{document}", f"\\section{{Result {n}}}\nThe law predicts every target.\n"
                                               "\\end{document}")
        made.append(f"RESULTS-{n}.md")
    tex.write_text(body, encoding="utf-8")
    (here / "main.pdf").write_bytes(tiny_pdf("Mock manuscript " + stamp()))
    (here / "EXPERIMENT_REPORT.md").write_text(f"# Report\n\nUpdated {stamp()}.\n")
    return made


def lab(job_id: str, here: Path, scenario: str) -> list[str]:
    if not job_id.startswith("lab-"):
        raise SystemExit(f"mock lab agent: job {job_id} is not a laboratory run (lab-<run-id>)")
    run_id = job_id[len("lab-"):]
    if not (here / "inbox" / run_id / "RUN-REQUEST.json").exists():
        raise SystemExit(f"mock lab agent: no RUN-REQUEST.json for {run_id}")
    out = here / "outbox" / run_id
    (out / "data").mkdir(parents=True, exist_ok=True)
    earlier = [p for p in (here / "outbox").iterdir() if p.is_dir() and p.name != run_id]
    status = "failed" if (scenario == "lab-redo" and not earlier) else "done"
    (out / "data" / "run.log").write_text(f"{stamp()} run {run_id} status {status}\n")
    (out / "data" / "sweep.csv").write_text("sequence,counts\nC0,28.53\nT1,28.39\n")
    (out / "data" / "raw_counts.npz").write_bytes(b"\x93NUMPY-mock" + bytes(64))
    (out / "deviations.md").write_text("none\n" if status == "done" else "Reference-pulse control failed.\n")
    (out / "RUN-RESULT.json").write_text(json.dumps({
        "run_id": run_id, "status": status, "started": stamp(), "finished": stamp(), "measurement_hours": 0.0,
        "files": ["data/run.log", "data/sweep.csv", "data/raw_counts.npz"],
        "calibration": {"reference_level": 1.0, "reference_drift": 0.0},
        "deviations": "none" if status == "done" else "see deviations.md", "notes": "mock run"}, indent=1))
    return [f"outbox/{run_id}/"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=["hpc", "lab"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--scenario", default="revision-then-win")
    a = ap.parse_args()
    here = Path.cwd()
    job_id = Path(a.prompt).stem
    if not Path(a.prompt).exists():
        raise SystemExit(f"mock agent: no prompt file {a.prompt}")
    made = hpc(task_key(job_id), here) if a.role == "hpc" else lab(job_id, here, a.scenario)
    notes = here / "NOTES-RESUME.md"
    with open(notes, "a", encoding="utf-8") as f:
        f.write(f"- {stamp()} task {Path(a.prompt).stem}: produced {', '.join(made)}\n")
    (here / "ROUND-DONE.json").write_text(json.dumps({"status": "done", "summary": "mock task completed",
                                                       "deliverables": made}, indent=1))
    print(f"mock {a.role} agent: done ({', '.join(made)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
