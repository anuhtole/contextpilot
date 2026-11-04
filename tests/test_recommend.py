import json

import numpy as np
import pytest

from contextpilot import recommend, replay, traces

MODEL = "claude-opus-5-5"


def usage(i, ctx, written, out=1_000, model=MODEL):
    return {"type": "assistant", "message": {"id": f"m{i}", "model": model, "usage": {
        "input_tokens": 0, "cache_read_input_tokens": ctx - written,
        "cache_creation_input_tokens": written, "output_tokens": out}}}


def session_lines(n_calls, growth, system=20_000):
    """A warm session whose context grows by `growth` tokens per call."""
    return [usage(i, system + i * growth, system if i == 0 else growth) for i in range(n_calls)]


def write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(map(json.dumps, lines)))


@pytest.fixture
def projects(tmp_path):
    for k in range(3):
        write(tmp_path / "-Users-x-proj" / f"s{k}.jsonl", session_lines(300, 3_000))
    write(tmp_path / "-Users-x-proj" / "s0" / "subagents" / "a.jsonl", session_lines(20, 2_000))
    write(tmp_path / "-Users-x-observer-sessions" / "o.jsonl", session_lines(50, 1_000))
    write(tmp_path / "-private-tmp-bench" / "b.jsonl", session_lines(50, 1_000))
    return tmp_path


def test_load_sessions_excludes_observer_and_tmp_benchmarks(projects):
    sessions = traces.load_sessions(str(projects))
    assert sorted(s["src"] for s in sessions) == ["main", "main", "main", "subagent"]


def test_increments_do_not_double_count_a_rewind():
    s = {"turns": [{"in": 0, "cr": c, "cw": 0, "out": 0, "model": MODEL} for c in (100, 150, 120, 160, 170)]}
    assert traces.increments(s).tolist() == [0, 50, 0, 10, 10]


def test_increments_reset_at_compaction():
    rows = [{"in": 0, "cr": c, "cw": 0, "out": 0, "model": MODEL} for c in (100, 300, 50, 80)]
    s = {"turns": [*rows[:2], {"compact": 1}, *rows[2:]]}
    assert traces.compaction_calls(s) == [2]
    assert traces.increments(s).tolist() == [0, 200, 0, 30]


def test_cold_calls_flag_full_rewrites_but_not_the_first_call():
    s = {"turns": [traces.usage_row(usage(i, c, w)["message"]) for i, (c, w) in
                   enumerate([(100, 100), (110, 10), (120, 120), (130, 10)])]}
    assert traces.cold_calls(s).tolist() == [False, False, True, False]


def test_logged_dollars_uses_one_hour_write_and_model_read_price():
    s = {"turns": [{"in": 1_000_000, "cr": 1_000_000, "cw": 1_000_000, "out": 1_000_000, "model": MODEL}]}
    price, read = replay.MODEL_PRICES[MODEL]
    assert replay.logged_dollars(s) == pytest.approx(price * (1 + read + 2 + 5))


def test_observed_schedule_replays_a_warm_log_closely(projects):
    s = traces.load_sessions(str(projects))[0]
    simulated, n = replay.cost(s, replay.ObservedSchedule(traces.compaction_calls(s)))
    assert n == 0
    assert simulated == pytest.approx(replay.logged_dollars(s), rel=0.05)


def test_settings_clamp_to_claude_code_and_api_limits():
    assert recommend.settings_for(10_000) == {"autoCompactWindow": 100_000, "api_compact_trigger": 50_000}
    assert recommend.settings_for(200_000) == {"autoCompactWindow": 275_000, "api_compact_trigger": 200_000}
    assert recommend.settings_for(990_000)["autoCompactWindow"] == 1_000_000


def test_recommend_lowers_the_trigger_and_saves_on_long_sessions(projects):
    r = recommend.recommend(traces.load_sessions(str(projects)))
    assert r["sessions"] == 3 and r["model"] == MODEL
    assert r["growth_per_call"] == pytest.approx(3_000, rel=0.01)
    assert 100_000 <= r["trigger"] < replay.DEFAULT_TRIGGER
    assert r["saved_frac"] > 0 and r["hurt"] == 0
    assert r["trigger"] % recommend.ROUND == 0


def test_recommend_rejects_unknown_model(projects):
    with pytest.raises(ValueError, match="unknown model"):
        recommend.recommend(traces.load_sessions(str(projects)), model="gpt-x")


def test_cli_prints_json(projects, capsys):
    r = recommend.main(["--projects", str(projects), "--json"])
    assert json.loads(capsys.readouterr().out) == r


def test_cli_exits_cleanly_with_no_sessions(tmp_path):
    with pytest.raises(SystemExit) as e:
        recommend.main(["--projects", str(tmp_path)])
    assert e.value.code == 1


def test_trigger_costs_shape(projects):
    sessions = traces.load_sessions(str(projects))[:2]
    grid = np.array([150_000, 490_000])
    assert replay.trigger_costs(sessions, grid).shape == (2, 2)
