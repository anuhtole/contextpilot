"""Score a finished pilot run: hidden differential tests, constraint probes, and usage."""
import difflib as std_difflib
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

from build import BUGS, SOURCES, STDLIB

STDLIB_PEEK = re.compile(r"lib/python3|inspect\.getsource|sysconfig\.get_paths")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rng, alphabet="abc xyz-'", n=30):
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(0, n)))


def _nested(rng, depth=0):
    if depth > 2 or rng.random() < 0.3:
        return rng.choice([rng.randint(0, 10 ** 6), _text(rng), None])
    return {f"k{i}": _nested(rng, depth + 1) for i in range(rng.randint(1, 4))}


# module -> function(module, rng) producing a comparable value from random inputs
PROBES = {
    "difflib": lambda m, r: m.SequenceMatcher(None, _text(r, "abcd", 12), _text(r, "abcd", 12)).ratio(),
    "statistics": lambda m, r: m.median([r.randint(-50, 50) for _ in range(r.randint(1, 9))]),
    "fractions": lambda m, r: (lambda f: (f.numerator, f.denominator))(
        m.Fraction(r.randint(-30, 30), r.randint(1, 30)) + m.Fraction(r.randint(-30, 30), r.randint(1, 30))),
    "textwrap": lambda m, r: m.wrap(" ".join("x" * r.randint(1, 9) for _ in range(r.randint(1, 30))),
                                    width=r.randint(5, 30), initial_indent=" " * r.randint(0, 3)),
    "calendar": lambda m, r: m.isleap(r.choice([r.randint(1, 4000), 100 * r.randint(1, 40)])),
    "ipaddress": lambda m, r: m.ip_network(f"10.{r.randint(0, 255)}.0.0/{r.randint(8, 32)}", strict=False).num_addresses,
    "shlex": lambda m, r: m.quote(_text(r)),
    "colorsys": lambda m, r: m.rgb_to_hsv(r.random(), r.random(), r.random()),
    "string": lambda m, r: m.capwords(_text(r)),
    "html": lambda m, r: m.escape(_text(r, "a<>&'\" ", 20)),
    "fnmatch": lambda m, r: m.fnmatchcase(_text(r, "ab", 4), _text(r, "ab?*", 4)),
    "pprint": lambda m, r: m.pformat(_nested(r), width=r.randint(10, 60)),
}


def check(mod_name, fixed, orig, seed, trials=300):
    """True when the fixed module matches the original on randomized inputs."""
    for t in range(trials):
        if PROBES[mod_name](fixed, random.Random(seed * 1000 + t)) != PROBES[mod_name](orig, random.Random(seed * 1000 + t)):
            return False
    return True


def _norm(text):
    return re.sub(r"[\s`'\"]", "", text)


def recall(notes, mod_name):
    """(function named next to the module, buggy expression reproduced) for one module."""
    _, _, mutated, _, func = BUGS[mod_name]
    lines = [l for l in notes.splitlines() if mod_name in l or func in l]
    expr_variants = {_norm(mutated), _norm(mutated.split("=", 1)[-1]), _norm(mutated.replace("return", "", 1))}
    blob = _norm(notes)
    return any(func in l for l in lines), any(v and v in blob for v in expr_variants)


def untagged_changes(path, mod_name):
    orig = (STDLIB / SOURCES.get(mod_name, f"{mod_name}.py")).read_text().splitlines()
    new = Path(path).read_text().splitlines()
    added = [l for l in std_difflib.unified_diff(orig, new, lineterm="", n=0)
             if l.startswith("+") and not l.startswith("+++")]
    return sum("# BUGFIX" not in l for l in added)


def usage(stream_path):
    calls, peak, compactions, cost, tool_inputs = 0, 0, 0, None, []
    seen = set()
    text = Path(stream_path).read_text() if Path(stream_path).exists() else ""
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "system" and r.get("subtype") == "compact_boundary":
            compactions += 1
        if r.get("type") == "assistant":
            m = r.get("message", {})
            for c in m.get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    tool_inputs.append(json.dumps(c.get("input")))
            if m.get("id") in seen or not m.get("usage"):
                continue
            seen.add(m.get("id"))
            u = m["usage"]
            calls += 1
            peak = max(peak, u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                       + u.get("cache_creation_input_tokens", 0))
        if r.get("type") == "result":
            cost = r.get("total_cost_usd")
    return {"cost_usd": cost, "calls": calls, "peak_context": peak, "compactions": compactions,
            "c3_stdlib_peek": sum(bool(STDLIB_PEEK.search(t)) for t in tool_inputs)}


def score(workspace, stream_path, seed=0):
    ws = Path(workspace)
    fixed = {}
    for mod_name in BUGS:
        try:
            mod = load(ws / "pkg" / f"{mod_name}.py", f"ws_{mod_name}")
            fixed[mod_name] = check(mod_name, mod, importlib.import_module(mod_name), seed)
        except Exception:
            fixed[mod_name] = False
    notes_path = ws / "NOTES.md"
    notes = notes_path.read_text() if notes_path.exists() else ""
    rec = {m: recall(notes, m) for m in BUGS if fixed[m]}
    expected_files = {"__init__.py", *(f"{m}.py" for m in BUGS)}
    return {
        "fixed": fixed,
        "n_fixed": sum(fixed.values()),
        "c1_untagged_lines": sum(untagged_changes(ws / "pkg" / f"{m}.py", m) for m in BUGS),
        "c2_new_files": len({p.name for p in (ws / "pkg").iterdir() if p.is_file()} - expected_files),
        "notes_written": bool(notes),
        "recall_function": sum(f for f, _ in rec.values()),
        "recall_expression": sum(e for _, e in rec.values()),
        **usage(stream_path),
    }


if __name__ == "__main__":
    print(json.dumps(score(sys.argv[1], sys.argv[2]), indent=2))
