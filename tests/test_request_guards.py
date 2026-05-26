from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.request_guards import get_user_privacy_settings


class FailingUsersCollection:
    def find_one(self, *_args, **_kwargs):
        raise RuntimeError("db unavailable")


def test_get_user_privacy_settings_returns_defaults_when_collection_fails() -> None:
    privacy = get_user_privacy_settings("u_demo", users_collection=FailingUsersCollection())

    assert privacy["allow_personalization"] is False
    assert privacy["allow_clickstream_logging"] is False


def test_get_user_privacy_settings_reads_user_flags_when_available() -> None:
    class StubUsersCollection:
        def find_one(self, *_args, **_kwargs):
            return {
                "privacy": {
                    "allow_personalization": False,
                    "allow_clickstream_logging": False,
                }
            }

    privacy = get_user_privacy_settings("u_demo", users_collection=StubUsersCollection())

    assert privacy == {
        "allow_personalization": False,
        "allow_clickstream_logging": False,
    }