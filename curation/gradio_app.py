"""Small local lab for real model reviews and reproducible pilot evaluation."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio as gr

from .evaluate import report_markdown, run_evaluation
from .experiment import assess
from .install_model import ROOT
from .local_llm import LocalReviewer


def build_app(port=8081):
    reviewer = LocalReviewer(port)

    def status():
        try:
            reviewer.health()
            manifest = json.loads((ROOT / "models" / "manifest.json").read_text())
            return f"Model server ready · {manifest['repository']} · {manifest['quantization']} · installed runtime: {manifest['device']}"
        except (RuntimeError, OSError) as exc:
            return str(exc)

    def review_claim(claim, evidence, progress=gr.Progress()):
        reviewer.health()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(time.time_ns())[-6:]
        folder = ROOT / "reports" / "interactive" / run_id
        folder.mkdir(parents=True)
        step = [0]

        def update(label):
            progress(step[0] / 6, desc=label)
            step[0] += 1

        result = assess(reviewer, claim, evidence, ROOT / "data" / "experiments" / (run_id + ".sqlite3"), progress=update)
        artifact = folder / "review.json"
        artifact.write_text(json.dumps(result, indent=2) + "\n")
        rows = [[phase, f"Reviewer {b['role'] + 1}", b["vote"], b["reason"], round(b["seconds"], 2), bool(b["error"])]
            for phase, ballots in (("Independent", result["initial"]), ("After discussion", result["revised"])) for b in ballots]
        outcomes = {1: "accept", -1: "reject", 0: "unresolved / arbitration"}
        summary = "\n".join(f"- **{name.replace('_', ' ')}:** {outcomes[pred]}" for name, pred in result["predictions"].items())
        summary += f"\n\nMeasured elapsed time: **{result['wall_seconds']:.2f} seconds**. No ground-truth label is supplied for this claim, so accuracy cannot be calculated."
        return summary, rows, result["protocol"], str(artifact)

    def evaluate(limit, progress=gr.Progress()):
        result, path = run_evaluation(int(limit), port,
            lambda i, n, label: progress(i/n, desc=label))
        rows = [[m["method"], m["correct"], m["n"], round(100*m["accuracy_all"], 1),
                 round(100*m["coverage"], 1), m["false_accepts"], m["unresolved"],
                 round(m["seconds_per_claim"], 2), m["total_tokens"]] for m in result["metrics"]]
        return report_markdown(result), rows, [str(path / name) for name in ("results.json", "metrics.csv", "REPORT.md")]

    def latest_report():
        files = sorted((ROOT / "reports").glob("*/REPORT.md"))
        return files[-1].read_text() if files else "No completed benchmark yet. Run an evaluation below."

    with gr.Blocks(title="Deliberative Knowledge Lab", analytics_enabled=False) as app:
        gr.Markdown("# Deliberative Knowledge Lab\nA small local model, auditable reviews, and measured outcomes.")
        health = gr.Textbox(label="Local model status", value="Click Check model to verify the server.", interactive=False)
        check = gr.Button("Check model")
        check.click(status, outputs=health, api_name="model_status")
        with gr.Tab("Review a claim"):
            gr.Markdown("Three roles use the **same Qwen model**. They assess the passage independently, exchange reasons, then commit and reveal their revised votes through the protocol engine. Votes mean **1: supported**, **−1: contradicted or unsupported**, **0: cannot decide**.")
            claim = gr.Textbox(label="Claim", value="The shipment contains 36 sensors.", max_length=2000)
            evidence = gr.Textbox(label="Evidence passage", lines=5, max_length=6000,
                value="The shipment contains 4 sealed boxes. Each box contains exactly 9 sensors. There are no additional sensors.")
            run = gr.Button("Run real model review", variant="primary")
            summary = gr.Markdown()
            ballots = gr.Dataframe(headers=["Phase", "Role", "Vote", "Reason", "Seconds", "Invalid output"], interactive=False, wrap=True)
            with gr.Accordion("Protocol decision and audit trail", open=False):
                audit = gr.JSON()
            download = gr.File(label="Download review trace")
            run.click(review_claim, [claim, evidence], [summary, ballots, audit, download],
                concurrency_limit=1, concurrency_id="local-model", api_name="review_claim")
            gr.Markdown("Review artifacts use a separate experiment database. The protocol clock is accelerated; inference timing is real. No claims are automatically published into your demo knowledge base.")
        with gr.Tab("Evaluate effectiveness"):
            gr.Markdown("Compare one reviewer, ordinary majority, the independent protocol, and the deliberative protocol. **24 synthetic labeled fixtures**, balanced between supported and unsupported claims. Labels are developer-authored, not independently validated. This is a pilot, not evidence of production reliability.")
            limit = gr.Dropdown(choices=[6, 12, 24], value=24, label="Number of fixtures")
            evaluate_button = gr.Button("Run benchmark", variant="primary")
            metrics = gr.Dataframe(headers=["Method", "Correct", "Cases", "Accuracy % (all)", "Coverage %", "False accepts", "Unresolved", "Seconds / claim", "Tokens"], interactive=False)
            report = gr.Markdown(value=latest_report())
            files = gr.File(label="Download results", file_count="multiple")
            evaluate_button.click(evaluate, [limit], [report, metrics, files], concurrency_limit=1,
                concurrency_id="local-model", api_name="evaluate")
        with gr.Tab("How to read the results"):
            gr.Markdown("""### Quality and cost
- **Accuracy (all):** correct accept/reject decisions divided by all cases. Unresolved cases are not counted as correct.
- **Coverage:** the fraction given a final accept/reject decision.
- **Accuracy on resolved:** correctness only among resolved cases; always compare it with coverage.
- **False accepts:** unsupported claims that entered the knowledge base.
- **Seconds and tokens:** measured inference cost. Download, model loading, and virtual waiting windows are excluded.

### What this experiment cannot establish
The reviewers share one small model and fixed equal weights. This does not test independent model diversity, learned reputation, graduated sanctions, or the isolated benefit of concealed voting. The ±0.5 protocol threshold is stricter than ordinary majority, so fewer false accepts may come at the price of more arbitration. Review quality is measured against the supplied passage, not independently verified truth.

The runtime stays on localhost. No hosted inference, public Gradio share link, or API key is used.
""")
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--model-port", type=int, default=8081)
    args = parser.parse_args()
    build_app(args.model_port).queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=args.port, share=False, inbrowser=False)


if __name__ == "__main__":
    main()
