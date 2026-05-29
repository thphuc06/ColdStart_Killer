"""Tests for scripts/import_eval_judgments.py."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_import_script_success() -> None:
    # Create a temporary CSV file with judgments
    with tempfile.NamedTemporaryFile(mode="w", newline="", suffix=".csv", delete=False) as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["query_id", "item_id", "relevance", "reason", "labels"])
        writer.writerow(["q001", "item_A", "3", "Matches perfect intent", "cold_item"])
        writer.writerow(["q001", "item_B", "1", "Tangential", ""])
        writer.writerow(["q002", "item_C", "0", "", "new_seller"])
        writer.writerow(["q002", "item_D", "", "", ""])  # Empty relevance (skipped)
        csv_file_name = csv_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as json_file:
        json_file_name = json_file.name

    try:
        # Run import script via subprocess
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "import_eval_judgments.py"),
            "--csv", csv_file_name,
            "--out", json_file_name,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert "Successfully imported 3 judgments" in result.stdout
        assert "Skipped 1 empty rows" in result.stdout

        # Read output and verify
        with open(json_file_name, "r", encoding="utf-8") as f:
            judgments = json.load(f)

        assert len(judgments) == 3
        assert judgments[0] == {
            "query_id": "q001",
            "item_id": "item_A",
            "relevance": 3,
            "reason": "Matches perfect intent",
            "labels": ["cold_item"],
            "judgment_source": "human_audited",
            "annotator_id": "",
            "audited_at": "",
        }
        assert judgments[1] == {
            "query_id": "q001",
            "item_id": "item_B",
            "relevance": 1,
            "reason": "Tangential",
            "labels": [],
            "judgment_source": "human_audited",
            "annotator_id": "",
            "audited_at": "",
        }
        assert judgments[2] == {
            "query_id": "q002",
            "item_id": "item_C",
            "relevance": 0,
            "reason": "",
            "labels": ["new_seller"],
            "judgment_source": "human_audited",
            "annotator_id": "",
            "audited_at": "",
        }

    finally:
        # Cleanup
        try:
            Path(csv_file_name).unlink()
            Path(json_file_name).unlink()
        except OSError:
            pass


def test_import_script_accepts_auditor_metadata() -> None:
    with tempfile.NamedTemporaryFile(mode="w", newline="", suffix=".csv", delete=False) as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["query_id", "item_id", "relevance", "reason", "labels", "annotator_id", "audited_at"])
        writer.writerow(["q001", "item_A", "3", "Human checked", "core", "auditor_a", "2026-05-29T12:00:00+00:00"])
        csv_file_name = csv_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as json_file:
        json_file_name = json_file.name

    try:
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "import_eval_judgments.py"),
            "--csv", csv_file_name,
            "--out", json_file_name,
            "--judgment-source", "mixed",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert "Successfully imported 1 judgments" in result.stdout

        judgments = json.loads(Path(json_file_name).read_text(encoding="utf-8"))
        assert judgments[0]["judgment_source"] == "mixed"
        assert judgments[0]["annotator_id"] == "auditor_a"
        assert judgments[0]["audited_at"] == "2026-05-29T12:00:00+00:00"

    finally:
        try:
            Path(csv_file_name).unlink()
            Path(json_file_name).unlink()
        except OSError:
            pass


def test_import_script_strict_failure() -> None:
    # Create a temporary CSV with an empty relevance value
    with tempfile.NamedTemporaryFile(mode="w", newline="", suffix=".csv", delete=False) as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["query_id", "item_id", "relevance", "reason", "labels"])
        writer.writerow(["q001", "item_A", "", "Missing relevance", ""])
        csv_file_name = csv_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as json_file:
        json_file_name = json_file.name

    try:
        # Run import script with --strict
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "import_eval_judgments.py"),
            "--csv", csv_file_name,
            "--out", json_file_name,
            "--strict",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode != 0
        assert "ERROR: Row 2 has empty relevance, but --strict is enabled." in result.stderr

    finally:
        # Cleanup
        try:
            Path(csv_file_name).unlink()
            Path(json_file_name).unlink()
        except OSError:
            pass
