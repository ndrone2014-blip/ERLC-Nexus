"""Permission catalog and default roles (least privilege)."""

from __future__ import annotations

from collections.abc import Iterable

WILDCARD = "*"

# key -> (category, description)
PERMISSIONS: dict[str, tuple[str, str]] = {
    # ERLC server
    "erlc.server.view": ("erlc", "View ERLC server information and live players"),
    "erlc.logs.view": ("erlc", "View ERLC join, kill, command and mod-call logs"),
    "erlc.server.command": ("erlc", "Run in-game server commands through the official API"),
    "erlc.server.announce": ("erlc", "Send in-game announcements (hints/messages)"),
    "erlc.server.moderate": ("erlc", "Kick, ban and unban players"),
    # CAD
    "cad.view": ("cad", "Open the CAD and view active incidents"),
    "cad.911.create": ("cad", "Place a 911 call"),
    "cad.incident.create": ("cad", "Create incidents"),
    "cad.incident.edit": ("cad", "Edit incidents and change status/priority"),
    "cad.incident.close": ("cad", "Close, cancel and reopen incidents"),
    "cad.incident.restricted": ("cad", "View restricted incident notes"),
    "cad.dispatch": ("cad", "Use the dispatch console and assign units"),
    "cad.unit.manage": ("cad", "Register, edit and remove units"),
    "cad.unit.self": ("cad", "Update your own unit status and location"),
    "cad.map.edit": ("cad", "Edit map locations and calibration"),
    "cad.traffic.manage": ("cad", "Create and manage traffic stops"),
    "cad.comms.send": ("cad", "Send dispatch communications"),
    "cad.comms.announce": ("cad", "Send dispatch announcements"),
    # Records / MDT
    "cad.records.search": ("records", "Search person, vehicle and BOLO records"),
    "cad.records.edit": ("records", "Create and edit person and vehicle records"),
    "cad.records.archive": ("records", "Archive and restore records"),
    "cad.records.discord_lookup": ("records", "Search records by Discord ID"),
    "cad.bolo.manage": ("records", "Create, update and close BOLOs"),
    "cad.warrants.view": ("records", "View warrants and cases"),
    "cad.warrants.manage": ("records", "Create and manage warrants and cases"),
    "cad.reports.create": ("records", "Write incident reports"),
    "cad.reports.view_all": ("records", "View all department reports"),
    "cad.reports.review": ("records", "Review, approve and return reports"),
    # Departments
    "dept.view": ("department", "View departments and rosters"),
    "cad.department.manage": ("department", "Create and configure departments"),
    "dept.personnel.manage": ("department", "Manage department personnel and callsigns"),
    "dept.ranks.manage": ("department", "Manage department ranks"),
    "dept.stats.view": ("department", "View department statistics"),
    # Shifts
    "shift.self": ("shift", "Clock in and out"),
    "shift.manage": ("shift", "Approve and edit other members' shifts"),
    # Civilian
    "civ.use": ("civilian", "Manage your own civilian characters and vehicles"),
    # Analytics & system
    "analytics.view": ("analytics", "View analytics and export reports"),
    "audit.view": ("system", "View audit logs"),
    "system.configure": ("system", "Change platform configuration"),
    "system.permissions": ("system", "Manage roles and permissions"),
    "system.database": ("system", "Create and restore database backups"),
    "system.security": ("system", "View security events and revoke sessions"),
}

_OFFICER = [
    "cad.view", "cad.unit.self", "cad.traffic.manage", "cad.records.search", "cad.bolo.manage",
    "cad.warrants.view", "cad.reports.create", "cad.comms.send", "cad.911.create",
    "dept.view", "shift.self", "erlc.server.view",
]

