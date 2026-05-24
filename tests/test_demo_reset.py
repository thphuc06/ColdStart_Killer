from __future__ import annotations

import pytest

from scripts import clear_demo_data
from scripts.reset_demo_behavior_data import build_reset_targets


def test_old_clear_demo_data_script_is_quarantined(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["clear_demo_data.py"])
    with pytest.raises(SystemExit, match="Refusing to run"):
        clear_demo_data.main()


def test_phase13_reset_targets_are_behavior_only() -> None:
    target_names = {target.collection for target in build_reset_targets(full=True, include_semantic_neighbors=True)}

    assert "items" not in target_names
    assert "retrieval_units" not in target_names
    assert "recommendation_logs" in target_names
    assert "clickstream_events" in target_names
