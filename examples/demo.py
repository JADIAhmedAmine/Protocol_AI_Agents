"""Ephemeral HTTP demo with simulated reviewers and an accelerated clock."""
import json
import secrets
import tempfile
import threading
import uuid
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from curation.engine import Engine, commitment
from curation.server import handler_for


def main():
    with tempfile.TemporaryDirectory() as directory:
        clock = [1000.0]
        engine = Engine(directory + "/demo.db", lambda: clock[0])
        tokens = {name: engine.enroll("demo", name, role) for name, role in
            [("author", "contributor"), ("reviewer-a", "reviewer"), ("reviewer-b", "reviewer"), ("operator", "admin")]}
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(engine))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def call(method, route, actor, body=None):
            request = Request(f"http://127.0.0.1:{server.server_port}/v1/knowledge-bases/demo/{route}",
                data=json.dumps(body).encode() if body is not None else None, method=method,
                headers={"Authorization": "Bearer " + tokens[actor], "Content-Type": "application/json",
                    "Idempotency-Key": str(uuid.uuid4())})
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        try:
            claim = call("POST", "claims", "author", {"text": "The example service uses SQLite persistence.",
                "topic": "demo", "source": {"url": "https://example.org/demo",
                    "passage": "Synthetic source for the API demonstration; not verified."}})
            route = "review-rounds/" + claim["round_id"]
            ballots = {a: {"vote": 1, "reason": "Simulated approval, not a factual evaluation",
                "nonce": secrets.token_hex(32)} for a in ("reviewer-a", "reviewer-b")}
            for actor in ballots:
                call("POST", route + "/arguments", actor, {"text": "Synthetic review for the demonstration."})
            clock[0] = 1060
            for actor, ballot in ballots.items():
                digest = commitment(claim["round_id"], actor, claim["revision"], **ballot)
                call("POST", route + "/commitments", actor, {"digest": digest})
            clock[0] = 1120
            for actor, ballot in ballots.items():
                call("POST", route + "/reveals", actor, ballot)
            clock[0] = 1180
            accepted = call("POST", "query", "author", {"text": "SQLite"})
            assert len(accepted["items"]) == 1
            disputed = call("POST", f"claims/{claim['id']}/disputes", "operator",
                {"reason": "Exercise challenge handling", "evidence": "Synthetic contradictory evidence"})
            assert disputed["state"] == "disputed"
            assert not call("POST", "query", "author", {"text": "SQLite"})["items"]
            clock[0] += 180
            dispute_route = "review-rounds/" + disputed["round_id"]
            call("POST", dispute_route + "/resolution", "operator",
                {"outcome": "retracted", "rationale": "Synthetic claim retired after demonstration"})
            events = call("GET", f"claims/{claim['id']}/events", "operator")
            print(json.dumps({"demo": "passed", "reviewers": "simulated", "clock": "accelerated",
                "flow": ["submitted", "reviewed", "accepted", "retrieved", "disputed", "retracted"],
                "audit_events": len(events["items"])}, indent=2))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    main()
