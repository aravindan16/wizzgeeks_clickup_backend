"""Project management business logic."""
from typing import Any

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.statuses import SYSTEM_TEMPLATES, normalize_statuses, statuses_for
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.space_role_repository import SpaceRoleRepository
from app.repositories.status_template_repository import StatusTemplateRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow

# Project-member role keys → friendly label for notifications.
ROLE_LABELS = {
    "super_admin": "Super Admin", "admin": "Admin", "employee": "Employee",
}

# Tasks considered "done" for progress calculations.
DONE_STATUSES = ["completed", "closed"]


def _serialize(project: dict[str, Any], member_count: int | None = None,
               owner_name: str | None = None) -> dict[str, Any]:
    out = dict(project)
    out["_id"] = str(project["_id"])
    if project.get("owner_id"):
        out["owner_id"] = str(project["owner_id"])
    if member_count is not None:
        out["member_count"] = member_count
    if owner_name is not None:
        out["owner_name"] = owner_name
    # Always expose a status workflow (legacy fallback for pre-feature spaces).
    out["statuses"] = statuses_for(project)
    return out


class ProjectService:
    def __init__(
        self,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        users: UserRepository,
        audit: AuditService,
        notifications: NotificationService,
        status_templates: "StatusTemplateRepository | None" = None,
        space_roles: "SpaceRoleRepository | None" = None,
    ):
        self.projects = projects
        self.members = members
        self.users = users
        self.audit = audit
        self.notifications = notifications
        self.status_templates = status_templates
        self.space_roles = space_roles

    async def _get_or_404(self, project_id: str) -> dict[str, Any]:
        if not is_valid_object_id(project_id):
            raise NotFoundError("Project not found")
        project = await self.projects.find_by_id(project_id)
        if not project or project.get("is_deleted"):
            raise NotFoundError("Project not found")
        return project

    # --- CRUD ---
    async def create_project(self, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        # The Space key is internal now (task IDs come from List keys), so we never
        # reject a Space on a key clash — just make it unique automatically.
        base = (data.get("key") or "SP").upper()
        key = base
        n = 1
        while await self.projects.find_by_key(key):
            n += 1
            key = f"{base}{n}"

        now = utcnow()
        doc = {
            "key": key,
            "name": data["name"],
            "description": data.get("description"),
            "status": "active",
            "owner_id": to_object_id(actor.user_id) if actor.user_id else None,
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "statuses": normalize_statuses(data.get("statuses")),
            "task_counter": 0,
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.projects.insert_one(doc)
        pid = str(created["_id"])

        # The creator joins as project_manager by default.
        if actor.user_id:
            await self.members.add(
                project_id=pid, user_id=actor.user_id,
                project_role="admin", added_by=actor.user_id, added_at=now,
            )

        await self.audit.log(
            actor_id=actor.user_id, action="project.created", entity_type="project",
            entity_id=pid, metadata={"key": key, "name": data["name"]}, ip=actor.ip,
        )
        return _serialize(created, member_count=1 if actor.user_id else 0,
                          owner_name=await self._owner_name(actor.user_id))

    async def _owner_name(self, owner_id: Any) -> str | None:
        if not owner_id:
            return None
        user = await self.users.find_safe_by_id(str(owner_id))
        return user.get("full_name") if user else None

    # --- status templates (reusable workflows) ---
    async def list_status_templates(self, actor: ActorContext) -> list[dict[str, Any]]:
        """System templates + the actor's saved templates."""
        out = [{"id": t["id"], "name": t["name"], "system": True, "statuses": t["statuses"]}
               for t in SYSTEM_TEMPLATES]
        if self.status_templates and actor.user_id:
            saved = await self.status_templates.list_for_owner(actor.user_id)
            for t in saved:
                out.append({"id": str(t["_id"]), "name": t.get("name"),
                            "system": False, "statuses": t.get("statuses", [])})
        return out

    async def save_status_template(
        self, name: str, statuses: list[dict[str, Any]], actor: ActorContext
    ) -> dict[str, Any]:
        if not self.status_templates:
            raise ValidationError("Templates are unavailable")
        doc = {
            "name": name.strip() or "My template",
            "owner_id": to_object_id(actor.user_id) if actor.user_id else None,
            "statuses": normalize_statuses(statuses),
            "created_at": utcnow(),
        }
        created = await self.status_templates.insert_one(doc)
        return {"id": str(created["_id"]), "name": doc["name"], "system": False,
                "statuses": doc["statuses"]}

    @staticmethod
    def _can_see_all(actor: ActorContext) -> bool:
        """Space visibility is STRICTLY membership-based for EVERYONE — including admins
        and super admins. A space is only visible to the user who created it (its owner)
        or an active member; nobody sees a space they neither created nor belong to.
        Roles' project.* permissions grant the ABILITY to act, but membership decides
        WHICH spaces are visible."""
        return False

    async def _can_view(self, project: dict[str, Any], actor: ActorContext) -> bool:
        if self._can_see_all(actor) or self._is_owner(project, actor):
            return True
        return bool(await self.members.find_active(str(project["_id"]), actor.user_id))

    async def get_project(self, project_id: str, actor: ActorContext) -> dict[str, Any]:
        project = await self._get_or_404(project_id)
        if not await self._can_view(project, actor):
            # 404 (not 403) so a non-member can't even confirm the space exists.
            raise NotFoundError("Project not found")
        count = await self.members.count_active_by_project(project_id)
        return _serialize(project, member_count=count,
                          owner_name=await self._owner_name(project.get("owner_id")))

    async def list_projects(
        self, *, actor: ActorContext, skip: int, limit: int, status: str | None, search: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        query: dict[str, Any] = {"is_deleted": {"$ne": True}}
        if status:
            query["status"] = status
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"key": {"$regex": search.upper(), "$options": "i"}},
            ]
        # Membership scoping: non-admins see only spaces they own or belong to.
        if not self._can_see_all(actor):
            member_ids = await self.members.list_projects_for_user(actor.user_id)
            owned = await self.projects.find_many(
                {"owner_id": to_object_id(actor.user_id)}, projection={"_id": 1}, limit=2000)
            owned_ids = [o["_id"] for o in owned]
            allowed = list({str(x): x for x in [*member_ids, *owned_ids]}.values())
            query["_id"] = {"$in": allowed}

        items = await self.projects.list_projects(query, skip=skip, limit=limit)
        total = await self.projects.count(query)
        # Resolve owner (lead) names in one batch.
        owner_ids = [p["owner_id"] for p in items if p.get("owner_id")]
        owners = await self.users.find_many({"_id": {"$in": owner_ids}}, limit=500,
                                            projection={"full_name": 1}) if owner_ids else []
        names = {str(u["_id"]): u.get("full_name") for u in owners}
        out = []
        for p in items:
            count = await self.members.count_active_by_project(str(p["_id"]))
            out.append(_serialize(p, member_count=count,
                                  owner_name=names.get(str(p.get("owner_id")))))
        return out, total

    async def update_project(
        self, project_id: str, data: dict[str, Any], actor: ActorContext
    ) -> dict[str, Any]:
        existing = await self._get_or_404(project_id)
        if not (actor.has("project.update") or self._is_owner(existing, actor)):
            raise PermissionDeniedError("Only the space owner or a manager can edit this space")
        update: dict[str, Any] = {"updated_at": utcnow()}
        for field in ("name", "description", "status", "start_date", "end_date"):
            if data.get(field) is not None:
                update[field] = data[field]
        if data.get("icon") is not None:
            update["icon"] = data["icon"] or None
        updated = await self.projects.update_by_id(project_id, update)
        await self.audit.log(
            actor_id=actor.user_id, action="project.updated", entity_type="project",
            entity_id=project_id, metadata={"fields": list(update.keys())}, ip=actor.ip,
        )
        count = await self.members.count_active_by_project(project_id)
        return _serialize(updated, member_count=count)

    @staticmethod
    def _is_owner(project: dict[str, Any], actor: ActorContext) -> bool:
        return bool(project.get("owner_id")) and str(project["owner_id"]) == actor.user_id

    async def archive_project(self, project_id: str, actor: ActorContext) -> dict[str, Any]:
        project = await self._get_or_404(project_id)
        if not (actor.has("project.update") or self._is_owner(project, actor)):
            raise PermissionDeniedError("Only the space owner or a manager can archive this space")
        updated = await self.projects.update_by_id(
            project_id, {"status": "archived", "updated_at": utcnow()}
        )
        await self.audit.log(
            actor_id=actor.user_id, action="project.archived", entity_type="project",
            entity_id=project_id, ip=actor.ip,
        )
        count = await self.members.count_active_by_project(project_id)
        return _serialize(updated, member_count=count)

    async def soft_delete(self, project_id: str, actor: ActorContext) -> None:
        project = await self._get_or_404(project_id)
        # Only the person who created the space (its owner) may delete it.
        # TODO: If permissions return, optionally also allow an admin (project.delete).
        if not self._is_owner(project, actor):
            raise PermissionDeniedError("Only the person who created this space can delete it")
        await self.projects.soft_delete_by_id(project_id, when=utcnow())
        await self.audit.log(
            actor_id=actor.user_id, action="project.deleted", entity_type="project",
            entity_id=project_id, ip=actor.ip,
        )

    # --- members ---
    async def _can_manage_members(self, project_id: str, project: dict[str, Any], actor: ActorContext) -> bool:
        """TODO: Re-introduce role-based member management in a future phase.
        For now, ANY member of the space (or its owner) can add / update / remove
        members — no specific role/permission is required."""
        if self._is_owner(project, actor):
            return True
        return bool(actor.user_id and await self.members.find_active(project_id, actor.user_id))

    async def add_member(
        self, project_id: str, project_role: str, actor: ActorContext,
        *, user_id: str | None = None, email: str | None = None,
    ) -> dict[str, Any]:
        project = await self._get_or_404(project_id)
        if not await self._can_manage_members(project_id, project, actor):
            raise PermissionDeniedError("You must be a member of this space to add members")

        # Resolve an email to an existing user (server-side — works even when the
        # caller can't browse the user directory).
        if not user_id and email:
            found = await self.users.find_by_email(email)
            if not found:
                raise NotFoundError(f"No user found with email '{email}'.")
            user_id = str(found["_id"])
        if not user_id:
            raise ValidationError("Provide a user_id or email")
        if not is_valid_object_id(user_id):
            raise ValidationError("Invalid user_id")
        user = await self.users.find_safe_by_id(user_id)
        if not user or user.get("is_deleted"):
            raise NotFoundError("User not found")
        if await self.members.find_active(project_id, user_id):
            raise ConflictError("User is already a member of this project")

        member = await self.members.add(
            project_id=project_id, user_id=user_id, project_role=project_role,
            added_by=actor.user_id, added_at=utcnow(),
        )
        await self.audit.log(
            actor_id=actor.user_id, action="project.member_added", entity_type="project",
            entity_id=project_id, metadata={"user_id": user_id, "role": project_role}, ip=actor.ip,
        )
        # Notify the added user (skip self-adds, e.g. the owner on space creation).
        if user_id != actor.user_id:
            role_label = ROLE_LABELS.get(project_role, project_role)
            await self.notifications.notify(
                recipient_id=user_id, type="project.member_added",
                title=f"You were added to {project['name']}",
                body=f"You joined the space as {role_label}.",
                entity_type="project", entity_id=project_id,
            )
        return self._member_view(member, user)

    async def update_member_role(
        self, project_id: str, user_id: str, project_role: str, actor: ActorContext
    ) -> dict[str, Any]:
        project = await self._get_or_404(project_id)
        if not await self._can_manage_members(project_id, project, actor):
            raise PermissionDeniedError("You must be a member of this space to manage members")
        member = await self.members.find_active(project_id, user_id)
        if not member:
            raise NotFoundError("Member not found in project")
        updated = await self.members.update_role(member["_id"], project_role)
        user = await self.users.find_safe_by_id(user_id)
        await self.audit.log(
            actor_id=actor.user_id, action="project.member_role_changed", entity_type="project",
            entity_id=project_id, metadata={"user_id": user_id, "role": project_role}, ip=actor.ip,
        )
        # Notify the member that their role/permissions changed.
        if user_id != actor.user_id:
            role_label = ROLE_LABELS.get(project_role, project_role)
            await self.notifications.notify(
                recipient_id=user_id, type="project.role_changed",
                title=f"Your role changed in {project['name']}",
                body=f"You are now a {role_label}.",
                entity_type="project", entity_id=project_id,
            )
        return self._member_view(updated, user)

    async def remove_member(self, project_id: str, user_id: str, actor: ActorContext) -> None:
        project = await self._get_or_404(project_id)
        if not await self._can_manage_members(project_id, project, actor):
            raise PermissionDeniedError("You must be a member of this space to manage members")
        removed = await self.members.remove(project_id, user_id, utcnow())
        if not removed:
            raise NotFoundError("Member not found in project")
        await self.audit.log(
            actor_id=actor.user_id, action="project.member_removed", entity_type="project",
            entity_id=project_id, metadata={"user_id": user_id}, ip=actor.ip,
        )

    # --- custom space roles (Jira-style role management) ---
    @staticmethod
    def _serialize_role(doc: dict[str, Any]) -> dict[str, Any]:
        out = dict(doc)
        out["_id"] = str(doc["_id"])
        out["project_id"] = str(doc["project_id"])
        out["is_system"] = False
        return out

    async def list_space_roles(self, project_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        project = await self._get_or_404(project_id)
        if not await self._can_view(project, actor):
            raise NotFoundError("Project not found")
        if not self.space_roles:
            return []
        docs = await self.space_roles.list_for_project(project_id)
        return [self._serialize_role(d) for d in docs]

    async def create_space_role(
        self, project_id: str, data: dict[str, Any], actor: ActorContext
    ) -> dict[str, Any]:
        project = await self._get_or_404(project_id)
        if not await self._can_manage_members(project_id, project, actor):
            raise PermissionDeniedError("You must be a member of this space to manage roles")
        if not self.space_roles:
            raise ValidationError("Role management is unavailable")
        doc = {
            "project_id": to_object_id(project_id),
            "name": data["name"].strip(),
            "description": (data.get("description") or "").strip() or None,
            "permissions": list(dict.fromkeys(data.get("permissions") or [])),
            "is_deleted": False,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        created = await self.space_roles.insert_one(doc)
        await self.audit.log(
            actor_id=actor.user_id, action="project.role_created", entity_type="project",
            entity_id=project_id, metadata={"name": doc["name"]}, ip=actor.ip,
        )
        return self._serialize_role(created)

    async def delete_space_role(self, project_id: str, role_id: str, actor: ActorContext) -> None:
        project = await self._get_or_404(project_id)
        if not await self._can_manage_members(project_id, project, actor):
            raise PermissionDeniedError("You must be a member of this space to manage roles")
        if not self.space_roles:
            raise NotFoundError("Role not found")
        role = await self.space_roles.find_by_id(role_id)
        if not role or role.get("is_deleted") or str(role.get("project_id")) != str(to_object_id(project_id)):
            raise NotFoundError("Role not found")
        await self.space_roles.soft_delete_by_id(role_id, when=utcnow())
        await self.audit.log(
            actor_id=actor.user_id, action="project.role_deleted", entity_type="project",
            entity_id=project_id, metadata={"role_id": role_id}, ip=actor.ip,
        )

    async def list_members(self, project_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        project = await self._get_or_404(project_id)
        if not await self._can_view(project, actor):
            raise NotFoundError("Project not found")
        members = await self.members.list_active_by_project(project_id)
        user_ids = [m["user_id"] for m in members]
        # Only surface members whose user is still active — a deleted/suspended user
        # must not appear as a ghost row (blank name) here or in the assignee picker.
        users = await self.users.find_many(
            {"_id": {"$in": user_ids}, "is_deleted": {"$ne": True}, "status": "active"},
            limit=500, projection={"password_hash": 0})
        by_id = {str(u["_id"]): u for u in users}
        return [self._member_view(m, by_id[str(m["user_id"])])
                for m in members if str(m["user_id"]) in by_id]

    @staticmethod
    def _member_view(member: dict[str, Any], user: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "_id": str(member["_id"]),
            "user_id": str(member["user_id"]),
            "full_name": user.get("full_name") if user else None,
            "email": user.get("email") if user else None,
            "avatar_color": user.get("avatar_color") if user else None,
            "avatar_url": user.get("avatar_url") if user else None,
            "project_role": member["project_role"],
            "added_at": member.get("added_at"),
        }

    async def get_activity(self, project_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        """Recent activity across the space's tasks (for the Summary view)."""
        project = await self._get_or_404(project_id)
        if not await self._can_view(project, actor):
            raise NotFoundError("Project not found")
        db = self.projects.db
        oid = to_object_id(project_id)
        tasks = await db.tasks.find({"project_id": oid}, {"key": 1}).to_list(length=5000)
        keymap = {str(t["_id"]): t["key"] for t in tasks}
        # activity_logs store entity_id as a string, so match on string ids.
        task_id_strs = list(keymap.keys())
        if not task_id_strs:
            return []
        logs = await db.activity_logs.find(
            {"entity_type": "task", "entity_id": {"$in": task_id_strs}}
        ).sort("created_at", -1).limit(30).to_list(length=30)

        actor_ids = [to_object_id(l["actor_id"]) for l in logs
                     if l.get("actor_id") and is_valid_object_id(str(l["actor_id"]))]
        users = await db.users.find({"_id": {"$in": actor_ids}}, {"full_name": 1}).to_list(length=200)
        names = {str(u["_id"]): u.get("full_name") for u in users}

        out: list[dict[str, Any]] = []
        for l in logs:
            created = l.get("created_at")
            out.append({
                "actor_name": names.get(str(l.get("actor_id"))),
                "action": l.get("action"),
                "task_key": keymap.get(str(l.get("entity_id"))),
                "metadata": l.get("metadata") or {},
                "created_at": int(created.timestamp() * 1000) if created else 0,
            })
        return out

    # --- stats ---
    async def get_stats(self, project_id: str, actor: ActorContext) -> dict[str, Any]:
        project = await self._get_or_404(project_id)
        if not await self._can_view(project, actor):
            raise NotFoundError("Project not found")
        tasks = self.projects.db["tasks"]
        oid = to_object_id(project_id)
        base = {"project_id": oid, "is_deleted": {"$ne": True}}
        total = await tasks.count_documents(base)
        completed = await tasks.count_documents({**base, "status": {"$in": DONE_STATUSES}})
        pending = max(0, total - completed)
        members = await self.members.count_active_by_project(project_id)
        progress = round((completed / total) * 100, 1) if total else 0.0
        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "pending_tasks": pending,
            "team_members": members,
            "progress_percentage": progress,
        }
