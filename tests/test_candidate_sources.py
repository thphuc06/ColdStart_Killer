from __future__ import annotations

from src.recommendation.candidate_sources import (
    clear_catalog_snapshot_cache,
    load_catalog_snapshot,
    load_item_snapshot,
    preferred_image_sources,
)


class RecordingCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(doc) for doc in docs]
        self.find_calls: list[dict] = []

    def find(self, filter_doc: dict, projection: dict | None = None):
        self.find_calls.append(dict(filter_doc))
        rows = []
        for doc in self.docs:
            if not self._matches(doc, filter_doc):
                continue
            if projection:
                rows.append({key: doc.get(key) for key, enabled in projection.items() if enabled and key in doc})
            else:
                rows.append(dict(doc))
        return rows

    @staticmethod
    def _matches(doc: dict, filter_doc: dict) -> bool:
        for key, value in filter_doc.items():
            if isinstance(value, dict) and "$in" in value:
                if doc.get(key) not in value["$in"]:
                    return False
                continue
            if doc.get(key) != value:
                return False
        return True


def test_load_item_snapshot_reads_only_requested_item_ids() -> None:
    items = RecordingCollection([{"_id": "A"}, {"_id": "B"}])
    stats = RecordingCollection([{"item_id": "A"}, {"item_id": "B"}])
    profiles = RecordingCollection([{"item_id": "A"}, {"item_id": "B"}])

    loaded_items, loaded_stats, loaded_profiles = load_item_snapshot(
        {"A"},
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
    )

    assert set(loaded_items) == {"A"}
    assert set(loaded_stats) == {"A"}
    assert set(loaded_profiles) == {"A"}
    assert items.find_calls == [{"_id": {"$in": ["A"]}}]
    assert stats.find_calls == [{"item_id": {"$in": ["A"]}}]
    assert profiles.find_calls == [{"item_id": {"$in": ["A"]}}]


def test_preferred_image_sources_uses_same_primary_without_thumbnail_resize() -> None:
    image_url, fallback_url = preferred_image_sources(
        {
            "image_url": "https://m.media-amazon.com/images/I/primary._AC_SR38,50_.jpg",
            "image_urls": [
                "https://m.media-amazon.com/images/I/primary._AC_SR38,50_.jpg",
                "https://m.media-amazon.com/images/I/primary._AC_.jpg",
                "https://m.media-amazon.com/images/I/gallery._AC_SL1500_.jpg",
            ],
        }
    )

    assert image_url == "https://m.media-amazon.com/images/I/primary._AC_.jpg"
    assert fallback_url == "https://m.media-amazon.com/images/I/primary._AC_SR38,50_.jpg"


def test_preferred_image_sources_upgrades_us_thumbnail_when_no_alternative_exists() -> None:
    image_url, fallback_url = preferred_image_sources(
        {"image_url": "https://m.media-amazon.com/images/I/primary._AC_US40_.jpg"}
    )

    assert image_url == "https://m.media-amazon.com/images/I/primary._AC_.jpg"
    assert fallback_url == "https://m.media-amazon.com/images/I/primary._AC_US40_.jpg"


def test_catalog_snapshot_cache_reuses_and_can_clear_full_profile_load() -> None:
    items = RecordingCollection([{"_id": "A"}])
    stats = RecordingCollection([{"item_id": "A"}])
    profiles = RecordingCollection([{"item_id": "A"}])
    clear_catalog_snapshot_cache()

    load_catalog_snapshot(
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
        use_cache=True,
    )
    load_catalog_snapshot(
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
        use_cache=True,
    )
    assert len(profiles.find_calls) == 1

    clear_catalog_snapshot_cache()
    load_catalog_snapshot(
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
        use_cache=True,
    )
    assert len(profiles.find_calls) == 2
    clear_catalog_snapshot_cache()


def test_catalog_snapshot_cache_reuses_and_can_clear_lightweight_load() -> None:
    items = RecordingCollection([{"_id": "A"}])
    stats = RecordingCollection([{"item_id": "A"}])
    profiles = RecordingCollection([{"item_id": "A"}])
    clear_catalog_snapshot_cache()

    load_catalog_snapshot(
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
        include_item_profiles=False,
        use_cache=True,
    )
    load_catalog_snapshot(
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
        include_item_profiles=False,
        use_cache=True,
    )
    assert len(items.find_calls) == 1
    assert len(stats.find_calls) == 1
    assert len(profiles.find_calls) == 0

    clear_catalog_snapshot_cache()
    load_catalog_snapshot(
        items_collection=items,
        item_stats_collection=stats,
        item_hype_profiles_collection=profiles,
        include_item_profiles=False,
        use_cache=True,
    )
    assert len(items.find_calls) == 2
    assert len(stats.find_calls) == 2
    clear_catalog_snapshot_cache()
