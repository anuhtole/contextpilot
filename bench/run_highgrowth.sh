#!/bin/bash
# High-growth grid: for each ordering h1-h5, the three arms run in parallel (paired in time).
# The ledger in results/highgrowth/ stops new runs once its spend reaches CAP.
export PILOT_WORKDIR=${PILOT_WORKDIR:-/tmp/contextpilot-hg}
CAP=${CAP:-95}
HEADROOM=${HEADROOM:-30}  # three parallel runs, each capped at $10 by --max-budget-usd
LEDGER=../results/highgrowth/ledger.jsonl
for v in ${ORDERINGS:-h1 h2 h3 h4 h5}; do
  spent=$(../.venv/bin/python -c "import json;print(sum(json.loads(l).get('cost_usd') or 0 for l in open('$LEDGER')))" 2>/dev/null || echo 0)
  if ../.venv/bin/python -c "import sys;sys.exit(0 if $spent + $HEADROOM <= $CAP else 1)"; then :; else
    echo "stopping before $v: spent \$$spent + headroom \$$HEADROOM > cap \$$CAP"; break
  fi
  for arm in ${ARMS:-auto eoq 150k}; do
    ../.venv/bin/python run_pilot.py "$v" "$arm" 1 "$CAP" &
  done
  wait
done
