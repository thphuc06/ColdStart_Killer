from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st
from pymongo import UpdateOne


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.embeddings import embed_texts
from src.enrichment import agentic_web_enrich
from src.indexing import build_contextual_header, build_hype_units, build_proposition_units
from src.llm_hype import generate_hype_queries_llm
from src.llm_propositions import extract_propositions_llm
from src.mongodb import collection_counts, get_items_collection, get_retrieval_units_collection, ping_mongodb
from src.normalize_amazon import (
    clean_string,
    content_richness_score,
    details_to_text,
    make_price_bucket,
    slugify_category,
    word_count,
)
from src.product_text import build_product_text_from_parts
from src.utils import parse_jsonish, stable_hash, utc_now_iso


SESSION_KEYS = {
    "generated_item_doc": None,
    "product_text_for_llm": "",
    "enrichment_result": None,
    "enrichment_accepted": False,
    "generated_propositions": [],
    "generated_hype_queries": [],
    "generated_embeddings": [],
    "generated_retrieval_units": [],
    "insert_ready": False,
    "last_insert_result": None,
    "input_signature": "",
}


def init_state() -> None:
    for key, value in SESSION_KEYS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def input_signature(payload: dict) -> str:
    return stable_hash(json.dumps(payload, sort_keys=True, ensure_ascii=False), length=16)


def parse_details(details_text: str) -> dict | str:
    parsed = parse_jsonish(details_text)
    if isinstance(parsed, (dict, list)):
        return parsed
    return clean_string(details_text)


def seller_item_id(title: str, brand: str, category_id: str) -> str:
    base = slugify_category(f"{brand} {title}")[:48] or "seller_product"
    suffix = stable_hash(f"{title}|{brand}|{category_id}", length=8)
    return f"seller_{base}_{suffix}"


def build_seller_item_doc(inputs: dict, seller_confirmed: bool) -> tuple[dict | None, list[str]]:
    errors = []
    title = clean_string(inputs["title_en"])
    category_id = slugify_category(inputs["category_id"])
    category_path = [part.strip() for part in inputs["category_path"].split(",") if part.strip()]
    description = clean_string(inputs["description"])
    features = [line.strip() for line in inputs["features"].splitlines() if line.strip()]
    details = parse_details(inputs["details_json"])
    details_text = details_to_text(details)
    brand = clean_string(inputs["brand"])

    if not title:
        errors.append("title_en is required.")
    if not category_id:
        errors.append("category_id is required.")
    if inputs["price_usd"] is None and inputs["price_vnd"] is None:
        errors.append("At least one price field is required.")
    if not description and not features:
        errors.append("Description or features are required.")
    if errors:
        return None, errors

    price_usd = float(inputs["price_usd"]) if inputs["price_usd"] is not None else None
    price_vnd = int(inputs["price_vnd"]) if inputs["price_vnd"] is not None else None
    if price_vnd is None and price_usd is not None:
        price_vnd = int(round(price_usd * 25_000))
    if price_usd is None and price_vnd is not None:
        price_usd = round(price_vnd / 25_000, 2)

    product_text = build_product_text_from_parts(
        title=title,
        brand=brand,
        category=category_path[0] if category_path else category_id,
        price_vnd=price_vnd,
        features=features,
        description=description,
        details=details,
    )
    title_words = word_count(title)
    description_words = word_count(description)
    features_words = word_count("\n".join(features))
    details_words = word_count(details_text)
    combined_words = description_words + features_words + details_words
    image_url = clean_string(inputs["image_url"]) or None
    now = utc_now_iso()
    item_id = seller_item_id(title, brand, category_id)
    richness = content_richness_score(
        title_words,
        description_words,
        features_words,
        details_words,
        price_usd is not None and price_usd > 0,
        image_url is not None,
        brand != "",
    )
    item = {
        "_id": item_id,
        "raw_parent_asin": item_id,
        "source_dataset": "seller_ui",
        "source_file": "apps/seller_insert_ui.py",
        "source_category": "seller_ui",
        "title_en": title,
        "title_vi": "",
        "brand": brand,
        "brand_source": "seller_input" if brand else "none",
        "category_id": category_id,
        "category_path": category_path or [category_id],
        "raw_main_category": category_path[0] if category_path else category_id,
        "price_usd": price_usd,
        "price_vnd": price_vnd,
        "price_parse_status": "parsed",
        "price_bucket": make_price_bucket(price_vnd),
        "in_stock": True,
        "image_url": image_url,
        "image_urls": [image_url] if image_url else [],
        "content_richness": richness,
        "quality_score": richness,
        "quality_tier": "seller_input",
        "product_text_for_llm": product_text,
        "source_text": {
            "description_text": description,
            "features_text": "\n".join(features),
            "details_text": details_text,
        },
        "text_stats": {
            "title_words": title_words,
            "description_words": description_words,
            "features_words": features_words,
            "details_words": details_words,
            "combined_words": combined_words,
        },
        "cold_start": {
            "is_cold_item": True,
            "interaction_count": 0,
            "rating_number_eval_only": None,
        },
        "description_enriched": {
            "source": "seller_input",
            "enrichment_quality": "not_requested",
            "seller_confirmed": seller_confirmed,
        },
        "created_at": now,
        "updated_at": now,
    }
    return item, []


