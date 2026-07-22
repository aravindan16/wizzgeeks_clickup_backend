"""Comment business logic for tasks, with ownership enforcement."""
import re
from typing import Any

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.comment_repository import CommentRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.user_service import ActorContext
from app.utils.datetime import utcnow

# Rich mentions are encoded as `@[Full Name](userId)` in the comment body.
_MENTION_RE = re.compile(r"@\[[^\]]+\]\(([0-9a-fA-F]{24})\)")


def _parse_mentions(body: str) -> list[str]:
    """Extract mentioned user ids from `@[Name](userId)` tokens (deduped, order-preserving)."""
    out: list[str] = []
    for uid in _MENTION_RE.findall(body or ""):
        if uid not in out:
            out.append(uid)
    return out


def _serialize(c: dict[str, Any], author_name: str | None = None) -> dict[str, Any]:
    return {
        "_id": str(c["_id"]),
        "task_id": str(c["entity_id"]),
        "author_id": str(c["author_id"]),
        "author_name": author_name,
        "body": c["body"],
        "is_edited": c.get("is_edited", False),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
    }


class CommentService:
    def __init__(
        self,
        comments: CommentRepository,
        tasks: TaskRepository,
        users: UserRepository,
        audit: AuditService,
        notifications: NotificationService | None = None,
    ):
        self.comments = comments
        self.tasks = tasks
        self.users = users
        self.audit = audit
        self.notifications = notifications

    async def _task_or_404(self, task_id: str) -> dict[str, Any]:
        if not is_valid_object_id(task_id):
            raise NotFoundError("Task not found")
        task = await self.tasks.find_by_id(task_id)
        if not task or task.get("is_deleted"):
            raise NotFoundError("Task not found")
        return task

    async def list_comments(self, task_id: str) -> list[dict[str, Any]]:
        await self._task_or_404(task_id)
        rows = await self.comments.list_for_task(task_id)
        author_ids = list({r["author_id"] for r in rows})
        users = await self.users.find_many({"_id": {"$in": author_ids}}, limit=500,
                                           projection={"full_name": 1})
        names = {str(u["_id"]): u.get("full_name") for u in users}
        return [_serialize(r, names.get(str(r["author_id"]))) for r in rows]

    async def add_comment(self, task_id: str, body: str, actor: ActorContext) -> dict[str, Any]:
        task = await self._task_or_404(task_id)
        now = utcnow()
        mentions = _parse_mentions(body)
        doc = {
            "entity_type": "task",
            "entity_id": to_object_id(task_id),
            "author_id": to_object_id(actor.user_id),
            "body": body,
            "mentions": [to_object_id(m) for m in mentions],
            "parent_comment_id": None,
            "is_edited": False,
            "is_deleted": False,
            "created_at": now,
            "updated_at": now,
        }
        created = await self.comments.insert_one(doc)
        await self.tasks.adjust_comment_count(task_id, 1)
        await self.audit.log(actor_id=actor.user_id, action="comment.created", entity_type="task",
                             entity_id=task_id, metadata={"comment_id": str(created["_id"])}, ip=actor.ip)
        user = await self.users.find_safe_by_id(actor.user_id)
        await self._notify_comment(task, body, mentions, actor, user)
        return _serialize(created, user.get("full_name") if user else None)

    async def _notify_comment(self, task, body, mentions, actor, actor_user) -> None:
        if not self.notifications:
            return
        disp = {
            "actor_id": actor.user_id,
            "actor_name": actor_user.get("full_name") if actor_user else None,
            "actor_avatar_url": actor_user.get("avatar_url") if actor_user else None,
            "actor_avatar_color": actor_user.get("avatar_color") if actor_user else None,
        }
        name = disp.get("actor_name") or "Someone"
        preview = (body or "").strip()
        if len(preview) > 140:
            preview = preview[:140] + "…"
        common = dict(entity_type="task", entity_id=str(task["_id"]),
                      entity_key=task.get("key"), entity_title=task.get("title"), **disp)
        # Mentioned users get an explicit mention notification.
        await self.notifications.notify_many(
            mentions, exclude=actor.user_id, type="comment.mention",
            title=f"{name} mentioned you", body=preview, **common)
        # Reporter + assignee (who aren't already mentioned or the author) get a comment notification.
        audience = {str(task[k]) for k in ("reporter_id", "assignee_id") if task.get(k)}
        audience -= set(mentions)
        await self.notifications.notify_many(
            audience, exclude=actor.user_id, type="comment.added",
            title=f"{name} commented · {task.get('key')}", body=preview, **common)

    async def _get_owned_or_elevated(self, comment_id: str, actor: ActorContext,
                                     *, for_delete: bool) -> dict[str, Any]:
        if not is_valid_object_id(comment_id):
            raise NotFoundError("Comment not found")
        comment = await self.comments.find_by_id(comment_id)
        if not comment or comment.get("is_deleted"):
            raise NotFoundError("Comment not found")
        is_author = str(comment["author_id"]) == actor.user_id
        # Authors can edit/delete their own. Elevated users (project.update) may delete others'.
        if is_author:
            return comment
        if for_delete and actor.has("project.update"):
            return comment
        raise PermissionDeniedError("You can only modify your own comments")

    async def edit_comment(self, comment_id: str, body: str, actor: ActorContext) -> dict[str, Any]:
        comment = await self._get_owned_or_elevated(comment_id, actor, for_delete=False)
        updated = await self.comments.update_by_id(
            comment["_id"], {"body": body, "is_edited": True, "updated_at": utcnow()}
        )
        user = await self.users.find_safe_by_id(str(updated["author_id"]))
        return _serialize(updated, user.get("full_name") if user else None)

    async def delete_comment(self, comment_id: str, actor: ActorContext) -> None:
        comment = await self._get_owned_or_elevated(comment_id, actor, for_delete=True)
        await self.comments.update_by_id(
            comment["_id"], {"is_deleted": True, "deleted_at": utcnow()}
        )
        await self.tasks.adjust_comment_count(str(comment["entity_id"]), -1)
        await self.audit.log(actor_id=actor.user_id, action="comment.deleted", entity_type="task",
                             entity_id=str(comment["entity_id"]),
                             metadata={"comment_id": comment_id}, ip=actor.ip)
