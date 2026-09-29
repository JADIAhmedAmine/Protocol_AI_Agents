# Deliberative Knowledge API

Runnable experimental API inspired by [Deliberative Curation](https://arxiv.org/html/2606.00007v1). The core API uses Python 3.11+ and SQLite without third-party dependencies. The optional [local LLM / Gradio lab](LLM_LAB.md) adds real GPU inference and measured evaluation. Product direction: [platform brief](PLATFORM_BRIEF.md).

## Try the complete flow

Activate the project environment first:

```bash
source .venv/bin/activate
```

The workspace environment was initially created without pip because the host lacks `ensurepip`. Pip and Gradio have since been installed for the optional LLM lab. The core API still runs without these dependencies.

```bash
python3 -m unittest discover -s tests -v
python3 -m examples.demo
```

The demo starts an ephemeral HTTP server, enrolls simulated reviewers, and uses an accelerated clock to submit, review, accept, retrieve, dispute, and retract a claim. It deletes its temporary database afterward. It makes no model calls and does not validate factual quality.

## Open the browser console

```bash
source .venv/bin/activate
python -m curation.seed
python -m curation.server --db data/demo.sqlite3
```

Open **http://127.0.0.1:8000**. Choose **Connect**, import `data/demo-credentials.json`, select `operator`, and connect. The credentials file is sensitive; it lives in the ignored `data/` directory. Tokens stay in browser memory and are cleared on reload or disconnect.

The seed command creates five clearly synthetic claims: accepted knowledge, a rejected claim, a tied review awaiting arbitration, a disputed claim, and a new proposal. It refuses to overwrite either an existing database or credentials file. To reuse an existing demo, run only the server command. For a fresh demo, pass new `--db` and `--credentials` paths to the seed command.

The console supports:

- Browsing paginated claims by state and searching accepted knowledge.
- Submitting a claim with its source passage.
- Inspecting review phases, deadlines, disclosed ballots, and the full audit history.
- Filing disputes and recording administrator resolutions with a rationale.
- Inspecting enrolled agents and switching between imported identities.

Reviewers still submit arguments and commit/reveal ballots through the API; the console is an operator interface. Updates are manual through **Refresh** and **Refresh record**. Demo sources are unverified and sample reviews are simulated. After three minutes, a new proposal without enough valid votes moves to arbitration.

## Run a persistent API

```bash
python3 -m curation.enroll author --role contributor
python3 -m curation.enroll reviewer-a
python3 -m curation.enroll reviewer-b
python3 -m curation.enroll operator --role admin
python3 -m curation.server
```

Each enrollment prints a bearer token once. Store it locally; the database stores only its hash. Enrollment is a local operator command, not a public endpoint. Names must be unique within a knowledge base. The default namespace is `demo`, database is `data/curation.sqlite3`, and address is `http://127.0.0.1:8000`. Both commands support `--db`; enrollment supports `--kb` and `--model`.

Use `Authorization: Bearer <token>` on API requests, `Content-Type: application/json`, and a unique `Idempotency-Key` on every POST. Repeating the exact request with the same key returns the original response; changing its body or path returns 409. Query retries also return the original snapshot, so use a new key for a fresh query.

The [OpenAPI contract](openapi.json) is served at `/openapi.json`. `/health` is public. All knowledge routes are scoped under `/v1/knowledge-bases/{kb_id}`. See [the runnable HTTP client](examples/demo.py) for payloads and ballot hashing.

## Implemented protocol

- Claims have an immutable revision, source passage, contributor, state, and decision provenance. Sources are explicitly unverified; the server does not fetch URLs.
- Rounds snapshot enrolled reviewers, models, weights, and policy. Contributors cannot review their own claims. Admins resolve arbitration but do not vote.
- Deliberation, commitment, and reveal each last 60 seconds. A persisted deadline worker runs every second; requests also advance overdue phases. Restarting preserves deadlines.
- Commitment is SHA-256 of ASCII JSON with sorted keys and compact separators containing `round_id`, `reviewer`, `revision`, `vote`, `reason`, and `nonce`. Use `curation.engine.commitment` and a cryptographically random nonce of at least 32 characters.
- Votes are -1, 0, or 1. At least two non-abstaining valid reveals are required. Weighted score is the signed sum divided by non-abstaining weight: at least 0.5 accepts, at most -0.5 retracts, otherwise arbitration. This score is not a truth probability.
- Ballots are disclosed only after the reveal deadline, including when arbitration is needed. Audit events never disclose ballot values during voting.
- Disputes immediately remove claims from ordinary retrieval and start a fresh round excluding the previous enrolled panel and challenger. Lack of eligible reviewers leads to arbitration. Admin resolution requires a rationale. At most three disputes are allowed per claim.
- Retrieval is case-insensitive literal substring matching, capped at 100 results, and returns only active, visible, unfrozen claims. Mutations, audit events, and idempotency responses commit together.

## Scope and next steps

This is a local prototype using Python's development HTTP server, not a production deployment. Its API and SQLite data survive restarts; a dependency-free browser console is served at `/`. Currently supported artifact states are `under_review`, `active`, `disputed`, and `retracted`; proposal registration is immediate and recorded in the audit log.

Fixed enrollment weights are intentional. Beta/EigenTrust learning, source verification, production review workers, superseding revisions, automated sanctions, fast track, webhook delivery, and semantic retrieval are not implemented. A separate local model experiment runner now exercises the engine with real model ballots and 24 synthetic evidence-entailment fixtures; it is not a production worker or independently validated factual benchmark. The dispute quorum and threshold currently match ordinary review, an explicit simplification of the paper. No claim of complete protocol conformance or demonstrated factual reliability is made.

Before external deployment, replace the development server, add TLS, credential rotation, rate limits, pagination for agents/rounds/events, migrations, operational monitoring, and per-namespace configurable policies. Claim listings support `limit` (1–100), `offset`, and an optional `state` filter. Bearer credentials provide namespace access; members can inspect the namespace's claims and audit history. Private per-source permissions are outside this initial slice.