def current_inputs() -> dict:
    return {
        "title_en": st.session_state.get("title_en", ""),
        "brand": st.session_state.get("brand", ""),
        "category_id": st.session_state.get("category_id", ""),
        "category_path": st.session_state.get("category_path", ""),
        "price_usd": st.session_state.get("price_usd"),
        "price_vnd": st.session_state.get("price_vnd"),
        "description": st.session_state.get("description", ""),
        "features": st.session_state.get("features", ""),
        "details_json": st.session_state.get("details_json", ""),
        "image_url": st.session_state.get("image_url", ""),
    }


@st.cache_data(ttl=10, show_spinner=False)
def _mongodb_status() -> dict:
    ping = ping_mongodb()
    counts = collection_counts() if ping.get("ok") else None
    return {"ping": ping, "counts": counts}


def show_status_panel() -> None:
    st.subheader("MongoDB Status")
    if st.button("Refresh MongoDB Status"):
        _mongodb_status.clear()
    status = _mongodb_status()
    ping = status["ping"]
    if ping.get("ok"):
        st.success("MongoDB connection OK")
        counts = status["counts"] or {}
        if counts.get("ok"):
            col1, col2 = st.columns(2)
            col1.metric("items", counts["items"])
            col2.metric("retrieval_units", counts["retrieval_units"])
    else:
        st.warning(ping.get("error", "MongoDB connection not available"))


def show_input_form() -> tuple[dict, bool]:
    st.subheader("Seller Product Input")
    with st.form("seller_product_form"):
        st.text_input("title_en", key="title_en")
        st.text_input("brand", key="brand")
        st.text_input("category_id", value="all_beauty", key="category_id")
        st.text_input("category_path comma-separated", value="All Beauty", key="category_path")
        col1, col2 = st.columns(2)
        col1.number_input("price_usd", min_value=0.0, step=1.0, value=0.0, key="price_usd")
        col2.number_input("price_vnd", min_value=0, step=1000, value=0, key="price_vnd")
        st.text_area("description", height=140, key="description")
        st.text_area("features one per line", height=140, key="features")
        st.text_area("details JSON", value="{}", height=120, key="details_json")
        st.text_input("image_url", key="image_url")
        seller_confirmed = st.checkbox("seller_confirmed", value=False)
        submitted = st.form_submit_button("Analyze Product")

    inputs = current_inputs()
    if inputs["price_usd"] == 0.0:
        inputs["price_usd"] = None
    if inputs["price_vnd"] == 0:
        inputs["price_vnd"] = None
    return inputs | {"seller_confirmed": seller_confirmed}, submitted


def maybe_warn_input_changed(signature: str) -> None:
    if st.session_state.input_signature and signature != st.session_state.input_signature:
        st.warning("Product input changed. Please regenerate retrieval units before inserting.")


def apply_accepted_enrichment(item: dict) -> dict:
    enrichment = st.session_state.enrichment_result
    if not st.session_state.enrichment_accepted or not enrichment:
        return item
    enriched_description = clean_string(enrichment.get("enriched_description"))
    if not enriched_description:
        return item
    updated = dict(item)
    updated["product_text_for_llm"] = (
        f"{item['product_text_for_llm']}\n\nEnriched Description:\n{enriched_description}"
    )
    source_text = dict(updated.get("source_text", {}))
    source_text["description_text"] = "\n\n".join(
        part for part in [source_text.get("description_text", ""), enriched_description] if clean_string(part)
    )
    updated["source_text"] = source_text
    updated["description_enriched"] = {
        "source": "brave_search",
        "enrichment_quality": enrichment.get("enrichment_quality", "low"),
        "seller_confirmed": item.get("description_enriched", {}).get("seller_confirmed", False),
    }
    return updated


