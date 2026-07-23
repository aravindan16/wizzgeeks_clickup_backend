"""Aggregates all v1 routers. New modules register their router here."""
from fastapi import APIRouter

from app.api.v1 import (
    audit, auth, chat, custom_fields, health, labels, lists, notifications,
    projects, roles, saved_filters, settings, tasks, user_dashboards, users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(lists.router, prefix="/lists", tags=["lists"])
api_router.include_router(custom_fields.router, prefix="/custom-fields", tags=["custom-fields"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(user_dashboards.router, prefix="/user-dashboards", tags=["user-dashboards"])
api_router.include_router(saved_filters.router, prefix="/saved-filters", tags=["saved-filters"])
api_router.include_router(labels.router, prefix="/labels", tags=["labels"])
api_router.include_router(settings.router, prefix="/admin", tags=["settings"])
api_router.include_router(audit.router, prefix="/admin", tags=["audit"])

# Module routers appended as they are built:
# api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
# ...
