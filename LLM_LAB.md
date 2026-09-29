# Local LLM and Gradio lab

Installed in this workspace:

- Qwen2.5-0.5B-Instruct, official Hugging Face GGUF, Q4_K_M quantization (491,400,032 bytes).
- llama.cpp build `b11146`, with CUDA 13.4 libraries inside `.runtime/`.
- Gradio 6.28.0 and pip inside `.venv`.
- A private `libgomp` library; no system packages or GPU drivers were changed.
- Detected hardware: NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB VRAM, driver 610.62.

GPU placement was verified with a diagnostic startup using the same model/runtime settings: layers 0–24 were assigned to `CUDA0`. The diagnostic log is `data/gpu-verification.log`; its temporary server was stopped after checking. The primary model service remains on port 8081.

The model is deliberately tiny. The first evaluation exposed substantial evidence-reasoning errors; do not treat its accepted claims as verified facts.

## Open the interface

If the services are already running, open **http://127.0.0.1:7860**.

Otherwise use two terminals from this directory:

```bash
source .venv/bin/activate
python -m curation.model_server
```

```bash
source .venv/bin/activate
python -m curation.gradio_app
```

The model listens on localhost port 8081; Gradio listens on localhost port 7860. Neither opens a public share link. `--cpu` disables GPU offload. GPU access must be allowed by WSL and the execution environment. The original API/browser console remains available independently on port 8000.

**Review a claim:** enter a claim and evidence passage. Three reviewer prompts run independently, exchange their reasons without vote totals, and reassess. Actual ballots go through the existing SQLite engine's commit/reveal and decision rules. The page shows individual assessments, the protocol result, elapsed time, and downloadable audit JSON. User input is stored locally in ignored `reports/interactive/` and `data/experiments/` directories.

**Evaluate effectiveness:** select 6, 12, or 24 synthetic fixtures. The interface produces a comparison table and downloadable JSON, CSV, and Markdown reports. One GPU job runs at a time through the Gradio queue.

The review laboratory uses isolated experiment databases and a virtual protocol clock. It does not automatically publish claims into the ordinary knowledge base. Inference timings are real; 60-second phase windows are advanced programmatically, not included in latency figures.

## First measured pilot

Full [report](reports/20260929T100054-470869/REPORT.md), [metrics CSV](reports/20260929T100054-470869/metrics.csv), and [raw prompts, outputs, and audits](reports/20260929T100054-470869/results.json).

| Method | Correct / 24 | Coverage | False accepts / 12 negative cases | Inference seconds / claim |
| --- | ---: | ---: | ---: | ---: |
| Single reviewer | 9 (37.5%) | 70.8% | 5 | 0.76 |
| Majority of three | 13 (54.2%) | 91.7% | 7 | 1.72 |
| Independent protocol | 6 (25.0%) | 41.7% | 3 | 1.72 |
| Deliberative protocol | 10 (41.7%) | 79.2% | 2 | 2.72 |

The full run made 144 model calls and took about 150 seconds including SQLite and artifact handling. It recorded zero invalid JSON outputs. The deliberative protocol reduced false accepts from 7 to 2 relative to majority in this sample, but increased false rejections from 2 to 7 and left 5 cases unresolved. It did **not** outperform majority in overall correctness. This is a measured tradeoff, not a demonstrated accuracy improvement.

These 24 labels were authored alongside self-contained synthetic passages and have not been independently human-validated. All roles use the same model; this does not establish performance across independent agents or real knowledge bases. Paired fixtures share source text. The JSON's descriptive Wilson intervals do not establish statistical significance. There is no claim of reproducing the paper's experiments.

## Metrics and experimental controls

- `accuracy_all = correct decisions / all cases`; unresolved cases are not correct.
- `coverage = resolved decisions / all cases`.
- `accuracy_resolved = correct / resolved`; undefined denominators are `null`, not perfect scores.
- `acceptance_precision = supported accepts / all accepts`.
- `false_accept_rate = unsupported accepts / negative cases`.
- `false_reject_rate = supported rejects / positive cases`; unresolved positives are reported separately.
- `seconds_per_claim` sums measured model latency for each method's required calls, divided by case count.
- Reports also contain token usage, invalid-output counts, acceptance recall, and correct decisions per 1,000 tokens.

All baselines reuse the same initial assessments. Single uses reviewer 1; majority uses the sign of three initial votes. The independent protocol replays those votes through the real engine. The deliberative version adds three reassessments after exchanging reasons. No ground-truth labels are sent to the model. Temperature is zero, prompt roles differ, and seeds and exact prompts are recorded.

The engine has fixed equal weights, quorum two, and a ±0.5 threshold. With three votes, a 2–1 split can resolve under majority but escalate under the protocol. This comparison does not isolate the causal benefit of concealment, reputation learning, or sanctions. The source passages are supplied data, not independently fetched or authenticated sources.

## Reproduce

```bash
python -m curation.evaluate --limit 24
python -m unittest discover -s tests -v
python -m examples.gradio_smoke
```

The model server must be running for evaluation. The Gradio smoke check also requires the Gradio app. Each benchmark gets a new report directory; prior runs are preserved.

To install in another compatible Linux x86-64/WSL environment:

```bash
python -m pip install -r requirements-llm.lock.txt
python -m curation.install_model --gpu
```

The installer pins model and runtime revisions and verifies SHA-256 hashes. Model weights, CUDA libraries, and native binaries remain ignored local artifacts. A compatible NVIDIA driver is required for the CUDA build. If `libgomp.so.1` is missing, download your distribution's `libgomp1` package into `.runtime/` and extract it with `dpkg-deb -x PACKAGE.deb .runtime/system-libs`; the server adds that private library directory automatically. The initial setup used Ubuntu's `libgomp1_16-20260322-1ubuntu1_amd64.deb` (SHA-256 `add19738c63794d2aa9ac529d3b8aebe2e88980faecb6c1c59f07aefd6c3c314`).

References: [official Qwen model](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF), [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), [Gradio quickstart](https://www.gradio.app/guides/quickstart).