def main() -> None:
    st.set_page_config(page_title="ColdStart Killer Seller Insert", layout="wide")
    init_state()
    st.title("ColdStart Killer Seller Insert")

    show_status_panel()
    inputs, submitted = show_input_form()
    signature = input_signature(inputs)
    maybe_warn_input_changed(signature)

    if submitted:
        item, errors = build_seller_item_doc(inputs, seller_confirmed=inputs["seller_confirmed"])
        if errors:
            for error in errors:
                st.error(error)
        else:
            st.session_state.generated_item_doc = item
            st.session_state.product_text_for_llm = item["product_text_for_llm"]
            st.session_state.input_signature = signature
            st.session_state.generated_propositions = []
            st.session_state.generated_hype_queries = []
            st.session_state.generated_embeddings = []
            st.session_state.generated_retrieval_units = []
            st.session_state.insert_ready = False

    item = st.session_state.generated_item_doc
    if item:
        st.subheader("Analysis")
        col1, col2, col3 = st.columns(3)
        col1.metric("combined words", item["text_stats"]["combined_words"])
        col2.metric("content richness", f"{item['content_richness']:.2f}")
        col3.metric("enrichment needed", "yes" if item["content_richness"] < 0.60 else "no")
        st.text_area("product_text_for_llm", value=st.session_state.product_text_for_llm, height=220)

        st.subheader("Optional Web Enrich")
        if st.button("Web Enrich"):
            st.session_state.enrichment_result = agentic_web_enrich(item)
            st.session_state.enrichment_accepted = False
        if st.session_state.enrichment_result:
            st.json(st.session_state.enrichment_result)
            st.session_state.enrichment_accepted = st.checkbox(
                "Accept enrichment",
                value=st.session_state.enrichment_accepted,
                key="accept_enrichment_checkbox",
            )
            preview_item = apply_accepted_enrichment(item) if st.session_state.enrichment_accepted else item
            st.session_state.product_text_for_llm = preview_item["product_text_for_llm"]

        st.subheader("Generate Retrieval Units")
        if st.button("Generate Retrieval Units"):
            if signature != st.session_state.input_signature:
                st.warning("Product input changed. Please regenerate retrieval units before inserting.")
            else:
                active_item = apply_accepted_enrichment(item)
                propositions = extract_propositions_llm(active_item)
                hype_queries = generate_hype_queries_llm(active_item, propositions)
                embedding_texts = [
                    f"{build_contextual_header(active_item)} {query['raw_text']}" for query in hype_queries
                ]
                embeddings = embed_texts(embedding_texts)
                retrieval_units = build_proposition_units(active_item, propositions) + build_hype_units(
                    active_item, hype_queries, embeddings
                )
                st.session_state.generated_item_doc = active_item
                st.session_state.generated_propositions = propositions
                st.session_state.generated_hype_queries = hype_queries
                st.session_state.generated_embeddings = embeddings
                st.session_state.generated_retrieval_units = retrieval_units
                st.session_state.insert_ready = True

        if st.session_state.generated_propositions:
            st.write("Propositions")
            st.dataframe(st.session_state.generated_propositions, use_container_width=True)
        if st.session_state.generated_hype_queries:
            st.write("HyPE Queries")
            st.dataframe(st.session_state.generated_hype_queries, use_container_width=True)
            st.metric("embedding count", len(st.session_state.generated_embeddings))

        st.subheader("Insert to MongoDB")
        if not st.session_state.insert_ready:
            st.info("Generate retrieval units before inserting.")
        if st.button("Insert to MongoDB", disabled=not st.session_state.insert_ready):
            if signature != st.session_state.input_signature:
                st.warning("Product input changed. Please regenerate retrieval units before inserting.")
            else:
                items_collection = get_items_collection()
                retrieval_collection = get_retrieval_units_collection()
                active_item = st.session_state.generated_item_doc
                retrieval_units = st.session_state.generated_retrieval_units
                items_collection.bulk_write(
                    [UpdateOne({"_id": active_item["_id"]}, {"$set": active_item}, upsert=True)],
                    ordered=False,
                )
                retrieval_collection.delete_many({"item_id": active_item["_id"]})
                if retrieval_units:
                    retrieval_collection.insert_many(retrieval_units, ordered=False)
                st.session_state.last_insert_result = {
                    "item_id": active_item["_id"],
                    "proposition_count": len(st.session_state.generated_propositions),
                    "hype_count": len(st.session_state.generated_hype_queries),
                }
                st.success("Inserted seller product and retrieval units.")
                st.json(st.session_state.last_insert_result)


if __name__ == "__main__":
    main()
