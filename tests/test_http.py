import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr

from curation.engine import Engine
from curation.server import handler_for


class Transport:
    """Exercise the real HTTP parser and handler without requiring a network socket."""
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = Engine(self.tmp.name + "/http.db")
        self.token = self.engine.enroll("demo", "operator", "admin")

    def request(self, path, method="GET", payload=None, auth=True, extra=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        headers = {"Host": "localhost", "Content-Length": str(len(body)), "Content-Type": "application/json",
            "Idempotency-Key": "test-key"}
        if auth:
            headers["Authorization"] = "Bearer " + self.token
        headers.update(extra or {})
        raw = f"{method} {path} HTTP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
        transport = Transport(raw.encode() + body)
        with redirect_stderr(io.StringIO()):
            handler_for(self.engine)(transport, ("127.0.0.1", 10000), None)
        head, content = bytes(transport.output).split(b"\r\n\r\n", 1)
        status = int(head.split(b" ")[1])
        return status, head.decode(), content

    def test_console_assets_and_contract(self):
        for route, mime in (("/", "text/html"), ("/console.js", "text/javascript"),
                            ("/console.css", "text/css"), ("/openapi.json", "application/json")):
            status, headers, body = self.request(route, auth=False)
            self.assertEqual(status, 200)
            self.assertIn(mime, headers)
            self.assertIn("Content-Security-Policy", headers)
            self.assertIn("nosniff", headers)
            self.assertTrue(body)
        status, _, body = self.request("/openapi.json", auth=False)
        self.assertIn("/v1/knowledge-bases/{kb_id}/me", json.loads(body)["paths"])
        self.assertEqual(self.request("/../engine.py", auth=False)[0], 401)

    def test_identity_and_query_parameters_over_http(self):
        base = "/v1/knowledge-bases/demo/"
        self.assertEqual(self.request(base + "me", auth=False)[0], 401)
        status, _, body = self.request(base + "me")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["id"], "operator")
        self.assertEqual(self.request(base + "claims?limit=0")[0], 400)
        self.assertEqual(self.request(base + "claims?limit=1")[0], 200)
        status, _, body = self.request(base + "claims", "POST", {"text": "Browser submission", "topic": "test",
            "source": {"url": "https://example.org", "passage": "fixture"}})
        self.assertEqual(status, 200)
        claim = json.loads(body)
        status, _, body = self.request(base + "claims?state=under_review&limit=1")
        self.assertEqual(json.loads(body)["items"][0]["id"], claim["id"])


if __name__ == "__main__":
    unittest.main()
