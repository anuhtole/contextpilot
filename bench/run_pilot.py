"""Run headless Claude Code on a pilot workspace under one compaction trigger and score it.

usage: python3 run_pilot.py <variant v1|v2|v3|v1L|v2L|v3L|h1..h5> <arm auto|eoq|early|150k> <rep> [cap_usd] [max_msgs]

The harness is never allowed to auto-compact below its window (Claude Code's floor is
100k). Instead this driver acts as an external controller: between user turns it
decides from observed usage whether to send `/compact`, exactly as a user could.
Appends one JSON line per run to results/pilot/ledger.jsonl and refuses to start
a run once the ledger's total spend reaches the cap.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import LARGE_BUGS, build, is_high_growth, messages_path  # noqa: E402
from contextpilot import sim  # noqa: E402
from score import score  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "pilot"
WORK = Path(os.environ.get("PILOT_WORKDIR", "/tmp/contextpilot-pilot"))
LEDGER = OUT / "ledger.jsonl"
PER_RUN_CAP_USD = 10.0
TIMEOUT_S = 90 * 60
TOOLS = "Read Edit Write Glob Grep Bash"
EARLY_HISTORY = 15_000   # aggressive arm: compact whenever history passes this
SUMMARY_TOKENS = 11_000  # post-compaction conversation size observed in pilot rep 1
NATIVE_AUTOCOMPACT = {"native150k": "150000"}  # CLI's own trigger; measured to fire at 69-85k total context
CONTEXT_TRIGGERS = {"150k": 150_000}  # external trigger on total context (the compaction API's default)


class Controller:
    """Tracks context from usage events and decides, between turns, whether to compact."""
    def __init__(self, arm):
        self.arm, self.base, self.ctx, self.growth = arm, None, None, []

    def on_usage(self, u):
        ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        if self.base is None:
            self.base = ctx
        elif self.ctx is not None and ctx > self.ctx:
            self.growth.append(ctx - self.ctx)
        self.ctx = ctx

    def on_compact(self, meta):
        self.ctx = self.base + meta.get("post_tokens", 0)

    def threshold(self):
        if self.arm == "early":
            return EARLY_HISTORY
        if self.arm in CONTEXT_TRIGGERS:
            return CONTEXT_TRIGGERS[self.arm] - self.base
        g = sum(self.growth) / len(self.growth) if self.growth else 2_000.0
        # Claude Code's compaction leaves ~10-13k tokens (measured in the pilot)
        env = sim.Env(system=self.base or 30_000, prices=sim.CLAUDE_CODE,
                      sigma_frac=0.0, sigma_min=SUMMARY_TOKENS, sigma_max=SUMMARY_TOKENS)
        return sim.steady_state_optimum(env, g)

    def should_compact(self):
        if self.arm == "auto" or self.arm in NATIVE_AUTOCOMPACT or self.ctx is None:
            return False
        return self.ctx - self.base >= self.threshold()
# Bash is auto-allowed only inside Claude Code's OS sandbox (writes confined to the workspace).
SANDBOX = json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}})


def out_dir(variant):
    """High-growth runs keep their own ledger, so their budget cap counts only their own spend."""
    return ROOT / "results" / "highgrowth" if is_high_growth(variant) else OUT


def spent(ledger=LEDGER):
    if not ledger.exists():
        return 0.0
    return sum(json.loads(l).get("cost_usd") or 0.0 for l in ledger.read_text().splitlines() if l.strip())


def drive(cmd, ws, env, msgs, stream, controller):
    """Send one user message per turn like a real user; the controller may insert /compact."""
    proc = subprocess.Popen(cmd, cwd=ws, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    deadline = time.time() + TIMEOUT_S
    pending, compacting, events = list(msgs), False, []

    def send(text):
        proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
        proc.stdin.flush()

    send(pending.pop(0))
    with open(stream, "w") as fh:
        for line in proc.stdout:
            fh.write(line)
            if time.time() > deadline:
                proc.kill()
                return "timeout", events
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant" and event.get("message", {}).get("usage"):
                controller.on_usage(event["message"]["usage"])
            if event.get("type") == "system" and event.get("subtype") == "compact_boundary":
                meta = event.get("compact_metadata", {})
                controller.on_compact(meta)
                events.append({"before_message": len(msgs) - len(pending), **meta})
            if event.get("type") != "result":
                continue
            if event.get("subtype") != "success" or not pending:
                break
            if not compacting and controller.should_compact():
                compacting = True
                send("/compact")
            else:
                compacting = False
                send(pending.pop(0))
    proc.stdin.close()
    try:
        return proc.wait(timeout=120), events
    except subprocess.TimeoutExpired:
        proc.kill()
        return "killed", events


def run(variant, arm, rep, cap, max_msgs=None):
    out = out_dir(variant)
    ledger = out / "ledger.jsonl"
    if spent(ledger) >= cap:
        sys.exit(f"budget cap reached: ${spent(ledger):.2f} >= ${cap}")
    tag = f"{variant}-{arm}-r{rep}" + (f"-cal{max_msgs}" if max_msgs else "")
    ws = build(WORK / tag, variant)
    out.mkdir(parents=True, exist_ok=True)
    stream = out / f"{tag}.jsonl"
    msgs = json.loads(messages_path(ws, variant).read_text())
    if max_msgs:  # calibration: opening rules, then the high-growth tail (large bugs, audits), then NOTES.md
        half = (max_msgs - 2) // 2
        n_large = len(LARGE_BUGS)
        large, audit = msgs[-1 - 2 * n_large:-1 - n_large], msgs[-1 - n_large:-1]
        msgs = [msgs[0], *large[:half], *audit[:max_msgs - 2 - half], msgs[-1]]
    cmd = ["claude", "-p", "--input-format", "stream-json", "--model", "sonnet",
           "--autocompact", NATIVE_AUTOCOMPACT.get(arm, "auto"), "--setting-sources", "project", "--strict-mcp-config",
           "--no-session-persistence", "--output-format", "stream-json", "--verbose",
           "--permission-mode", "dontAsk", "--allowedTools", TOOLS,
           "--settings", SANDBOX, "--max-budget-usd", str(PER_RUN_CAP_USD)]
    env = {**os.environ, "CLAUDE_VAULT_SYNC": "off", "ECC_GATEGUARD": "off"}
    start = time.time()
    status, compactions = drive(cmd, ws, env, msgs, stream, Controller(arm))
    row = {"tag": tag, "variant": variant, "arm": arm, "rep": rep, "status": status,
           "seconds": round(time.time() - start), "compaction_events": compactions, **score(ws, stream, variant=variant)}
    with open(ledger, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


if __name__ == "__main__":
    v, a, r = sys.argv[1], sys.argv[2], int(sys.argv[3])
    cap = float(sys.argv[4]) if len(sys.argv) > 4 else 25.0
    max_msgs = int(sys.argv[5]) if len(sys.argv) > 5 else None
    print(json.dumps(run(v, a, r, cap, max_msgs)))
