import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from urllib.parse import parse_qs, urlparse, urlsplit


class Error(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def commitment(round_id, reviewer, revision, vote, reason, nonce):
    return hashlib.sha256(canonical({"round_id": round_id, "reviewer": reviewer,
        "revision": revision, "vote": vote, "reason": reason, "nonce": nonce}).encode()).hexdigest()


def required(body, name, maximum=10000):
    value = body.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Error(400, f"{name} must be a nonempty string of at most {maximum} characters")
    return value.strip()


class Engine:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS agents (
                    kb TEXT, id TEXT, token_hash TEXT UNIQUE, role TEXT, model TEXT,
                    weight REAL, PRIMARY KEY(kb,id));
                CREATE TABLE IF NOT EXISTS claims (id TEXT PRIMARY KEY, kb TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS rounds (id TEXT PRIMARY KEY, kb TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, kb TEXT, claim_id TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS requests (
                    kb TEXT, agent TEXT, key TEXT, fingerprint TEXT, response TEXT,
                    PRIMARY KEY(kb,agent,key));
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def enroll(self, kb, agent, role="reviewer", model="simulated", weight=1.0):
        if role not in ("reviewer", "contributor", "admin") or not 0 < weight <= 1:
            raise ValueError("Invalid role or weight")
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?)", (kb, agent,
                hashlib.sha256(token.encode()).hexdigest(), role, model, weight))
        return token

    def authenticate(self, db, token, kb):
        agent = db.execute("SELECT * FROM agents WHERE token_hash=? AND kb=?",
            (hashlib.sha256(token.encode()).hexdigest(), kb)).fetchone()
        if not agent:
            raise Error(401, "Invalid credentials or knowledge-base membership")
        return dict(agent)

    def get(self, db, table, kb, item_id):
        row = db.execute(f"SELECT body FROM {table} WHERE kb=? AND id=?", (kb, item_id)).fetchone()
        if not row:
            raise Error(404, "Resource not found")
        return json.loads(row[0])

    def save(self, db, table, kb, body):
        db.execute(f"INSERT INTO {table} VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (body["id"], kb, canonical(body)))

    def event(self, db, kb, claim_id, action, actor, **details):
        db.execute("INSERT INTO events(kb,claim_id,body) VALUES (?,?,?)", (kb, claim_id,
            canonical({"action": action, "actor": actor, "at": self.clock(), **details})))

    def new_round(self, db, kb, claim, excluded=()):
        reviewers = {row["id"]: {"weight": row["weight"], "model": row["model"]}
            for row in db.execute("SELECT * FROM agents WHERE kb=? AND role='reviewer'", (kb,))
            if row["id"] != claim["contributor"] and row["id"] not in excluded}
        now = self.clock()
        review = {"id": str(uuid.uuid4()), "claim_id": claim["id"], "revision": claim["revision"],
            "phase": "deliberation", "policy": {"version": "prototype-1", "quorum": 2,
                "threshold": 0.5, "weighting": "enrolled-fixed", "abstentions_count_for_quorum": False},
            "deadlines": {"deliberation": now + 60, "commit": now + 120, "reveal": now + 180},
            "reviewers": reviewers, "arguments": [], "commitments": {}, "ballots": {}}
        claim["round_id"] = review["id"]
        self.save(db, "rounds", kb, review)
        self.save(db, "claims", kb, claim)
        self.event(db, kb, claim["id"], "review_started", "system", round_id=review["id"],
            revision=claim["revision"], policy=review["policy"], reviewers=reviewers)
        return review

    def advance(self, db, kb):
        for row in db.execute("SELECT body FROM rounds WHERE kb=?", (kb,)).fetchall():
            review = json.loads(row[0])
            if review["phase"] in ("closed", "arbitration"):
                continue
            before = review["phase"]
            now = self.clock()
            if now >= review["deadlines"]["reveal"]:
                self.decide(db, kb, review)
            elif now >= review["deadlines"]["commit"]:
                review["phase"] = "reveal"
            elif now >= review["deadlines"]["deliberation"]:
                review["phase"] = "commit"
            if before != review["phase"]:
                self.save(db, "rounds", kb, review)
                self.event(db, kb, review["claim_id"], "phase_changed", "system",
                    round_id=review["id"], phase=review["phase"])

    def decide(self, db, kb, review):
        claim = self.get(db, "claims", kb, review["claim_id"])
        if claim["revision"] != review["revision"] or claim["round_id"] != review["id"]:
            raise Error(409, "Stale review round")
        ballots = review["ballots"]
        count = sum(b["vote"] != 0 for b in ballots.values())
        total = sum(review["reviewers"][a]["weight"] for a, b in ballots.items() if b["vote"] != 0)
        score = sum(review["reviewers"][a]["weight"] * b["vote"] for a, b in ballots.items())
        normalized = score / total if total else 0
        enough = count >= review["policy"]["quorum"]
        outcome = ("active" if normalized >= review["policy"]["threshold"] else
                   "retracted" if normalized <= -review["policy"]["threshold"] else None) if enough else None
        review["result"] = {"participating_votes": count, "score": normalized,
            "outcome": outcome or "arbitration", "decided_at": self.clock()}
        review["phase"] = "closed" if outcome else "arbitration"
        claim["frozen"] = not bool(outcome)
        if outcome:
            claim["state"] = outcome
            claim["decision_at"] = self.clock()
        claim["policy_version"] = review["policy"]["version"]
        self.save(db, "claims", kb, claim)
        self.event(db, kb, claim["id"], "decision", "system", round_id=review["id"],
            revision=review["revision"], result=review["result"])

    def tick(self):
        with self.db() as db:
            for row in db.execute("SELECT DISTINCT kb FROM rounds").fetchall():
                self.advance(db, row[0])

    def execute(self, method, path, token, body=None, key=None):
        body = {} if body is None else body
        if not isinstance(body, dict):
            raise Error(400, "JSON body must be an object")
        parsed = urlsplit(path)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4 or parts[:2] != ["v1", "knowledge-bases"]:
            raise Error(404, "Route not found")
        kb, route = parts[2], parts[3:]
        if method == "POST" and (not key or len(key) > 200):
            raise Error(400, "An Idempotency-Key of 1–200 characters is required")
        with self.db() as db:
            actor = self.authenticate(db, token, kb)
            fingerprint = hashlib.sha256(canonical([method, path, body]).encode()).hexdigest()
            if method == "POST":
                cached = db.execute("SELECT * FROM requests WHERE kb=? AND agent=? AND key=?",
                    (kb, actor["id"], key)).fetchone()
                if cached:
                    if cached["fingerprint"] != fingerprint:
                        raise Error(409, "Idempotency key reused for a different request")
                    return json.loads(cached["response"])
            self.advance(db, kb)
            result = self.dispatch(db, kb, actor, method, route, body, parse_qs(parsed.query))
            if method == "POST":
                db.execute("INSERT INTO requests VALUES (?,?,?,?,?)",
                    (kb, actor["id"], key, fingerprint, canonical(result)))
            return result

    def public_round(self, review):
        result = {k: v for k, v in review.items() if k not in ("commitments", "ballots")}
        result["commitment_count"] = len(review["commitments"])
        result["reveal_count"] = len(review["ballots"])
        if review["phase"] in ("closed", "arbitration"):
            result["ballots"] = review["ballots"]
        return result

    def dispatch(self, db, kb, actor, method, route, body, query=None):
        who = actor["id"]
        query = query or {}
        if method == "GET" and route == ["me"]:
            return {k: actor[k] for k in ("id", "kb", "role", "model", "weight")}
        if method == "GET" and route == ["agents"]:
            return {"items": [dict(r) for r in db.execute(
                "SELECT id,role,model,weight FROM agents WHERE kb=? ORDER BY id", (kb,))]}
        if method == "GET" and route == ["claims"]:
            try:
                limit = int(query.get("limit", ["25"])[0])
                offset = int(query.get("offset", ["0"])[0])
            except ValueError:
                raise Error(400, "limit and offset must be integers")
            if not 1 <= limit <= 100 or offset < 0:
                raise Error(400, "limit must be 1–100 and offset must be nonnegative")
            state = query.get("state", [None])[0]
            where, params = "kb=?", [kb]
            if state:
                if state not in ("under_review", "active", "disputed", "retracted"):
                    raise Error(400, "Unknown claim state")
                where += " AND json_extract(body, '$.state')=?"
                params.append(state)
            total = db.execute(f"SELECT count(*) FROM claims WHERE {where}", params).fetchone()[0]
            items = [json.loads(r[0]) for r in db.execute(
                f"SELECT body FROM claims WHERE {where} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*params, limit, offset])]
            return {"items": items, "total": total,
                "next_offset": offset + limit if offset + limit < total else None}
        if method == "POST" and route == ["claims"]:
            text = required(body, "text")
            source = body.get("source")
            if not isinstance(source, dict):
                raise Error(400, "source must contain url and passage")
            url, passage = required(source, "url", 2000), required(source, "passage")
            if urlparse(url).scheme not in ("https", "http") or not urlparse(url).netloc:
                raise Error(400, "source.url must be an HTTP(S) URL")
            claim = {"id": str(uuid.uuid4()), "revision": str(uuid.uuid4()), "text": text,
                "source": {"url": url, "passage": passage, "verification": "unverified"},
                "topic": required(body, "topic", 200), "contributor": who, "state": "under_review",
                "hidden": False, "frozen": False, "dispute_count": 0, "created_at": self.clock()}
            self.event(db, kb, claim["id"], "submitted", who, revision=claim["revision"])
            self.new_round(db, kb, claim)
            return claim
        if method == "POST" and route == ["query"]:
            query = required(body, "text", 1000).casefold()
            matches = [json.loads(r[0]) for r in db.execute("SELECT body FROM claims WHERE kb=?", (kb,))]
            return {"items": [c for c in matches if c["state"] == "active" and not c["hidden"]
                and not c["frozen"] and query in c["text"].casefold()][:100], "search": "literal-substring"}
        if method == "GET" and route == ["review-rounds"]:
            reviews = [json.loads(r[0]) for r in db.execute("SELECT body FROM rounds WHERE kb=?", (kb,))]
            return {"items": [self.public_round(r) for r in reviews if
                (who in r["reviewers"] or actor["role"] == "admin") and r["phase"] != "closed"]}
        if len(route) == 3 and route[0] == "agents" and route[2] == "standing" and method == "GET":
            row = db.execute("SELECT id,role,model,weight FROM agents WHERE kb=? AND id=?", (kb, route[1])).fetchone()
            if not row:
                raise Error(404, "Agent not found")
            return {**dict(row), "reputation_mode": "fixed enrollment weight; no learned reputation"}
        if len(route) >= 2 and route[0] == "claims":
            claim = self.get(db, "claims", kb, route[1])
            if method == "GET" and len(route) == 2:
                return claim
            if method == "GET" and route[2:] == ["events"]:
                return {"items": [{"sequence": r["seq"], **json.loads(r["body"])} for r in db.execute(
                    "SELECT seq,body FROM events WHERE kb=? AND claim_id=? ORDER BY seq", (kb, claim["id"]))]}
            if method == "POST" and route[2:] == ["disputes"]:
                if actor["role"] not in ("reviewer", "admin"):
                    raise Error(403, "Reviewer or admin role required")
                if claim["state"] != "active" or claim["frozen"] or claim["dispute_count"] >= 3:
                    raise Error(409, "Claim cannot be disputed")
                evidence = required(body, "evidence")
                reason = required(body, "reason")
                prior = self.get(db, "rounds", kb, claim["round_id"])
                claim["state"], claim["dispute_count"] = "disputed", claim["dispute_count"] + 1
                self.event(db, kb, claim["id"], "disputed", who, reason=reason, evidence=evidence)
                self.new_round(db, kb, claim, excluded=set(prior["reviewers"]) | {who})
                return claim
        if len(route) >= 2 and route[0] == "review-rounds":
            review = self.get(db, "rounds", kb, route[1])
            if method == "GET" and len(route) == 2:
                return self.public_round(review)
            if method == "POST" and route[2:] == ["resolution"]:
                if actor["role"] != "admin":
                    raise Error(403, "Admin role required")
                if review["phase"] != "arbitration":
                    raise Error(409, "Round is not awaiting arbitration")
                outcome = body.get("outcome")
                if outcome not in ("active", "retracted"):
                    raise Error(400, "outcome must be active or retracted")
                rationale = required(body, "rationale")
                claim = self.get(db, "claims", kb, review["claim_id"])
                claim.update(state=outcome, frozen=False, decision_at=self.clock())
                review.update(phase="closed", resolution={"outcome": outcome, "rationale": rationale,
                    "actor": who, "at": self.clock()})
                self.save(db, "claims", kb, claim)
                self.save(db, "rounds", kb, review)
                self.event(db, kb, claim["id"], "admin_resolution", who, outcome=outcome, rationale=rationale,
                    round_id=review["id"], revision=review["revision"])
                return self.public_round(review)
            if method == "POST" and len(route) == 3 and route[2] in ("arguments", "commitments", "reveals"):
                if who not in review["reviewers"]:
                    raise Error(403, "Agent is not an eligible reviewer for this round")
                expected = {"arguments": "deliberation", "commitments": "commit", "reveals": "reveal"}[route[2]]
                if review["phase"] != expected:
                    raise Error(409, f"Operation requires {expected} phase")
                if route[2] == "arguments":
                    review["arguments"].append({"reviewer": who, "text": required(body, "text")})
                elif route[2] == "commitments":
                    digest = required(body, "digest", 64)
                    if not re.fullmatch(r"[0-9a-f]{64}", digest):
                        raise Error(400, "digest must be a lowercase SHA-256 hex digest")
                    if who in review["commitments"]:
                        raise Error(409, "Reviewer already committed")
                    review["commitments"][who] = digest
                else:
                    vote = body.get("vote")
                    if type(vote) is not int or vote not in (-1, 0, 1):
                        raise Error(400, "vote must be -1, 0, or 1")
                    reason, nonce = required(body, "reason", 1000), required(body, "nonce", 256)
                    if len(nonce) < 32:
                        raise Error(400, "nonce must have at least 32 characters")
                    if who in review["ballots"]:
                        raise Error(409, "Reviewer already revealed")
                    expected_hash = commitment(review["id"], who, review["revision"], vote, reason, nonce)
                    if not hmac.compare_digest(expected_hash, review["commitments"].get(who, "")):
                        raise Error(409, "Reveal does not match commitment")
                    review["ballots"][who] = {"vote": vote, "reason": reason, "nonce": nonce}
                self.save(db, "rounds", kb, review)
                # Never put ballot contents in events before the voting period ends.
                self.event(db, kb, review["claim_id"], route[2], who, round_id=review["id"])
                return {"accepted": True}
        raise Error(404, "Route not found")
