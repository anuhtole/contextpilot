"""Generate the paper's LaTeX tables from results/*.json so numbers never drift from the data."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper"
PRICE = {"uncached": "uncached", "cached": "cached 0.1$\\times$",
         "cached (5.5-gen 0.05x read)": "cached 0.05$\\times$",
         "Claude Code (0.05x read, 1h 2x write)": "Claude Code"}


def pct(x):
    return f"${100 * x:+.1f}$"


def main_table():
    rows = json.loads((ROOT / "results" / "closed_form.json").read_text())
    lines = [r"\begin{tabular}{lllrrrrrrr}", r"\toprule",
             r"Data & Prices & $W$ & $H^\star$ & 150k ctx & 70\%$W$ & Break-even & Online & Best fixed & Opt.\\",
             r"\midrule"]
    for r in rows:
        data, prices, window = [p.strip() for p in r["setting"].split("|")]
        data = data.replace("Claude Code traces", "Claude Code").replace(" (n=1500)", "") \
                   .replace("real-trace replay (25)", "Replay (25)")
        prices = PRICE.get(prices, "Claude Code" if "Claude Code" in prices else prices)
        lines.append(f"{data} & {prices} & {window.replace('1000k', '1M')} & "
                     f"{r['closed_form_H'] / 1e3:.0f}k & {pct(r['api_default_150k'])} & {pct(r['window_70pct'])} & "
                     f"{pct(r['break_even'])} & {pct(r['closed_form_online'])} & "
                     f"{pct(r['best_fixed'])} ({r['best_fixed_H'] / 1e3:.0f}k) & {pct(r['optimum'])}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    worst_gap = max(r["online_vs_best"] for r in rows)
    (OUT / "table_main.tex").write_text("\n".join(lines) + "\n")
    return worst_gap


SHORT = {"steady-state optimum (online g)": "online steady-state",
         "steady-state optimum (recent g, half-life 10)": "online, recent $g$ (exploratory)",
         "steady-state optimum (recent g, half-life 10) + horizon gate (Lindy, lam=0.5)": "online, recent $g$ + horizon gate",
         "ski-rental break-even": "break-even", "ski-rental randomized": "randomized break-even"}


def worst_table():
    res = json.loads((ROOT / "results" / "worst_case.json").read_text())
    names = sorted(res["1000k"], key=lambda k: res["1000k"][k]["max"])
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Policy (Claude Code prices) & max, 200k & max, 1M & p99, 1M & mean, 1M\\", r"\midrule"]
    for n in names:
        a, b = res["200k"][n], res["1000k"][n]
        label = SHORT.get(n, n).replace('%', chr(92) + '%')
        lines.append(f"{label} & {a['max']:.3f} & {b['max']:.3f} & {b['p99']:.3f} & {b['mean']:.3f}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_worst.tex").write_text("\n".join(lines) + "\n")


HORIZON_COLS = [("steady-state", "steady-state"), ("steady-state, recent g", "+ recent $g$"),
                ("horizon-gated, recent g", "+ gate (learned)"), ("horizon-gated, recent g, oracle", "+ gate (oracle)"),
                ("150k context", "150k"), ("break-even", "break-even")]


def horizon_table():
    rows = json.loads((ROOT / "results" / "horizon.json").read_text())["rows"]
    lines = [r"\begin{tabular}{l" + "r" * len(HORIZON_COLS) + "}", r"\toprule",
             "Setting & " + " & ".join(label for _, label in HORIZON_COLS) + r"\\", r"\midrule"]
    for r in rows:
        name = r["setting"].replace("Claude Code (0.05x read, 1h 2x write)", "Claude Code").replace(", Claude Code prices", "")
        lines.append(f"{name} & " + " & ".join(pct(r["policies"][k]["vs_best_fixed"]) for k, _ in HORIZON_COLS) + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_horizon.tex").write_text("\n".join(lines) + "\n")


WILD_ARMS = [("API default (150k)", "fixed 150k (API default)"), ("closed form (online g)", "online steady-state"),
             ("break-even", "break-even"), ("fixed trigger, leave-one-out", "fixed, leave-one-out"),
             ("hindsight best fixed (per session)", "best fixed per session (hindsight)")]
WILD_BASE = "Claude Code default (490k)"


def wild_table():
    res = json.loads((ROOT / "results" / "wild.json").read_text())
    cols = [("main / warm", "main, warm"), ("main / cold", "main, misses"), ("all / warm", "all 40, warm")]
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule",
             "Policy vs.\\ 490k default & " + " & ".join(label for _, label in cols) + r" & helped/hurt\\", r"\midrule"]
    for key, label in WILD_ARMS:
        cells = [pct(res[c][key]["total_usd"] / res[c][WILD_BASE]["total_usd"] - 1) for c, _ in cols]
        base, arm = res["main / warm"][WILD_BASE]["per_session_usd"], res["main / warm"][key]["per_session_usd"]
        rel = [a / b - 1 for a, b in zip(arm, base)]
        helped, hurt = sum(r < -0.01 for r in rel), sum(r > 0.01 for r in rel)
        lines.append(f"{label} & " + " & ".join(cells) + f" & {helped}/{hurt}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_wild.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    gap = main_table()
    worst_table()
    horizon_table()
    wild_table()
    print(f"wrote tables; worst online-vs-best gap {100 * gap:.2f}%")
