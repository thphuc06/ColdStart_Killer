from __future__ import annotations

from scripts.sync_demo_users_from_profiles import build_sync_operations, sync_demo_users_from_profiles


class FakeCursor(list):
    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        return FakeCursor(self[:n])


class FakeProfilesCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, *_args, **_kwargs):
        return FakeCursor(self.docs)


class FakeUsersCollection:
    def __init__(self):
        self.bulk_write_calls = []

    def bulk_write(self, operations, ordered=False):
        self.bulk_write_calls.append((operations, ordered))
        raise AssertionError("bulk_write should not run in dry-run")


def test_sync_demo_users_from_profiles_dry_run_does_not_write() -> None:
    users = FakeUsersCollection()
    profiles = FakeProfilesCollection([{"user_id_hash": "u_syn_1", "profile_status": "warm"}])

    result = sync_demo_users_from_profiles(
        users_collection=users,
        user_profiles_collection=profiles,
        write=False,
    )

    assert result["mode"] == "dry-run"
    assert result["planned_upserts"] == 1
    assert users.bulk_write_calls == []


def test_build_sync_operations_are_idempotent_upserts() -> None:
    operations = build_sync_operations([{"user_id_hash": "u_syn_1", "profile_status": "warm"}], now="2026-01-01")

    assert len(operations) == 1
    operation = operations[0]
    assert operation._filter == {"user_id_hash": "u_syn_1"}
    assert operation._upsert is True
    assert operation._doc["$set"]["profile_status"] == "warm"
    assert operation._doc["$setOnInsert"]["user_id_hash"] == "u_syn_1"
    assert set(operation._doc["$set"]).isdisjoint(operation._doc["$setOnInsert"])
