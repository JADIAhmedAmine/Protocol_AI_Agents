import json
import tempfile
import unittest
from unittest.mock import patch

from curation.evaluate import summarize, wilson
from curation.experiment import assess, protocol_decision
from curation.local_llm import LocalReviewer


def ballot(vote):
    return {"vote": vote, "reason": "fixture", "seconds": 2, "usage": {"total_tokens": 10}, "error": None}


class EvaluationTests(unittest.TestCase):
    def test_metrics_count_unresolved_and_false_acceptance_correctly(self):
        rows = []
        for label, prediction in [(1, 1), (-1, 1), (1, 0), (-1, -1)]:
            rows.append({"label": label, "predictions": {m: prediction for m in
                ("single", "majority", "protocol_independent", "protocol_deliberative")},
                "initial": [ballot(prediction) for _ in range(3)], "revised": [ballot(prediction) for _ in range(3)]})
        metrics = summarize(rows)
        first = metrics[0]
        self.assertEqual(first["correct"], 2)
        self.assertEqual(first["accuracy_all"], 0.5)
        self.assertEqual(first["coverage"], 0.75)
        self.assertEqual(first["accuracy_resolved"], 2/3)
        self.assertEqual(first["false_accept_rate"], 0.5)
        self.assertEqual(first["acceptance_precision"], 0.5)
        self.assertEqual(first["seconds_per_claim"], 2)
        self.assertEqual(metrics[-1]["model_calls"], 24)
        self.assertEqual(metrics[-1]["total_tokens"], 240)
        self.assertEqual(metrics[-1]["seconds_per_claim"], 12)

    def test_undefined_precision_is_not_reported_as_perfect(self):
        row = {"label": 1, "predictions": {m: 0 for m in
            ("single", "majority", "protocol_independent", "protocol_deliberative")},
            "initial": [ballot(0)]*3, "revised": [ballot(0)]*3}
        metric = summarize([row])[0]
        self.assertIsNone(metric["acceptance_precision"])
        self.assertIsNone(metric["accuracy_resolved"])
        self.assertEqual(metric["accuracy_all"], 0)
        self.assertEqual(wilson(0, 0), [None, None])

    def test_protocol_threshold_and_audit_are_exercised(self):
        with tempfile.TemporaryDirectory() as tmp:
            votes = [ballot(1), ballot(1), ballot(-1)]
            result = protocol_decision("claim", "evidence", votes, votes, tmp + "/experiment.db")
            self.assertEqual(result["prediction"], 0)
            self.assertEqual(result["review"]["phase"], "arbitration")
            actions = [e["action"] for e in result["events"]]
            self.assertEqual(actions.count("commitments"), 3)
            self.assertEqual(actions.count("reveals"), 3)
            self.assertLess(actions.index("commitments"), actions.index("reveals"))

    def test_discussion_never_includes_ballot_scores(self):
        class FakeReviewer:
            def __init__(self):
                self.calls = []

            def review(self, claim, evidence, role, discussion=None, seed=0):
                self.calls.append(discussion)
                return ballot(1)

        reviewer = FakeReviewer()
        with tempfile.TemporaryDirectory() as tmp:
            result = assess(reviewer, "claim", "evidence", tmp + "/db")
        self.assertEqual(reviewer.calls[:3], [None]*3)
        self.assertEqual(reviewer.calls[3:], [["fixture"]*3]*3)
        self.assertEqual(result["predictions"]["protocol_deliberative"], 1)

    def test_invalid_model_output_is_abstention_and_preserves_trace(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return json.dumps({"choices": [{"message": {"content": '{"vote": true, "reason": "bad"}'},
                    "finish_reason": "stop"}], "usage": {"total_tokens": 9}}).encode()

        with patch("curation.local_llm.urlopen", return_value=Response()):
            result = LocalReviewer().review("claim", "evidence")
        self.assertEqual(result["vote"], 0)
        self.assertIsNotNone(result["error"])
        self.assertIn("true", result["raw"])


if __name__ == "__main__":
    unittest.main()
