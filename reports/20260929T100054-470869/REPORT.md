# Local model evaluation

Run: 20260929T100054-470869

Model: `Qwen/Qwen2.5-0.5B-Instruct-GGUF`, `Q4_K_M`; installed runtime: CUDA.

| Method | Correct / all | Coverage | Accuracy on resolved | False accepts | Seconds / claim | Model calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| single | 9/24 (37.5%) | 70.8% | 52.9% | 5 | 0.76 | 24 |
| majority | 13/24 (54.2%) | 91.7% | 59.1% | 7 | 1.72 | 72 |
| protocol_independent | 6/24 (25.0%) | 41.7% | 60.0% | 3 | 1.72 | 72 |
| protocol_deliberative | 10/24 (41.7%) | 79.2% | 52.6% | 2 | 2.72 | 144 |

## Interpretation and limits

- This is a small, developer-authored synthetic evidence-entailment benchmark, not independently human-validated real-world truth evaluation.
- All reviewer roles share one model. Temperature is 0; role prompts differ. They are correlated, not independent model families.
- Accuracy on all cases counts arbitration and abstention as unresolved, not correct. Resolved-only accuracy must be read alongside coverage.
- Single and majority baselines reuse initial outputs. The independent protocol ablation replays those same ballots through the actual engine. Deliberative protocol adds three reassessments after exchanging reasons without vote totals.
- The protocol uses fixed equal weights, quorum two, and a normalized ±0.5 threshold; majority uses the sign of the initial vote sum. A 2–1 split can resolve under majority and escalate under the protocol.
- Commit/reveal is exercised, but this experiment does not isolate its causal benefit against visible sequential voting. Learned reputation and sanctions are not evaluated.
- Timings sum measured model-call latency for the calls each method would use, excluding download, startup, and policy waiting windows. Baseline timings share calls and are not separate end-to-end runs.
- Protocol phases use a virtual clock to avoid waiting three minutes per case. Full audit records and prompts are saved in the JSON report; SQLite artifacts are in the experiment directory.
- Wilson intervals in JSON are descriptive only: paired fixtures share evidence, so independence assumptions do not hold strictly. Do not claim statistical significance from this pilot.
- Ground-truth labels are never sent to the model. No held-out tuning or independently reviewed dataset has been used.
