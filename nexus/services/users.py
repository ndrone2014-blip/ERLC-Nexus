"""Users, roles and actor resolution.

Permissions are always computed on the server from:
  * roles assigned directly in ERLC Nexus,
  * roles mapped to Discord role IDs that were verified server-side
    (OAuth guild-member lookup or the bot's gateway cache — never the browser),
  * extra permissions attached to the user's department ranks.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexus.core.audit import audit
from nexus.core.context import Actor, Conflict, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.permissions import WILDCARD, expand, validate_keys
from nexus.db.base import utcnow
from nexus.db.models import DepartmentMembership, DiscordAccount, Role, User, UserRole


async def get_or_create_user(
    session: AsyncSession, discord_id: str, *, username: str = "", display_name: str = "", avatar_url: str = ""
) -> User:
    user = (await session.execute(select(User).where(User.discord_id == str(discord_id)))).scalar_one_or_none()
    if user is None:
        user = User(discord_id=str(discord_id), username=username or "", display_name=display_name or username or "",
                    avatar_url=avatar_url or "", preferences={})
        session.add(user)
        await session.flush()
    else:
        if username:
            user.username = username
        if display_name:
            user.display_name = display_name
        if avatar_url:
            user.avatar_url = avatar_url
    return user


async def update_discord_roles(
    session: AsyncSession, user: User, role_ids: list[str] | None, *, in_guild: bool, source: str,
    username: str = "", global_name: str | None = None,
) -> DiscordAccount:
    acct = (await session.execute(select(DiscordAccount).where(DiscordAccount.user_id == user.id))).scalar_one_or_none()
    if acct is None:
        acct = DiscordAccount(user_id=user.id, discord_id=user.discord_id)
        session.add(acct)
    acct.username = username or acct.username or user.username
    if global_name is not None:
        acct.global_name = global_name
    acct.in_guild = in_guild
    acct.guild_role_ids = [str(r) for r in (role_ids or [])]
    acct.roles_synced_at = utcnow()
    acct.roles_source = source
    return acct


async def effective_roles(session: AsyncSession, user: User) -> list[Role]:
    direct = (await session.execute(
        select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)
    )).scalars().all()
    acct = (await session.execute(select(DiscordAccount).where(DiscordAccount.user_id == user.id))).scalar_one_or_none()
    mapped: list[Role] = []
    if acct and acct.in_guild and acct.guild_role_ids:
        guild_roles = set(acct.guild_role_ids)
        for role in (await session.execute(select(Role))).scalars():
            if guild_roles.intersection(role.discord_role_ids or []):
                mapped.append(role)
    seen: dict[int, Role] = {}
    for r in list(direct) + mapped:
        seen[r.id] = r
    return sorted(seen.values(), key=lambda r: -r.priority)


async def resolve_actor(session: AsyncSession, user: User, *, source: str = "web", ip: str = "") -> Actor:
    if not user.is_active:
        return Actor(user_id=user.id, name=user.name, permissions=frozenset(), discord_id=user.discord_id,
                     source=source, ip=ip)
    perms: set[str] = set()
    for role in await effective_roles(session, user):
        perms.update(role.permissions or [])
    memberships = (await session.execute(
        select(DepartmentMembership).options(selectinload(DepartmentMembership.rank))
        .where(DepartmentMembership.user_id == user.id, DepartmentMembership.status.in_(("active", "leave")))
    )).scalars().all()
    dept_ids, sup_ids = set(), set()
    for m in memberships:
        dept_ids.add(m.department_id)
        if m.rank:
            perms.update(m.rank.permissions or [])
            if m.rank.is_supervisor or m.rank.is_command:
                sup_ids.add(m.department_id)
    return Actor(user_id=user.id, name=user.name, permissions=frozenset(perms), department_ids=frozenset(dept_ids),
                 supervisor_department_ids=frozenset(sup_ids), discord_id=user.discord_id, source=source, ip=ip)


async def actor_for_discord(session: AsyncSession, discord_id: str, *, name: str = "", role_ids: list[str] | None = None,
                            avatar_url: str = "", in_guild: bool = True) -> tuple[User, Actor]:
    """Used by the bot: role IDs come from Discord's gateway (trusted)."""
    user = await get_or_create_user(session, discord_id, username=name, display_name=name, avatar_url=avatar_url)
    if role_ids is not None:
        await update_discord_roles(session, user, role_ids, in_guild=in_guild, source="bot", username=name)
    await session.flush()
    return user, await resolve_actor(session, user, source="discord")


