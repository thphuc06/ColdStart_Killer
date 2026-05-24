from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from src.recommendation.search_personalizer import personalized_search


router = APIRouter(prefix="/api")


@router.get("/search")
def search(
    user_id_hash: str = Query(..., min_length=1),
    session_id: str = Query(..., min_length=1),
    q: str = Query(..., min_length=1),
    top_k: int = Query(20, ge=1, le=100),
    personalized: bool = True,
) -> dict[str, Any]:
    result = personalized_search(
        user_id_hash=user_id_hash,
        session_id=session_id,
        raw_query=q,
        top_k=top_k,
        personalized=personalized,
    )
    result["user_id_hash"] = user_id_hash
    return result
