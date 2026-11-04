"""Draw the Auctopus emblem: the PI medallion of Fig. 1b of the paper as the head, ringed by the five stage-coloured
arcs, with one tapered arm per agent that curls at its tip (an Euler spiral: curvature grows along the arm).

    python make_logo.py            writes emblem.tex, logo.tex and logo-dark.tex next to this file
    pdflatex emblem.tex; pdflatex logo.tex; pdflatex logo-dark.tex
    pdftocairo -svg emblem.pdf ../auctopus-emblem.svg     (and likewise logo, logo-dark)
"""
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

# the five arcs of Fig. 1b: angle (deg) and colour (proposers, computational researcher, manager, experimentalist,
# reviewers)
ARMS = [(90, "cask"), (18, "cprove"), (-54, "cdesign"), (-126, "cmeasure"), (162, "creview")]
COLOURS = r"""
\definecolor{cblue}{RGB}{31,90,166}
\definecolor{cdark}{RGB}{50,52,56}
\definecolor{cask}{RGB}{135,139,144}
\definecolor{cprove}{RGB}{31,90,166}
\definecolor{cdesign}{RGB}{176,125,18}
\definecolor{cmeasure}{RGB}{37,136,37}
\definecolor{creview}{RGB}{122,92,158}
"""


def arm_outline(angle_deg: float, r0: float = 5.0, length: float = 15.5, turn: float = 4.6, w0: float = 1.45,
                w1: float = 0.16, steps: int = 220) -> list[tuple[float, float]]:
    """Closed outline of one tapered arm leaving the head at `angle_deg`, curling counter-clockwise at its tip."""
    k0 = 0.035                                   # initial curvature: a gentle bend
    k1 = 2 * (turn - k0 * length) / length ** 2  # curvature growth, so the tip has turned by `turn` radians
    a = math.radians(angle_deg)
    x, y, th = r0 * math.cos(a), r0 * math.sin(a), a
    ds = length / steps
    centre, normal, width = [], [], []
    for i in range(steps + 1):
        s = i * ds
        centre.append((x, y))
        normal.append((-math.sin(th), math.cos(th)))
        width.append(w1 + (w0 - w1) * (1 - s / length) ** 1.35)
        th += (k0 + k1 * s) * ds
        x += math.cos(th) * ds
        y += math.sin(th) * ds
    left = [(cx + nx * w / 2, cy + ny * w / 2) for (cx, cy), (nx, ny), w in zip(centre, normal, width)]
    right = [(cx - nx * w / 2, cy - ny * w / 2) for (cx, cy), (nx, ny), w in zip(centre, normal, width)]
    tip = centre[-1]
    return left + [tip] + right[::-1]


def suckers(angle_deg: float, r0: float = 5.0, length: float = 15.5, turn: float = 4.6, n: int = 7):
    """Small dots along the inner side of the arm (the document deliveries of Fig. 1c)."""
    k0 = 0.035
    k1 = 2 * (turn - k0 * length) / length ** 2
    a = math.radians(angle_deg)
    x, y, th = r0 * math.cos(a), r0 * math.sin(a), a
    steps = 400
    ds = length / steps
    out = []
    marks = {int(steps * f) for f in [0.14 + 0.095 * j for j in range(n)]}
    for i in range(steps + 1):
        s = i * ds
        if i in marks:
            w = 0.16 + (1.45 - 0.16) * (1 - s / length) ** 1.35
            out.append((x, y, max(0.09, 0.2 * w)))
        th += (k0 + k1 * s) * ds
        x += math.cos(th) * ds
        y += math.sin(th) * ds
    return out


def emblem_tikz() -> str:
    lines = []
    for ang, col in ARMS:
        pts = arm_outline(ang)
        path = " -- ".join(f"({px:.3f},{py:.3f})" for px, py in pts)
        lines.append(f"\\fill[{col}] {path} -- cycle;")
        for sx, sy, sr in suckers(ang):
            lines.append(f"\\fill[white, opacity=0.85] ({sx:.3f},{sy:.3f}) circle ({sr:.3f});")
    # the five arcs around the medallion, as in Fig. 1b
    for ang, col in ARMS:
        lines.append(f"\\draw[{col}, line width=3.2pt, line cap=round] ({ang - 27}:5.0) arc ({ang - 27}:{ang + 27}:5.0);")
    # the PI medallion
    lines += [r"\filldraw[draw=cblue, line width=2.2pt, fill=white] (0,0) circle (3.55);",
              r"\draw[cblue!50, line width=0.9pt] (0,0) circle (2.6);",
              r"\fill[cblue] (0,0) circle (1.62);"]
    return "\n".join(lines)


def document(body: str) -> str:
    return ("\\documentclass[tikz,border=4pt]{standalone}\n\\usepackage[T1]{fontenc}\n"
            "\\usepackage[scaled=0.92]{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}\n" + COLOURS +
            "\\begin{document}\n\\begin{tikzpicture}[x=1mm, y=1mm]\n" + body + "\n\\end{tikzpicture}\n\\end{document}\n")


def wordmark(text_colour: str) -> str:
    # the name alone: the README explains the project in text right under the logo
    return (rf"\node[anchor=base west, text={text_colour}, inner sep=0pt] at (24,-5.6) "
            r"{\fontsize{46}{50}\selectfont\bfseries Auctopus};")


emblem = emblem_tikz()
(HERE / "emblem.tex").write_text(document(emblem), encoding="utf-8")
(HERE / "logo.tex").write_text(document(emblem + "\n" + wordmark("cdark")), encoding="utf-8")
# for GitHub's dark theme: light lettering, same emblem
(HERE / "logo-dark.tex").write_text(document(emblem + "\n" + wordmark("black!8")), encoding="utf-8")
print("wrote emblem.tex, logo.tex and logo-dark.tex")