def user_summary(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "name": user.name, "discord_id": user.discord_id, "avatar_url": user.avatar_url,
            "roblox_username": user.roblox_username}


async def user_profile(session: AsyncSession, user: User, actor: Actor | None = None) -> dict[str, Any]:
    roles = await effective_roles(session, user)
    a = actor or await resolve_actor(session, user)
    return {
        **user_summary(user),
        "username": user.username,
        "roblox_id": user.roblox_id,
        "is_active": user.is_active,
        "roles": [{"id": r.id, "key": r.key, "name": r.name, "color": r.color} for r in roles],
        "permissions": sorted(a.permissions) if WILDCARD not in a.permissions else [WILDCARD],
        "effective_permissions": expand(a.permissions),
        "department_ids": sorted(a.department_ids),
        "preferences": user.preferences or {},
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


# ---- role management ----------------------------------------------------------


def role_dict(r: Role) -> dict[str, Any]:
    return {"id": r.id, "key": r.key, "name": r.name, "description": r.description, "color": r.color,
            "permissions": r.permissions, "discord_role_ids": r.discord_role_ids, "priority": r.priority,
            "is_system": r.is_system}


async def list_roles(session: AsyncSession) -> list[Role]:
    return list((await session.execute(select(Role).order_by(Role.priority.desc(), Role.name))).scalars())


async def save_role(session: AsyncSession, actor: Actor, data: dict[str, Any], role_id: int | None = None) -> Role:
    actor.require("system.permissions")
    perms = data.get("permissions")
    if perms is not None:
        bad = validate_keys(perms)
        if bad:
            raise ValidationFailed(f"Unknown permissions: {', '.join(bad)}")
        if WILDCARD in perms and not actor.can(WILDCARD):
            raise Forbidden("Only an owner can grant full platform access.")
    if role_id is None:
        key = (data.get("key") or data.get("name", "")).strip().lower().replace(" ", "_")
        if not key or not data.get("name"):
            raise ValidationFailed("Role name is required.")
        if (await session.execute(select(Role).where(Role.key == key))).scalar_one_or_none():
            raise Conflict("A role with that key already exists.")
        role = Role(key=key, name=data["name"], description=data.get("description", ""),
                    color=data.get("color", "#5b8def"), permissions=perms or [],
                    discord_role_ids=[str(x) for x in data.get("discord_role_ids", [])],
                    priority=int(data.get("priority", 20)))
        session.add(role)
        await session.flush()
        await audit(session, actor, "system", "role.created", target_type="role", target_id=role.id, target_ref=role.name,
                    new=role_dict(role))
        return role
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFound("Role not found.")
    if role.key == "owner" and not actor.can(WILDCARD):
        raise Forbidden("Only an owner can modify the Owner role.")
    before = role_dict(role)
    for field in ("name", "description", "color"):
        if field in data:
            setattr(role, field, data[field])
    if perms is not None:
        if role.key == "owner" and WILDCARD not in perms:
            raise ValidationFailed("The Owner role must keep full access.")
        role.permissions = perms
    if "discord_role_ids" in data:
        role.discord_role_ids = [str(x) for x in data["discord_role_ids"] if str(x).strip()]
    if "priority" in data:
        role.priority = int(data["priority"])
    await audit(session, actor, "system", "role.updated", target_type="role", target_id=role.id, target_ref=role.name,
                old=before, new=role_dict(role))
    emit(session, "permissions.changed", {"role_id": role.id}, origin=actor.source)
    return role


async def delete_role(session: AsyncSession, actor: Actor, role_id: int) -> None:
    actor.require("system.permissions")
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFound("Role not found.")
    if role.is_system:
        raise ValidationFailed("Built-in roles cannot be deleted (you can edit their permissions).")
    await audit(session, actor, "system", "role.deleted", target_type="role", target_id=role.id, target_ref=role.name,
                old=role_dict(role))
    await session.delete(role)


async def set_user_roles(session: AsyncSession, actor: Actor, user_id: int, role_ids: list[int]) -> None:
    actor.require("system.permissions")
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    roles = (await session.execute(select(Role).where(Role.id.in_(role_ids)))).scalars().all() if role_ids else []
    if any(r.key == "owner" for r in roles) and not actor.can(WILDCARD):
        raise Forbidden("Only an owner can grant the Owner role.")
    existing = (await session.execute(select(UserRole).where(UserRole.user_id == user_id))).scalars().all()
    old_ids = sorted(ur.role_id for ur in existing)
    owner_role = (await session.execute(select(Role).where(Role.key == "owner"))).scalar_one_or_none()
    if owner_role and owner_role.id in old_ids and owner_role.id not in role_ids:
        if not actor.can(WILDCARD):
            raise Forbidden("Only an owner can remove the Owner role.")
        owners = (await session.execute(select(func.count()).select_from(UserRole).where(UserRole.role_id == owner_role.id))).scalar()
        if owners <= 1:
            raise ValidationFailed("At least one owner must remain.")
    for ur in existing:
        if ur.role_id not in role_ids:
            await session.delete(ur)
    for r in roles:
        if r.id not in old_ids:
            session.add(UserRole(user_id=user_id, role_id=r.id, granted_by=actor.user_id))
    await audit(session, actor, "system", "user.roles_changed", target_type="user", target_id=user_id, target_ref=user.name,
                old=old_ids, new=sorted(role_ids))
    emit(session, "permissions.changed", {"user_id": user_id}, origin=actor.source)


async def search_users(session: AsyncSession, q: str = "", limit: int = 50, offset: int = 0) -> list[User]:
    stmt = select(User).order_by(User.display_name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.username.ilike(like), User.discord_id == q,
                              User.roblox_username.ilike(like)))
    return list((await session.execute(stmt.limit(limit).offset(offset))).scalars())


