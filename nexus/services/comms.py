"""Dispatch communications feed (website + optional Discord sync)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.db.models import Department, DispatchMessage, Incident, Unit
from nexus.services import notifications

CHANNELS = ("dispatch", "department", "unit", "broadcast")
KINDS = ("message", "announcement", "status", "incident")


def msg_dict(m: DispatchMessage) -> dict[str, Any]:
    return {"id": m.id, "channel": m.channel, "kind": m.kind, "department_id": m.department_id, "unit_id": m.unit_id,
            "incident_id": m.incident_id, "sender_user_id": m.sender_user_id, "sender": m.sender_label, "body": m.body,
            "restricted": m.is_restricted, "source": m.source, "created_at": m.created_at}


async def send(s: AsyncSession, actor: Actor, *, body: str, channel: str = "dispatch", kind: str = "message",
               department_id: int | None = None, unit_id: int | None = None, incident_id: int | None = None,
               restricted: bool = False, sender_label: str = "") -> DispatchMessage:
    actor.require("cad.comms.send")
    body = (body or "").strip()
    if not body:
        raise ValidationFailed("Message text is required.")
    if len(body) > 1000:
        raise ValidationFailed("Messages are limited to 1000 characters.")
    if channel not in CHANNELS or kind not in KINDS:
        raise ValidationFailed("Unknown channel or message type.")
    if kind == "announcement" or channel == "broadcast":
        actor.require("cad.comms.announce")
    if restricted:
        actor.require("cad.incident.restricted")
    if channel == "department":
        if not department_id or await s.get(Department, department_id) is None:
            raise ValidationFailed("Choose a department.")
        if department_id not in actor.department_ids and not actor.can("cad.dispatch"):
            raise Forbidden("You can only message your own department.")
    if channel == "unit" and (not unit_id or await s.get(Unit, unit_id) is None):
        raise ValidationFailed("Choose a unit.")
    if incident_id and await s.get(Incident, incident_id) is None:
        raise NotFound("Incident not found.")
    m = DispatchMessage(channel=channel, kind=kind, department_id=department_id, unit_id=unit_id, incident_id=incident_id,
                        sender_user_id=actor.user_id, sender_label=sender_label or actor.name, body=body,
                        is_restricted=restricted, source=actor.source)
    s.add(m)
    await s.flush()
    await audit(s, actor, "cad", "comms.sent", target_type="message", target_id=m.id, department_id=department_id,
                context={"channel": channel, "kind": kind})
    emit(s, "comms.message", msg_dict(m) | {"created_at": m.created_at.isoformat()}, origin=actor.source)
    if kind == "announcement":
        await notifications.notify(s, "comms.announcement", f"Dispatch announcement from {m.sender_label}", body[:300],
                                   audience="perm:cad.view", department_id=department_id, link="/#/cad/dispatch",
                                   severity="warning")
    return m


async def feed(s: AsyncSession, actor: Actor, *, channel: str = "", department_id: int | None = None,
               incident_id: int | None = None, before_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    actor.require("cad.view")
    stmt = select(DispatchMessage).order_by(DispatchMessage.id.desc()).limit(min(limit, 300))
    if channel:
        stmt = stmt.where(DispatchMessage.channel == channel)
    if department_id:
        stmt = stmt.where(DispatchMessage.department_id == department_id)
    if incident_id:
        stmt = stmt.where(DispatchMessage.incident_id == incident_id)
    if before_id:
        stmt = stmt.where(DispatchMessage.id < before_id)
    if not actor.can("cad.incident.restricted"):
        stmt = stmt.where(DispatchMessage.is_restricted.is_(False))
    if not actor.can("cad.dispatch"):
        stmt = stmt.where(or_(DispatchMessage.channel.in_(("dispatch", "broadcast", "unit")),
                              DispatchMessage.department_id.in_(list(actor.department_ids) or [-1])))
    return [msg_dict(m) for m in (await s.execute(stmt)).scalars()]
