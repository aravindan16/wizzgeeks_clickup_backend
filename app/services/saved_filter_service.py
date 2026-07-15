"""Business logic for saved filters (the Filters page).

Filters are owned by a user and can be shared with members (a user id array on
the doc). Owner ∪ members can view/use; only the owner deletes or shares. The
filter tree (`cards`) and conjunction (`conj`) are stored verbatim.
"""
from __future__ import annotations  # `list` method shadows builtin in class body; defer annotations

import re
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import ConflictError, NotFoundError
from app.repositories.base import to_object_id
from app.repositories.list_repository import ListRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.saved_filter_repository import SavedFilterRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.filter_eval import task_matches
from app.utils.datetime import utcnow

# Upper bound on the candidate task set scanned when evaluating a filter server-side.
_EVAL_TASK_CAP = 5000


def _task_view(task: dict[str, Any]) -> dict[str, Any]:
    """Task shape the Filters results table consumes (ids stringified)."""
    out = dict(task)
    out["_id"] = str(task["_id"])
    for f in ("project_id", "reporter_id", "assignee_id", "parent_id", "list_id"):
        if task.get(f):
            out[f] = str(task[f])
    return out


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", "Filter"),
        "cards": doc.get("cards", []) or [],
        "conj": doc.get("conj", "AND"),
        "owner_id": str(doc["owner_id"]) if doc.get("owner_id") else None,
        "owner_name": doc.get("owner_name"),
        "member_ids": [str(m) for m in (doc.get("members") or [])],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


