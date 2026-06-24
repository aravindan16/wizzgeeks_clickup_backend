"""Task management business logic: CRUD, assignment, workflow transitions,
watchers, worklog, metrics — with project-member access enforcement."""
from typing import Any

from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.statuses import default_status_key, status_keys
from app.core.workflow import (
    BLOCKED,
    DONE_STATUSES,
)
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.status_history_repository import StatusHistoryRepository
from app.repositories.task_assignment_repository import TaskAssignmentRepository
from app.repositories.list_repository import ListRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.repositories.worklog_repository import WorklogRepository
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow


# Issue-link relationships and their inverse (stored on the other task).
LINK_INVERSE = {
    "relates_to": "relates_to",
    "blocks": "blocked_by",
    "blocked_by": "blocks",
    "duplicates": "duplicated_by",
    "duplicated_by": "duplicates",
}


def _serialize(task: dict[str, Any]) -> dict[str, Any]:
    out = dict(task)
    out["_id"] = str(task["_id"])
    for f in ("project_id", "reporter_id", "assignee_id", "parent_id", "list_id"):
        if task.get(f):
            out[f] = str(task[f])
    out["watchers"] = [str(w) for w in task.get("watchers", [])]
    out["links"] = [
        {"task_id": str(link["task_id"]), "type": link.get("type", "relates_to")}
        for link in task.get("links", [])
    ]
    return out


