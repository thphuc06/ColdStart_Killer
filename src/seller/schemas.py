from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


DEFAULT_SELLER_ID = "seller_demo_001"


SellerDraftStatus = Literal["draft", "validated", "previewed", "approved", "indexed", "failed", "rejected"]


class SellerDraftPayload(BaseModel):
    seller_id: str = Field(default=DEFAULT_SELLER_ID, min_length=1)
    title: str = Field(default="", max_length=240)
    description: str = Field(default="", max_length=5000)
    brand: str = Field(default="", max_length=160)
    category_id: str = Field(default="", max_length=120)
    price_vnd: int | None = Field(default=None, ge=0)
    price_bucket: str = Field(default="unknown", max_length=80)
    image_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class SellerDraftDocument(SellerDraftPayload):
    draft_id: str
    status: SellerDraftStatus = "draft"
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    proposed_item_id: str
    indexing_preview: dict[str, Any] | None = None
    enrichment: dict[str, Any] | None = None
    source: dict[str, Any] = Field(default_factory=lambda: {"type": "seller", "seller_confirmed": False})
    created_at: str
    updated_at: str
    approved_at: str | None = None
    indexed_at: str | None = None
