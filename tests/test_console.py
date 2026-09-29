import json
from pathlib import Path
import tempfile
import unittest
import uuid

from curation.engine import Engine, Error
from curation.seed import seed


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "demo.db"
        self.credentials = Path(self.tmp.name) / "credentials.json"
        seed(self.db, self.credentials)
        self.tokens = json.loads(self.credentials.read_text())["tokens"]
        self.engine = Engine(self.db)

    def call(self, route, actor="operator", body=None):
        return self.engine.execute("GET" if body is None else "POST",
            "/v1/knowledge-bases/demo/" + route, self.tokens[actor], body, str(uuid.uuid4()))

    def test_identity_and_registry_never_expose_credentials(self):
        me = self.call("me")
        self.assertEqual(me["role"], "admin")
        self.assertEqual(me["id"], "operator")
        agents = self.call("agents")
        self.assertEqual(len(agents["items"]), 4)
        self.assertNotIn("token", json.dumps([me, agents]))

    def test_paginated_claims_and_state_filter(self):
        first = self.call("claims?limit=2")
        second = self.call(f"claims?limit=2&offset={first['next_offset']}")
        third = self.call(f"claims?limit=2&offset={second['next_offset']}")
        ids = [c["id"] for page in (first, second, third) for c in page["items"]]
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(first["total"], 5)
        self.assertIsNone(third["next_offset"])
        active = self.call("claims?state=active")
        self.assertEqual(active["total"], 1)
        self.assertEqual(active["items"][0]["state"], "active")
        for query in ("limit=0", "limit=101", "offset=-1", "limit=abc", "state=missing"):
            with self.assertRaises(Error) as ctx:
                self.call("claims?" + query)
            self.assertEqual(ctx.exception.status, 400)

    def test_fixtures_exercise_arbitration_and_preserve_existing_files(self):
        rounds = self.call("review-rounds")["items"]
        arbitration = [r for r in rounds if r["phase"] == "arbitration"]
        self.assertEqual(len(arbitration), 2)
        review = arbitration[0]
        self.call(f"review-rounds/{review['id']}/resolution", body={"outcome": "retracted", "rationale": "Test operator decision"})
        claim = self.call(f"claims/{review['claim_id']}")
        self.assertEqual(claim["state"], "retracted")
        original_credentials = self.credentials.read_bytes()
        with self.assertRaises(ValueError):
            seed(self.db, self.credentials)
        self.assertEqual(original_credentials, self.credentials.read_bytes())

    def test_namespace_isolation_for_new_routes(self):
        token = self.engine.enroll("other", "outsider")
        for route in ("claims", "agents", "me"):
            with self.assertRaises(Error) as ctx:
                self.engine.execute("GET", "/v1/knowledge-bases/demo/" + route, token)
            self.assertEqual(ctx.exception.status, 401)
        response = self.engine.execute("GET", "/v1/knowledge-bases/other/claims", token)
        self.assertEqual(response["items"], [])


if __name__ == "__main__":
    unittest.main()
