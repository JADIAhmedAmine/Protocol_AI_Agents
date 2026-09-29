# Deliberative knowledge platform — initial brief

Status: general-purpose agent knowledge API confirmed by the user. A runnable Python/SQLite prototype implements submission, review, retrieval, and disputes. A browser operator console supports claim submission, inspection, search, disputes, and arbitration. A separate demo setup provides synthetic claims and local agent credentials. See README.md for implemented behavior and explicit simplifications. Meaning of `applied_engineer` remains unspecified.

The local LLM lab now adds Qwen2.5-0.5B GPU inference, a Gradio interface, and a completed 24-case synthetic pilot. See LLM_LAB.md for results, costs, and limitations. The first run reduced false acceptance but did not improve overall accuracy versus majority voting.

## Research foundation

Steven Johnson, *Deliberative Curation: A Protocol for Multi-Agent Knowledge Bases*, [paper](https://arxiv.org/html/2606.00007v1), ORCID 0009-0007-4864-2001.

The paper combines artifact lifecycle management, deliberation followed by concealed voting, reputation weighting, and escalation. Its artifact states are proposed, under_review, active, disputed, superseded, and retracted. Fast track, formal voting, and arbitration provide increasingly involved decisions. The evaluation is a simulation; several mechanisms, including graduated sanctions, remain unvalidated. Treat this as an experimental protocol foundation rather than evidence of production reliability.

## Proposed product

A general-purpose API where agents submit sourced claims, assess evidence, and retrieve accepted knowledge with provenance. Human operators inspect and challenge decisions through a minimal administrative interface. Applications integrate the API into their own research, company knowledge, or agent workflows.

The core user question is: “Why is this claim in our knowledge base, and what evidence would change its status?”

First demonstration: submit one claim and its source, collect independent assessments, exchange evidence, close voting, display the decision and its full history, then challenge it with contradictory evidence.

## First implementation slice

1. Claim submission API: create a claim with a source URL, exact supporting passage, topic, and revision identifier inside a knowledge-base namespace.
2. Review queue API: expose eligible work, evidence, structured arguments, and deadlines; distinguish model identity from reviewer role.
3. Decision service: enforce phases and permissions on the server; freeze the artifact revision, policy version, and voting weights for each round.
4. Concealed ballots: use separate commit and reveal phases. Bind commitments to round, reviewer, revision, vote, reason, and a random nonce. Reject altered reveals and duplicates. Never expose ballot choices before commitment closes.
5. Knowledge library: display current status and provenance. Default retrieval includes active, visible, unfrozen claims only; historical and disputed records remain available through explicit audit views.
6. Human review queue: handle inconclusive rounds and challenges, requiring a recorded rationale for every administrative decision.

These are proposed deployment choices. Begin with formal review for every claim; defer automatic acceptance by silence until review coverage has been measured. Use deterministic simulated reviewers for development and label their outputs clearly. Add real model integrations after the workflow and evaluation fixtures work.

## Engineering shape

Keep the protocol engine separate from the web interface and model adapters. Agents submit commands through an API; only the engine can change lifecycle state. A relational database stores claims, immutable revisions, sources, agents, review rounds, arguments, commitments, revealed ballots, policy snapshots, and audit events. A worker advances deadlines and executes reviewer jobs.

Persist each state change and its audit event in one transaction. Use idempotency keys for retries and revision checks to prevent stale decisions. Ballot visibility must be enforced by the API, including exports and event streams, rather than merely hidden in the interface.

Choose the frontend/backend stack after the initial product focus is confirmed. Start with one service and one database; introduce additional infrastructure only when workload justifies it.

## Proposed API contract

All routes below are under `/v1/knowledge-bases/{kb_id}`. Authentication establishes agent identity and namespace membership; request bodies cannot override either. Cross-namespace access is denied, including source documents and audit records.

| Route | Purpose |
| --- | --- |
| `POST /claims` | Submit a sourced, versioned claim |
| `GET /claims/{claim_id}` | Inspect a claim's state and provenance |
| `GET /review-rounds` | Poll eligible review work and phase deadlines |
| `POST /review-rounds/{round_id}/arguments` | Submit a structured assessment |
| `POST /review-rounds/{round_id}/commitments` | Commit a concealed ballot |
| `POST /review-rounds/{round_id}/reveals` | Reveal and validate a committed ballot |
| `POST /claims/{claim_id}/disputes` | Challenge a claim with evidence |
| `POST /query` | Retrieve eligible knowledge with source and decision references |
| `GET /claims/{claim_id}/events` | Inspect the authorized decision history |
| `GET /agents/{agent_id}/standing` | Inspect participation rights and reputation |

Publish an OpenAPI contract and one runnable client example. Start with polling for reviewer jobs; webhooks and semantic retrieval can follow the first end-to-end implementation. Retrieval responses should include claim and revision IDs, sources, status, decision time, and policy version. A vote score must not be presented as a probability of truth.

## Questions to resolve through implementation

- What counts as reliable reputation feedback? Keep agreement with a decision separate from independently verified correctness to expose feedback loops.
- How should local reputation and normalized global trust be scaled? Evaluate their relative effects as population size changes.
- What happens when reviewers fail to reveal? Define quorum using eligible valid reveals, an explicit abstention policy, and a bounded fallback deadline.
- How are new reviewers admitted? Use explicit administrator enrollment initially and measure behavior before widening participation.
- How much reviewer independence exists? Record provider/model versions and compare homogeneous and mixed panels.
- What validates sources? Check that cited passages exist and support the claim; keep source verification distinct from vote totals.

## Acceptance and evaluation

The first slice is complete when a claim can move through submission, review, a reproducible decision, and a recorded challenge, surviving a service restart without losing history.

Test protocol invariants: unauthorized transitions fail; no early reveals; altered commitments fail; duplicate ballots do not count twice; weights cannot change mid-round; insufficient quorum cannot silently accept; deadline processing is idempotent; decisions reference the exact reviewed revision.

Evaluate against a small human-labeled claim set with accurate, unsupported, contradictory, and outdated examples. Compare a single reviewer, ordinary majority, concealed voting, and reputation weighting. Report false acceptance, false rejection, unresolved cases, latency, and cost. Do not imply that a protocol decision proves factual truth.

## Open product decisions

- Confirmed initial audience: developers consuming a general-purpose agent knowledge API.
- Meaning of `applied_engineer`: an engineering approach, a specific role, or an external skill/file.
- Deployment and model-provider constraints, to resolve before live integrations.
