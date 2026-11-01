"""Analytics and exportable reports."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import db_session, require
from nexus.core.context import Actor, ValidationFailed
from nexus.services import analytics

router = APIRouter(prefix="/api/analytics")


async def _compute(kind: str, s: AsyncSession, days: int, date_from, date_to, department_id):
    start, end = analytics.period(days, date_from, date_to)
    if kind == "server":
        data = await analytics.server_analytics(s, start, end)
    elif kind == "cad":
        data = await analytics.cad_analytics(s, start, end, department_id)
    elif kind == "departments":
        data = await analytics.department_analytics(s, start, end)
    elif kind == "dispatchers":
        data = await analytics.dispatcher_analytics(s, start, end)
    elif kind == "activity":
        data = await analytics.activity_report(s, start, end)
    else:
        raise ValidationFailed("Unknown analytics report.")
    return {"period": {"from": start, "to": end}, "data": data}


@router.get("/{kind}.csv", response_class=PlainTextResponse)
async def export_csv(kind: str, days: int = 7, date_from: datetime | None = None, date_to: datetime | None = None,
                     department_id: int | None = None, actor: Actor = Depends(require("analytics.view")),
                     s: AsyncSession = Depends(db_session)):
    res = (await _compute(kind, s, days, date_from, date_to, department_id))["data"]
    if kind == "cad":
        rows = res["trend"]
    elif kind == "server":
        rows = res["player_history"]
    elif kind == "activity":
        rows = [{"action": k, "count": v} for k, v in res["top_actions"].items()]
    else:
        rows = res
    return PlainTextResponse(analytics.to_csv(rows), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="nexus-{kind}.csv"'})


@router.get("/{kind}")
async def report(kind: str, days: int = 7, date_from: datetime | None = None, date_to: datetime | None = None,
                 department_id: int | None = None, actor: Actor = Depends(require("analytics.view")),
                 s: AsyncSession = Depends(db_session)):
    return await _compute(kind, s, max(1, min(days, 366)), date_from, date_to, department_id)