async def update_user(session: AsyncSession, actor: Actor, user_id: int, data: dict[str, Any]) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("User not found.")
    is_self = actor.user_id == user_id
    allowed_self = {"display_name", "roblox_username", "roblox_id", "preferences"}
    if not is_self:
        actor.require("dept.personnel.manage")
    before = {"display_name": user.display_name, "roblox_id": user.roblox_id, "roblox_username": user.roblox_username,
              "is_active": user.is_active}
    for key, value in data.items():
        if is_self and key not in allowed_self and not actor.can("system.permissions"):
            continue
        if key == "is_active":
            actor.require("system.permissions")
            if is_self:
                raise ValidationFailed("You cannot deactivate yourself.")
            user.is_active = bool(value)
        elif key == "preferences" and isinstance(value, dict):
            prefs = dict(user.preferences or {})
            prefs.update(value)
            user.preferences = prefs
        elif key == "display_name":
            name = (value or "").strip()[:100]
            if not name:
                raise ValidationFailed("Display name cannot be empty.")
            user.display_name = name
        elif key == "roblox_username":
            user.roblox_username = (value or "").strip()[:64] or None
        elif key == "roblox_id":
            value = str(value or "").strip()
            if value and not value.isdigit():
                raise ValidationFailed("Roblox ID must be numeric.")
            user.roblox_id = value or None
    after = {"display_name": user.display_name, "roblox_id": user.roblox_id, "roblox_username": user.roblox_username,
             "is_active": user.is_active}
    if before != after:
        await audit(session, actor, "department", "user.updated", target_type="user", target_id=user.id,
                    target_ref=user.name, old=before, new=after)
    return user
