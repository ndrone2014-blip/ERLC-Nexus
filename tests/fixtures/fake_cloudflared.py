#!/usr/bin/env python3
"""Stand-in for cloudflared used by the tests (Cloudflare can't be reached from CI).

`--version` prints a version. `tunnel --no-autoupdate --url http://127.0.0.1:PORT` prints
the same banner a real quick tunnel prints, then acts as the edge: it listens on
FAKE_CF_LISTEN (default 127.0.0.1:0) and forwards HTTP requests to PORT with the
CF-Connecting-IP / X-Forwarded-For headers Cloudflare adds. FAKE_CF_MODE=fail prints the
error a blocked network produces and exits.
"""
import http.client
import http.server
import os
import sys
import threading

args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("cloudflared version 2026.10.7 (fake for tests)")
    sys.exit(0)
if os.environ.get("FAKE_CF_MODE") == "fail":
    print('failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": no such host', flush=True)
    sys.exit(1)
target = int(args[args.index("--url") + 1].rsplit(":", 1)[1])
visitor = os.environ.get("FAKE_CF_VISITOR_IP", "203.0.113.7")


class Edge(http.server.BaseHTTPRequestHandler):
    def _forward(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("connection",)}
        headers["CF-Connecting-IP"] = visitor
        headers["X-Forwarded-For"] = visitor
        headers["X-Forwarded-Proto"] = "https"
        c = http.client.HTTPConnection("127.0.0.1", target, timeout=20)
        c.request(self.command, self.path, body=body or None, headers=headers)
        r = c.getresponse()
        data = r.read()
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _forward

    def log_message(self, *a):
        pass


host, _, port = os.environ.get("FAKE_CF_LISTEN", "127.0.0.1:0").partition(":")
srv = http.server.ThreadingHTTPServer((host, int(port)), Edge)
port_file = os.environ.get("FAKE_CF_PORT_FILE")
if port_file:
    open(port_file, "w").write(str(srv.server_address[1]))
print("INF Requesting new quick Tunnel on trycloudflare.com...", flush=True)
print("INF +--------------------------------------------------------------------------------------------+", flush=True)
print("INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |", flush=True)
print("INF |  https://brave-lunar-octopus-ridge.trycloudflare.com                                        |", flush=True)
print("INF +--------------------------------------------------------------------------------------------+", flush=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
try:
    threading.Event().wait()
except KeyboardInterrupt:
    pass
