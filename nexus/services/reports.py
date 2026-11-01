"""Incident reports with immutable revisions and supervisor review.

Every save after the first submission creates a new revision snapshot, so a
previously submitted version is never silently overwritten.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.audit import audit
from nexus.core.context import Actor, Forbidden, NotFound, ValidationFailed
from nexus.core.events import emit
from nexus.core.numbering import next_number
from nexus.core.settings_store import get_setting
from nexus.db.base import utcnow
from nexus.db.models import Department, Incident, Report, ReportComment, ReportRevision, User
from nexus.services import notifications

FIELDS = ["title", "template_key", "incident_id", "department_id", "callsign", "incident_type", "location", "occurred_at",
          "involved_personnel", "summary", "description", "notes", "evidence", "custom_fields"]
STATUSES = ("draft", "submitted", "under_review", "approved", "returned", "archived")
STATUS_LABELS = {"draft": "Draft", "submitted": "Submitted", "under_review": "Under Review", "approved": "Approved",
                 "returned": "Returned for Changes", "archived": "Archived"}
EDITABLE_BY_AUTHOR = ("draft", "returned")


async def _names(s: AsyncSession, uids: set) -> dict[int, str]:
    uids = {u for u in uids if u is not None}
    if not uids:
        return {}
    return dict((await s.execute(select(User.id, User.display_name).where(User.id.in_(uids)))).all())


def report_dict(r: Report, *, full: bool = True, names: dict[int, str] | None = None) -> dict[str, Any]:
    names = names or {}
    d = {"id": r.id, "number": r.number, "title": r.title, "template_key": r.template_key, "incident_id": r.incident_id,
         "author_user_id": r.author_user_id, "author": names.get(r.author_user_id), "department_id": r.department_id,
         "callsign": r.callsign, "incident_type": r.incident_type, "status": r.status,
         "status_label": STATUS_LABELS.get(r.status, r.status), "revision": r.revision, "summary": r.summary,
         "created_at": r.created_at, "updated_at": r.updated_at, "submitted_at": r.submitted_at,
         "reviewed_by": r.reviewed_by, "reviewer": names.get(r.reviewed_by), "reviewed_at": r.reviewed_at,
         "record_type": "Fictional ERLC roleplay record"}
    if full:
        d.update({k: getattr(r, k) for k in ("location", "occurred_at", "involved_personnel", "description", "notes",
                                             "evidence", "custom_fields")})
    return d


def _snapshot(r: Report) -> dict[str, Any]:
    out = {}
    for f in FIELDS:
        v = getattr(r, f)
        out[f] = v.isoformat() if isinstance(v, datetime) else v
    return out


async def _values(s: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    templates = {t["key"]: t for t in await get_setting(s, "reports.templates")}
    for f in FIELDS:
        if f not in data:
            continue
        v = data[f]
        if f == "template_key" and v not in templates:
            raise ValidationFailed("Unknown report template.")
        if f == "incident_id" and v not in (None, ""):
            inc = await s.get(Incident, int(v)) if str(v).isdigit() else (await s.execute(
                select(Incident).where(Incident.number == str(v).upper()))).scalar_one_or_none()
            if inc is None:
                raise ValidationFailed("Linked incident not found.")
            v = inc.id
        elif f in ("incident_id", "department_id") and v in (None, ""):
            v = None
        elif f == "department_id" and v is not None and await s.get(Department, int(v)) is None:
            raise ValidationFailed("Department not found.")
        elif f == "occurred_at":
            v = datetime.fromisoformat(v.replace("Z", "+00:00")) if isinstance(v, str) and v else (v or None)
        elif f == "custom_fields":
            v = {str(k)[:40]: str(val)[:2000] for k, val in (v or {}).items()}
        elif isinstance(v, str):
            v = v.strip()[:20000 if f == "description" else 4000 if f in ("notes", "evidence") else 600]
        out[f] = v
    return out


async def _revision(s: AsyncSession, actor: Actor, r: Report, reason: str) -> None:
    r.revision += 1
    s.add(ReportRevision(report_id=r.id, revision=r.revision, status=r.status, snapshot=_snapshot(r),
                         user_id=actor.user_id, reason=reason[:200]))


async def create(s: AsyncSession, actor: Actor, data: dict[str, Any]) -> Report:
    actor.require("cad.reports.create")
    vals = await _values(s, data)
    vals.setdefault("template_key", "incident")
    if vals.get("incident_id") and not vals.get("incident_type"):
        inc = await s.get(Incident, vals["incident_id"])
        vals["incident_type"] = inc.subtype or inc.category
        vals.setdefault("location", inc.location_name or inc.street)
        vals.setdefault("department_id", inc.department_id)
    if not vals.get("department_id") and actor.department_ids:
        vals["department_id"] = min(actor.department_ids)
    r = Report(number=await next_number(s, "report"), author_user_id=actor.user_id, status="draft", revision=0, **vals)
    if not r.title:
        r.title = f"{r.template_key.replace('_', ' ').title()} {r.number}"
    s.add(r)
    await s.flush()
    await _revision(s, actor, r, "created")
    await audit(s, actor, "mdt", "report.created", target_type="report", target_id=r.id, target_ref=r.number,
                department_id=r.department_id)
    emit(s, "report.changed", {"id": r.id, "number": r.number, "status": r.status}, origin=actor.source)
    return r


async def get(s: AsyncSession, actor: Actor, ref: int | str) -> Report:
    if isinstance(ref, int) or str(ref).isdigit():
        r = await s.get(Report, int(ref))
    else:
        r = (await s.execute(select(Report).where(Report.number == str(ref).upper().strip()))).scalar_one_or_none()
    if r is None:
        raise NotFound("Report not found.")
    if r.author_user_id != actor.user_id and not (actor.can("cad.reports.view_all") or actor.can("cad.reports.review")):
        raise Forbidden("You can only view your own reports.")
    return r


async def update(s: AsyncSession, actor: Actor, rid: int, data: dict[str, Any], reason: str = "edited") -> Report:
    r = await get(s, actor, rid)
    if r.author_user_id != actor.user_id:
        raise Forbidden("Only the author can edit a report. Reviewers use comments.")
    if r.status not in EDITABLE_BY_AUTHOR:
        raise ValidationFailed(f"Report is {STATUS_LABELS[r.status]} and can no longer be edited.")
    before = _snapshot(r)
    for k, v in (await _values(s, data)).items():
        setattr(r, k, v)
    if _snapshot(r) != before:
        await _revision(s, actor, r, reason)
        await audit(s, actor, "mdt", "report.updated", target_type="report", target_id=r.id, target_ref=r.number,
                    context={"revision": r.revision})
        emit(s, "report.changed", {"id": r.id, "number": r.number, "status": r.status}, origin=actor.source)
    return r


async def submit(s: AsyncSession, actor: Actor, rid: int) -> Report:
    r = await get(s, actor, rid)
    if r.author_user_id != actor.user_id:
        raise Forbidden("Only the author can submit this report.")
    if r.status not in EDITABLE_BY_AUTHOR:
        raise ValidationFailed(f"Report is already {STATUS_LABELS[r.status]}.")
    if not (r.summary and r.description):
        raise ValidationFailed("A summary and full description are required before submitting.")
    r.status = "submitted"
    r.submitted_at = utcnow()
    await _revision(s, actor, r, "submitted")
    await audit(s, actor, "mdt", "report.submitted", target_type="report", target_id=r.id, target_ref=r.number,
                department_id=r.department_id)
    emit(s, "report.submitted", {"id": r.id, "number": r.number, "title": r.title, "author": actor.name,
                                 "department_id": r.department_id}, origin=actor.source)
    await notifications.notify(s, "report.submitted", f"Report {r.number} awaiting review", f"{r.title} — {actor.name}",
                               audience="perm:cad.reports.review", department_id=r.department_id,
                               link=f"/#/records/report/{r.id}")
    return r


async def review(s: AsyncSession, actor: Actor, rid: int, action: str, comment: str = "") -> Report:
    """action: start | approve | return | archive | comment"""
    actor.require("cad.reports.review")
    r = await get(s, actor, rid)
    if r.author_user_id == actor.user_id and action in ("approve", "return") and not actor.can("*"):
        raise Forbidden("You cannot review your own report.")
    if r.department_id and not actor.can_manage_department(r.department_id, "cad.reports.review") \
            and not actor.can("cad.reports.view_all"):
        raise Forbidden("This report belongs to another department.")
    transitions = {"start": ({"submitted"}, "under_review"), "approve": ({"submitted", "under_review"}, "approved"),
                   "return": ({"submitted", "under_review"}, "returned"),
                   "archive": ({"approved", "returned", "draft", "submitted", "under_review"}, "archived")}
    if action == "comment":
        if not comment.strip():
            raise ValidationFailed("Comment text is required.")
    elif action not in transitions:
        raise ValidationFailed("Unknown review action.")
    else:
        allowed, new_status = transitions[action]
        if r.status not in allowed:
            raise ValidationFailed(f"Cannot {action} a report that is {STATUS_LABELS[r.status]}.")
        if action == "return" and not comment.strip():
            raise ValidationFailed("Explain what needs to change when returning a report.")
        r.status = new_status
        r.reviewed_by = actor.user_id
        r.reviewed_at = utcnow()
        await _revision(s, actor, r, f"review: {action}")
    s.add(ReportComment(report_id=r.id, user_id=actor.user_id, action=action, body=comment.strip()[:4000]))
    await audit(s, actor, "mdt", f"report.review_{action}", target_type="report", target_id=r.id, target_ref=r.number,
                new={"status": r.status}, context={"comment": comment[:300]} if comment else None)
    emit(s, "report.changed", {"id": r.id, "number": r.number, "status": r.status}, origin=actor.source)
    if action in ("approve", "return") and r.author_user_id:
        await notifications.notify(s, "report.reviewed", f"Report {r.number} {STATUS_LABELS[r.status].lower()}",
                                   comment[:300], user_id=r.author_user_id, link=f"/#/records/report/{r.id}",
                                   severity="success" if action == "approve" else "warning")
    return r


async def detail(s: AsyncSession, actor: Actor, rid: int) -> dict[str, Any]:
    r = await get(s, actor, rid)
    comments = (await s.execute(select(ReportComment).where(ReportComment.report_id == r.id).order_by(ReportComment.id))).scalars().all()
    revs = (await s.execute(select(ReportRevision).where(ReportRevision.report_id == r.id).order_by(ReportRevision.revision.desc()))).scalars().all()
    uids = {r.author_user_id, r.reviewed_by} | {c.user_id for c in comments} | {v.user_id for v in revs}
    names = await _names(s, uids)
    d = report_dict(r, names=names)
    d["comments"] = [{"id": c.id, "action": c.action, "body": c.body, "user": names.get(c.user_id), "created_at": c.created_at}
                     for c in comments]
    d["revisions"] = [{"revision": v.revision, "status": v.status, "reason": v.reason, "user": names.get(v.user_id),
                       "created_at": v.created_at} for v in revs]
    d["can_edit"] = r.author_user_id == actor.user_id and r.status in EDITABLE_BY_AUTHOR
    d["can_review"] = actor.can("cad.reports.review") and r.author_user_id != actor.user_id
    if r.incident_id:
        inc = await s.get(Incident, r.incident_id)
        d["incident_number"] = inc.number if inc else None
    return d


async def revision_snapshot(s: AsyncSession, actor: Actor, rid: int, revision: int) -> dict[str, Any]:
    await get(s, actor, rid)
    rev = (await s.execute(select(ReportRevision).where(ReportRevision.report_id == rid,
                                                        ReportRevision.revision == revision))).scalar_one_or_none()
    if rev is None:
        raise NotFound("Revision not found.")
    return {"revision": rev.revision, "status": rev.status, "snapshot": rev.snapshot, "reason": rev.reason,
            "created_at": rev.created_at}


async def search(s: AsyncSession, actor: Actor, *, q: str = "", status: str = "", mine: bool = False,
                 department_id: int | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
                 limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    stmt = select(Report).order_by(Report.id.desc())
    if mine or not (actor.can("cad.reports.view_all") or actor.can("cad.reports.review")):
        stmt = stmt.where(Report.author_user_id == actor.user_id)
    if status == "awaiting_review":
        stmt = stmt.where(Report.status.in_(("submitted", "under_review")))
    elif status:
        stmt = stmt.where(Report.status == status)
    if department_id:
        stmt = stmt.where(Report.department_id == department_id)
    if date_from:
        stmt = stmt.where(Report.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Report.created_at <= date_to)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Report.number.ilike(like), Report.title.ilike(like), Report.summary.ilike(like),
                              Report.description.ilike(like), Report.location.ilike(like)))
    rows = (await s.execute(stmt.limit(min(limit, 200)).offset(offset))).scalars().all()
    uids = {r.author_user_id for r in rows} | {r.reviewed_by for r in rows}
    names = await _names(s, uids)
    return [report_dict(r, full=False, names=names) for r in rows]


def export_text(d: dict[str, Any]) -> str:
    """Plain-text export used for downloads and printing."""
    lines = [f"ERLC NEXUS — {d['title']}", f"Report {d['number']} · Revision {d['revision']} · {d['status_label']}",
             "FICTIONAL ERLC ROLEPLAY RECORD", "=" * 60]
    for label, key in (("Author", "author"), ("Callsign", "callsign"), ("Incident", "incident_number"),
                       ("Incident type", "incident_type"), ("Location", "location"), ("Occurred", "occurred_at"),
                       ("Involved personnel", "involved_personnel"), ("Reviewer", "reviewer")):
        if d.get(key):
            lines.append(f"{label}: {d[key]}")
    for label, key in (("SUMMARY", "summary"), ("DESCRIPTION", "description"), ("NOTES", "notes"), ("EVIDENCE", "evidence")):
        if d.get(key):
            lines += ["", label, "-" * len(label), str(d[key])]
    for k, v in (d.get("custom_fields") or {}).items():
        lines.append(f"{k}: {v}")
    if d.get("comments"):
        lines += ["", "REVIEW COMMENTS", "---------------"]
        lines += [f"[{c['created_at']}] {c['user']} ({c['action']}): {c['body']}" for c in d["comments"]]
    return "\n".join(lines) + "\n"


def export_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    cols = ["number", "title", "status_label", "author", "callsign", "incident_type", "created_at", "submitted_at", "reviewer"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()
