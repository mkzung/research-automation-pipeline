"""Generic publication-quality matplotlib chart utility.

Designed for LLM-driven pipelines where a structured chart spec is rendered
into a static PNG. Features:

- Adaptive label hiding (small slices/bars get no label to prevent overlap)
- Smart axis-label rotation + truncation
- Density-aware font sizing
- Neutral default palette (override via spec.palette)
- Reproducibility footer (study_id + timestamp) so any rendered chart
  is traceable back to the run that produced it

The chart spec is a JSON-style dict — example:

    {
        "type": "horizontal_bar",
        "title": "Revenue by region (2025)",
        "x": "region",
        "y": "revenue_usd",
        "footer": "study_id=abc123 · 2026-05-09",
        "data": [{"region": "EMEA", "revenue_usd": 12.4}, ...]
    }
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Neutral palette — override per-chart via spec["palette"]
DEFAULT_PALETTE = [
    "#2E5C8A",  # navy
    "#A33D49",  # crimson
    "#5A8B5A",  # green
    "#D2A24A",  # gold
    "#6E5B8A",  # purple
    "#3A3A3A",  # gray
]

CANVAS_W, CANVAS_H = 1350, 1080  # LinkedIn-friendly
DPI = 150


# ---------------------------------------------------------------------------
def _new_figure() -> plt.Figure:
    fig = plt.figure(figsize=(CANVAS_W / DPI, CANVAS_H / DPI), dpi=DPI)
    fig.patch.set_facecolor("white")
    return fig


def _adaptive_fontsize(n_items: int, base: float = 12) -> float:
    if n_items <= 6:
        return base
    if n_items <= 12:
        return base - 1
    if n_items <= 20:
        return base - 2
    return max(7, base - 4)


def _truncate(label: str, max_chars: int = 28) -> str:
    return label if len(label) <= max_chars else label[: max_chars - 1] + "…"


# ---------------------------------------------------------------------------
def _render_horizontal_bar(spec: dict, ax: plt.Axes) -> None:
    rows = spec["data"]
    x_field, y_field = spec["x"], spec["y"]
    palette = spec.get("palette", DEFAULT_PALETTE)
    fontsize = _adaptive_fontsize(len(rows))

    # Sort descending for typical "ranking" chart
    rows = sorted(rows, key=lambda r: r[y_field], reverse=True)
    labels = [_truncate(str(r[x_field])) for r in rows]
    values = [r[y_field] for r in rows]
    colors = [palette[i % len(palette)] for i in range(len(rows))]

    bars = ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.set_xlabel(spec.get("x_label", y_field), fontsize=fontsize)
    ax.tick_params(axis="y", labelsize=fontsize)
    ax.tick_params(axis="x", labelsize=fontsize - 1)

    # Hide bar labels for thin bars (to avoid overlap)
    max_v = max(values) if values else 1
    for bar, v in zip(bars, values[::-1]):
        if v / max_v < 0.05:  # too thin → skip label
            continue
        ax.text(
            bar.get_width() * 1.01,
            bar.get_y() + bar.get_height() / 2,
            f"{v:,.1f}" if isinstance(v, float) else f"{v:,}",
            va="center",
            fontsize=fontsize - 1,
        )

    ax.spines[["top", "right"]].set_visible(False)


def _render_vertical_bar(spec: dict, ax: plt.Axes) -> None:
    rows = spec["data"]
    x_field, y_field = spec["x"], spec["y"]
    palette = spec.get("palette", DEFAULT_PALETTE)
    fontsize = _adaptive_fontsize(len(rows))

    labels = [_truncate(str(r[x_field])) for r in rows]
    values = [r[y_field] for r in rows]
    colors = [palette[i % len(palette)] for i in range(len(rows))]

    ax.bar(labels, values, color=colors)
    ax.set_ylabel(spec.get("y_label", y_field), fontsize=fontsize)
    rotation = 0 if len(rows) <= 8 else 30
    ax.tick_params(axis="x", labelsize=fontsize, rotation=rotation)
    ax.tick_params(axis="y", labelsize=fontsize - 1)
    ax.spines[["top", "right"]].set_visible(False)


def _render_line(spec: dict, ax: plt.Axes) -> None:
    rows = spec["data"]
    x_field, y_field = spec["x"], spec["y"]
    palette = spec.get("palette", DEFAULT_PALETTE)
    series_field = spec.get("series")  # optional grouping

    if series_field:
        series_groups: dict[str, list[tuple[Any, Any]]] = {}
        for r in rows:
            series_groups.setdefault(r[series_field], []).append((r[x_field], r[y_field]))
        for i, (name, points) in enumerate(series_groups.items()):
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ax.plot(xs, ys, color=palette[i % len(palette)], linewidth=2, label=str(name))
        ax.legend(fontsize=10, frameon=False)
    else:
        xs = [r[x_field] for r in rows]
        ys = [r[y_field] for r in rows]
        ax.plot(xs, ys, color=palette[0], linewidth=2)

    ax.set_xlabel(x_field, fontsize=12)
    ax.set_ylabel(spec.get("y_label", y_field), fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)


def _render_pie(spec: dict, ax: plt.Axes) -> None:
    rows = spec["data"]
    x_field, y_field = spec["x"], spec["y"]
    palette = spec.get("palette", DEFAULT_PALETTE)

    labels = [str(r[x_field]) for r in rows]
    values = [r[y_field] for r in rows]
    total = sum(values)

    # Hide label for tiny slices (<3%)
    display_labels = [
        f"{l}\n{v/total*100:.1f}%" if v / total >= 0.03 else ""
        for l, v in zip(labels, values)
    ]
    ax.pie(
        values,
        labels=display_labels,
        colors=[palette[i % len(palette)] for i in range(len(values))],
        startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 11},
    )
    ax.axis("equal")


# ---------------------------------------------------------------------------
RENDERERS = {
    "horizontal_bar": _render_horizontal_bar,
    "vertical_bar": _render_vertical_bar,
    "line": _render_line,
    "pie": _render_pie,
}


def render_chart(spec: dict, output_path: str | Path) -> Path:
    """Render a chart spec → PNG at output_path. Returns the path."""
    chart_type = spec.get("type")
    if chart_type not in RENDERERS:
        raise ValueError(
            f"unknown chart type: {chart_type!r}. supported: {sorted(RENDERERS)}"
        )

    fig = _new_figure()
    ax = fig.add_subplot(111)

    if title := spec.get("title"):
        ax.set_title(title, fontsize=18, fontweight="bold", pad=16, loc="left")
    if subtitle := spec.get("subtitle"):
        fig.text(0.05, 0.93, subtitle, fontsize=12, color="#6B6B6B")

    RENDERERS[chart_type](spec, ax)

    if footer := spec.get("footer"):
        fig.text(0.05, 0.02, footer, fontsize=9, color="#9A9A9A", style="italic")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="Render a chart spec → PNG.")
    p.add_argument("--spec", required=True, help="path to spec JSON or '-' for stdin")
    p.add_argument("--output", required=True, help="output PNG path")
    args = p.parse_args()

    if args.spec == "-":
        spec = json.load(sys.stdin)
    else:
        spec = json.loads(Path(args.spec).read_text())

    out = render_chart(spec, args.output)
    print(json.dumps({"ok": True, "output": str(out)}))


if __name__ == "__main__":
    main()
