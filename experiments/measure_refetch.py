"""Measure the re-fetch fraction rho from pilot runs with compactions: tokens of tool
output re-read after a compaction for files/commands already seen before it, divided by
the tokens the compaction dropped (pre_tokens - post_tokens)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "results" / "pilot"
CHARS_PER_TOKEN = 4.0


def key(tool):
    inp = tool.get("input", {})
    return (tool.get("name"), inp.get("file_path") or inp.get("pattern") or inp.get("command"))


def measure(stream):
    seen_before, uses, segments = set(), {}, []
    current = {"refetch": 0.0}
    dropped = []
    for line in stream.read_text().splitlines():
        r = json.loads(line)
        if r.get("type") == "system" and r.get("subtype") == "compact_boundary":
            meta = r.get("compact_metadata", {})
            dropped.append(meta.get("pre_tokens", 0) - meta.get("post_tokens", 0))
            segments.append(current)
            current = {"refetch": 0.0}
            seen_before = seen_before | {k for k in uses.values()}
        if r.get("type") == "assistant":
            for c in r["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    uses[c["id"]] = key(c)
        if r.get("type") == "user":
            content = r.get("message", {}).get("content")
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and dropped:
                    if uses.get(c.get("tool_use_id")) in seen_before:
                        current["refetch"] += len(json.dumps(c.get("content"))) / CHARS_PER_TOKEN
    segments.append(current)
    refetched = sum(s["refetch"] for s in segments[1:])
    return refetched, sum(dropped), len(dropped)


if __name__ == "__main__":
    total_r, total_d = 0.0, 0.0
    for stream in sorted(PILOT.glob("*-early-r1.jsonl")):
        r, d, k = measure(stream)
        total_r, total_d = total_r + r, total_d + d
        print(f"{stream.stem:16s} compactions {k:2d}  dropped {d / 1e3:6.1f}k  re-fetched {r / 1e3:5.1f}k  rho {r / d:.3f}")
    print(f"pooled rho = {total_r / total_d:.3f}")
