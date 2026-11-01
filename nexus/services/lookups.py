"""Helpers for configurable CAD lists (priorities, statuses, categories)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.context import ValidationFailed
from nexus.core.settings_store import get_setting


async def priorities(s: AsyncSession) -> list[dict[str, Any]]:
    return sorted(await get_setting(s, "cad.priorities"), key=lambda p: p["level"])


async def priority(s: AsyncSession, level: int) -> dict[str, Any]:
    for p in await priorities(s):
        if p["level"] == level:
            return p
    raise ValidationFailed(f"Priority {level} is not configured.")


async def incident_statuses(s: AsyncSession) -> list[dict[str, Any]]:
    return await get_setting(s, "cad.incident_statuses")


async def incident_status(s: AsyncSession, key: str) -> dict[str, Any]:
    for st in await incident_statuses(s):
        if st["key"] == key:
            return st
    raise ValidationFailed(f"Incident status '{key}' is not configured.")


async def open_status_keys(s: AsyncSession) -> list[str]:
    return [st["key"] for st in await incident_statuses(s) if st.get("open")]


async def categories(s: AsyncSession) -> list[dict[str, Any]]:
    return await get_setting(s, "cad.incident_categories")


async def category(s: AsyncSession, key: str) -> dict[str, Any]:
    for c in await categories(s):
        if c["key"] == key:
            return c
    raise ValidationFailed(f"Incident category '{key}' is not configured.")


async def unit_statuses(s: AsyncSession) -> list[dict[str, Any]]:
    return await get_setting(s, "cad.unit_statuses")


async def unit_status(s: AsyncSession, key: str) -> dict[str, Any]:
    for st in await unit_statuses(s):
        if st["key"] == key:
            return st
    raise ValidationFailed(f"Unit status '{key}' is not configured.")


def label(items: list[dict], key: Any, field: str = "key", out: str = "label") -> str:
    for it in items:
        if it.get(field) == key:
            return it.get(out, str(key))
    return str(key)
