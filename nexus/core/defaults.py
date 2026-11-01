"""Sensible defaults so a new community can start immediately.

Everything here is editable from System/Appearance/CAD settings in the website.
"""

from __future__ import annotations

INCIDENT_PRIORITIES = [
    {"level": 1, "name": "Emergency", "description": "Immediate threat to life or property.", "color": "#ef4444", "weight": 100, "notify": True},
    {"level": 2, "name": "Urgent", "description": "Requires prompt response.", "color": "#f97316", "weight": 75, "notify": True},
    {"level": 3, "name": "Routine", "description": "Standard response.", "color": "#3b82f6", "weight": 50, "notify": False},
    {"level": 4, "name": "Non-emergency", "description": "Low priority / informational.", "color": "#64748b", "weight": 25, "notify": False},
]

INCIDENT_STATUSES = [
    {"key": "new", "label": "New", "color": "#a855f7", "open": True},
    {"key": "pending", "label": "Pending Dispatch", "color": "#f59e0b", "open": True},
    {"key": "dispatched", "label": "Dispatched", "color": "#3b82f6", "open": True},
    {"key": "en_route", "label": "Units En Route", "color": "#0ea5e9", "open": True},
    {"key": "on_scene", "label": "On Scene", "color": "#22c55e", "open": True},
    {"key": "in_progress", "label": "In Progress", "color": "#10b981", "open": True},
    {"key": "awaiting_units", "label": "Awaiting Additional Units", "color": "#eab308", "open": True},
    {"key": "resolved", "label": "Resolved", "color": "#64748b", "open": False},
    {"key": "closed", "label": "Closed", "color": "#475569", "open": False},
    {"key": "cancelled", "label": "Cancelled", "color": "#334155", "open": False},
]

INCIDENT_CATEGORIES = [
    {"key": "traffic", "label": "Traffic", "dept_kinds": ["law", "dot"], "subtypes": ["Collision", "Reckless Driving", "Disabled Vehicle", "Hit and Run", "DUI"]},
    {"key": "crime", "label": "Crime in Progress", "dept_kinds": ["law"], "subtypes": ["Robbery", "Burglary", "Assault", "Shots Fired", "Theft", "Vandalism", "Pursuit"]},
    {"key": "disturbance", "label": "Disturbance", "dept_kinds": ["law"], "subtypes": ["Noise", "Fight", "Suspicious Person", "Trespassing"]},
    {"key": "fire", "label": "Fire", "dept_kinds": ["fire"], "subtypes": ["Structure Fire", "Vehicle Fire", "Brush Fire", "Alarm", "Hazmat"]},
    {"key": "medical", "label": "Medical", "dept_kinds": ["fire", "ems"], "subtypes": ["Unconscious Person", "Injury", "Cardiac", "Overdose", "Rescue"]},
    {"key": "road", "label": "Road Assistance", "dept_kinds": ["dot"], "subtypes": ["Tow Request", "Vehicle Recovery", "Road Obstruction", "Traffic Control", "Debris"]},
    {"key": "civil", "label": "Civilian Assistance", "dept_kinds": ["law", "civilian"], "subtypes": ["Welfare Check", "Lost Property", "Information"]},
    {"key": "other", "label": "Other", "dept_kinds": [], "subtypes": ["General"]},
]

UNIT_STATUSES = [
    {"key": "available", "label": "Available", "color": "#22c55e", "group": "available", "code": "10-8"},
    {"key": "en_route", "label": "En Route", "color": "#0ea5e9", "group": "busy", "code": "10-76"},
    {"key": "on_scene", "label": "On Scene", "color": "#3b82f6", "group": "busy", "code": "10-23"},
    {"key": "busy", "label": "Busy", "color": "#f59e0b", "group": "busy", "code": "10-6"},
    {"key": "transporting", "label": "Transporting", "color": "#a855f7", "group": "busy", "code": "10-15"},
    {"key": "returning", "label": "Returning to Service", "color": "#14b8a6", "group": "busy", "code": "10-98"},
    {"key": "on_break", "label": "On Break", "color": "#94a3b8", "group": "unavailable", "code": "10-7B"},
    {"key": "out_of_service", "label": "Out of Service", "color": "#475569", "group": "unavailable", "code": "10-7"},
]

