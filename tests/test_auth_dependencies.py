from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.auth.dependencies import require_admin, require_seller_or_admin
from src.auth.service import extract_bearer_token


def test_disabled_auth_mode_allows_admin_dependency(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.setenv("ADMIN_TOKEN", "")

    context = require_admin()

    assert context.role == "disabled"
    assert context.authenticated is True


def test_demo_auth_missing_admin_token_returns_503(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "")

    with pytest.raises(HTTPException) as exc:
        require_admin()

    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "admin_token_not_configured"


def test_wrong_admin_token_is_rejected_without_exposing_expected(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")

    with pytest.raises(HTTPException) as exc:
        require_admin(x_admin_token="wrong-token")

    assert exc.value.status_code == 403
    assert "expected-token" not in str(exc.value.detail)


def test_bearer_admin_token_passes(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")

    context = require_admin(authorization="Bearer expected-token")

    assert context.authenticated is True
    assert context.role == "admin"


def test_seller_or_admin_accepts_seller_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("SELLER_TOKEN", "seller-token")

    context = require_seller_or_admin(x_seller_token="seller-token")

    assert context.authenticated is True
    assert context.role == "seller"


def test_seller_or_admin_accepts_admin_token(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("SELLER_TOKEN", "")

    context = require_seller_or_admin(authorization="Bearer admin-token")

    assert context.role == "admin"


def test_extract_bearer_token_is_strict() -> None:
    assert extract_bearer_token("Bearer abc") == "abc"
    assert extract_bearer_token("bearer abc") == "abc"
    assert extract_bearer_token("Basic abc") is None
    assert extract_bearer_token("Bearer") is None

