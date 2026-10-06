#!/usr/bin/env python3
"""Tiny HTTP server that serves the sample inbound feed XML.

Lets the demo point portal.connector.inbound_feed_url at a local URL
without needing real Bayut/Dubizzle credentials.

Usage:
    python3 feed_server.py [port]

Default port: 18099
Serves the contents of tests/fixtures/sample_bayut_feed.xml at
http://localhost:<port>/sample_bayut_feed.xml
"""
import http.server
import os
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18099
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.normpath(os.path.join(
    HERE, "..", "..", "tests", "fixtures", "sample_bayut_feed.xml",
))


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.lstrip("/") in ("sample_bayut_feed.xml", ""):
            self.path = "/" + os.path.basename(FIXTURE)
        return super().do_GET()

    def log_message(self, format, *args):
        pass


os.chdir(os.path.dirname(FIXTURE))
with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    print(f"feed_server: serving {FIXTURE} at http://0.0.0.0:{PORT}/")
    httpd.serve_forever()