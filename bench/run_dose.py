"""Dose-response runs (EVAL_PLAN.md, quality cost of extra compactions), two at a time.

usage: python3 run_dose.py <cap_usd> <variant:arm:rep> [...]

Every run goes to results/dose/, whose ledger counts only this experiment's spend. A run starts
only while spend plus HEADROOM (the other run in flight at its $10 per-run cap) stays under the cap.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_pilot import ROOT, spent  # noqa: E402

OUT = "dose"
PARALLEL = int(os.environ.get("PARALLEL", 2))
HEADROOM = float(os.environ.get("HEADROOM", 20))
LEDGER = ROOT / "results" / OUT / "ledger.jsonl"


def launch(job, cap):
    v, arm, rep = job.split(":")
    if spent(LEDGER) + HEADROOM > cap:
        print(f"skip {job}: spent ${spent(LEDGER):.2f} + headroom ${HEADROOM} > cap ${cap}", flush=True)
        return
    env = {**os.environ, "PILOT_OUT": OUT, "PILOT_WORKDIR": "/tmp/contextpilot-dose"}
    res = subprocess.run([sys.executable, "run_pilot.py", v, arm, rep, str(cap)], cwd=Path(__file__).parent,
                         env=env, capture_output=True, text=True)
    print(f"{job}: exit {res.returncode} {res.stdout.strip()[-300:]} {res.stderr.strip()[-300:]}", flush=True)


if __name__ == "__main__":
    cap, jobs = float(sys.argv[1]), sys.argv[2:]
    with ThreadPoolExecutor(PARALLEL) as pool:
        list(pool.map(lambda j: launch(j, cap), jobs))
