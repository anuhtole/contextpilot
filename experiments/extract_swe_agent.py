"""Turn nebius/SWE-agent-trajectories shards into numeric context-growth traces.

For model call k the context is the system prompt plus every message before the
k-th assistant turn; we keep only per-call token increments (chars / 4, a standard
approximation; no tokenizer is shipped with the data), never the text itself.
Output: data/swe_agent_traces.json
"""
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

CHARS_PER_TOKEN = 4.0
ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "swe_agent_traces.json"


def tokens(text):
    return len(text or "") / CHARS_PER_TOKEN


def convert(traj):
    system = sum(tokens(s["system_prompt"]) + tokens(s["text"]) for s in traj if s["role"] == "system")
    increments, outputs, pending = [], [], 0.0
    for step in traj:
        if step["role"] == "system":
            continue
        if step["role"] == "ai":
            increments.append(pending)
            outputs.append(tokens(step["text"]))
            pending = tokens(step["text"])
        else:
            pending += tokens(step["text"])
    return system, increments, outputs


def main(paths):
    sessions = []
    for path in paths:
        table = pq.read_table(path, columns=["model_name", "target", "exit_status", "trajectory"])
        for row in table.to_pylist():
            system, g, out = convert(row["trajectory"])
            if len(g) >= 3:
                sessions.append({"model": row["model_name"], "resolved": bool(row["target"]),
                                 "exit": row["exit_status"], "system": round(system),
                                 "g": [round(x) for x in g], "out": [round(x) for x in out]})
    DEST.write_text(json.dumps(sessions))
    print(f"{len(sessions)} trajectories -> {DEST}")


if __name__ == "__main__":
    main(sys.argv[1:] or sorted(str(p) for p in (ROOT / "data" / "external").glob("*.parquet")))