class TaskService:
    def __init__(
        self,
        tasks: TaskRepository,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        users: UserRepository,
        history: StatusHistoryRepository,
        assignments: TaskAssignmentRepository,
        audit: AuditService,
        notifications: NotificationService,
        worklogs: WorklogRepository,
        lists: "ListRepository | None" = None,
    ):
        self.tasks = tasks
        self.projects = projects
        self.members = members
        self.users = users
        self.history = history
        self.assignments = assignments
        self.audit = audit
        self.notifications = notifications
        self.worklogs = worklogs
        self.lists = lists

    async def _notify_assignee(self, assignee_id: str, actor: ActorContext, task: dict[str, Any]) -> None:
        if not assignee_id or assignee_id == actor.user_id:
            return  # don't notify self-assignments
        await self.notifications.notify(
            recipient_id=assignee_id, type="task.assigned",
            title=f"Task assigned: {task.get('key')}",
            body=task.get("title"), entity_type="task", entity_id=str(task["_id"]),
        )

    # --- access control ---
    async def _assert_project_access(self, project_id: str, actor: ActorContext) -> None:
        """Project members only — unless the actor has elevated (manager/admin) rights."""
        if actor.has("project.update"):  # managers, admins, super admins
            return
        if not actor.user_id or not await self.members.find_active(project_id, actor.user_id):
            raise PermissionDeniedError("You are not a member of this project")

    async def _get_task_or_404(self, task_id: str) -> dict[str, Any]:
        if not is_valid_object_id(task_id):
            raise NotFoundError("Task not found")
        task = await self.tasks.find_by_id(task_id)
        if not task or task.get("is_deleted"):
            raise NotFoundError("Task not found")
        return task

    async def _ensure_assignee_member(self, project_id: str, assignee_id: str, actor: ActorContext) -> None:
        """Tasks can only be assigned to members of the space (same-space only)."""
        if not is_valid_object_id(assignee_id):
            raise ValidationError("Invalid assignee_id")
        user = await self.users.find_safe_by_id(assignee_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("Assignee user not found")
        if not await self.members.find_active(project_id, assignee_id):
            raise ValidationError("Assignee must be a member of this space. Add them in Members first.")

    async def _resolve_assignee(self, assignee_id: str | None, assignee_email: str | None) -> str | None:
        """Return an assignee user id from an id or an email (looked up server-side)."""
        if assignee_id:
            return assignee_id
        if assignee_email:
            user = await self.users.find_by_email(assignee_email)
            if not user:
                raise NotFoundError(f"No user found with email '{assignee_email}'.")
            return str(user["_id"])
        return None

    # --- CRUD ---
    async def create_task(self, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        project_id = data["project_id"]
        if not is_valid_object_id(project_id):
            raise ValidationError("Invalid project_id")
        project = await self.projects.find_by_id(project_id)
        if not project or project.get("is_deleted"):
            raise NotFoundError("Project not found")
        await self._assert_project_access(project_id, actor)

        assignee_id = await self._resolve_assignee(data.get("assignee_id"), data.get("assignee_email"))
        if assignee_id:
            await self._ensure_assignee_member(project_id, assignee_id, actor)

        # Optional parent (subtask creation) — must live in the same space.
        parent_oid = None
        parent_id = data.get("parent_id")
        if parent_id:
            if not is_valid_object_id(parent_id):
                raise ValidationError("Invalid parent_id")
            parent = await self.tasks.find_by_id(parent_id)
            if not parent or parent.get("is_deleted"):
                raise NotFoundError("Parent task not found")
            if str(parent["project_id"]) != project_id:
                raise ValidationError("A subtask must be in the same space as its parent")
            parent_oid = to_object_id(parent_id)

        # List resolution: use the given list, else default to the Space's first List
        # (ClickUp-style — a task created without a List lands in the first List).
        list_oid = None
        list_id = data.get("list_id")
        if list_id and is_valid_object_id(list_id):
            list_oid = to_object_id(list_id)
        elif not list_id and self.lists:
            first = await self.lists.first_for_space(project_id)
            if first:
                list_oid = first["_id"]

        # Status workflow: a List with custom statuses overrides the Space's workflow.
        status_source = project
        if list_oid and self.lists:
            lst = await self.lists.find_by_id(list_oid)
            if lst and lst.get("status_mode") == "custom" and lst.get("statuses"):
                status_source = lst
        allowed = status_keys(status_source)
        init_status = data.get("status") or default_status_key(status_source)
        if init_status not in allowed:
            raise ValidationError(f"Invalid status '{init_status}' for this list/space")

        seq = await self.projects.next_task_seq(project_id)
        key = f"{project['key']}-{seq}"
        now = utcnow()
        doc = {
            "project_id": to_object_id(project_id),
            "key": key,
            "title": data["title"],
            "description": data.get("description"),
            "type": data.get("type", "task"),
            "status": init_status,
            "priority": data.get("priority", "medium"),
            "reporter_id": to_object_id(actor.user_id) if actor.user_id else None,
            "assignee_id": to_object_id(assignee_id) if assignee_id else None,
            "watchers": [],
            "labels": data.get("labels", []),
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "due_date": data.get("due_date"),
            "estimate_hours": data.get("estimate_hours"),
            "actual_hours": 0,
            "comment_count": 0,
            "parent_id": parent_oid,
            "list_id": list_oid,
            "custom_fields": data.get("custom_fields") or {},
            "links": [],
            "is_archived": False,
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.tasks.insert_one(doc)
        tid = str(created["_id"])

        await self.history.record({
            "task_id": created["_id"], "from_status": None, "to_status": init_status,
            "changed_by": actor.user_id, "note": "Task created", "created_at": now,
        })
        if assignee_id:
            await self.assignments.add(task_id=tid, assignee_id=assignee_id,
                                       assigned_by=actor.user_id, when=now)
            await self._notify_assignee(assignee_id, actor, created)

        await self.audit.log(actor_id=actor.user_id, action="task.created", entity_type="task",
                             entity_id=tid, metadata={"key": key, "project_id": project_id}, ip=actor.ip)
        return _serialize(created)

    async def get_task(self, task_id: str, actor: ActorContext) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        return _serialize(task)

    async def list_tasks(
        self, *, actor: ActorContext, skip: int, limit: int, project_id: str | None,
        status: str | None, assignee_id: str | None, priority: str | None,
        label: str | None, search: str | None, include_archived: bool,
        sort_by: str, sort_dir: int, list_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {"is_deleted": {"$ne": True}}
        if not include_archived:
            query["is_archived"] = {"$ne": True}
        if project_id and is_valid_object_id(project_id):
            query["project_id"] = to_object_id(project_id)
        if list_id and is_valid_object_id(list_id):
            query["list_id"] = to_object_id(list_id)
        if status:
            query["status"] = status
        if assignee_id and is_valid_object_id(assignee_id):
            query["assignee_id"] = to_object_id(assignee_id)
        if priority:
            query["priority"] = priority
        if label:
            query["labels"] = label
        if search:
            query["$or"] = [
                {"title": {"$regex": search, "$options": "i"}},
                {"key": {"$regex": search, "$options": "i"}},
            ]

        allowed_sort = {"created_at", "updated_at", "priority", "due_date", "status"}
        sort_field = sort_by if sort_by in allowed_sort else "created_at"
        items = await self.tasks.list_tasks(
            query, skip=skip, limit=limit, sort=[(sort_field, sort_dir)]
        )
        total = await self.tasks.count(query)
        return [_serialize(t) for t in items], total

    async def update_task(
        self, task_id: str, data: dict[str, Any], actor: ActorContext
    ) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)

        update: dict[str, Any] = {"updated_at": utcnow()}
        for field_name in ("title", "description", "type", "priority", "start_date", "end_date", "due_date",
                           "labels", "estimate_hours", "custom_fields"):
            if data.get(field_name) is not None:
                update[field_name] = data[field_name]
        updated = await self.tasks.update_by_id(task_id, update)
        changes = {k: v for k, v in update.items() if k != "updated_at"}
        await self.audit.log(actor_id=actor.user_id, action="task.updated", entity_type="task",
                             entity_id=task_id,
                             metadata={"fields": list(changes.keys()), "changes": changes}, ip=actor.ip)
        return _serialize(updated)

    async def change_status(
        self, task_id: str, to_status: str, note: str | None, actor: ActorContext
    ) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)

        from_status = task["status"]
        # ClickUp-style free movement. A task in a List with custom statuses validates
        # against that List's workflow; otherwise against the Space's.
        status_source = await self.projects.find_by_id(str(task["project_id"]))
        if task.get("list_id") and self.lists:
            lst = await self.lists.find_by_id(task["list_id"])
            if lst and lst.get("status_mode") == "custom" and lst.get("statuses"):
                status_source = lst
        allowed = status_keys(status_source)
        if to_status not in allowed:
            raise ValidationError(
                f"Invalid status '{to_status}' for this list/space",
                {"to": to_status, "allowed": allowed},
            )

        now = utcnow()
        updated = await self.tasks.update_by_id(task_id, {"status": to_status, "updated_at": now})
        await self.history.record({
            "task_id": to_object_id(task_id), "from_status": from_status, "to_status": to_status,
            "changed_by": actor.user_id, "note": note, "created_at": now,
        })
        await self.audit.log(actor_id=actor.user_id, action="task.status_changed", entity_type="task",
                             entity_id=task_id, metadata={"from": from_status, "to": to_status}, ip=actor.ip)
        return _serialize(updated)

    # --- assignment ---
    async def assign(self, task_id: str, assignee_id: str | None, actor: ActorContext) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        project_id = str(task["project_id"])
        await self._assert_project_access(project_id, actor)

        now = utcnow()
        await self.assignments.deactivate_active(task_id, now)
        if assignee_id:
            await self._ensure_assignee_member(project_id, assignee_id, actor)
            await self.assignments.add(task_id=task_id, assignee_id=assignee_id,
                                       assigned_by=actor.user_id, when=now)
            new_val = to_object_id(assignee_id)
        else:
            new_val = None

        updated = await self.tasks.update_by_id(task_id, {"assignee_id": new_val, "updated_at": now})
        if assignee_id:
            await self._notify_assignee(assignee_id, actor, updated)
        await self.audit.log(actor_id=actor.user_id, action="task.assigned", entity_type="task",
                             entity_id=task_id, metadata={"assignee_id": assignee_id}, ip=actor.ip)
        return _serialize(updated)

    # --- watchers ---
    async def add_watcher(self, task_id: str, user_id: str, actor: ActorContext) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        if not is_valid_object_id(user_id) or not await self.users.find_safe_by_id(user_id):
            raise ValidationError("Invalid user_id")
        updated = await self.tasks.add_watcher(task_id, user_id)
        return _serialize(updated)

    async def remove_watcher(self, task_id: str, user_id: str, actor: ActorContext) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        updated = await self.tasks.remove_watcher(task_id, user_id)
        return _serialize(updated)

    # --- worklog ---
    async def log_work(
        self, task_id: str, hours: float, actor: ActorContext, note: str | None = None
    ) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        now = utcnow()
        await self.worklogs.insert_one({
            "task_id": to_object_id(task_id),
            "user_id": to_object_id(actor.user_id) if actor.user_id else None,
            "hours": hours,
            "note": (note.strip() if note and note.strip() else None),
            "created_at": now,
        })
        updated = await self.tasks.increment_actual_hours(task_id, hours)
        await self.audit.log(actor_id=actor.user_id, action="task.worklog", entity_type="task",
                             entity_id=task_id, metadata={"hours": hours}, ip=actor.ip)
        return _serialize(updated)

    async def list_worklogs(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        rows = await self.worklogs.list_for_task(task_id)
        out = []
        for r in rows:
            uid = str(r["user_id"]) if r.get("user_id") else None
            name = None
            if uid:
                u = await self.users.find_safe_by_id(uid)
                name = u.get("full_name") if u else None
            out.append({
                "_id": str(r["_id"]), "task_id": str(r["task_id"]),
                "user_id": uid, "user_name": name,
                "hours": r.get("hours"), "note": r.get("note"),
                "created_at": r.get("created_at"),
            })
        return out

    # --- subtasks ---
    async def list_subtasks(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        rows = await self.tasks.list_subtasks(task_id)
        return [_serialize(r) for r in rows]

    # --- issue links ---
    async def list_links(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        out = []
        for link in task.get("links", []):
            t = await self.tasks.find_by_id(link["task_id"])
            if not t or t.get("is_deleted"):
                continue
            out.append({
                "type": link.get("type", "relates_to"),
                "task_id": str(t["_id"]), "key": t.get("key"), "title": t.get("title"),
                "status": t.get("status"), "task_type": t.get("type"),
            })
        return out

    async def add_link(
        self, task_id: str, target_id: str, link_type: str, actor: ActorContext
    ) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        if link_type not in LINK_INVERSE:
            raise ValidationError(f"Invalid link type '{link_type}'")
        if target_id == task_id:
            raise ValidationError("A task cannot be linked to itself")
        target = await self._get_task_or_404(target_id)
        # Store reciprocal links so the relationship shows on both issues.
        await self.tasks.add_link(task_id, target_id, link_type)
        await self.tasks.add_link(target_id, task_id, LINK_INVERSE[link_type])
        await self.audit.log(actor_id=actor.user_id, action="task.link_added", entity_type="task",
                             entity_id=task_id, metadata={"target": target_id, "type": link_type}, ip=actor.ip)
        return await self.list_links(task_id, actor)

    async def remove_link(
        self, task_id: str, target_id: str, actor: ActorContext
    ) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        await self.tasks.remove_link(task_id, target_id)
        await self.tasks.remove_link(target_id, task_id)
        await self.audit.log(actor_id=actor.user_id, action="task.link_removed", entity_type="task",
                             entity_id=task_id, metadata={"target": target_id}, ip=actor.ip)
        return await self.list_links(task_id, actor)

    # --- archive / delete ---
    async def archive(self, task_id: str, actor: ActorContext) -> dict[str, Any]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        updated = await self.tasks.update_by_id(task_id, {"is_archived": True, "updated_at": utcnow()})
        await self.audit.log(actor_id=actor.user_id, action="task.archived", entity_type="task",
                             entity_id=task_id, ip=actor.ip)
        return _serialize(updated)

    async def soft_delete(self, task_id: str, actor: ActorContext) -> None:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        await self.tasks.soft_delete_by_id(task_id, when=utcnow())
        await self.audit.log(actor_id=actor.user_id, action="task.deleted", entity_type="task",
                             entity_id=task_id, ip=actor.ip)

    # --- activity (audit feed: created + every update) ---
    async def task_activity(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        items, _ = await self.audit.list_logs(
            skip=0, limit=200, entity_type="task", entity_id=task_id
        )
        name_cache: dict[str, str | None] = {}
        out = []
        for it in items:
            aid = it.get("actor_id")
            name = None
            if aid:
                if aid not in name_cache:
                    u = await self.users.find_safe_by_id(aid) if is_valid_object_id(aid) else None
                    name_cache[aid] = u.get("full_name") if u else None
                name = name_cache[aid]
            out.append({
                "_id": it["_id"], "actor_id": aid, "actor_name": name,
                "action": it.get("action"), "metadata": it.get("metadata", {}),
                "created_at": it.get("created_at"),
            })
        return out

    # --- history ---
    async def status_history(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        rows = await self.history.list_for_task(task_id)
        out = []
        for r in rows:
            r["_id"] = str(r["_id"])
            out.append(r)
        return out

    async def assignment_history(self, task_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        task = await self._get_task_or_404(task_id)
        await self._assert_project_access(str(task["project_id"]), actor)
        rows = await self.assignments.list_for_task(task_id)
        out = []
        for r in rows:
            r["_id"] = str(r["_id"])
            if r.get("assignee_id"):
                r["assignee_id"] = str(r["assignee_id"])
            if r.get("assigned_by"):
                r["assigned_by"] = str(r["assigned_by"])
            out.append(r)
        return out

    # --- metrics ---
    async def metrics(self, *, project_id: str | None, assignee_id: str | None) -> dict[str, int]:
        base: dict[str, Any] = {"is_deleted": {"$ne": True}, "is_archived": {"$ne": True}}
        if project_id and is_valid_object_id(project_id):
            base["project_id"] = to_object_id(project_id)
        if assignee_id and is_valid_object_id(assignee_id):
            base["assignee_id"] = to_object_id(assignee_id)

        done = list(DONE_STATUSES)
        today = utcnow().strftime("%Y-%m-%d")
        open_tasks = await self.tasks.count({**base, "status": {"$nin": done}})
        closed_tasks = await self.tasks.count({**base, "status": {"$in": done}})
        blocked_tasks = await self.tasks.count({**base, "status": BLOCKED})
        overdue_tasks = await self.tasks.count({
            **base, "status": {"$nin": done},
            "due_date": {"$ne": None, "$lt": today},
        })
        return {
            "open_tasks": open_tasks,
            "closed_tasks": closed_tasks,
            "blocked_tasks": blocked_tasks,
            "overdue_tasks": overdue_tasks,
        }
