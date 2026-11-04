"""Read numeric-only token traces from local Claude Code transcripts.

Only per-call usage counts and tool-result sizes are kept; no message text, file
paths, or tool arguments leave the transcript.
"""
import glob
import json
import os
from collections import Counter

import numpy as np

PROJECTS = os.path.expanduser("~/.claude/projects")
MIN_CALLS = 5
COLD_FRAC = 0.5  # a call writing over half its context to cache counts as a cache miss


def source_of(path):
    if "observer" in path:
        return "observer"
    return "subagent" if "/subagents/" in path else "main"


def is_excluded(path, root=PROJECTS):
    """Observer (claude-mem) sessions and benchmark runs launched from /private/tmp are not real work."""
    project = os.path.relpath(path, root).split(os.sep)[0]
    return source_of(path) == "observer" or project.startswith("-private-tmp")


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


def n_calls(session):
    return sum("in" in t for t in session["turns"])


def load_sessions(root=PROJECTS, min_calls=MIN_CALLS, exclude=True):
    files = sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
    files = [f for f in files if not (exclude and is_excluded(f, root))]
    return [s for s in map(parse_session, files) if n_calls(s) >= min_calls]


def calls(session):
    return [t for t in session["turns"] if "in" in t]


def context(session):
    """Total input context of each call (uncached + cache read + cache write)."""
    return np.array([t["in"] + t["cr"] + t["cw"] for t in calls(session)], dtype=float)


def increments(session):
    """Per-call growth of the running peak context, reset at each compaction.

    Rewinds and interleaved side calls drop context without compacting; measuring growth past the
    peak keeps the rebound from counting twice, so the replayed history never undershoots the log."""
    ctx, at = context(session), set(compaction_calls(session))
    g, peak = np.zeros(len(ctx)), ctx[0] if len(ctx) else 0.0
    for i in range(1, len(ctx)):
        if i in at:
            peak = ctx[i]
            continue
        g[i] = max(0.0, ctx[i] - peak)
        peak = max(peak, ctx[i])
    return g


def cold_calls(session, frac=COLD_FRAC):
    """Calls that rewrote most of their prefix: the cache had expired (idle gap or model switch)."""
    cold = np.array([t["cw"] > frac * c for t, c in zip(calls(session), context(session))], dtype=bool)
    if len(cold):
        cold[0] = False  # the first call always writes the prefix; it is not a miss
    return cold


def compaction_calls(session):
    """Indices of the first call after each compaction boundary."""
    idx, k = [], 0
    for t in session["turns"]:
        if "compact" in t:
            idx.append(k)
        else:
            k += 1
    return [i for i in idx if i < n_calls(session)]


def dominant_model(session):
    models = Counter(t["model"] for t in calls(session) if t["model"] and t["model"] != "<synthetic>")
    return models.most_common(1)[0][0] if models else ""
