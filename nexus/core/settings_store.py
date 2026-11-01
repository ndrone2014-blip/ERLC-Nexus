"""Centralized configuration stored in the database with built-in defaults."""

from __future__ import annotations

import copy
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, ValidationFailed
from nexus.core.defaults import SETTINGS_DEFAULTS
from nexus.core.events import emit
from nexus.db.models import Setting

# Keys whose values must never be returned by the public settings API.
PRIVATE_KEYS = {"erlc.server_key_encrypted"}

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 5.0


def invalidate_cache() -> None:
    _cache.clear()


async def get_setting(session: AsyncSession, key: str) -> Any:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return copy.deepcopy(hit[1])
    row = await session.get(Setting, key)
    value = row.value if row is not None else copy.deepcopy(SETTINGS_DEFAULTS.get(key))
    _cache[key] = (time.monotonic(), value)
    return copy.deepcopy(value)


async def get_many(session: AsyncSession, keys: list[str] | None = None, include_private: bool = False) -> dict[str, Any]:
    keys = keys or list(SETTINGS_DEFAULTS)
    rows = {r.key: r.value for r in (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars()}
    out = {}
    for k in keys:
        if k in PRIVATE_KEYS and not include_private:
            continue
        out[k] = rows.get(k, copy.deepcopy(SETTINGS_DEFAULTS.get(k)))
    return out


def _validate(key: str, value: Any) -> None:
    if key not in SETTINGS_DEFAULTS:
        raise ValidationFailed(f"Unknown setting '{key}'.")
    default = SETTINGS_DEFAULTS[key]
    if default is not None and not isinstance(value, type(default)):
        if not (isinstance(default, float) and isinstance(value, int)):
            raise ValidationFailed(f"Setting '{key}' must be of type {type(default).__name__}.")
    if key == "cad.priorities":
        levels = [p.get("level") for p in value]
        if not value or len(set(levels)) != len(levels) or not all(isinstance(lv, int) for lv in levels):
            raise ValidationFailed("Priorities need unique integer levels.")
    if key in ("cad.incident_statuses", "cad.unit_statuses", "cad.incident_categories"):
        ks = [s.get("key") for s in value]
        if not value or len(set(ks)) != len(ks) or not all(isinstance(k, str) and k for k in ks):
            raise ValidationFailed("Each entry needs a unique, non-empty key.")
    if key == "cad.incident_statuses":
        required = {"new", "closed", "cancelled"}
        if not required.issubset({s["key"] for s in value}):
            raise ValidationFailed("Incident statuses must include new, closed and cancelled.")
    if key == "cad.unit_statuses":
        if not {"available", "out_of_service"}.issubset({s["key"] for s in value}):
            raise ValidationFailed("Unit statuses must include available and out_of_service.")
    if key == "cad.incident_prefix":
        if not value.isalnum() or len(value) > 8:
            raise ValidationFailed("Incident prefix must be 1-8 letters/numbers.")


async def set_setting(session: AsyncSession, actor: Actor, key: str, value: Any, *, audit_value: bool = True) -> None:
    actor.require("system.configure")
    _validate(key, value)
    row = await session.get(Setting, key)
    old = row.value if row else SETTINGS_DEFAULTS.get(key)
    if row is None:
        session.add(Setting(key=key, value=value, updated_by=actor.user_id))
    else:
        row.value = value
        row.updated_by = actor.user_id
    await audit(session, actor, "system", "config.changed", target_type="setting", target_id=key, target_ref=key,
                old=old if audit_value and key not in PRIVATE_KEYS else "[hidden]",
                new=value if audit_value and key not in PRIVATE_KEYS else "[hidden]")
    emit(session, "config.changed", {"key": key}, origin=actor.source)
    _cache.pop(key, None)


async def set_internal(session: AsyncSession, key: str, value: Any) -> None:
    """Write a setting without permission checks (system use only)."""
    row = await session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    _cache.pop(key, None)
