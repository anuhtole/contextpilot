#!/bin/bash
# Pilot grid: for each rep and variant, run the three arms in parallel; stops at the budget cap.
export PILOT_WORKDIR=${PILOT_WORKDIR:-/tmp/contextpilot-pilot}
CAP=${CAP:-23}
for rep in ${REPS:-1}; do
  for v in v1 v2 v3; do
    for arm in auto eoq early; do
      ../.venv/bin/python run_pilot.py "$v" "$arm" "$rep" "$CAP" &
    done
    wait
  done
done