DEFAULT_ROLES: list[dict] = [
    {"key": "owner", "name": "Owner", "priority": 100, "color": "#f59e0b",
     "description": "Full platform access and all configuration.", "permissions": [WILDCARD]},
    {"key": "administrator", "name": "Administrator", "priority": 90, "color": "#ef4444",
     "description": "Server management, system configuration, department management.",
     "permissions": [p for p in PERMISSIONS if p not in ("system.permissions",)]},
    {"key": "command_staff", "name": "Command Staff", "priority": 70, "color": "#a855f7",
     "description": "Department oversight, personnel management and statistics.",
     "permissions": _OFFICER + [
         "dept.personnel.manage", "dept.ranks.manage", "dept.stats.view", "cad.reports.review",
         "cad.reports.view_all", "shift.manage", "analytics.view", "cad.incident.restricted",
         "cad.records.edit", "cad.warrants.manage", "cad.records.archive", "audit.view",
         "erlc.logs.view", "cad.comms.announce",
     ]},
    {"key": "supervisor", "name": "Supervisor", "priority": 60, "color": "#22c55e",
     "description": "Personnel oversight, incident and report review, shift oversight.",
     "permissions": _OFFICER + [
         "cad.reports.review", "cad.reports.view_all", "shift.manage", "dept.stats.view", "dept.personnel.manage",
         "cad.incident.edit", "cad.incident.close", "cad.incident.restricted", "cad.records.edit",
         "cad.warrants.manage", "erlc.logs.view",
     ]},
    {"key": "dispatcher", "name": "Dispatcher", "priority": 50, "color": "#06b6d4",
     "description": "Incident creation, assignment, unit status and communications.",
     "permissions": [
         "cad.view", "cad.incident.create", "cad.incident.edit", "cad.incident.close", "cad.dispatch",
         "cad.unit.manage", "cad.unit.self", "cad.comms.send", "cad.comms.announce", "cad.records.search",
         "cad.bolo.manage", "cad.warrants.view", "dept.view", "shift.self", "erlc.server.view", "cad.911.create",
     ]},
    {"key": "officer", "name": "Officer", "priority": 40, "color": "#3b82f6",
     "description": "MDT, traffic stops, assigned incidents and incident reports.",
     "permissions": _OFFICER + ["cad.records.edit"]},
    {"key": "fire", "name": "Fire Personnel", "priority": 40, "color": "#f97316",
     "description": "Fire department tools and assigned incidents.",
     "permissions": ["cad.view", "cad.unit.self", "cad.reports.create", "cad.comms.send", "dept.view",
                     "shift.self", "erlc.server.view", "cad.911.create"]},
    {"key": "dot", "name": "DOT Personnel", "priority": 40, "color": "#eab308",
     "description": "DOT operations, road assistance records and assigned incidents.",
     "permissions": ["cad.view", "cad.unit.self", "cad.reports.create", "cad.comms.send", "dept.view",
                     "shift.self", "erlc.server.view", "cad.911.create"]},
    {"key": "civilian", "name": "Civilian", "priority": 10, "color": "#94a3b8",
     "description": "Civilian characters, vehicles and 911 calls.",
     "permissions": ["civ.use", "cad.911.create", "erlc.server.view"]},
    {"key": "viewer", "name": "Viewer", "priority": 0, "color": "#64748b",
     "description": "Read-only access to explicitly permitted information.",
     "permissions": ["erlc.server.view"]},
]


def has_permission(granted: Iterable[str], required: str) -> bool:
    """Check a permission against a granted set.

    Supports the global wildcard ``*`` and prefix wildcards such as ``cad.*``.
    """
    granted = set(granted)
    if WILDCARD in granted or required in granted:
        return True
    parts = required.split(".")
    for i in range(1, len(parts)):
        if ".".join(parts[:i]) + ".*" in granted:
            return True
    return False


def expand(granted: Iterable[str]) -> list[str]:
    """Expand wildcards into concrete catalog keys (for display / API)."""
    granted = set(granted)
    return sorted(k for k in PERMISSIONS if has_permission(granted, k))


def validate_keys(keys: Iterable[str]) -> list[str]:
    bad = []
    for k in keys:
        if k == WILDCARD or k in PERMISSIONS:
            continue
        if k.endswith(".*") and any(p.startswith(k[:-1]) for p in PERMISSIONS):
            continue
        bad.append(k)
    return bad
