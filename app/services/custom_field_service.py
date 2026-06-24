"""Custom field management. Fields are scoped to a Space (inherited by all its
Lists) or to a single List. Supports create / edit / rename / delete / move /
reuse, across the three supported types: dropdown, relationship, text."""
from typing import Any

from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.custom_field_repository import CustomFieldRepository
from app.repositories.list_repository import ListRepository
from app.repositories.project_member_repository import ProjectMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow


class CustomFieldService:
    def __init__(
        self,
        fields: CustomFieldRepository,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        lists: ListRepository,
        users: UserRepository,
        audit: AuditService,
    ):
        self.fields = fields
        self.projects = projects
        self.members = members
        self.lists = lists
        self.users = users
        self.audit = audit

    # --- access ---
    async def _space_or_404(self, space_id: str) -> dict[str, Any]:
        if not is_valid_object_id(space_id):
            raise NotFoundError("Space not found")
        p = await self.projects.find_by_id(space_id)
        if not p or p.get("is_deleted"):
            raise NotFoundError("Space not found")
        return p

    async def _assert_member(self, space_id: str, project: dict[str, Any], actor: ActorContext) -> None:
        if actor.has("project.update"):
            return
        if project.get("owner_id") and str(project["owner_id"]) == actor.user_id:
            return
        if actor.user_id and await self.members.find_active(space_id, actor.user_id):
            return
        raise PermissionDeniedError("You are not a member of this space")

    async def _list_or_404(self, list_id: str) -> dict[str, Any]:
        if not is_valid_object_id(list_id):
            raise NotFoundError("List not found")
        doc = await self.lists.find_by_id(list_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundError("List not found")
        return doc

    async def _field_or_404(self, field_id: str) -> dict[str, Any]:
        if not is_valid_object_id(field_id):
            raise NotFoundError("Field not found")
        doc = await self.fields.find_by_id(field_id)
        if not doc or doc.get("is_deleted"):
            raise NotFoundError("Field not found")
        return doc

    # --- serialize ---
    async def _name_cache(self):
        cache: dict[str, str | None] = {}

        async def resolve(uid):
            if not uid:
                return None
            uid = str(uid)
            if uid not in cache:
                u = await self.users.find_safe_by_id(uid) if is_valid_object_id(uid) else None
                cache[uid] = u.get("full_name") if u else None
            return cache[uid]
        return resolve

    @staticmethod
    def _base(doc: dict[str, Any], *, inherited: bool, location: str | None,
              created_by_name: str | None) -> dict[str, Any]:
        return {
            "_id": str(doc["_id"]),
            "scope": doc.get("scope"),
            "space_id": str(doc["space_id"]),
            "list_id": str(doc["list_id"]) if doc.get("list_id") else None,
            "name": doc.get("name"),
            "type": doc.get("type"),
            "config": doc.get("config", {}),
            "order": doc.get("order", 0),
            "inherited": inherited,
            "location": location,
            "created_by": str(doc["created_by"]) if doc.get("created_by") else None,
            "created_by_name": created_by_name,
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }

    # --- validation ---
    @staticmethod
    def _clean_config(ftype: str, config: dict[str, Any]) -> dict[str, Any]:
        config = config or {}
        fill = config.get("fill_method") if config.get("fill_method") in ("manual", "ai") else "manual"
        if ftype == "dropdown":
            opts = []
            for o in config.get("options", []):
                label = (o.get("label") or "").strip()
                if label:
                    item = {"label": label, "color": o.get("color") or "#6b7280"}
                    if o.get("default"):
                        item["default"] = True
                    opts.append(item)
            return {"options": opts, "multiple": bool(config.get("multiple", False)), "fill_method": fill}
        if ftype == "text":
            return {"multiline": bool(config.get("multiline", False)), "fill_method": fill}
        if ftype == "relationship":
            related = config.get("related_to") if config.get("related_to") in ("workspace", "list") else "workspace"
            out: dict[str, Any] = {"target": "task", "related_to": related, "rollup": bool(config.get("rollup", False))}
            if related == "list" and config.get("list_id"):
                out["list_id"] = config["list_id"]
            return out
        return {}

    # --- CRUD ---
    async def create_field(self, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        space_id = data["space_id"]
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)

        scope = data["scope"]
        list_oid = None
        if scope == "list":
            if not data.get("list_id"):
                raise ValidationError("list_id is required for a List-scoped field")
            lst = await self._list_or_404(data["list_id"])
            if str(lst["space_id"]) != space_id:
                raise ValidationError("List does not belong to this Space")
            list_oid = to_object_id(data["list_id"])

        if data["type"] not in ("dropdown", "relationship", "text"):
            raise ValidationError("Unsupported field type")

        # Append after existing fields in the same scope (ClickUp keeps insertion order).
        siblings = await self.fields.list_for_list(data["list_id"]) if scope == "list" \
            else await self.fields.list_for_space(space_id)
        order = max((f.get("order", 0) for f in siblings), default=-1) + 1

        now = utcnow()
        doc = {
            "scope": scope,
            "space_id": to_object_id(space_id),
            "list_id": list_oid,
            "name": data["name"].strip(),
            "type": data["type"],
            "config": self._clean_config(data["type"], data.get("config") or {}),
            "order": order,
            "created_by": to_object_id(actor.user_id) if actor.user_id else None,
            "is_deleted": False,
            "deleted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.fields.insert_one(doc)
        await self.audit.log(actor_id=actor.user_id, action="custom_field.created", entity_type="custom_field",
                             entity_id=str(created["_id"]), metadata={"name": doc["name"], "scope": scope}, ip=actor.ip)
        resolve = await self._name_cache()
        loc = project["name"] if scope == "space" else (await self._list_or_404(str(list_oid)))["name"]
        return self._base(created, inherited=False, location=loc, created_by_name=await resolve(actor.user_id))

    async def list_fields(self, space_id: str, list_id: str | None, actor: ActorContext) -> list[dict[str, Any]]:
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        resolve = await self._name_cache()
        out: list[dict[str, Any]] = []

        space_fields = await self.fields.list_for_space(space_id)
        if list_id:
            lst = await self._list_or_404(list_id)
            # Space fields are inherited (read-only here); then the List's own fields.
            for f in space_fields:
                out.append(self._base(f, inherited=True, location=project["name"],
                                      created_by_name=await resolve(f.get("created_by"))))
            for f in await self.fields.list_for_list(list_id):
                out.append(self._base(f, inherited=False, location=lst["name"],
                                      created_by_name=await resolve(f.get("created_by"))))
        else:
            for f in space_fields:
                out.append(self._base(f, inherited=False, location=project["name"],
                                      created_by_name=await resolve(f.get("created_by"))))
        return out

    async def list_all_fields(self, space_id: str, actor: ActorContext) -> list[dict[str, Any]]:
        """Every field anywhere under a Space (space-scoped + all Lists), with location."""
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        resolve = await self._name_cache()
        lists = await self.lists.list_for_space(space_id)
        list_names = {str(l["_id"]): l["name"] for l in lists}
        out = []
        for f in await self.fields.list_all_in_space(space_id):
            loc = project["name"] if f.get("scope") == "space" else list_names.get(str(f.get("list_id")), "List")
            out.append(self._base(f, inherited=False, location=loc,
                                  created_by_name=await resolve(f.get("created_by"))))
        return out

    async def reusable_fields(self, space_id: str, list_id: str | None, actor: ActorContext) -> list[dict[str, Any]]:
        """Existing fields elsewhere in the Space that can be added (reused) here."""
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        resolve = await self._name_cache()
        target_list = to_object_id(list_id) if list_id else None
        out = []
        for f in await self.fields.list_all_in_space(space_id):
            # Skip fields already in the target scope.
            if list_id:
                if f.get("scope") == "list" and str(f.get("list_id")) == list_id:
                    continue
            else:
                if f.get("scope") == "space":
                    continue
            loc = project["name"] if f.get("scope") == "space" else "List"
            out.append(self._base(f, inherited=False, location=loc,
                                  created_by_name=await resolve(f.get("created_by"))))
        _ = target_list
        return out

    async def update_field(self, field_id: str, data: dict[str, Any], actor: ActorContext) -> dict[str, Any]:
        doc = await self._field_or_404(field_id)
        project = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), project, actor)
        update: dict[str, Any] = {"updated_at": utcnow()}
        if data.get("name") is not None:
            update["name"] = data["name"].strip()
        if data.get("config") is not None:
            update["config"] = self._clean_config(doc["type"], data["config"])
        updated = await self.fields.update_by_id(field_id, update)
        await self.audit.log(actor_id=actor.user_id, action="custom_field.updated", entity_type="custom_field",
                             entity_id=field_id, ip=actor.ip)
        resolve = await self._name_cache()
        return self._base(updated, inherited=False, location=None, created_by_name=await resolve(updated.get("created_by")))

    async def delete_field(self, field_id: str, actor: ActorContext) -> None:
        doc = await self._field_or_404(field_id)
        project = await self._space_or_404(str(doc["space_id"]))
        await self._assert_member(str(doc["space_id"]), project, actor)
        await self.fields.soft_delete_by_id(field_id, when=utcnow())
        await self.audit.log(actor_id=actor.user_id, action="custom_field.deleted", entity_type="custom_field",
                             entity_id=field_id, ip=actor.ip)

    async def move_field(self, field_id: str, scope: str, list_id: str | None, actor: ActorContext) -> dict[str, Any]:
        doc = await self._field_or_404(field_id)
        space_id = str(doc["space_id"])
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        update: dict[str, Any] = {"scope": scope, "updated_at": utcnow()}
        if scope == "list":
            if not list_id:
                raise ValidationError("list_id is required to move to a List")
            lst = await self._list_or_404(list_id)
            if str(lst["space_id"]) != space_id:
                raise ValidationError("Target List is not in this Space")
            update["list_id"] = to_object_id(list_id)
        else:
            update["list_id"] = None
        updated = await self.fields.update_by_id(field_id, update)
        await self.audit.log(actor_id=actor.user_id, action="custom_field.moved", entity_type="custom_field",
                             entity_id=field_id, metadata={"scope": scope}, ip=actor.ip)
        resolve = await self._name_cache()
        return self._base(updated, inherited=False, location=None, created_by_name=await resolve(updated.get("created_by")))

    async def duplicate_field(self, field_id: str, scope: str, space_id: str,
                              list_id: str | None, actor: ActorContext) -> dict[str, Any]:
        src = await self._field_or_404(field_id)
        project = await self._space_or_404(space_id)
        await self._assert_member(space_id, project, actor)
        list_oid = None
        if scope == "list":
            if not list_id:
                raise ValidationError("list_id is required")
            await self._list_or_404(list_id)
            list_oid = to_object_id(list_id)
        now = utcnow()
        doc = {
            "scope": scope, "space_id": to_object_id(space_id), "list_id": list_oid,
            "name": src["name"], "type": src["type"], "config": src.get("config", {}),
            "created_by": to_object_id(actor.user_id) if actor.user_id else None,
            "is_deleted": False, "deleted_at": None, "created_at": now, "updated_at": now,
        }
        created = await self.fields.insert_one(doc)
        await self.audit.log(actor_id=actor.user_id, action="custom_field.reused", entity_type="custom_field",
                             entity_id=str(created["_id"]), metadata={"from": field_id}, ip=actor.ip)
        resolve = await self._name_cache()
        return self._base(created, inherited=False, location=None, created_by_name=await resolve(actor.user_id))

    async def reorder_fields(self, ids: list[str], actor: ActorContext) -> None:
        """Persist a new display order for a set of fields (must share one Space)."""
        if not ids:
            return
        now = utcnow()
        space_id: str | None = None
        for idx, fid in enumerate(ids):
            doc = await self._field_or_404(fid)
            if space_id is None:
                space_id = str(doc["space_id"])
                project = await self._space_or_404(space_id)
                await self._assert_member(space_id, project, actor)
            elif str(doc["space_id"]) != space_id:
                raise ValidationError("All fields must belong to the same Space")
            await self.fields.update_by_id(fid, {"order": idx, "updated_at": now})
