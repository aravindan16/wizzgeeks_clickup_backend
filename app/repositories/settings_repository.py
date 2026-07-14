"""Singleton settings documents (`settings` collection, keyed by `key`)."""
from typing import Any

from app.repositories.base import BaseRepository

ORG_KEY = "org"
ICON_COLORS_KEY = "icon_colors"

# The default icon-colour palette. Seeded into the DB on first read so it becomes
# DB-driven (editable) instead of hardcoded in the frontend.
DEFAULT_ICON_COLORS = [
    "#6b7280", "#111827", "#7c3aed", "#6d28d9", "#4f46e5", "#2563eb", "#0ea5e9", "#0d9488",
    "#059669", "#16a34a", "#65a30d", "#ca8a04", "#eab308", "#f59e0b", "#ea580c", "#ef4444",
    "#e11d48", "#ec4899", "#a855f7", "#a16207", "#78716c",
]


class SettingsRepository(BaseRepository):
    collection_name = "settings"

    async def get_org(self) -> dict[str, Any] | None:
        return await self.find_one({"key": ORG_KEY})

    async def upsert_org(self, values: dict[str, Any], when: Any) -> dict[str, Any]:
        await self.collection.update_one(
            {"key": ORG_KEY},
            {"$set": {**values, "updated_at": when},
             "$setOnInsert": {"key": ORG_KEY, "created_at": when}},
            upsert=True,
        )
        return await self.get_org()

    # --- icon-colour palette (DB-driven, editable) ---
    async def get_icon_colors(self) -> list[str]:
        doc = await self.find_one({"key": ICON_COLORS_KEY})
        if doc and doc.get("colors"):
            return doc["colors"]
        # Seed the defaults so the palette lives in the DB from now on.
        await self.collection.update_one(
            {"key": ICON_COLORS_KEY},
            {"$setOnInsert": {"key": ICON_COLORS_KEY, "colors": list(DEFAULT_ICON_COLORS)}},
            upsert=True,
        )
        return list(DEFAULT_ICON_COLORS)

    async def set_icon_colors(self, colors: list[str], when: Any) -> list[str]:
        await self.collection.update_one(
            {"key": ICON_COLORS_KEY},
            {"$set": {"colors": colors, "updated_at": when},
             "$setOnInsert": {"key": ICON_COLORS_KEY, "created_at": when}},
            upsert=True,
        )
        doc = await self.find_one({"key": ICON_COLORS_KEY})
        return (doc or {}).get("colors", colors)
