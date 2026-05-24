from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pymongo import UpdateOne


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.behavior.schemas import OnboardingState, PrivacySettings, UserDocument
from src.config import get_settings
from src.schemas import to_mongo_dict
from src.utils import utc_now_iso


def build_user_doc_from_profile(profile_doc: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    user_id_hash = str(profile_doc.get("user_id_hash") or "").strip()
    if not user_id_hash:
        raise ValueError("profile_doc.user_id_hash is required")
    timestamp = now or utc_now_iso()
    explicit_prefs = profile_doc.get("explicit_prefs") if isinstance(profile_doc.get("explicit_prefs"), dict) else {}
    doc = UserDocument(
        _id=user_id_hash,
        user_id_hash=user_id_hash,
        profile_status=profile_doc.get("profile_status") or "warm",
        privacy=PrivacySettings(allow_personalization=True, allow_clickstream_logging=True),
        onboarding=OnboardingState(
            completed=explicit_prefs.get("source") == "onboarding",
            selected_categories=list(explicit_prefs.get("categories", [])),
            selected_price_buckets=list(explicit_prefs.get("price_buckets", [])),
            selected_seed_item_ids=list(explicit_prefs.get("seed_item_ids", [])),
        ),
        created_at=profile_doc.get("updated_at") or timestamp,
        updated_at=profile_doc.get("updated_at") or timestamp,
    )
    mongo_doc = to_mongo_dict(doc)
    mongo_doc["demo_label"] = f"Profile-backed shopper {user_id_hash[-6:]}"
    mongo_doc["demo_source"] = "user_profile_sync"
    return mongo_doc


def build_sync_operations(profile_docs: list[dict[str, Any]], *, now: str | None = None) -> list[UpdateOne]:
    operations = []
    for profile_doc in profile_docs:
        user_doc = build_user_doc_from_profile(profile_doc, now=now)
        created_doc = dict(user_doc)
        created_doc.pop("updated_at", None)
        operations.append(
            UpdateOne(
                {"user_id_hash": user_doc["user_id_hash"]},
                {
                    "$setOnInsert": created_doc,
                    "$set": {
                        "profile_status": user_doc["profile_status"],
                        "onboarding": user_doc["onboarding"],
                        "demo_label": user_doc["demo_label"],
                        "demo_source": user_doc["demo_source"],
                        "updated_at": user_doc["updated_at"],
                    },
                },
                upsert=True,
            )
        )
    return operations


def sync_demo_users_from_profiles(
    *,
    users_collection: Any,
    user_profiles_collection: Any,
    write: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    cursor = user_profiles_collection.find(
        {},
        {
            "_id": 0,
            "user_id_hash": 1,
            "profile_status": 1,
            "explicit_prefs": 1,
            "updated_at": 1,
        },
    ).sort("updated_at", -1)
    if limit is not None:
        cursor = cursor.limit(limit)
    profile_docs = [doc for doc in cursor if str(doc.get("user_id_hash") or "").strip()]
    operations = build_sync_operations(profile_docs)
    result: dict[str, Any] = {
        "mode": "write" if write else "dry-run",
        "profiles_seen": len(profile_docs),
        "planned_upserts": len(operations),
        "sample_user_ids": [doc["user_id_hash"] for doc in profile_docs[:5]],
    }
    if not write or not operations:
        return result

    write_result = users_collection.bulk_write(operations, ordered=False)
    result["write_result"] = {
        "matched_count": write_result.matched_count,
        "modified_count": write_result.modified_count,
        "upserted_count": write_result.upserted_count,
    }
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create demo users from existing user_profiles so the React selector can choose profile-backed users. "
            "Dry-run is the default and this script never modifies profiles, items, or retrieval_units."
        )
    )
    parser.add_argument("--write", action="store_true", help="Upsert users from existing profiles.")
    parser.add_argument("--limit", type=int, default=None, help="Optional profile limit for dry-run/sample sync.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    payload: dict[str, Any] = {
        "target_database": settings.mongodb_db_name,
        "write_requested": bool(args.write),
    }

    from src.mongodb import get_user_profiles_collection, get_users_collection

    result = sync_demo_users_from_profiles(
        users_collection=get_users_collection(),
        user_profiles_collection=get_user_profiles_collection(),
        write=bool(args.write),
        limit=args.limit,
    )
    payload.update(result)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
