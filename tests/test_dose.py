import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import dose  # noqa: E402


def test_fe_slope_ignores_ordering_level_differences():
    # Arrange: same slope (-1 per compaction) in two orderings with different baselines
    a = np.array([[0, 20], [2, 18], [4, 16]], float)
    b = np.array([[0, 10], [2, 8]], float)
    # Act / Assert
    assert dose.fe_slope([a, b]) == -1.0


def test_refetch_counts_distinct_files_reread_after_a_compaction(tmp_path):
    def read(f):
        return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read",
                                                              "input": {"file_path": f}}]}}
    boundary = {"type": "system", "subtype": "compact_boundary"}
    events = [read("a"), read("a"), read("b"), boundary, read("a"), read("a"), read("c"), boundary, read("b")]
    stream = tmp_path / "s.jsonl"
    stream.write_text("\n".join(map(json.dumps, events)))
    # a after the first compaction, b after the second: 2 files over 2 compactions
    assert dose.refetch_rate(stream) == 1.0


def test_refetch_is_undefined_without_compactions(tmp_path):
    stream = tmp_path / "s.jsonl"
    stream.write_text(json.dumps({"type": "assistant", "message": {"content": []}}))
    assert dose.refetch_rate(stream) is None
