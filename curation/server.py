"""Local HTTP adapter. Production hosting requires a hardened server and TLS."""
import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .engine import Engine, Error


def handler_for(engine):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.handle_api()

        def do_POST(self):
            self.handle_api()

        def handle_api(self):
            try:
                path = urlsplit(self.path).path
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                    "/console.js": ("console.js", "text/javascript; charset=utf-8"),
                    "/console.css": ("console.css", "text/css; charset=utf-8")}
                if self.command == "GET" and path in assets:
                    name, content_type = assets[path]
                    payload = (Path(__file__).parent / "static" / name).read_bytes()
                    return self.respond_bytes(200, payload, content_type)
                if self.command == "GET" and path == "/health":
                    return self.respond(200, {"status": "ok", "mode": "experimental"})
                if self.command == "GET" and path == "/openapi.json":
                    return self.respond(200, json.loads((Path(__file__).parent.parent / "openapi.json").read_text()))
                body = None
                if self.command == "POST":
                    if self.headers.get("Transfer-Encoding"):
                        raise Error(400, "Transfer encoding is unsupported")
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        raise Error(400, "Invalid Content-Length")
                    if not 0 < length <= 65536:
                        raise Error(413, "JSON body must be between 1 and 65536 bytes")
                    if self.headers.get_content_type() != "application/json":
                        raise Error(415, "Content-Type must be application/json")
                    try:
                        body = json.loads(self.rfile.read(length))
                    except (ValueError, UnicodeDecodeError):
                        raise Error(400, "Invalid JSON")
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    raise Error(401, "Bearer token required")
                result = engine.execute(self.command, self.path, auth[7:], body, self.headers.get("Idempotency-Key"))
                self.respond(200, result)
            except Error as exc:
                self.respond(exc.status, {"error": exc.message})
            except Exception:
                logging.exception("API request failed")
                self.respond(500, {"error": "Internal server error"})

        def respond(self, status, body):
            payload = json.dumps(body).encode()
            self.respond_bytes(status, payload, "application/json")

        def respond_bytes(self, status, payload, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/curation.sqlite3")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    engine = Engine(args.db)
    stop = threading.Event()

    def worker():
        while not stop.wait(1):
            try:
                engine.tick()
            except Exception:
                logging.exception("Deadline worker failed")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(engine))
    print(f"API listening on http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        thread.join()
        server.server_close()


if __name__ == "__main__":
    main()
