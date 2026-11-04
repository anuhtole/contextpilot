"""Extract numeric-only token traces from local Claude Code transcripts.

Only per-call usage counts and tool-result sizes are kept; no message text,
file paths, or tool arguments leave the transcript. Output: data/traces.json (the snapshot
the paper's calibration uses; experiments/wild.py reads live logs with the exclusions).
"""
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contextpilot.traces import MIN_CALLS, PROJECTS, parse_session  # noqa: E402

DEST = Path(__file__).resolve().parents[1] / "data" / "traces.json"


def main():
    files = glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True)
    sessions = [s for s in map(parse_session, files)
                if sum("in" in t for t in s["turns"]) >= MIN_CALLS]
    DEST.parent.mkdir(exist_ok=True)
    DEST.write_text(json.dumps(sessions))
    calls = sum(sum("in" in t for t in s["turns"]) for s in sessions)
    print(f"{len(files)} files -> {len(sessions)} sessions, {calls} API calls -> {DEST}")


if __name__ == "__main__":
    main()
