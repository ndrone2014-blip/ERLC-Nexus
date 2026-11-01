"""Permissions, settings, audit chain, notifications, config parsing, backups, migrations."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import select, text

from nexus.config import load_settings, parse_env_file
from nexus.core.audit import audit, verify_chain
from nexus.core.context import Forbidden, ValidationFailed
from nexus.core.permissions import DEFAULT_ROLES, PERMISSIONS, has_permission, validate_keys
from nexus.core.settings_store import get_setting, set_setting
from nexus.db.models import AuditLog, Role
from nexus.services import backup, notifications, users

pytestmark = pytest.mark.anyio


def test_has_permission_wildcards():
    assert has_permission(["*"], "system.configure")
    assert has_permission(["cad.*"], "cad.incident.create")
    assert not has_permission(["cad.*"], "system.configure")
    assert has_permission(["cad.view"], "cad.view") and not has_permission(["cad.view"], "cad.dispatch")
    assert validate_keys(["cad.view", "cad.*", "*", "nope.x"]) == ["nope.x"]


def test_default_roles_are_least_privilege():
    roles = {r["key"]: set(r["permissions"]) for r in DEFAULT_ROLES}
    assert roles["owner"] == {"*"}
    assert "system.permissions" not in roles["administrator"]
    assert roles["viewer"] == {"erlc.server.view"}
    assert not any(p.startswith("system.") for p in roles["officer"] | roles["dispatcher"] | roles["civilian"])
    for perms in roles.values():
        assert not validate_keys(perms)
    assert {"cad.incident.create", "cad.incident.edit", "cad.incident.close", "cad.unit.manage", "cad.records.search",
            "cad.records.edit", "cad.reports.review", "cad.department.manage", "erlc.server.view", "erlc.server.moderate",
            "system.configure"} <= set(PERMISSIONS)


def test_env_file_parsing(tmp_path):
    f = tmp_path / "c.env"
    f.write_text('# comment\nDISCORD_BOT_TOKEN="abc"\nWEB_PORT=9000  # inline\nexport LOG_LEVEL=debug\nERLC_SYNC_INTERVAL=\n')
    assert parse_env_file(f)["WEB_PORT"] == "9000"
    s = load_settings(env_file=f)
    assert s.discord_bot_token == "abc" and s.web_port == 9000 and s.log_level == "DEBUG" and s.erlc_sync_interval == 20
    assert s.safe_dict()["discord_bot_token"] == "configured"
    with pytest.raises(Exception):
        load_settings(env_file=f, overrides={"erlc_sync_interval": 2})  # below documented-safe minimum


async def test_discord_role_mapping_grants_permissions(rt, admin):
    async with rt.db.session() as s:
        dispatcher = (await s.execute(select(Role).where(Role.key == "dispatcher"))).scalar_one()
        await users.save_role(s, admin, {"discord_role_ids": ["777"]}, dispatcher.id)
        await s.commit()
        user, actor = await users.actor_for_discord(s, "800000000000000001", name="Disp", role_ids=["777"])
        assert actor.can("cad.dispatch")
        _, actor2 = await users.actor_for_discord(s, "800000000000000001", name="Disp", role_ids=[])
        assert not actor2.can("cad.dispatch")
        # role IDs reported for a different/unknown guild are ignored
        _, actor3 = await users.actor_for_discord(s, "800000000000000001", name="Disp", role_ids=["777"], in_guild=False)
        assert not actor3.can("cad.dispatch")


async def test_owner_protections(rt, admin, make_user):
    adm = await make_user("800000000000000002", ["administrator"], "Admin2")
    async with rt.db.session() as s:
        owner = (await s.execute(select(Role).where(Role.key == "owner"))).scalar_one()
        with pytest.raises(Forbidden):
            await users.save_role(s, adm, {"permissions": ["cad.view"]}, owner.id)  # admin lacks system.permissions
        with pytest.raises(ValidationFailed):
            await users.save_role(s, admin, {"permissions": ["cad.view"]}, owner.id)  # owner must keep *
        with pytest.raises(ValidationFailed):
            await users.set_user_roles(s, admin, admin.user_id, [])  # last owner can't be removed
        custom = await users.save_role(s, admin, {"name": "Training Officer", "permissions": ["cad.view", "cad.reports.review"]})
        await s.commit()
        with pytest.raises(ValidationFailed):
            await users.save_role(s, admin, {"name": "Bad", "permissions": ["made.up"]})
        await users.delete_role(s, admin, custom.id)
        builtin = (await s.execute(select(Role).where(Role.key == "officer"))).scalar_one()
        with pytest.raises(ValidationFailed):
            await users.delete_role(s, admin, builtin.id)


async def test_settings_validation(rt, admin, make_user):
    officer = await make_user("800000000000000003", ["officer"], "O")
    async with rt.db.session() as s:
        with pytest.raises(Forbidden):
            await set_setting(s, officer, "community.name", "Hacked")
        with pytest.raises(ValidationFailed):
            await set_setting(s, admin, "cad.incident_statuses", [{"key": "new", "label": "New"}])  # missing closed/cancelled
        with pytest.raises(ValidationFailed):
            await set_setting(s, admin, "unknown.key", 1)
        await set_setting(s, admin, "community.name", "Springfield RP")
        await s.commit()
        assert await get_setting(s, "community.name") == "Springfield RP"


async def test_audit_chain_detects_tampering(rt, admin):
    async with rt.db.session() as s:
        for i in range(3):
            await audit(s, admin, "cad", "test.event", target_ref=str(i), new={"i": i})
        await s.commit()
        assert (await verify_chain(s))["ok"]
        row = (await s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))).scalar_one()
        await s.execute(text("UPDATE audit_logs SET target_ref='forged' WHERE id=:i"), {"i": row.id})
        await s.commit()
    async with rt.db.session() as s:
        res = await verify_chain(s)
        assert not res["ok"] and res["broken_at"] == row.id


async def test_notifications_grouping_and_audience(rt, admin, make_user):
    officer = await make_user("800000000000000004", ["officer"], "O")
    async with rt.db.session() as s:
        await notifications.notify(s, "erlc.api", "API down", audience="perm:system.configure", dedupe_key="k")
        await notifications.notify(s, "erlc.api", "API down again", audience="perm:system.configure", dedupe_key="k")
        await notifications.notify(s, "incident.created", "For everyone")
        await s.commit()
        admin_items = await notifications.list_for(s, admin)
        grouped = [n for n in admin_items if n["kind"] == "erlc.api"]
        assert len(grouped) == 1 and grouped[0]["count"] == 2
        officer_items = await notifications.list_for(s, officer)
        assert [n["title"] for n in officer_items] == ["For everyone"]
        await notifications.mark_read(s, officer)
        await s.commit()
        assert await notifications.list_for(s, officer, unread_only=True) == []


async def test_backup_verify_stage_and_apply(rt, admin):
    from nexus.services import records

    async with rt.db.session() as s:
        await records.create_person(s, admin, {"first_name": "Before"})
        await s.commit()
    info = await backup.create_backup(rt.settings, "test")
    assert info["integrity"] == "ok"
    assert backup.list_backups(rt.settings)[0]["name"] == info["name"]
    async with rt.db.session() as s:
        await records.create_person(s, admin, {"first_name": "After"})
        await s.commit()
    staged = await backup.stage_restore(rt.settings, info["name"])
    assert "Restart" in staged["message"]
    await rt.db.dispose()
    msg = backup.apply_pending_restore(rt.settings)
    assert msg and not backup.pending_restore_path(rt.settings).exists()
    db_file = rt.settings.data_path / "nexus.db"
    names = {r[0] for r in sqlite3.connect(db_file).execute("SELECT first_name FROM persons")}
    assert names == {"Before"}
    assert any("before_restore" in b["name"] for b in backup.list_backups(rt.settings))
    with pytest.raises(ValidationFailed):
        backup.backup_path(rt.settings, "../../etc/passwd")


async def test_migrations_match_models(settings, tmp_path):
    """The shipped Alembic migration must create exactly the schema the models define."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from nexus.db.base import Base, Database
    from nexus.db.migrate import current_revision, upgrade_to_head

    db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}")
    await upgrade_to_head(db)
    await upgrade_to_head(db)  # idempotent
    assert await current_revision(db) == "0001"

    def _diff(conn):
        mc = MigrationContext.configure(conn, opts={"compare_type": False})
        return compare_metadata(mc, Base.metadata)

    async with db.engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    await db.dispose()
    assert diff == [], diff
