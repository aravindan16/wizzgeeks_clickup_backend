"""Chat business logic: direct (1:1) and group conversations + messages.

Access is membership-scoped — a user can only read/post in conversations they
belong to. New messages and message updates (edit/delete/react/pin) are pushed
in realtime to every member's open sockets over the shared notification hub.
"""
from typing import Any, Iterable

from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.realtime.hub import hub
from app.repositories.base import is_valid_object_id, to_object_id
from app.repositories.chat_message_repository import ChatMessageRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
from app.utils.datetime import utcnow
from app.utils.storage import presign_url, store_group_avatar


def _preview(body: str | None, n: int = 120) -> str:
    body = (body or "").strip()
    return body if len(body) <= n else body[:n] + "…"


class ChatService:
    def __init__(
        self,
        conversations: ConversationRepository,
        messages: ChatMessageRepository,
        users: UserRepository,
    ):
        self.conversations = conversations
        self.messages = messages
        self.users = users

    # --- helpers ---
    async def _user_map(self, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        oids = [to_object_id(i) for i in {str(i) for i in ids} if is_valid_object_id(str(i))]
        rows = await self.users.find_many(
            {"_id": {"$in": oids}}, limit=500,
            projection={"full_name": 1, "avatar_url": 1, "avatar_color": 1, "email": 1})
        return {str(u["_id"]): u for u in rows}

    @staticmethod
    def _serialize_last(lm: dict[str, Any] | None) -> dict[str, Any] | None:
        if not lm:
            return None
        return {
            "body": lm.get("body"),
            "sender_id": str(lm["sender_id"]) if lm.get("sender_id") else None,
            "sender_name": lm.get("sender_name"),
            "created_at": lm.get("created_at"),
        }

    @staticmethod
    def _serialize_msg(m: dict[str, Any], umap: dict[str, dict], me: str | None = None) -> dict[str, Any]:
        u = umap.get(str(m["sender_id"])) or {}
        deleted = bool(m.get("is_deleted"))
        att = m.get("attachment")
        if att and not deleted and att.get("url"):
            att = {**att, "url": presign_url(att.get("url"))}  # private S3 → temporary signed URL
        return {
            "id": str(m["_id"]),
            "conversation_id": str(m["conversation_id"]),
            "sender_id": str(m["sender_id"]),
            "sender_name": u.get("full_name") or u.get("email"),
            "sender_avatar_url": u.get("avatar_url"),
            "sender_avatar_color": u.get("avatar_color"),
            "body": None if deleted else m.get("body"),
            "attachment": None if deleted else att,
            "poll": None if deleted else m.get("poll"),
            "created_at": m.get("created_at"),
            "is_edited": bool(m.get("is_edited")),
            "is_deleted": deleted,
            "reply_to": None if deleted else m.get("reply_to"),
            "forwarded_from": None if deleted else m.get("forwarded_from"),
            "reactions": {} if deleted else (m.get("reactions") or {}),
            "pinned": bool(m.get("pinned")),
            "bookmarked": bool(me and me in (m.get("bookmarked_by") or [])),
        }

    async def _serialize_conv(self, conv: dict[str, Any], me: str, umap: dict[str, dict]) -> dict[str, Any]:
        member_ids = [str(m) for m in conv.get("member_ids", [])]
        if conv.get("type") == "group":
            name = conv.get("name") or "Group chat"
            avatar_url, avatar_color = presign_url(conv.get("avatar_url")), None
        else:  # direct → show the OTHER participant
            other = next((m for m in member_ids if m != me), me)
            u = umap.get(other) or {}
            name = u.get("full_name") or u.get("email") or "Direct message"
            avatar_url, avatar_color = u.get("avatar_url"), u.get("avatar_color")
        reads = conv.get("reads") or {}
        since = reads.get(me)
        unread = await self.messages.count_unread(str(conv["_id"]), me, since)
        members = [{
            "id": mid,
            "name": (umap.get(mid) or {}).get("full_name") or (umap.get(mid) or {}).get("email"),
            "avatar_url": (umap.get(mid) or {}).get("avatar_url"),
            "avatar_color": (umap.get(mid) or {}).get("avatar_color"),
        } for mid in member_ids]
        return {
            "id": str(conv["_id"]),
            "type": conv.get("type"),
            "name": name,
            "avatar_url": avatar_url,
            "avatar_color": avatar_color,
            "created_by": str(conv["created_by"]) if conv.get("created_by") else None,
            "member_ids": member_ids,
            "members": members,
            "unread": unread,
            "reads": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in reads.items()},
            "last_message": self._serialize_last(conv.get("last_message")),
            "created_at": conv.get("created_at"),
            "updated_at": conv.get("updated_at"),
        }

    async def _require_member(self, conv_id: str, user_id: str) -> dict[str, Any]:
        conv = await self.conversations.get_for_member(conv_id, user_id) if is_valid_object_id(conv_id) else None
        if not conv:
            raise NotFoundError("Conversation not found")
        return conv

    async def _require_message(self, message_id: str, user_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        msg = await self.messages.find_by_id(message_id) if is_valid_object_id(message_id) else None
        if not msg:
            raise NotFoundError("Message not found")
        conv = await self._require_member(str(msg["conversation_id"]), user_id)
        return msg, conv

    async def _assert_users_exist(self, ids: Iterable[str]) -> None:
        ids = [i for i in ids]
        if not ids:
            return
        umap = await self._user_map(ids)
        if [i for i in ids if i not in umap]:
            raise ValidationError("One or more users were not found")

    async def list_contacts(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self.users.find_many(
            {"status": "active", "is_deleted": {"$ne": True}}, limit=500,
            projection={"full_name": 1, "email": 1, "avatar_url": 1, "avatar_color": 1})
        out = [{
            "id": str(u["_id"]),
            "name": u.get("full_name") or u.get("email"),
            "email": u.get("email"),
            "avatar_url": u.get("avatar_url"),
            "avatar_color": u.get("avatar_color"),
        } for u in rows if str(u["_id"]) != user_id]
        out.sort(key=lambda x: (x["name"] or "").lower())
        return out

    # --- conversations ---
    async def list_conversations(self, user_id: str) -> list[dict[str, Any]]:
        convs = await self.conversations.list_for_member(user_id)
        ids = {user_id}
        for c in convs:
            ids.update(str(m) for m in c.get("member_ids", []))
        umap = await self._user_map(ids)
        return [await self._serialize_conv(c, user_id, umap) for c in convs]

    async def create_direct(self, user_id: str, other_id: str) -> dict[str, Any]:
        if not is_valid_object_id(other_id):
            raise ValidationError("Invalid user id")
        if other_id == user_id:
            raise ValidationError("You can't start a chat with yourself")
        await self._assert_users_exist([other_id])
        existing = await self.conversations.find_direct(user_id, other_id)
        now = utcnow()
        conv = existing or await self.conversations.create({
            "type": "direct", "name": None,
            "member_ids": [to_object_id(user_id), to_object_id(other_id)],
            "created_by": to_object_id(user_id), "reads": {}, "last_message": None,
            "created_at": now, "last_activity_at": now, "updated_at": now,
        })
        umap = await self._user_map([user_id, other_id])
        return await self._serialize_conv(conv, user_id, umap)

    async def create_group(self, user_id: str, name: str, member_ids: list[str]) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Group name is required")
        others = [m for m in dict.fromkeys(member_ids) if m and m != user_id]
        await self._assert_users_exist(others)
        if not others:
            raise ValidationError("Add at least one other member")
        members = [user_id, *others]
        now = utcnow()
        conv = await self.conversations.create({
            "type": "group", "name": name,
            "member_ids": [to_object_id(m) for m in members],
            "created_by": to_object_id(user_id), "reads": {}, "last_message": None,
            "created_at": now, "last_activity_at": now, "updated_at": now,
        })
        umap = await self._user_map(members)
        return await self._serialize_conv(conv, user_id, umap)

    async def set_group_avatar(self, conv_id: str, user_id: str, content: bytes, content_type: str) -> dict[str, Any]:
        conv = await self._require_member(conv_id, user_id)
        if conv.get("type") != "group":
            raise ValidationError("Only group chats can have a photo")
        url = store_group_avatar(conv_id, content, content_type)
        updated = await self.conversations.update_by_id(conv_id, {"avatar_url": url, "updated_at": utcnow()})
        umap = await self._user_map([str(m) for m in (updated or conv)["member_ids"]] + [user_id])
        return await self._serialize_conv(updated or conv, user_id, umap)

    async def get_conversation(self, conv_id: str, user_id: str) -> dict[str, Any]:
        conv = await self._require_member(conv_id, user_id)
        umap = await self._user_map([str(m) for m in conv["member_ids"]] + [user_id])
        return await self._serialize_conv(conv, user_id, umap)

    # --- messages ---
    async def list_messages(self, conv_id: str, user_id: str, *, skip: int, limit: int):
        await self._require_member(conv_id, user_id)
        rows = await self.messages.list_for_conversation(conv_id, skip=skip, limit=limit)
        total = await self.messages.count_for_conversation(conv_id)
        umap = await self._user_map({str(r["sender_id"]) for r in rows})
        await self.conversations.set_read(conv_id, user_id, utcnow())
        items = [self._serialize_msg(r, umap, user_id) for r in reversed(rows)]  # oldest → newest
        return items, total

    async def list_pinned(self, conv_id: str, user_id: str) -> list[dict[str, Any]]:
        await self._require_member(conv_id, user_id)
        rows = await self.messages.list_pinned(conv_id)
        umap = await self._user_map({str(r["sender_id"]) for r in rows})
        return [self._serialize_msg(r, umap, user_id) for r in rows]

    async def list_bookmarks(self, user_id: str) -> list[dict[str, Any]]:
        rows = await self.messages.list_bookmarked(user_id)
        umap = await self._user_map({str(r["sender_id"]) for r in rows})
        return [self._serialize_msg(r, umap, user_id) for r in rows if not r.get("is_deleted")]

    async def send_message(self, conv_id: str, user_id: str, body: str,
                           reply_to_id: str | None = None,
                           attachment: dict[str, Any] | None = None) -> dict[str, Any]:
        body = (body or "").strip()
        if not body and not attachment:
            raise ValidationError("Message cannot be empty")
        conv = await self._require_member(conv_id, user_id)
        reply_to = await self._reply_ref(reply_to_id, conv_id)
        return await self._create_and_broadcast(conv, user_id, body, reply_to=reply_to, attachment=attachment)

    async def create_poll(self, conv_id: str, user_id: str, question: str,
                          options: list[str], multi: bool = False) -> dict[str, Any]:
        question = (question or "").strip()
        opts = [o.strip() for o in options if o and o.strip()]
        if not question:
            raise ValidationError("Poll question is required")
        if len(opts) < 2:
            raise ValidationError("Add at least two options")
        conv = await self._require_member(conv_id, user_id)
        poll = {
            "question": question,
            "multi": bool(multi),
            "options": [{"id": str(i), "text": t, "votes": []} for i, t in enumerate(opts)],
        }
        return await self._create_and_broadcast(conv, user_id, "", poll=poll)

    async def vote_poll(self, message_id: str, user_id: str, option_id: str) -> dict[str, Any]:
        msg, conv = await self._require_message(message_id, user_id)
        poll = msg.get("poll")
        if not poll:
            raise ValidationError("This message is not a poll")
        options = poll.get("options") or []
        if not any(o["id"] == option_id for o in options):
            raise ValidationError("Invalid option")
        for o in options:
            voters = [v for v in o.get("votes", []) if v != user_id]
            if o["id"] == option_id:
                # toggle: add my vote unless I already had it (then it stays removed)
                if user_id not in o.get("votes", []):
                    voters.append(user_id)
            elif not poll.get("multi"):
                pass  # single-choice: my vote was already stripped above
            else:
                voters = o.get("votes", [])  # multi: leave other options untouched
            o["votes"] = voters
        updated = await self.messages.update_by_id(message_id, {"poll": poll})
        return await self._push_updated(conv, updated, user_id)

    async def _reply_ref(self, reply_to_id: str | None, conv_id: str) -> dict[str, Any] | None:
        if not reply_to_id or not is_valid_object_id(reply_to_id):
            return None
        src = await self.messages.find_by_id(reply_to_id)
        if not src or str(src["conversation_id"]) != str(conv_id) or src.get("is_deleted"):
            return None
        sender = await self.users.find_safe_by_id(str(src["sender_id"]))
        return {"id": str(src["_id"]), "sender_name": (sender or {}).get("full_name"),
                "body": _preview(src.get("body"))}

    async def forward_message(self, message_id: str, user_id: str, target_conv_id: str) -> dict[str, Any]:
        src, _ = await self._require_message(message_id, user_id)
        if src.get("is_deleted"):
            raise ValidationError("Cannot forward a deleted message")
        target = await self._require_member(target_conv_id, user_id)
        orig_sender = await self.users.find_safe_by_id(str(src["sender_id"]))
        fwd = {"sender_name": (orig_sender or {}).get("full_name") or "someone"}
        return await self._create_and_broadcast(target, user_id, src.get("body") or "",
                                                forwarded_from=fwd, attachment=src.get("attachment"))

    async def _create_and_broadcast(self, conv, user_id, body, *, reply_to=None, forwarded_from=None,
                                    attachment=None, poll=None):
        now = utcnow()
        sender = await self.users.find_safe_by_id(user_id)
        created = await self.messages.create({
            "conversation_id": conv["_id"],
            "sender_id": to_object_id(user_id),
            "body": body, "attachment": attachment, "poll": poll, "created_at": now,
            "reply_to": reply_to, "forwarded_from": forwarded_from,
            "is_edited": False, "is_deleted": False,
            "reactions": {}, "pinned": False, "pinned_at": None, "pinned_by": None,
            "bookmarked_by": [],
        })
        if body:
            preview = body
        elif poll:
            preview = f"📊 Poll: {poll.get('question')}"
        elif attachment:
            preview = "📷 Photo" if (attachment.get("kind") == "image") else f"📎 {attachment.get('name') or 'File'}"
        else:
            preview = ""
        await self.conversations.touch_last_message(str(conv["_id"]), {
            "body": preview, "sender_id": to_object_id(user_id),
            "sender_name": (sender or {}).get("full_name"), "created_at": now,
        }, now)
        await self.conversations.set_read(str(conv["_id"]), user_id, now)
        msg = self._serialize_msg(created, {user_id: sender} if sender else {}, user_id)
        await self._push(conv, "chat.message", msg)
        return msg

    # --- message actions ---
    async def edit_message(self, message_id: str, user_id: str, body: str) -> dict[str, Any]:
        body = (body or "").strip()
        if not body:
            raise ValidationError("Message cannot be empty")
        msg, conv = await self._require_message(message_id, user_id)
        if str(msg["sender_id"]) != user_id:
            raise PermissionDeniedError("You can only edit your own messages")
        if msg.get("is_deleted"):
            raise ValidationError("Cannot edit a deleted message")
        updated = await self.messages.update_by_id(message_id, {"body": body, "is_edited": True, "updated_at": utcnow()})
        return await self._push_updated(conv, updated, user_id)

    async def delete_message(self, message_id: str, user_id: str) -> dict[str, Any]:
        msg, conv = await self._require_message(message_id, user_id)
        if str(msg["sender_id"]) != user_id:
            raise PermissionDeniedError("You can only delete your own messages")
        updated = await self.messages.update_by_id(message_id, {
            "is_deleted": True, "deleted_at": utcnow(), "body": None,
            "reactions": {}, "reply_to": None, "forwarded_from": None,
            "pinned": False, "bookmarked_by": [],
        })
        return await self._push_updated(conv, updated, user_id)

    async def react(self, message_id: str, user_id: str, emoji: str) -> dict[str, Any]:
        emoji = (emoji or "").strip()
        if not emoji:
            raise ValidationError("Emoji required")
        msg, conv = await self._require_message(message_id, user_id)
        if msg.get("is_deleted"):
            raise ValidationError("Cannot react to a deleted message")
        reactions = dict(msg.get("reactions") or {})
        users = list(reactions.get(emoji, []))
        if user_id in users:
            users.remove(user_id)
        else:
            users.append(user_id)
        if users:
            reactions[emoji] = users
        else:
            reactions.pop(emoji, None)
        updated = await self.messages.update_by_id(message_id, {"reactions": reactions})
        return await self._push_updated(conv, updated, user_id)

    async def set_pin(self, message_id: str, user_id: str, pinned: bool) -> dict[str, Any]:
        msg, conv = await self._require_message(message_id, user_id)
        updated = await self.messages.update_by_id(message_id, {
            "pinned": pinned,
            "pinned_at": utcnow() if pinned else None,
            "pinned_by": user_id if pinned else None,
        })
        return await self._push_updated(conv, updated, user_id)

    async def set_bookmark(self, message_id: str, user_id: str, bookmarked: bool) -> dict[str, Any]:
        msg, conv = await self._require_message(message_id, user_id)
        marks = [m for m in (msg.get("bookmarked_by") or []) if m != user_id]
        if bookmarked:
            marks.append(user_id)
        updated = await self.messages.update_by_id(message_id, {"bookmarked_by": marks})
        # Bookmarks are personal — don't broadcast; just return the caller's view.
        umap = await self._user_map([str(updated["sender_id"])])
        return self._serialize_msg(updated, umap, user_id)

    async def mark_read(self, conv_id: str, user_id: str) -> None:
        await self._require_member(conv_id, user_id)
        await self.conversations.set_read(conv_id, user_id, utcnow())

    # --- realtime ---
    async def _push(self, conv: dict[str, Any], event: str, msg: dict[str, Any]) -> None:
        try:
            data = dict(msg)
            if hasattr(data.get("created_at"), "isoformat"):
                data["created_at"] = data["created_at"].isoformat()
            data.pop("bookmarked", None)  # personal flag — clients keep their own
            payload = {"event": event, "data": data}
            for m in conv.get("member_ids", []):
                await hub.push(str(m), payload)
        except Exception:  # noqa: BLE001
            pass

    async def _push_updated(self, conv: dict[str, Any], updated: dict[str, Any], me: str) -> dict[str, Any]:
        umap = await self._user_map([str(updated["sender_id"])])
        msg = self._serialize_msg(updated, umap, me)
        await self._push(conv, "chat.message.updated", msg)
        return msg
