"""List management: Lists live inside a Space (project). A List groups tasks and
can be created, renamed, duplicated, archived, deleted, and moved between Spaces.
Access mirrors Space membership; tasks reference a list via `list_id`."""
from typing import Any

from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.core.statuses import normalize_statuses
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.list_repository import ListRepository
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.services.audit_service import AuditService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow


def _serialize(doc: dict[str, Any], task_count: int | None = None) -> dict[str, Any]:
    out = dict(doc)
    out["_id"] = str(doc["_id"])
    out["space_id"] = str(doc["space_id"])
    if doc.get("owner_id"):
        out["owner_id"] = str(doc["owner_id"])
    if task_count is not None:
        out["task_count"] = task_count
    out["status_mode"] = doc.get("status_mode", "inherit")
    out["statuses"] = doc.get("statuses", [])
    return out


class ListService:
    def __init__(
        self,
        lists: ListRepository,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        tasks: TaskRepository,
        audit: AuditService,
    ):
        self.lists = lists
        self.projects = projects
        self.members = members
        self.tasks = tasks
        self.audit = audit

    # --- access ---
    async def _space_or_404(self, space_id: str) -> dict[str, Any]:
        if not is_valid_object_id(space_id):
            raise NotFoundError("Space not found")
        project = await self.projects.find_by_id(space_id)
        if not project or project.get("is_deleted"):
            raise NotFoundError("Space not found")
        return project

    async def _assert_member(self, space_id: str, project: dict[str, Any], actor: ActorContext) -> None:
        if actor.has("project.update"):
            return
        if project.get("owner_id") and str(project["owner_id"]) == actor.user_id:
            return
        if actor.user_id and await self.members.find_active(space_id, actor.user_id):
            return
        raise PermissionDeniedError("You are not a member of this space")

    def _can_manage(self, project: dict[str, Any], actor: ActorContext) -> bool:
        return (actor.has("project.member.manage")
                or (project.get("owner_id") and str(project["owner_id"]) == actor.user_id))

    async def _list_or_404(self, list_id: str) -> dict[str, Any]:
        if not is_valid_object_id(list_id):
            raise NotFoundError("List not found")
        doc = await self.lists.find_by_id(list_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundError("List not found")
        return doc

    async def _task_count(self, list_id: str) -> int:
        return await self.tasks.count({"list_id": to_object_id(list_id),
                                       "is_deleted": {"$ne": True}, "is_archived": {"$ne": True}})

    # --- CRUD ---
    async def create_list(self, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        space_id = data["space_id"]
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        now = utcnow()
        order = await self.lists.count_for_space(space_id)
        # Task-ID prefix for this List (e.g. FE → FE-1). Uppercased + uniqueness-checked.
        key = (data.get("key") or "").strip().upper()
        if not key:
            raise ValidationError("List key is required")
        existing = await self.lists.find_one({"space_id": to_object_id(space_id), "key": key, "is_deleted": {"$ne": True}})
        if existing:
            raise ValidationError(f"A list with key '{key}' already exists in this space")
        doc = {
            "space_id": to_object_id(space_id),
            "name": data["name"].strip(),
            "key": key,
            "task_counter": 0,
            "privacy": data.get("privacy", "public"),
            "owner_id": to_object_id(actor.user_id) if actor.user_id else None,
            "is_archived": False,
            "is_deleted": False,
            "deleted_at": None,
            "order": order,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.lists.insert_one(doc)
        await self.audit.log(actor_id=actor.user_id, action="list.created", entity_type="list",
                             entity_id=str(created["_id"]), metadata={"space_id": space_id, "name": doc["name"]}, ip=actor.ip)
        return _serialize(created, task_count=0)

    async def list_lists(self, space_id: str, actor: ActorContext, *, include_archived: bool = False) -> list[dict[str, Any]]:
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        rows = await self.lists.list_for_space(space_id, include_archived=include_archived)
        can_manage = self._can_manage(project, actor)
        out = []
        for r in rows:
            # Private lists are visible only to their owner or a space manager.
            if r.get("privacy") == "private" and not can_manage and str(r.get("owner_id")) != actor.user_id:
                continue
            out.append(_serialize(r, task_count=await self._task_count(str(r["_id"]))))
        return out

    async def get_list(self, list_id: str, actor: ActorContext) -> dict[str, Any]:
        doc = await self._list_or_404(list_id)
        project = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), project, actor)
        return _serialize(doc, task_count=await self._task_count(list_id))

    async def update_list(self, list_id: str, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        doc = await self._list_or_404(list_id)
        project = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), project, actor)
        update: dict[str, Any] = {"updated_at": utcnow()}
        if data.get("name") is not None:
            update["name"] = data["name"].strip()
        if data.get("privacy") is not None:
            update["privacy"] = data["privacy"]
        if data.get("icon") is not None:
            update["icon"] = data["icon"] or None
        if data.get("status_mode") is not None:
            update["status_mode"] = data["status_mode"]
            # Custom → store the normalized list; Inherit → drop any custom statuses.
            if data["status_mode"] == "custom":
                update["statuses"] = normalize_statuses(data.get("statuses"))
            else:
                update["statuses"] = []
        elif data.get("statuses") is not None:
            update["statuses"] = normalize_statuses(data["statuses"])
        updated = await self.lists.update_by_id(list_id, update)
        await self.audit.log(actor_id=actor.user_id, action="list.updated", entity_type="list",
                             entity_id=list_id, metadata={"fields": list(update.keys())}, ip=actor.ip)
        return _serialize(updated, task_count=await self._task_count(list_id))

    async def archive_list(self, list_id: str, actor: ActorContext) -> dict[str, Any]:
        doc = await self._list_or_404(list_id)
        project = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), project, actor)
        updated = await self.lists.update_by_id(list_id, {"is_archived": not doc.get("is_archived", False), "updated_at": utcnow()})
        await self.audit.log(actor_id=actor.user_id, action="list.archived", entity_type="list",
                             entity_id=list_id, ip=actor.ip)
        return _serialize(updated, task_count=await self._task_count(list_id))

    async def delete_list(self, list_id: str, actor: ActorContext) -> None:
        doc = await self._list_or_404(list_id)
        project = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), project, actor)
        now = utcnow()
        await self.lists.soft_delete_by_id(list_id, when=now)
        # Soft-delete the list's tasks (they belong to the list).
        await self.tasks.collection.update_many(
            {"list_id": to_object_id(list_id), "is_deleted": {"$ne": True}},
            {"$set": {"is_deleted": True, "deleted_at": now}},
        )
        await self.audit.log(actor_id=actor.user_id, action="list.deleted", entity_type="list",
                             entity_id=list_id, ip=actor.ip)

    async def move_list(self, list_id: str, target_space_id: str, actor: ActorContext) -> dict[str, Any]:
        doc = await self._list_or_404(list_id)
        src = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), src, actor)
        target = await self._space_or_404(target_space_id)
        await self._assert_member(target_space_id, target, actor)
        order = await self.lists.count_for_space(target_space_id)
        updated = await self.lists.update_by_id(list_id, {"space_id": to_object_id(target_space_id),
                                                          "order": order, "updated_at": utcnow()})
        # Move the list's tasks to the target space too.
        await self.tasks.collection.update_many(
            {"list_id": to_object_id(list_id), "is_deleted": {"$ne": True}},
            {"$set": {"project_id": to_object_id(target_space_id), "updated_at": utcnow()}},
        )
        await self.audit.log(actor_id=actor.user_id, action="list.moved", entity_type="list",
                             entity_id=list_id, metadata={"to": target_space_id}, ip=actor.ip)
        return _serialize(updated, task_count=await self._task_count(list_id))

    async def duplicate_list(self, list_id: str, actor: ActorContext) -> dict[str, Any]:
        doc = await self._list_or_404(list_id)
        space_id = str(doc["space_id"])
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        now = utcnow()
        order = await self.lists.count_for_space(space_id)
        clone = {
            "space_id": doc["space_id"],
            "name": f"{doc['name']} (copy)",
            "privacy": doc.get("privacy", "public"),
            "owner_id": to_object_id(actor.user_id) if actor.user_id else None,
            "is_archived": False, "is_deleted": False, "deleted_at": None,
            "order": order, "created_at": now, "updated_at": now,
        }
        created = await self.lists.insert_one(clone)
        new_id = created["_id"]
        # Copy the list's tasks (shallow) into the new list.
        src_tasks = await self.tasks.find_many(
            {"list_id": to_object_id(list_id), "is_deleted": {"$ne": True}}, limit=500)
        for t in src_tasks:
            seq = await self.projects.next_task_seq(space_id)
            await self.tasks.insert_one({
                "project_id": doc["space_id"], "list_id": new_id,
                "key": f"{project['key']}-{seq}", "title": t.get("title"),
                "description": t.get("description"), "type": t.get("type", "task"),
                "status": t.get("status"), "priority": t.get("priority", "medium"),
                "reporter_id": to_object_id(actor.user_id) if actor.user_id else None,
                "assignee_id": t.get("assignee_id"), "watchers": [], "labels": t.get("labels", []),
                "due_date": t.get("due_date"), "estimate_hours": t.get("estimate_hours"),
                "actual_hours": 0, "comment_count": 0, "parent_id": None, "links": [],
                "is_archived": False, "is_deleted": False, "deleted_at": None,
                "created_at": now, "updated_at": now,
            })
        await self.audit.log(actor_id=actor.user_id, action="list.duplicated", entity_type="list",
                             entity_id=str(new_id), metadata={"from": list_id}, ip=actor.ip)
        return _serialize(created, task_count=len(src_tasks))