class SavedFilterService:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.repo = SavedFilterRepository(db)
        self.users = UserRepository(db)
        self.tasks = TaskRepository(db)
        self.projects = ProjectRepository(db)
        self.lists = ListRepository(db)

    # --- server-side evaluation (Filters results) ---
    async def _evaluate(self, cards: list[dict[str, Any]], conj: str, user_id: str) -> dict[str, Any]:
        """Evaluate a rule tree over all tasks and return the matched set plus the small
        reference data the results table needs (spaces, lists, assignee users) — so the
        frontend renders everything from ONE response instead of fanning out to several
        endpoints and filtering in the browser."""
        candidates = await self.tasks.list_tasks(
            {"is_deleted": {"$ne": True}, "is_archived": {"$ne": True}},
            skip=0, limit=_EVAL_TASK_CAP, sort=[("created_at", -1)],
        )
        matched = [t for t in candidates if task_matches(cards or [], conj, t, user_id)]

        # Reference data limited to what the matched tasks actually reference.
        space_ids = {t["project_id"] for t in matched if t.get("project_id")}
        list_ids = {t["list_id"] for t in matched if t.get("list_id")}
        assignee_ids = {t["assignee_id"] for t in matched if t.get("assignee_id")}

        projects = await self.projects.find_many({"_id": {"$in": list(space_ids)}}, limit=1000) if space_ids else []
        lists = await self.lists.find_many({"_id": {"$in": list(list_ids)}}, limit=2000) if list_ids else []
        users = await self.users.find_many(
            {"_id": {"$in": list(assignee_ids)}}, limit=2000,
            projection={"full_name": 1, "email": 1, "avatar_color": 1, "avatar_url": 1},
        ) if assignee_ids else []

        spaces = [{"_id": str(p["_id"]), "key": p.get("key"), "name": p.get("name"),
                   "statuses": p.get("statuses", []) or []} for p in projects]
        # Lists link to their space via `space_id` (NOT project_id, which is a task field).
        lists_out = [{"_id": str(l["_id"]), "name": l.get("name"),
                      "spaceId": str(l["space_id"]) if l.get("space_id") else None,
                      "status_mode": l.get("status_mode"), "statuses": l.get("statuses", []) or []}
                     for l in lists]
        users_out = [{"user_id": str(u["_id"]), "full_name": u.get("full_name"), "email": u.get("email"),
                      "avatar_color": u.get("avatar_color"), "avatar_url": u.get("avatar_url")} for u in users]

        return {
            "items": [_task_view(t) for t in matched],
            "total": len(matched),
            "spaces": spaces,
            "lists": lists_out,
            "users": users_out,
        }

    async def evaluate(self, cards: list[dict[str, Any]], conj: str, user_id: str) -> dict[str, Any]:
        """Evaluate an arbitrary rule tree (used by the live builder preview)."""
        return await self._evaluate(cards, conj if conj in ("AND", "OR") else "AND", user_id)

    async def results(self, filter_id: str, user_id: str) -> dict[str, Any]:
        """Load a saved filter AND its evaluated results in a single call."""
        doc = await self.repo.get_for_user(filter_id, user_id)
        if not doc:
            raise NotFoundError("Filter not found")
        payload = await self._evaluate(doc.get("cards", []) or [], doc.get("conj", "AND"), user_id)
        payload["filter"] = _serialize(doc)
        return payload

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self.repo.list_for_user(user_id)
        return [_serialize(r) for r in rows]

    async def get(self, filter_id: str, user_id: str) -> dict[str, Any]:
        doc = await self.repo.get_for_user(filter_id, user_id)
        if not doc:
            raise NotFoundError("Filter not found")
        return _serialize(doc)

    async def create(self, owner_id: str, *, name: str, cards: list[dict[str, Any]] | None = None,
                     conj: str = "AND") -> dict[str, Any]:
        owner = await self.users.find_safe_by_id(owner_id)
        now = utcnow()
        doc = {
            "owner_id": to_object_id(owner_id),
            "owner_name": (owner or {}).get("full_name"),
            "name": name.strip() or "Filter",
            "cards": cards or [],
            "conj": conj if conj in ("AND", "OR") else "AND",
            "members": [],
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.repo.create(doc)
        return _serialize(created)

    async def update(self, filter_id: str, user_id: str, *, name: str | None = None,
                     cards: list[dict[str, Any]] | None = None, conj: str | None = None) -> dict[str, Any]:
        update: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            update["name"] = name.strip() or "Filter"
        if cards is not None:
            update["cards"] = cards
        if conj is not None:
            update["conj"] = conj if conj in ("AND", "OR") else "AND"
        doc = await self.repo.update_for_user(filter_id, user_id, update)
        if not doc:
            raise NotFoundError("Filter not found")
        return _serialize(doc)

    async def delete(self, filter_id: str, owner_id: str) -> None:
        ok = await self.repo.soft_delete_for_owner(filter_id, owner_id, utcnow())
        if not ok:
            raise NotFoundError("Filter not found")

    # --- user directory (for the share picker; any authenticated user) ---
    async def search_users(self, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        q = (query or "").strip()
        match: dict[str, Any] = {"is_deleted": {"$ne": True}, "status": "active"}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            match["$or"] = [{"full_name": rx}, {"email": rx}]
        users = await self.users.find_many(match, limit=limit, sort=[("full_name", 1)],
                                           projection={"full_name": 1, "email": 1})
        return [{"user_id": str(u["_id"]), "full_name": u.get("full_name"), "email": u.get("email"), "is_owner": False}
                for u in users]

    # --- members ---
    def _member_view(self, user: dict[str, Any] | None, uid: str, *, is_owner: bool) -> dict[str, Any]:
        return {
            "user_id": uid,
            "full_name": user.get("full_name") if user else None,
            "email": user.get("email") if user else None,
            "is_owner": is_owner,
        }

    async def list_members(self, filter_id: str, user_id: str) -> list[dict[str, Any]]:
        doc = await self.repo.get_for_user(filter_id, user_id)
        if not doc:
            raise NotFoundError("Filter not found")
        owner_id = str(doc["owner_id"])
        member_ids = [str(m) for m in (doc.get("members") or [])]
        ids = [owner_id, *member_ids]
        users = await self.users.find_many({"_id": {"$in": [to_object_id(i) for i in ids]}},
                                           limit=500, projection={"password_hash": 0})
        by_id = {str(u["_id"]): u for u in users}
        return [self._member_view(by_id.get(i), i, is_owner=(i == owner_id)) for i in ids]

    async def add_member(self, filter_id: str, owner_id: str, *, member_user_id: str) -> list[dict[str, Any]]:
        user = await self.users.find_safe_by_id(member_user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        if str(user["_id"]) == owner_id:
            raise ConflictError("Owner already has access")
        ok = await self.repo.add_member(filter_id, owner_id, member_user_id)
        if not ok:
            raise NotFoundError("Filter not found")
        return await self.list_members(filter_id, owner_id)

    async def remove_member(self, filter_id: str, owner_id: str, member_user_id: str) -> list[dict[str, Any]]:
        ok = await self.repo.remove_member(filter_id, owner_id, member_user_id)
        if not ok:
            raise NotFoundError("Filter not found")
        return await self.list_members(filter_id, owner_id)
