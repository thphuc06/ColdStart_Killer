from __future__ import annotations

import pytest

from scripts.reset_demo_behavior_data import build_reset_targets, execute_reset, main, validate_reset_targets


class DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, count: int) -> None:
        self.count = count
        self.deleted_filters = []

    def count_documents(self, filter_doc):
        return self.count

    def delete_many(self, filter_doc):
        self.deleted_filters.append(filter_doc)
        return DeleteResult(self.count)


class FakeDatabase:
    def __init__(self) -> None:
        self.collections = {}

    def __getitem__(self, name: str):
        self.collections.setdefault(name, FakeCollection(3))
        return self.collections[name]


def test_reset_targets_never_include_catalog_collections() -> None:
    soft_targets = build_reset_targets(full=False)
    full_targets = build_reset_targets(full=True)

    assert {target.collection for target in soft_targets}.isdisjoint({"items", "retrieval_units"})
    assert {target.collection for target in full_targets}.isdisjoint({"items", "retrieval_units"})


def test_validate_reset_targets_refuses_catalog_collections() -> None:
    with pytest.raises(ValueError, match="catalog"):
        validate_reset_targets([type("Target", (), {"collection": "items"})()])


def test_reset_dry_run_does_not_delete() -> None:
    database = FakeDatabase()

    result = execute_reset(database, full=False, write=False)

    assert result["mode"] == "dry-run"
    assert result["reset_type"] == "soft"
    assert result["dry_run"] is True
    assert "items" in result["protected_collections"]
    assert "item_item_cf_edges" in result["kept_collections"]
    assert result["rebuild_order"]
    assert all(not collection.deleted_filters for collection in database.collections.values())


def test_reset_write_requires_confirmation() -> None:
    with pytest.raises(RuntimeError, match="Confirmation required"):
        execute_reset(FakeDatabase(), full=True, write=True)


def test_reset_write_deletes_only_allowlisted_behavior_collections() -> None:
    database = FakeDatabase()

    result = execute_reset(database, full=True, write=True, confirm="FULL_DEMO_RESET")

    assert result["mode"] == "write"
    assert "items" not in result["deleted"]
    assert "retrieval_units" not in result["deleted"]
    assert result["deleted"]["clickstream_events"] == 3


def test_reset_cli_accepts_explicit_dry_run(monkeypatch, capsys) -> None:
    import src.mongodb as mongodb

    monkeypatch.setattr(mongodb, "get_database", lambda: FakeDatabase())

    result = main(["--soft", "--dry-run"])
    captured = capsys.readouterr()

    assert result == 0
    assert '"mode": "dry-run"' in captured.out
    assert "item_item_cf_edges" in captured.out


def test_reset_cli_rejects_write_and_dry_run_together(capsys) -> None:
    result = main(["--full", "--dry-run", "--write"])
    captured = capsys.readouterr()

    assert result == 2
    assert "choose either --dry-run or --write" in captured.err


def test_reset_cli_rejects_write_without_confirmation_before_preflight(capsys) -> None:
    result = main(["--full", "--write"])
    captured = capsys.readouterr()

    assert result == 2
    assert "Confirmation required" in captured.out
    assert "about_to_write" not in captured.err