UNIT_TYPES = {
    "law": ["Patrol", "Traffic", "K-9", "Supervisor", "SWAT", "Detective", "Air"],
    "fire": ["Engine", "Rescue", "Ladder", "Battalion", "Support", "Ambulance"],
    "ems": ["Ambulance", "Supervisor", "Support"],
    "dot": ["Tow", "Road Crew", "Traffic Control", "Recovery"],
    "dispatch": ["Dispatch"],
    "civilian": ["Civilian"],
    "other": ["General"],
}

LOCATION_CATEGORIES = [
    {"key": "police", "label": "Police Station", "color": "#3b82f6", "icon": "shield"},
    {"key": "fire", "label": "Fire Station", "color": "#ef4444", "icon": "flame"},
    {"key": "hospital", "label": "Hospital", "color": "#f8fafc", "icon": "cross"},
    {"key": "dot", "label": "DOT Yard", "color": "#eab308", "icon": "cone"},
    {"key": "landmark", "label": "Landmark", "color": "#a855f7", "icon": "star"},
    {"key": "business", "label": "Business", "color": "#14b8a6", "icon": "store"},
    {"key": "intersection", "label": "Intersection", "color": "#94a3b8", "icon": "cross-road"},
    {"key": "custom", "label": "Custom", "color": "#f472b6", "icon": "pin"},
]

REPORT_TEMPLATES = [
    {"key": "incident", "label": "Incident Report", "fields": []},
    {"key": "arrest", "label": "Arrest Report", "fields": [
        {"key": "arrestee", "label": "Arrestee", "type": "text"},
        {"key": "charges", "label": "Charges", "type": "textarea"},
        {"key": "miranda", "label": "Rights read", "type": "select", "options": ["Yes", "No", "N/A"]},
    ]},
    {"key": "use_of_force", "label": "Use of Force Report", "fields": [
        {"key": "force_type", "label": "Type of force", "type": "text"},
        {"key": "injuries", "label": "Injuries", "type": "textarea"},
    ]},
    {"key": "fire", "label": "Fire Incident Report", "fields": [
        {"key": "cause", "label": "Suspected cause", "type": "text"},
        {"key": "property_loss", "label": "Property loss", "type": "text"},
    ]},
    {"key": "dot", "label": "DOT Recovery / Road Report", "fields": [
        {"key": "tow_destination", "label": "Tow destination", "type": "text"},
        {"key": "road_status", "label": "Road status", "type": "select", "options": ["Open", "Partially closed", "Closed"]},
    ]},
]

# Default locations derived from commonly known ERLC/Liberty County map points.
# Coordinates are placeholders and SHOULD be adjusted with the Map Editor; they
# are labelled as presets, not API data.
DEFAULT_LOCATIONS = [
    {"name": "River City Police Department", "category": "police", "x": -600, "z": -300},
    {"name": "Springfield Police Station", "category": "police", "x": 900, "z": 650},
    {"name": "River City Fire Station", "category": "fire", "x": -450, "z": -150},
    {"name": "Springfield Fire Station", "category": "fire", "x": 1050, "z": 500},
    {"name": "Liberty County Hospital", "category": "hospital", "x": -200, "z": 120},
    {"name": "DOT Headquarters", "category": "dot", "x": 300, "z": -700},
    {"name": "Bank", "category": "business", "x": -700, "z": 50},
    {"name": "Jewelry Store", "category": "business", "x": -800, "z": -50},
    {"name": "Gas Station (Downtown)", "category": "business", "x": -350, "z": 300},
]

DEFAULT_DEPARTMENTS = [
    {"name": "Liberty County Sheriff's Office", "abbreviation": "LCSO", "kind": "law", "color": "#b45309",
     "callsign_format": "{num}A-{seq:02}", "ranks": ["Sheriff", "Undersheriff", "Captain", "Lieutenant", "Sergeant", "Deputy", "Probationary Deputy"]},
    {"name": "River City Police Department", "abbreviation": "RCPD", "kind": "law", "color": "#2563eb",
     "callsign_format": "{num}L-{seq:02}", "ranks": ["Chief", "Deputy Chief", "Captain", "Lieutenant", "Sergeant", "Officer", "Probationary Officer"]},
    {"name": "Liberty County Fire Department", "abbreviation": "LCFD", "kind": "fire", "color": "#dc2626",
     "callsign_format": "{type}-{seq:02}", "ranks": ["Fire Chief", "Battalion Chief", "Captain", "Lieutenant", "Firefighter", "Probationary Firefighter"]},
    {"name": "Department of Transportation", "abbreviation": "DOT", "kind": "dot", "color": "#ca8a04",
     "callsign_format": "DOT-{seq:02}", "ranks": ["Director", "Supervisor", "Senior Operator", "Operator"]},
    {"name": "Liberty County Communications", "abbreviation": "LCC", "kind": "dispatch", "color": "#0891b2",
     "callsign_format": "DISP-{seq:02}", "ranks": ["Communications Director", "Supervisor", "Dispatcher", "Trainee"]},
    {"name": "Civilian Operations", "abbreviation": "CIV", "kind": "civilian", "color": "#64748b",
     "callsign_format": "CIV-{seq:02}", "ranks": ["Civilian"]},
]

