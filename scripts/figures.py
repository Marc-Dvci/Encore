"""Draw the README figures: Encore against the model alone, and the lounge film for every resident.

Reads eval/results.json (written by scripts/evaluate.py) and the lounge from a running Encore
(`/api/lounge`). Writes docs/figures/model_alone.png and docs/figures/lounge_fit.png: white
background, no titles, captions live in the README.

Usage: python scripts/figures.py [base_url]      (default: the live demo)
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIGS = ROOT / "docs" / "figures"
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://44-199-155-121.sslip.io"
TEAL = "#0E7A6B"
GREY = "#B9B9B4"
INK = "#222222"
MUTED = "#7A7A7A"
plt.rcParams.update({"font.family": "Source Sans Pro", "font.size": 15, "text.color": INK,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK})


def _clean(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#CFCFCF")
    ax.tick_params(left=False, length=0)


def _count(text: str) -> tuple[int, int]:
    """'108/140 (77%)' -> (108, 140)."""
    a, b = text.split(" ")[0].split("/")
    return int(a), int(b)


def model_alone(results: dict) -> None:
    rows = {r["metric"]: r for r in results["rows"]}
    found = rows["Answers that exist in Qloo's catalogue"]["llm_only"]  # "singers 109/140 (78%), films 108/140 (77%)"
    s, f = (_count(part.strip().split(" ", 1)[1]) for part in found.split(","))
    bars = [
        ("Found in Qloo's catalogue", (280, 280), (s[0] + f[0], s[1] + f[1])),
        ("Singers active in the\nresident's ages 10 to 30", _count(rows["Singers active in the resident's ages 10 to 30"]["encore"]),
         _count(rows["Singers active in the resident's ages 10 to 30"]["llm_only"])),
        ("Films released in the\nresident's ages 10 to 30", _count(rows["Films released in the resident's ages 10 to 30"]["encore"]),
         _count(rows["Films released in the resident's ages 10 to 30"]["llm_only"])),
    ]
    fig, ax = plt.subplots(figsize=(12, 4.6))
    h = 0.34
    for i, (label, enc, llm) in enumerate(bars):
        y = len(bars) - 1 - i
        for dy, (n, d), colour, who in ((h / 2 + 0.02, enc, TEAL, "Encore"), (-h / 2 - 0.02, llm, GREY, "Model alone")):
            ax.barh(y + dy, n / d * 100, height=h, color=colour)
            ax.text(n / d * 100 + 1, y + dy, f"{who}  {n}/{d}", va="center", fontsize=14,
                    color=INK if colour == TEAL else MUTED)
    ax.set_yticks(range(len(bars)))
    ax.set_yticklabels([b[0] for b in reversed(bars)], fontsize=15)
    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0", "25", "50", "75", "100%"], fontsize=13)
    _clean(ax)
    fig.savefig(FIGS / "model_alone.png", dpi=200, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    plt.close(fig)


def lounge_fit(lounge: dict) -> None:
    by_name = {c["name"]: c for c in lounge["candidates"]}
    films = [("Encore's pick", lounge["pick"])]
    for alt in lounge["alternatives"]:
        label = "Highest average" if alt["rule"].startswith("Highest") else "Most popular"
        films.append((label, by_name[alt["name"]]))
    fig, ax = plt.subplots(figsize=(12, 4.4))
    for i, (rule, film) in enumerate(films):
        y = len(films) - 1 - i
        fits = sorted((p["pct"], p["name"]) for p in film["per_resident"])
        colour = TEAL if i == 0 else "#8C8C88"
        ax.plot([0, 1], [y, y], color="#ECECE8", lw=1, zorder=0)
        ax.scatter([f for f, _ in fits], [y] * len(fits), s=150, color=colour, alpha=0.85, lw=0, zorder=2)
        low, who = fits[0]
        ax.scatter([low], [y], s=320, facecolor="none", edgecolor="#C0392B", lw=1.8, zorder=3)
        ax.text(low, y - 0.3, f"{who} {low:.2f}", ha="center", va="top", fontsize=13, color="#C0392B")
        ax.text(-0.03, y + 0.08, f"{film['name']} ({film['year']})", ha="right", va="bottom", fontsize=15)
        ax.text(-0.03, y - 0.06, rule, ha="right", va="top", fontsize=13, color=MUTED)
    ax.set_xlim(-0.02, 1.03)
    ax.set_ylim(-0.75, len(films) - 0.45)
    ax.set_yticks([])
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0", "0.25", "0.5", "0.75", "1"], fontsize=13)
    ax.set_xlabel("Fit for each of the 14 residents (1 = top of their own Qloo ranking)", fontsize=14, color=MUTED)
    _clean(ax)
    fig.savefig(FIGS / "lounge_fit.png", dpi=200, bbox_inches="tight", pad_inches=0.15, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    FIGS.mkdir(parents=True, exist_ok=True)
    model_alone(json.loads((ROOT / "eval" / "results.json").read_text(encoding="utf-8")))
    with urllib.request.urlopen(f"{BASE}/api/lounge", timeout=60) as r:
        lounge_fit(json.loads(r.read().decode("utf-8")))
    print("wrote", FIGS / "model_alone.png", "and", FIGS / "lounge_fit.png")
