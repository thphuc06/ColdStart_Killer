from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from src.recommendation.search_personalizer import personalized_search
from .request_guards import personalization_enabled_for_user


router = APIRouter(prefix="/api")


@router.get("/search")
def search(
    user_id_hash: str = Query(..., min_length=1),
    session_id: str = Query(..., min_length=1),
    q: str = Query(..., min_length=1),
    top_k: int = Query(20, ge=1, le=100),
    personalized: bool = True,
) -> dict[str, Any]:
    effective_personalized = personalization_enabled_for_user(
        user_id_hash,
        personalized=personalized,
    )
    result = personalized_search(
        user_id_hash=user_id_hash,
        session_id=session_id,
        raw_query=q,
        top_k=top_k,
        personalized=effective_personalized,
    )
    result["user_id_hash"] = user_id_hash
    return result
