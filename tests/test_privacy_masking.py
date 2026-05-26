from __future__ import annotations

from src.auth.privacy import mask_email, mask_user_id, sanitize_debug_payload, strip_secret_fields


def test_secret_fields_are_redacted_recursively() -> None:
    payload = {
        "ADMIN_TOKEN": "hidden",
        "nested": {"TAVILY_API_KEY": "key", "safe": "ok"},
        "items": [{"password": "pw"}],
    }

    sanitized = strip_secret_fields(payload)

    assert sanitized["ADMIN_TOKEN"] == "[redacted]"
    assert sanitized["nested"]["TAVILY_API_KEY"] == "[redacted]"
    assert sanitized["nested"]["safe"] == "ok"
    assert sanitized["items"][0]["password"] == "[redacted]"


def test_user_ids_are_stably_masked() -> None:
    masked = mask_user_id("user_raw_123")

    assert masked == mask_user_id("user_raw_123")
    assert masked.startswith("user_")
    assert "user_raw_123" not in masked


def test_email_masking_preserves_domain() -> None:
    assert mask_email("alice@example.com") == "al***@example.com"


def test_sanitize_debug_payload_preserves_counts_and_masks_raw_identity() -> None:
    original = {
        "counts": {"clickstream_events": 12},
        "user": {"user_id_hash": "u_1", "email": "judge@example.com"},
        "recent_events": [{"user_id_hash": "u_1", "event_id": "evt_1"}],
        "params": {"token": "secret-token"},
    }

    sanitized = sanitize_debug_payload(original)

    assert sanitized["counts"] == {"clickstream_events": 12}
    assert sanitized["user"]["user_id_hash"] != "u_1"
    assert sanitized["user"]["email"] == "ju***@example.com"
    assert sanitized["recent_events"][0]["event_id"] == "evt_1"
    assert sanitized["params"]["token"] == "[redacted]"
    assert original["user"]["user_id_hash"] == "u_1"

