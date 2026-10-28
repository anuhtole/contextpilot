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


def worst_table():
    res = json.loads((ROOT / "results" / "worst_case.json").read_text())
    names = sorted(res["1000k"], key=lambda k: res["1000k"][k]["max"])
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule",
             r"Policy (Claude Code prices) & max, 200k & max, 1M & p99, 1M & mean, 1M\\", r"\midrule"]
    for n in names:
        a, b = res["200k"][n], res["1000k"][n]
        lines.append(f"{n.replace('%', chr(92) + '%')} & {a['max']:.3f} & {b['max']:.3f} & {b['p99']:.3f} & {b['mean']:.3f}\\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "table_worst.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    gap = main_table()
    worst_table()
    print(f"wrote tables; worst online-vs-best gap {100 * gap:.2f}%")
