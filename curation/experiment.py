"""Run real local reviews through the existing engine using virtual phase deadlines."""
import secrets
import time
import uuid
from pathlib import Path

from .engine import Engine, commitment


def protocol_decision(claim_text, evidence, initial, ballots, db_path, topic="experiment"):
    clock = [time.time()]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = Engine(db_path, lambda: clock[0])
    kb = "experiment-" + uuid.uuid4().hex
    tokens = {"author": engine.enroll(kb, "author", "contributor", "experiment-input")}
    for index in range(3):
        tokens[f"reviewer-{index}"] = engine.enroll(kb, f"reviewer-{index}", "reviewer", "Qwen2.5-0.5B-Instruct-Q4_K_M")

    def call(method, route, actor="author", body=None):
        return engine.execute(method, f"/v1/knowledge-bases/{kb}/" + route, tokens[actor], body, str(uuid.uuid4()))

    claim = call("POST", "claims", body={"text": claim_text, "topic": topic,
        "source": {"url": "https://example.invalid/user-supplied-evidence", "passage": evidence}})
    route = "review-rounds/" + claim["round_id"]
    for index, assessment in enumerate(initial):
        call("POST", route + "/arguments", f"reviewer-{index}", {"text": assessment["reason"]})
    clock[0] += 60
    reveals = []
    for index, assessment in enumerate(ballots):
        actor = f"reviewer-{index}"
        ballot = {"vote": assessment["vote"], "reason": assessment["reason"], "nonce": secrets.token_hex(32)}
        reveals.append(ballot)
        call("POST", route + "/commitments", actor,
            {"digest": commitment(claim["round_id"], actor, claim["revision"], **ballot)})
    clock[0] += 60
    for index, ballot in enumerate(reveals):
        call("POST", route + "/reveals", f"reviewer-{index}", ballot)
    clock[0] += 60
    engine.tick()
    review = call("GET", route)
    return {"prediction": {"active": 1, "retracted": -1}.get(review["result"]["outcome"], 0),
        "claim": call("GET", "claims/" + claim["id"]), "review": review,
        "events": call("GET", f"claims/{claim['id']}/events")["items"], "kb": kb,
        "clock": "virtual: phases advance without sleeping; model latency measured separately"}


def assess(reviewer, claim, evidence, db_path, seed=42, progress=None):
    started = time.perf_counter()
    initial = []
    for i in range(3):
        if progress:
            progress(f"Independent review {i + 1}/3")
        initial.append(reviewer.review(claim, evidence, i, seed=seed + i))
    comments = [b["reason"] for b in initial]  # No scores or ballot choices disclosed.
    revised = []
    for i in range(3):
        if progress:
            progress(f"Post-deliberation review {i + 1}/3")
        revised.append(reviewer.review(claim, evidence, i, discussion=comments, seed=seed + 100 + i))
    independent = protocol_decision(claim, evidence, initial, initial, db_path, "independent-ablation")
    deliberative = protocol_decision(claim, evidence, initial, revised, db_path, "deliberative-experiment")
    majority_score = sum(b["vote"] for b in initial)
    predictions = {"single": initial[0]["vote"], "majority": (majority_score > 0) - (majority_score < 0),
        "protocol_independent": independent["prediction"], "protocol_deliberative": deliberative["prediction"]}
    return {"claim": claim, "evidence": evidence, "initial": initial, "revised": revised,
        "predictions": predictions, "protocol_independent": independent, "protocol": deliberative,
        "wall_seconds": time.perf_counter() - started}
