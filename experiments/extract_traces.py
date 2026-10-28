"""Extract numeric-only token traces from local Claude Code transcripts.

Only per-call usage counts and tool-result sizes are kept; no message text,
file paths, or tool arguments leave the transcript. Output: data/traces.json.
"""
import glob
import json
import os
from pathlib import Path

MIN_CALLS = 5
TRANSCRIPTS = os.path.expanduser("~/.claude/projects/**/*.jsonl")
DEST = Path(__file__).resolve().parents[1] / "data" / "traces.json"


def source_of(path):
    if "observer" in path:
        return "observer"
    return "subagent" if "/subagents/" in path else "main"


def usage_row(message):
    u = message["usage"]
    return {
        "in": u.get("input_tokens", 0),
        "cr": u.get("cache_read_input_tokens", 0) or 0,
        "cw": u.get("cache_creation_input_tokens", 0) or 0,
        "out": u.get("output_tokens", 0),
        "model": message.get("model", ""),
    }


def parse_session(path):
    turns, tool_sizes, compacts, seen = [], [], 0, set()
    with open(path, errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("type") == "system" and r.get("subtype") == "compact_boundary":
                compacts += 1
                turns.append({"compact": 1})
                continue
            if r.get("isCompactSummary"):
                continue
            m = r.get("message")
            if not isinstance(m, dict):
                continue
            if r.get("type") == "assistant" and m.get("usage") and m.get("id") not in seen:
                seen.add(m.get("id"))  # streamed messages repeat the same id
                turns.append(usage_row(m))
            if r.get("type") == "user" and isinstance(m.get("content"), list):
                tool_sizes += [len(json.dumps(c.get("content")))
                               for c in m["content"]
                               if isinstance(c, dict) and c.get("type") == "tool_result"]
    return {"src": source_of(path), "turns": turns, "tool_result_chars": tool_sizes, "compacts": compacts}


def main():
    files = glob.glob(TRANSCRIPTS, recursive=True)
    sessions = [s for s in map(parse_session, files)
                if sum("in" in t for t in s["turns"]) >= MIN_CALLS]
    DEST.parent.mkdir(exist_ok=True)
    DEST.write_text(json.dumps(sessions))
    calls = sum(sum("in" in t for t in s["turns"]) for s in sessions)
    print(f"{len(files)} files -> {len(sessions)} sessions, {calls} API calls -> {DEST}")


if __name__ == "__main__":
    main()
