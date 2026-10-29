"""Build a long-horizon bug-fix workspace for the real-agent compaction pilot.

Twelve standard-library modules are copied into pkg/ with one injected bug each.
Bugs are reported vaguely, one user message at a time, so context grows the
way it does in a real long interactive coding session. Hidden differential tests
(score.py) compare each fixed module against the untouched original.
"""
import json
import random
import shutil
import sys
import sysconfig
from pathlib import Path

STDLIB = Path(sysconfig.get_paths()["stdlib"])

# module -> (line number, original line, mutated line, user-facing report, function)
BUGS = {
    "difflib": (620, "return _calculate_ratio(matches, len(self.a) + len(self.b))",
                "return _calculate_ratio(matches, len(self.a) + len(self.a))",
                "SequenceMatcher.ratio() gives wrong similarity scores when the two sequences differ in length.",
                "ratio"),
    "statistics": (562, "data = sorted(data)", "data = list(data)",
                   "statistics.median() returns wrong answers for some inputs.", "median"),
    "fractions": (460, "t = na * (db // g) + nb * s", "t = na * (db // g) + nb * g",
                  "Adding two Fractions sometimes gives the wrong result.", "_add"),
    "textwrap": (280, "width = self.width - len(indent)", "width = self.width - len(indent) + 1",
                 "textwrap.wrap() sometimes produces lines longer than the requested width.", "_wrap_chunks"),
    "calendar": (104, "return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)",
                 "return year % 4 == 0 and (year % 100 != 0 or year % 40 == 0)",
                 "calendar.isleap() is wrong for some century years.", "isleap"),
    "ipaddress": (782, "return int(self.broadcast_address) - int(self.network_address) + 1",
                  "return int(self.broadcast_address) - int(self.network_address)",
                  "IPv4Network/IPv6Network.num_addresses is off for every network.", "num_addresses"),
    "shlex": (334, "return \"'\" + s.replace(\"'\", \"'\\\"'\\\"'\") + \"'\"",
              "return \"'\" + s.replace(\"'\", \"'\\\"'\") + \"'\"",
              "shlex.quote() output is parsed incorrectly by the shell when the input contains a single quote.",
              "quote"),
    "colorsys": (132, "s = rangec / maxc", "s = rangec / (maxc + minc)",
                 "colorsys.rgb_to_hsv() returns the wrong saturation.", "rgb_to_hsv"),
    "string": (48, "return (sep or ' ').join(map(str.capitalize, s.split(sep)))",
               "return (sep or ' ').join(map(str.title, s.split(sep)))",
               "string.capwords() mangles words that contain apostrophes or hyphens.", "capwords"),
    "html": (21, 's = s.replace(">", "&gt;")', 's = s.replace(">", "&lt;")',
             "html.escape() output renders some characters wrongly in a browser.", "escape"),
    "fnmatch": (92, "add('.')", "add('.?')",
                "fnmatch's '?' wildcard matches filenames it should not.", "translate"),
    "pprint": (179, "max_width = self._width - indent - allowance", "max_width = self._width - indent + allowance",
               "pprint.pformat() sometimes keeps a structure on one line even though it exceeds the width.",
               "_format"),
}

SOURCES = {"html": "html/__init__.py"}

# High-growth variant: eight large pure-Python modules (1.4-3.3k lines), one bug each, reported by
# symptom only, plus an end-to-end audit of each module, so the agent reads whole files.
LARGE_BUGS = {
    "argparse": (1053, "items.append(values)", "items = [values]",
                 "an option declared with action='append' keeps only the last value when given several times.",
                 "_AppendAction"),
    "pathlib": (639, "if 0 < i < len(name) - 1:", "if 0 <= i < len(name) - 1:",
                "PurePath.suffix reports a suffix for hidden dotfiles such as '.bashrc'.", "suffix"),
    "configparser": (609, "'0': False, 'no': False, 'false': False, 'off': False}",
                     "'0': False, 'no': False, 'false': False, 'off': True}",
                     "ConfigParser.getboolean() returns the wrong value for one of the documented false spellings.",
                     "BOOLEAN_STATES"),
    "inspect": (879, "margin = min(margin, indent)", "margin = min(margin, indent + 1)",
                "inspect.cleandoc() sometimes chops the first character off docstring lines.", "cleandoc"),
    "ast": (108, "return left - right", "return left + right",
            "ast.literal_eval() mis-evaluates some complex-number literals.", "literal_eval"),
    "dataclasses": (1065, "for name, op in [('__lt__', '<'),", "for name, op in [('__lt__', '<='),",
                    "with order=True, `a < b` is True for some pairs of equal instances.", "_process_class"),
    "tarfile": (1130, 'itn(info.get("mtime", 0), 12, format),', 'itn(info.get("mtime", 0) - 3600, 12, format),',
                "member modification times are wrong after writing an archive and reading it back.",
                "_create_header"),
    "optparse": (413, "radix = 8", "radix = 10",
                 "options with type='int' parse values with a leading zero (such as 017) incorrectly.", "_parse_num"),
}
LAST_TOPLEVEL = {"argparse": "ArgumentParser", "pathlib": "WindowsPath", "configparser": "ConverterMapping",
                 "inspect": "_main", "ast": "main", "dataclasses": "replace", "tarfile": "main",
                 "optparse": "_match_abbrev"}
