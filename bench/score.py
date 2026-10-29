"""Score a finished pilot run: hidden differential tests, constraint probes, and usage."""
import difflib as std_difflib
import importlib.util
import json
import random
import re
import sys
from pathlib import Path

from build import BUGS, LARGE_BUGS, LAST_TOPLEVEL, RULE5_TOKEN, SOURCES, STDLIB, bugs_for

STDLIB_PEEK = re.compile(r"lib/python3|inspect\.getsource|sysconfig\.get_paths")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses looks itself up in sys.modules
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
    "argparse": lambda m, r: _argparse_probe(m, r),
    "pathlib": lambda m, r: m.PurePosixPath(_text(r, "ab.", 6) or "a").suffix,
    "configparser": lambda m, r: _configparser_probe(m, r),
    "inspect": lambda m, r: m.cleandoc("\n".join(" " * r.randint(0, 6) + _text(r, "ab ", 8) for _ in range(r.randint(1, 6)))),
    "ast": lambda m, r: m.literal_eval(f"{r.randint(-9, 9)}{r.choice('+-')}{r.randint(0, 9)}j"),
    "dataclasses": lambda m, r: _dataclass_probe(m, r),
    "tarfile": lambda m, r: _tarfile_probe(m, r),
    "optparse": lambda m, r: _optparse_probe(m, r),
}


def _argparse_probe(m, r):
    parser = m.ArgumentParser(prog="p", exit_on_error=False)
    parser.add_argument("-x", action="append")
    return parser.parse_args(sum((["-x", str(r.randint(0, 9))] for _ in range(r.randint(0, 4))), [])).x


def _configparser_probe(m, r):
    cp = m.ConfigParser()
    word = r.choice(["1", "yes", "true", "on", "0", "no", "false", "off"])
    cp.read_string(f"[s]\nk = {word}\n")
    return cp.getboolean("s", "k")


def _dataclass_probe(m, r):
    cls = m.make_dataclass("P", ["x", "y"], order=True)
    a, b = cls(r.randint(0, 2), r.randint(0, 2)), cls(r.randint(0, 2), r.randint(0, 2))
    return (a < b, a <= b, a > b, a >= b)


def _tarfile_probe(m, r):
    import io
    buf, data = io.BytesIO(), b"x" * r.randint(0, 50)
    info = m.TarInfo("f.txt")
    info.size, info.mtime = len(data), r.randint(10 ** 6, 2 * 10 ** 9)
    with m.open(fileobj=buf, mode="w") as tf:
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    with m.open(fileobj=buf, mode="r") as tf:
        member = tf.getmembers()[0]
        return member.mtime, member.size


def _optparse_probe(m, r):
    parser = m.OptionParser()
    parser.add_option("-n", type="int")
    val = r.choice(["0" + "".join(r.choice("01234567") for _ in range(r.randint(1, 3))),
                    str(r.randint(0, 999)), hex(r.randint(0, 999)), bin(r.randint(0, 99))])
    return parser.parse_args(["-n", val])[0].n


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
    _, _, mutated, _, func = {**BUGS, **LARGE_BUGS}[mod_name]
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


def audits(ws):
    """Per audited module: (audit file exists, line count right within 2, last top-level name right,
    rule-5 token on the first line). Only high-growth runs request audits."""
    out = {}
    for m in LARGE_BUGS:
        path = ws / "scratch" / f"audit_{m}.md"
        if not path.exists():
            out[m] = (False, False, False, False)
            continue
        text = path.read_text()
        n_lines = len((ws / "pkg" / f"{m}.py").read_text().splitlines())
        counts = [int(x) for x in re.findall(r"\b\d{3,5}\b", text.replace(",", ""))]
        out[m] = (True, any(abs(c - n_lines) <= 2 for c in counts), LAST_TOPLEVEL[m] in text,
                  RULE5_TOKEN in (text.splitlines() or [""])[0])
    return out


def rule5_violations(ws):
    """scratch/ files without the rule-5 token; only audit files are certain to postdate rule 5."""
    return sum(RULE5_TOKEN not in (p.read_text(errors="ignore").splitlines() or [""])[0]
               for p in (ws / "scratch").glob("audit_*.md"))


def score(workspace, stream_path, seed=0, variant="v1"):
    ws = Path(workspace)
    bugs = bugs_for(variant)
    fixed = {}
    for mod_name in bugs:
        try:
            mod = load(ws / "pkg" / f"{mod_name}.py", f"ws_{mod_name}")
            fixed[mod_name] = check(mod_name, mod, importlib.import_module(mod_name), seed)
        except Exception:
            fixed[mod_name] = False
    notes_path = ws / "NOTES.md"
    notes = notes_path.read_text() if notes_path.exists() else ""
    rec = {m: recall(notes, m) for m in bugs if fixed[m]}
    expected_files = {"__init__.py", *(f"{m}.py" for m in bugs)}
    extra = {}
    if bugs is not BUGS:
        a = audits(ws)
        extra = {"audits_written": sum(x[0] for x in a.values()), "audit_linecount_ok": sum(x[1] for x in a.values()),
                 "audit_lastdef_ok": sum(x[2] for x in a.values()), "c5_rule5_violations": rule5_violations(ws)}
    return {
        "fixed": fixed,
        "n_fixed": sum(fixed.values()),
        "c1_untagged_lines": sum(untagged_changes(ws / "pkg" / f"{m}.py", m) for m in bugs),
        "c2_new_files": len({p.name for p in (ws / "pkg").iterdir() if p.is_file()} - expected_files),
        "notes_written": bool(notes),
        "recall_function": sum(f for f, _ in rec.values()),
        "recall_expression": sum(e for _, e in rec.values()),
        **extra,
        **usage(stream_path),
    }


if __name__ == "__main__":
    print(json.dumps(score(sys.argv[1], sys.argv[2], variant=sys.argv[3] if len(sys.argv) > 3 else "v1"), indent=2))
