"""Paper figures: cost vs compaction point (flatness) and the optimal point vs growth rate."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot import sim  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "paper" / "figures"
# validated categorical slots 1-4 (light); two fall below 3:1 contrast, so every line is
# also direct-labeled and carries its own dash pattern
SERIES = [("#2a78d6", "-"), ("#eb6834", "--"), ("#1baf7a", "-."), ("#eda100", ":")]
INK, MUTED, GRID = "#1f1f1e", "#6b6a64", "#e4e3de"
REGIMES = [(sim.UNCACHED, "uncached"), (sim.CACHED, "cached 0.1x"),
           (sim.CACHED_55, "cached 0.05x"), (sim.CLAUDE_CODE, "Claude Code (0.05x, 1h writes)")]
# summaries of a roughly constant size (the square-root formula is then exact)
ENV = sim.Env(system=40_000, out_per_call=1_200, sigma_frac=0.0, sigma_min=4_000, sigma_max=4_000)
PRODUCT_TRIGGERS = [(100_000 - 40_000, "Claude Code\nflag floor (100k)"),
                    (150_000 - 40_000, "Anthropic API\ndefault (150k)"),
                    (967_000 - 40_000, "Claude Code\n1M window (~967k)")]


def style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def flatness(g=3_800):
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    hs = np.geomspace(8_000, 1_200_000, 400)
    for (prices, label), (color, dash) in zip(REGIMES, SERIES):
        env = ENV.with_(prices=prices)
        rates = np.array([sim.steady_state_rate(env, g, h) for h in hs])
        rel = rates / np.nanmin(rates[np.isfinite(rates)])
        best = hs[np.nanargmin(rates)]
        ax.plot(hs, rel, color=color, linestyle=dash, linewidth=2, label=f"{label} (H* = {best / 1e3:.0f}k)")
        ax.plot([best], [1.0], "o", color=color, markersize=6, markeredgecolor="white", markeredgewidth=1.5)
    for (h, label), y in zip(PRODUCT_TRIGGERS, (5.2, 6.4, 7.7)):
        ax.axvline(h, color=MUTED, linewidth=0.8, linestyle=(0, (2, 2)))
        ax.text(h * 1.05, y, label, fontsize=6.5, color=MUTED, ha="left", va="top")
    ax.legend(loc="upper left", fontsize=7, frameon=False, labelcolor=INK)
    ax.set_xscale("log")
    ax.set_ylim(0.9, 8)
    ax.set_xlim(8_000, 1_500_000)
    ax.set_xlabel("history at which compaction triggers (tokens)", fontsize=8, color=INK)
    ax.set_ylabel("controllable cost / optimum", fontsize=8, color=INK)
    ax.set_title(f"Steady-state cost of a compaction trigger (growth {g:,} tokens/call)", fontsize=9, color=INK, loc="left")
    style(ax)
    fig.tight_layout()
    return fig


def optimum_vs_growth():
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    gs = np.geomspace(200, 12_000, 60)
    for (prices, label), (color, dash) in zip(REGIMES, SERIES):
        hs = [sim.steady_state_optimum(ENV.with_(prices=prices), g) for g in gs]
        ax.plot(gs, hs, color=color, linestyle=dash, linewidth=2, label=label)
    for h, label in PRODUCT_TRIGGERS:
        ax.axhline(h, color=MUTED, linewidth=0.8, linestyle=(0, (2, 2)))
        ax.text(210, h * 1.06, label.replace("\n", " "), fontsize=6.5, color=MUTED, va="bottom")
    for g, label in ((484, "SWE-agent\nmean"), (3_828, "local Claude Code\nmean")):
        ax.axvline(g, color=GRID, linewidth=1.2)
        ax.text(g * 1.05, 4.0e5, label, fontsize=6.5, color=MUTED, ha="left", va="center")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.legend(loc="lower right", fontsize=7, frameon=False, labelcolor=INK)
    ax.set_xlim(200, 12_000)
    ax.set_ylim(1_000, 2_000_000)
    ax.set_xlabel("context growth g (tokens per call)", fontsize=8, color=INK)
    ax.set_ylabel("optimal compaction point H* (tokens)", fontsize=8, color=INK)
    ax.set_title("Cost-optimal compaction point vs. product triggers", fontsize=9, color=INK, loc="left")
    style(ax)
    fig.tight_layout()
    return fig


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    for name, make in (("flatness", flatness), ("optimum_vs_growth", optimum_vs_growth)):
        fig = make()
        for ext in ("pdf", "png"):
            fig.savefig(FIG / f"{name}.{ext}", dpi=200)
        print("wrote", FIG / f"{name}.png")
