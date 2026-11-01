"""Website assets: every page module and route target exists, nothing loads from paid/unknown CDNs."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def test_index_and_assets_served(web):
    r = web.get("/")
    assert r.status_code == 200 and "ERLC Nexus" in r.text
    for path in ("/css/app.css", "/js/app.js", "/js/core.js", "/js/charts.js", "/vendor/leaflet/leaflet.js", "/img/favicon.svg"):
        assert web.get(path).status_code == 200, path


def test_route_table_points_at_existing_page_exports():
    app_js = (WEB / "js" / "app.js").read_text()
    routes = re.findall(r'\[/\^.*?\$/, "([a-z]+)"(?:, "([A-Za-z0-9]+)")?\]', app_js)
    assert len(routes) >= 50
    for module, export in routes:
        src = (WEB / "js" / "pages" / f"{module}.js").read_text()
        if export:
            assert re.search(rf"export (async )?function {export}\b", src), f"{module}.{export} missing"
        else:
            assert "export default" in src, module


def test_every_spec_navigation_item_exists():
    app_js = (WEB / "js" / "app.js").read_text()
    for label in ["Overview", "Notifications", "Activity", "Server Overview", "Live Players", "Player Search", "Server Moderation",
                  "Server Commands", "Server Configuration", "CAD Overview", "Dispatch Center", "Live Map", "Active Calls",
                  "Incident History", "Unit Management", "Traffic Stops", "Person Records", "Vehicle Records", "BOLO Database",
                  "Warrant Records", "Incident Reports", "Search Records", "Department Overview", "Personnel", "Ranks", "Callsigns",
                  "Shift Management", "Department Statistics", "Server Analytics", "CAD Analytics", "Department Analytics",
                  "Dispatcher Analytics", "Activity Reports", "Discord Integration", "API Configuration", "Permissions", "Logging",
                  "Appearance", "Database", "System Health", "Security"]:
        assert f'"{label}"' in app_js, label


def test_no_innerhtml_with_dynamic_content():
    for f in (WEB / "js").rglob("*.js"):
        src = f.read_text()
        assert ".innerHTML" not in src.replace("outerHTML", ""), f"{f.name} uses innerHTML"


def test_only_local_scripts():
    html = (WEB / "index.html").read_text()
    for src in re.findall(r'<script[^>]+src="([^"]+)"', html):
        assert src.startswith("/"), src
