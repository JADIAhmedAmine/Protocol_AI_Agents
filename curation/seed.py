"""Create a separate, synthetic demonstration database and local credentials."""
import argparse
import json
import os
from pathlib import Path
import secrets
import time
import uuid

from .engine import Engine, commitment


def seed(path, credentials):
    path, credentials = Path(path), Path(credentials)
    if path.resolve() == credentials.resolve():
        raise ValueError("Database and credentials paths must differ")
    if path.exists() or credentials.exists():
        raise ValueError("Demo files already exist; choose new paths to preserve existing data")
    path.parent.mkdir(parents=True, exist_ok=True)
    credentials.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents overwriting an existing database or credential file.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    clock = [time.time() - 3600]
    engine = Engine(path, lambda: clock[0])
    tokens = {name: engine.enroll("demo", name, role, "synthetic-fixture") for name, role in
        [("operator", "admin"), ("author", "contributor"), ("reviewer-a", "reviewer"), ("reviewer-b", "reviewer")]}
    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"kb": "demo", "tokens": tokens, "synthetic": True}, f, indent=2)

    def call(method, route, actor="operator", body=None):
        return engine.execute(method, "/v1/knowledge-bases/demo/" + route, tokens[actor], body, str(uuid.uuid4()))

    fixtures = [
        ("Every curated claim retains a source passage and an immutable revision.", "Provenance", (1, 1)),
        ("An accepted claim can be challenged with new evidence.", "Governance", (1, 1)),
        ("Agreement between reviewers guarantees that a claim is true.", "Evaluation", (-1, -1)),
        ("Two reviewers using the same model count as independent evidence.", "Evaluation", (1, -1)),
    ]
    for text, topic, votes in fixtures:
        claim = call("POST", "claims", "author", {"text": text, "topic": topic,
            "source": {"url": "https://example.org/synthetic-fixture", "passage": "Synthetic sample: " + text}})
        route = "review-rounds/" + claim["round_id"]
        ballots = {a: {"vote": v, "reason": "Synthetic demonstration ballot", "nonce": secrets.token_hex(32)}
            for a, v in zip(("reviewer-a", "reviewer-b"), votes)}
        for actor in ballots:
            call("POST", route + "/arguments", actor, {"text": "This is a simulated assessment for demonstrating the workflow."})
        clock[0] += 60
        for actor, ballot in ballots.items():
            call("POST", route + "/commitments", actor,
                {"digest": commitment(claim["round_id"], actor, claim["revision"], **ballot)})
        clock[0] += 60
        for actor, ballot in ballots.items():
            call("POST", route + "/reveals", actor, ballot)
        clock[0] += 60
        engine.tick()
        if topic == "Governance":
            call("POST", f"claims/{claim['id']}/disputes", body={"reason": "Demonstration challenge",
                "evidence": "Synthetic evidence requiring an operator decision."})
            clock[0] += 180
            engine.tick()
        clock[0] += 1
    clock[0] = time.time()
    call("POST", "claims", "author", {"text": "Review timeouts should reflect topic sensitivity.", "topic": "Policy",
        "source": {"url": "https://example.org/synthetic-fixture", "passage": "Synthetic proposal for a configurable review policy."}})
    return {"database": str(path), "credentials": str(credentials), "claims": 5}


def main():
    parser = argparse.ArgumentParser(description="Create synthetic samples without modifying an existing database.")
    parser.add_argument("--db", default="data/demo.sqlite3")
    parser.add_argument("--credentials", default="data/demo-credentials.json")
    args = parser.parse_args()
    try:
        result = seed(args.db, args.credentials)
    except (ValueError, FileExistsError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Created {result['claims']} synthetic claims. Credentials: {result['credentials']}")
    print(f"Start: python -m curation.server --db {result['database']}")
    print("Open http://127.0.0.1:8000 and import the credentials file. Votes and sources are synthetic.")


if __name__ == "__main__":
    main()
