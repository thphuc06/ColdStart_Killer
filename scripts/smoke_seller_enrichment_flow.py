from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.app import create_app
from src.config import DEFAULT_ENV_PATH, get_settings
from src.mongodb import get_seller_product_drafts_collection, get_web_enrichment_requests_collection


CRITICAL_OVERRIDE_KEYS = (
    "AUTH_MODE",
    "ENABLE_SELLER_TOOLS",
    "ENABLE_WEB_ENRICHMENT",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run protected seller/enrichment smoke flow (create draft -> preview -> request -> apply) "
            "against the current local backend config."
        )
    )
    parser.add_argument(
        "--role",
        choices=["auto", "seller", "admin"],
        default="auto",
        help="Which token role to use for Authorization header. Default: auto (seller, then admin).",
    )
    parser.add_argument(
        "--allow-env-override",
        action="store_true",
        help=(
            "Allow process-level env overrides for critical keys (AUTH_MODE / ENABLE_SELLER_TOOLS / "
            "ENABLE_WEB_ENRICHMENT). By default, mismatches vs .env fail fast to avoid stale terminal state."
        ),
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not delete the created draft and enrichment request after the smoke run.",
    )
    parser.add_argument(
        "--draft-title-prefix",
        default="Protected Smoke Draft",
        help="Prefix for the temporary seller draft title.",
    )
    return parser.parse_args(argv)


def _critical_overrides(env_path: Path) -> dict[str, dict[str, str]]:
    file_values = dotenv_values(env_path)
    mismatches: dict[str, dict[str, str]] = {}
    for key in CRITICAL_OVERRIDE_KEYS:
        process_value = str(__import__("os").environ.get(key, "")).strip()
        file_value = str(file_values.get(key, "") or "").strip()
        if process_value and file_value and process_value != file_value:
            mismatches[key] = {"process": process_value, "dot_env": file_value}
    return mismatches


def _pick_token(*, role: str, seller_token: str, admin_token: str) -> tuple[str, str]:
    if role == "seller":
        return "seller", seller_token
    if role == "admin":
        return "admin", admin_token
    if seller_token:
        return "seller", seller_token
    return "admin", admin_token


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.allow_env_override:
        overrides = _critical_overrides(DEFAULT_ENV_PATH)
        if overrides:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "env_override_detected",
                        "message": (
                            "Critical env values differ between process env and .env. "
                            "Clear session overrides or rerun with --allow-env-override intentionally."
                        ),
                        "mismatches": overrides,
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2

    settings = get_settings()
    if not settings.enable_seller_tools:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "seller_tools_disabled",
                    "message": "Set ENABLE_SELLER_TOOLS=true before running this smoke.",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    if not settings.enable_web_enrichment:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "web_enrichment_disabled",
                    "message": "Set ENABLE_WEB_ENRICHMENT=true before running this smoke.",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    auth_mode = str(settings.auth_mode or "").strip().lower()
    role_used = "disabled"
    headers: dict[str, str] = {}
    if auth_mode != "disabled":
        role_used, token = _pick_token(
            role=args.role,
            seller_token=str(settings.seller_token or "").strip(),
            admin_token=str(settings.admin_token or "").strip(),
        )
        if not token:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "missing_token",
                        "message": (
                            f"No token available for role={role_used}. Configure ADMIN_TOKEN/SELLER_TOKEN in .env "
                            "or use --role accordingly."
                        ),
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
        headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(create_app())
    draft_id: str | None = None
    request_id: str | None = None
    title = f"{args.draft_title_prefix} {uuid4().hex[:10]}"

    try:
        payload = {
            "title": title,
            "description": "Protected smoke draft for seller enrichment flow validation.",
            "brand": "SmokeBrand",
            "category_id": "All Beauty",
            "price_vnd": 199000,
            "price_bucket": "100k_300k",
            "image_url": "https://example.test/smoke.jpg",
            "attributes": {"spf": "50"},
        }
        create_resp = client.post("/api/seller/drafts", json=payload, headers=headers)
        create_resp.raise_for_status()
        draft_id = create_resp.json()["draft"]["draft_id"]

        preview_resp = client.post(f"/api/enrichment/seller-drafts/{draft_id}/preview", headers=headers)
        preview_resp.raise_for_status()

        request_resp = client.post(f"/api/enrichment/seller-drafts/{draft_id}/request", headers=headers)
        request_resp.raise_for_status()
        request_body = request_resp.json()
        request_id = request_body["request"]["request_id"]
        suggestions = dict(request_body["request"].get("suggested_fields") or {})
        selected = (
            ["attributes.web_evidence_summary"]
            if "attributes.web_evidence_summary" in suggestions
            else (["description"] if "description" in suggestions else [])
        )
        if not selected:
            raise RuntimeError("No applicable enrichment suggestions returned by provider")

        apply_resp = client.post(
            f"/api/enrichment/requests/{request_id}/apply?confirm={settings.web_enrichment_apply_confirmation}",
            json={"fields_to_apply": selected},
            headers=headers,
        )
        apply_resp.raise_for_status()
        apply_body = apply_resp.json()

        print(
            json.dumps(
                {
                    "ok": True,
                    "auth_mode": settings.auth_mode,
                    "role_used": role_used,
                    "create_status": create_resp.status_code,
                    "preview_status": preview_resp.status_code,
                    "request_status": request_resp.status_code,
                    "request_result": request_body.get("status"),
                    "apply_status": apply_resp.status_code,
                    "apply_result": apply_body.get("status"),
                    "applied_fields": apply_body.get("applied_fields", []),
                    "draft_id": draft_id,
                    "request_id": request_id,
                    "cleanup": not bool(args.no_cleanup),
                },
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "smoke_failed",
                    "message": str(exc),
                    "auth_mode": settings.auth_mode,
                    "role_used": role_used,
                    "draft_id": draft_id,
                    "request_id": request_id,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if not args.no_cleanup:
            if request_id:
                get_web_enrichment_requests_collection().delete_many({"request_id": request_id})
            if draft_id:
                get_seller_product_drafts_collection().delete_many({"draft_id": draft_id})


if __name__ == "__main__":
    raise SystemExit(main())
