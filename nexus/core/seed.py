"""First-run initialisation: permissions catalog, roles, departments, locations."""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.defaults import DEFAULT_DEPARTMENTS, DEFAULT_LOCATIONS, UNIT_TYPES
from nexus.core.permissions import DEFAULT_ROLES, PERMISSIONS
from nexus.db.models import Department, Location, Permission, Rank, Role, User, UserRole

log = logging.getLogger("nexus.seed")


async def seed_permissions_and_roles(session: AsyncSession) -> None:
    existing = {p.key: p for p in (await session.execute(select(Permission))).scalars()}
    for key, (cat, desc) in PERMISSIONS.items():
        if key in existing:
            existing[key].category, existing[key].description = cat, desc
        else:
            session.add(Permission(key=key, category=cat, description=desc))
    roles = {r.key: r for r in (await session.execute(select(Role))).scalars()}
    for spec in DEFAULT_ROLES:
        if spec["key"] not in roles:
            session.add(Role(key=spec["key"], name=spec["name"], description=spec["description"], color=spec["color"],
                             permissions=list(spec["permissions"]), priority=spec["priority"], is_system=True,
                             discord_role_ids=[]))
        elif spec["key"] == "owner":
            roles["owner"].permissions = ["*"]  # owner always keeps full access
            roles["owner"].is_system = True


async def seed_departments(session: AsyncSession) -> None:
    if (await session.execute(select(func.count()).select_from(Department))).scalar():
        return
    for order, spec in enumerate(DEFAULT_DEPARTMENTS):
        dept = Department(name=spec["name"], abbreviation=spec["abbreviation"], kind=spec["kind"], color=spec["color"],
                          callsign_format=spec["callsign_format"], unit_types=list(UNIT_TYPES.get(spec["kind"], [])),
                          sort_order=order, description="")
        session.add(dept)
        await session.flush()
        n = len(spec["ranks"])
        for i, name in enumerate(spec["ranks"]):
            session.add(Rank(department_id=dept.id, name=name, sort_order=i,
                             is_command=i == 0, is_supervisor=i < max(1, n // 2) and n > 1, permissions=[]))


async def seed_locations(session: AsyncSession) -> None:
    if (await session.execute(select(func.count()).select_from(Location))).scalar():
        return
    for spec in DEFAULT_LOCATIONS:
        session.add(Location(name=spec["name"], category=spec["category"], x=spec["x"], z=spec["z"],
                             description="Starter location with an approximate, unverified position. "
                                         "Drag it to the correct spot in the Map Editor.",
                             is_preset=True, verified=False))


async def ensure_initial_admin(session: AsyncSession, discord_id: str) -> None:
    """Grant the Owner role to INITIAL_ADMIN_DISCORD_ID (idempotent)."""
    if not discord_id:
        return
    user = (await session.execute(select(User).where(User.discord_id == str(discord_id)))).scalar_one_or_none()
    if user is None:
        user = User(discord_id=str(discord_id), username="", display_name="Initial Administrator", preferences={})
        session.add(user)
        await session.flush()
    owner = (await session.execute(select(Role).where(Role.key == "owner"))).scalar_one()
    has = (await session.execute(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == owner.id)
    )).scalar_one_or_none()
    if not has:
        session.add(UserRole(user_id=user.id, role_id=owner.id))
        log.info("Granted Owner role to initial administrator %s", discord_id)


async def seed_all(session: AsyncSession, initial_admin: str = "") -> None:
    await seed_permissions_and_roles(session)
    await session.flush()
    await seed_departments(session)
    await seed_locations(session)
    await ensure_initial_admin(session, initial_admin)
    await session.commit()