NOTIFICATION_CHANNELS = {
    # event kind -> Discord channel ID ("" disables). Configured in System > Discord Integration.
    "incident.created": "", "incident.priority": "", "incident.closed": "", "unit.assigned": "",
    "unit.status": "", "bolo.created": "", "bolo.expired": "", "report.submitted": "",
    "shift.started": "", "shift.ended": "", "erlc.status": "", "erlc.api": "", "erlc.modcall": "",
    "erlc.911": "", "comms.announcement": "", "audit": "",
}

DISCORD_EMBEDS = {
    "color": "#3b82f6", "footer": "ERLC Nexus", "show_timestamps": True, "thumbnail_url": "",
}

DASHBOARD_WIDGETS = [
    "server", "cad", "units", "queue", "activity", "players_chart", "bolos", "shifts",
]

DISPATCH_SHORTCUTS = {
    "new_incident": "Alt+N", "search": "Alt+S", "unit_board": "Alt+U", "active_calls": "Alt+C",
    "dashboard": "Alt+D", "focus_note": "Alt+M",
}

ERLC_COMMAND_TEMPLATES = {
    "kick": ":kick {player} {reason}",
    "ban": ":ban {player}",
    "unban": ":unban {player}",
    "hint": ":h {message}",
    "message": ":m {message}",
}

SETTINGS_DEFAULTS: dict[str, object] = {
    "community.name": "My ERLC Community",
    "community.logo_url": "",
    "appearance.accent": "#3b82f6",
    "appearance.default_theme": "dark",
    "cad.incident_prefix": "NX",
    "cad.priorities": INCIDENT_PRIORITIES,
    "cad.incident_statuses": INCIDENT_STATUSES,
    "cad.incident_categories": INCIDENT_CATEGORIES,
    "cad.unit_statuses": UNIT_STATUSES,
    "cad.unit_types": UNIT_TYPES,
    "cad.queue_alert_seconds": {"1": 60, "2": 120, "3": 300, "4": 600},
    "cad.auto_status_on_assign": True,
    "cad.import_erlc_911": True,
    "cad.api_unit_locations": True,
    "map.location_categories": LOCATION_CATEGORIES,
    "map.style": "fall_postals",
    "map.calibration": {"scale": 1.0, "offset_x": 2677.5, "offset_z": 2677.5, "verified": False},
    "map.marker_colors": {"incident": "#ef4444", "unit": "#22c55e", "traffic": "#f59e0b", "bolo": "#a855f7", "player": "#94a3b8"},
    "records.searchable_fields": {"person": ["name", "alias", "number", "vehicle", "roblox"], "vehicle": ["plate", "owner", "make", "model", "color"]},
    "records.disclaimer": "All records are fictional Emergency Response: Liberty County roleplay data.",
    "reports.templates": REPORT_TEMPLATES,
    "bolo.default_expiry_hours": 24,
    "discord.channels": NOTIFICATION_CHANNELS,
    "discord.embeds": DISCORD_EMBEDS,
    "discord.sync_comms": True,
    "discord.comms_channel": "",
    "dashboard.widgets": DASHBOARD_WIDGETS,
    "dashboard.refresh_seconds": 15,
    "dispatch.shortcuts": DISPATCH_SHORTCUTS,
    "erlc.command_templates": ERLC_COMMAND_TEMPLATES,
    "erlc.blocked_commands": [],
    "erlc.server_key_encrypted": "",
    "notifications.throttle_seconds": 30,
    "shift.require_approval": False,
    "shift.max_hours_flag": 8,
}