RULE5_TOKEN = "CPB-5"

ORDERS = {
    "v1": ["calendar", "difflib", "shlex", "statistics", "html", "ipaddress",
           "colorsys", "fractions", "pprint", "textwrap", "string", "fnmatch"],
    "v2": ["pprint", "ipaddress", "string", "textwrap", "fnmatch", "difflib",
           "calendar", "shlex", "fractions", "colorsys", "statistics", "html"],
    "v3": ["fractions", "colorsys", "statistics", "fnmatch", "textwrap", "html",
           "difflib", "string", "ipaddress", "pprint", "calendar", "shlex"],
}

CONSTRAINTS = """Ground rules for this whole session (they apply to every request I send, until the very end):
1. Every line you change in pkg/ must end with the comment `# BUGFIX`.
2. Do not create any new files inside pkg/ (put scratch scripts in scratch/).
3. Do not read or import the Python standard library's own copies of these modules; work only from pkg/.
4. Do not write any notes or summary files until I ask; when I do, NOTES.md must list, for each module
   you fixed, the function you changed and the exact original buggy expression you replaced."""


PUBLIC_API = {"fractions": "Fraction.__add__", "textwrap": "wrap", "pprint": "pformat"}
FOLLOWUP = ("Next request: write scratch/test_{m}.py with five focused unit tests for {f}() in pkg/{m}.py "
            "(plain asserts, no frameworks), run it with python3, and fix the tests if any are wrong.")


def messages(order, long=False):
    """One user message per request, as in a long interactive session; rules come only first.
    The long variant adds twelve test-writing requests between the fixes and the final
    NOTES.md request, so recalling the fixes must survive any compactions in between."""
    first = (f"You are maintaining a vendored copy of {len(order)} Python modules in pkg/. I will send bug "
             f"reports one at a time.\n\n{CONSTRAINTS}\n\nRun scripts with `python3`. Each report has exactly "
             f"one root cause; read the relevant code and verify your fix with a quick script.\n\n"
             f"First report: pkg/{order[0]}.py: {BUGS[order[0]][3]}")
    rest = [f"Next report: pkg/{m}.py: {BUGS[m][3]}" for m in order[1:]]
    followups = [FOLLOWUP.format(m=m, f=PUBLIC_API.get(m, BUGS[m][4])) for m in order] if long else []
    final = "That's all for today. Now write NOTES.md as required by rule 4."
    return [first, *rest, *followups, final]


RULE5 = (f"One more ground rule, effective now for the rest of the session: 5. Every file you create in "
         f"scratch/ from now on must have the token {RULE5_TOKEN} on its first line.")
AUDIT = ("Next request: audit pkg/{m}.py end to end. Read the entire file, every line (do not rely on grep), "
         "then write scratch/audit_{m}.md with (a) the file's exact line count, (b) the name of the last "
         "top-level function or class defined in it, and (c) three spots you consider fragile, with line numbers.")


def is_high_growth(variant):
    return variant.startswith("h")


def high_growth_order(variant):
    """Seeded orderings h1-h5 of the small bugs, the large bugs, and the audits."""
    rng = random.Random(int(variant[1:]))
    small, large, audits = list(BUGS), list(LARGE_BUGS), list(LARGE_BUGS)
    for xs in (small, large, audits):
        rng.shuffle(xs)
    return small, large, audits


def high_growth_messages(variant):
    """Small bugs (rule 5 arrives after the ninth), then large bugs, audits, and NOTES.md."""
    small, large, audits = high_growth_order(variant)
    msgs = messages(small)[:-1]
    msgs[0] = msgs[0].replace(f"{len(BUGS)} Python modules", f"{len(BUGS) + len(LARGE_BUGS)} Python modules")
    msgs.insert(9, RULE5)
    msgs += [f"Next report: pkg/{m}.py: {LARGE_BUGS[m][3]}" for m in large]
    msgs += [AUDIT.format(m=m) for m in audits]
    return [*msgs, "That's all for today. Now write NOTES.md as required by rule 4."]


def _write_mutated(dest, mod, bug):
    lineno, orig, mutated = bug[:3]
    lines = (STDLIB / SOURCES.get(mod, f"{mod}.py")).read_text().splitlines(keepends=True)
    assert lines[lineno - 1].strip() == orig, (mod, lines[lineno - 1])
    lines[lineno - 1] = lines[lineno - 1].replace(orig, mutated)
    (dest / "pkg" / f"{mod}.py").write_text("".join(lines))


def bugs_for(variant):
    return {**BUGS, **LARGE_BUGS} if is_high_growth(variant) else BUGS


def messages_path(dest, variant):
    """High-growth variants keep the script outside the workspace so the agent cannot read ahead."""
    dest = Path(dest)
    return dest.parent / f"{dest.name}.messages.json" if is_high_growth(variant) else dest / "MESSAGES.json"


def build(dest, variant):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "pkg").mkdir(parents=True)
    (dest / "scratch").mkdir()
    (dest / "pkg" / "__init__.py").write_text("")
    for mod, bug in bugs_for(variant).items():
        _write_mutated(dest, mod, bug)
    if is_high_growth(variant):
        msgs = high_growth_messages(variant)
    else:
        msgs = messages(ORDERS[variant.rstrip("L")], long=variant.endswith("L"))
    messages_path(dest, variant).write_text(json.dumps(msgs))
    return dest


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
