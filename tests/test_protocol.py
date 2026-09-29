import json
import tempfile
import unittest
import uuid
from curation.engine import Engine, Error, commitment


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000
        self.engine = Engine(self.tmp.name + "/test.db", lambda: self.now)
        self.tokens = {a: self.engine.enroll("kb", a, role) for a, role in
            [("author", "contributor"), ("r1", "reviewer"), ("r2", "reviewer"), ("admin", "admin")]}
        self.claim = self.call("POST", "claims", "author", {"text": "Water freezes at 0 C under stated conditions",
            "topic": "science", "source": {"url": "https://example.org/source", "passage": "fixture, unverified"}})
        self.round = self.claim["round_id"]

    def call(self, method, route, actor="r1", body=None, key=None):
        return self.engine.execute(method, "/v1/knowledge-bases/kb/" + route,
            self.tokens[actor], body, key or str(uuid.uuid4()))

    def fails(self, status, method, route, actor="r1", body=None):
        with self.assertRaises(Error) as ctx:
            self.call(method, route, actor, body)
        self.assertEqual(ctx.exception.status, status)

    def ballot(self, actor, vote=1):
        return {"vote": vote, "reason": "fixture assessment", "nonce": actor * 32}

    def commit(self, actor, vote=1):
        b = self.ballot(actor, vote)
        return self.call("POST", f"review-rounds/{self.round}/commitments", actor,
            {"digest": commitment(self.round, actor, self.claim["revision"], **b)})

    def finish(self, votes=(1, 1)):
        self.now = 1060
        for actor, vote in zip(("r1", "r2"), votes):
            self.commit(actor, vote)
        self.now = 1120
        for actor, vote in zip(("r1", "r2"), votes):
            self.call("POST", f"review-rounds/{self.round}/reveals", actor, self.ballot(actor, vote))
        self.now = 1180
        self.engine.tick()

    def test_accept_retrieve_restart_dispute(self):
        self.finish()
        self.engine = Engine(self.engine.path, lambda: self.now)
        self.assertEqual(len(self.call("POST", "query", body={"text": "water"})["items"]), 1)
        claim = self.call("POST", f"claims/{self.claim['id']}/disputes", "admin",
            {"reason": "conditions missing", "evidence": "new fixture evidence"})
        self.assertEqual(claim["state"], "disputed")
        self.assertEqual(self.call("POST", "query", body={"text": "water"})["items"], [])
        fresh = self.call("GET", f"review-rounds/{claim['round_id']}")
        self.assertNotIn("r1", fresh["reviewers"])

    def test_phase_integrity_and_no_leaks(self):
        route = f"review-rounds/{self.round}"
        self.fails(409, "POST", route + "/reveals", body=self.ballot("r1"))
        self.now = 1060
        self.commit("r1")
        self.fails(409, "POST", route + "/commitments", body={"digest": "0" * 64})
        self.fails(403, "POST", route + "/commitments", "author", {"digest": "0" * 64})
        self.now = 1120
        self.fails(409, "POST", route + "/reveals", body=self.ballot("r1", -1))
        self.call("POST", route + "/reveals", body=self.ballot("r1"))
        self.fails(409, "POST", route + "/reveals", body=self.ballot("r1"))
        self.assertNotIn("ballots", self.call("GET", route))
        events = self.call("GET", f"claims/{self.claim['id']}/events")
        self.assertNotIn("fixture assessment", json.dumps(events))

    def test_quorum_admin_resolution_and_idempotent_deadlines(self):
        self.finish((1,))
        route = f"review-rounds/{self.round}"
        self.assertEqual(self.call("GET", route)["phase"], "arbitration")
        before = self.call("GET", f"claims/{self.claim['id']}/events")
        self.engine.tick()
        self.assertEqual(before, self.call("GET", f"claims/{self.claim['id']}/events"))
        self.fails(403, "POST", route + "/resolution", body={"outcome": "active", "rationale": "manual"})
        self.call("POST", route + "/resolution", "admin", {"outcome": "active", "rationale": "manual fixture check"})
        self.assertEqual(self.call("GET", f"claims/{self.claim['id']}")["state"], "active")

    def test_rejection_abstention_and_tie(self):
        self.finish((-1, -1))
        self.assertEqual(self.call("GET", f"claims/{self.claim['id']}")["state"], "retracted")

    def test_abstentions_do_not_satisfy_quorum(self):
        self.finish((1, 0))
        self.assertEqual(self.call("GET", f"review-rounds/{self.round}")["phase"], "arbitration")

    def test_tie_escalates(self):
        self.finish((1, -1))
        self.assertEqual(self.call("GET", f"review-rounds/{self.round}")["phase"], "arbitration")

    def test_namespace_isolation_and_retry(self):
        foreign = self.engine.enroll("other", "foreign")
        with self.assertRaises(Error) as ctx:
            self.engine.execute("GET", f"/v1/knowledge-bases/kb/claims/{self.claim['id']}", foreign)
        self.assertEqual(ctx.exception.status, 401)
        self.tokens["foreign"] = foreign
        with self.assertRaises(Error) as ctx:
            self.engine.execute("GET", f"/v1/knowledge-bases/other/claims/{self.claim['id']}", foreign)
        self.assertEqual(ctx.exception.status, 404)
        body = {"text": "water"}
        result = self.call("POST", "query", body=body, key="retry")
        self.assertEqual(result, self.call("POST", "query", body=body, key="retry"))
        with self.assertRaises(Error) as ctx:
            self.call("POST", "query", body={"text": "other"}, key="retry")
        self.assertEqual(ctx.exception.status, 409)

    def test_weight_snapshot(self):
        with self.engine.db() as db:
            db.execute("UPDATE agents SET weight=0.1 WHERE id='r1'")
        review = self.call("GET", f"review-rounds/{self.round}")
        self.assertEqual(review["reviewers"]["r1"]["weight"], 1)


if __name__ == "__main__":
    unittest.main()
