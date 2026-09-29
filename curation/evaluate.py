import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import time

from .experiment import assess
from .install_model import ROOT
from .local_llm import LocalReviewer

METHODS = ["single", "majority", "protocol_independent", "protocol_deliberative"]


def ratio(a, b):
    return a / b if b else None


def wilson(successes, total):
    if not total:
        return [None, None]
    z = 1.96
    p = successes / total
    center = (p + z*z/(2*total)) / (1 + z*z/total)
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / (1 + z*z/total)
    return [max(0, center-half), min(1, center+half)]


def summarize(rows):
    metrics = []
    for method in METHODS:
        n = len(rows)
        positives = sum(r["label"] == 1 for r in rows)
        negatives = n - positives
        predictions = [r["predictions"][method] for r in rows]
        correct = sum(p == r["label"] for p, r in zip(predictions, rows))
        resolved = sum(p != 0 for p in predictions)
        tp = sum(p == 1 and r["label"] == 1 for p, r in zip(predictions, rows))
        fp = sum(p == 1 and r["label"] == -1 for p, r in zip(predictions, rows))
        fn = sum(p == -1 and r["label"] == 1 for p, r in zip(predictions, rows))
        reviews = []
        for row in rows:
            reviews.extend(row["initial"][:1] if method == "single" else row["initial"])
            if method == "protocol_deliberative":
                reviews.extend(row["revised"])
        seconds = sum(b["seconds"] for b in reviews)
        tokens = sum(b["usage"].get("total_tokens", 0) for b in reviews)
        metrics.append({"method": method, "n": n, "correct": correct, "resolved": resolved,
            "unresolved": n-resolved, "accuracy_all": ratio(correct, n), "accuracy_wilson95": wilson(correct, n),
            "accuracy_resolved": ratio(correct, resolved), "coverage": ratio(resolved, n),
            "acceptance_precision": ratio(tp, tp+fp), "acceptance_recall": ratio(tp, positives),
            "false_accepts": fp, "false_accept_rate": ratio(fp, negatives),
            "false_rejects": fn, "false_reject_rate": ratio(fn, positives),
            "model_calls": len(reviews), "model_seconds": seconds, "seconds_per_claim": ratio(seconds, n),
            "total_tokens": tokens, "correct_per_1000_tokens": ratio(correct*1000, tokens),
            "invalid_outputs": sum(bool(b["error"]) for b in reviews)})
    return metrics


def report_markdown(result):
    def pct(value):
        return "n/a" if value is None else f"{value:.1%}"
    lines = ["# Local model evaluation", "", f"Run: {result['run_id']}", "",
        f"Model: `{result['model']['repository']}`, `{result['model']['quantization']}`; installed runtime: {result['model']['device']}.", "",
        "| Method | Correct / all | Coverage | Accuracy on resolved | False accepts | Seconds / claim | Model calls |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for m in result["metrics"]:
        lines.append(f"| {m['method']} | {m['correct']}/{m['n']} ({pct(m['accuracy_all'])}) | {pct(m['coverage'])} | {pct(m['accuracy_resolved'])} | {m['false_accepts']} | {m['seconds_per_claim']:.2f} | {m['model_calls']} |")
    lines += ["", "## Interpretation and limits", "",
        "- This is a small, developer-authored synthetic evidence-entailment benchmark, not independently human-validated real-world truth evaluation.",
        "- All reviewer roles share one model. Temperature is 0; role prompts differ. They are correlated, not independent model families.",
        "- Accuracy on all cases counts arbitration and abstention as unresolved, not correct. Resolved-only accuracy must be read alongside coverage.",
        "- Single and majority baselines reuse initial outputs. The independent protocol ablation replays those same ballots through the actual engine. Deliberative protocol adds three reassessments after exchanging reasons without vote totals.",
        "- The protocol uses fixed equal weights, quorum two, and a normalized ±0.5 threshold; majority uses the sign of the initial vote sum. A 2–1 split can resolve under majority and escalate under the protocol.",
        "- Commit/reveal is exercised, but this experiment does not isolate its causal benefit against visible sequential voting. Learned reputation and sanctions are not evaluated.",
        "- Timings sum measured model-call latency for the calls each method would use, excluding download, startup, and policy waiting windows. Baseline timings share calls and are not separate end-to-end runs.",
        "- Protocol phases use a virtual clock to avoid waiting three minutes per case. Full audit records and prompts are saved in the JSON report; SQLite artifacts are in the experiment directory.",
        "- Wilson intervals in JSON are descriptive only: paired fixtures share evidence, so independence assumptions do not hold strictly. Do not claim statistical significance from this pilot.",
        "- Ground-truth labels are never sent to the model. No held-out tuning or independently reviewed dataset has been used.", ""]
    return "\n".join(lines)


def run_evaluation(limit=24, port=8081, progress=None, output_dir=None):
    dataset_path = ROOT / "benchmarks" / "claims.json"
    dataset = json.loads(dataset_path.read_text())
    cases = dataset["cases"][:int(limit)]
    if not cases:
        raise ValueError("Select at least one case")
    reviewer = LocalReviewer(port)
    reviewer.health()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(time.time_ns())[-6:]
    output_dir = Path(output_dir) if output_dir else ROOT / "reports" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    db_path = ROOT / "data" / "experiments" / (run_id + ".sqlite3")
    rows = []
    start = time.perf_counter()
    for index, case in enumerate(cases):
        if progress:
            progress(index, len(cases), f"Case {case['id']}: {case['category']}")
        row = assess(reviewer, case["claim"], case["evidence"], db_path, seed=42 + index*1000)
        row.update(id=case["id"], label=case["label"], category=case["category"])
        rows.append(row)
        with (output_dir / "cases.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
    result = {"run_id": run_id, "model": json.loads((ROOT / "models" / "manifest.json").read_text()),
        "python": platform.python_version(), "platform": platform.platform(), "dataset": dataset["version"],
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "temperature": 0.0, "base_seed": 42, "max_output_tokens": 128,
        "wall_seconds": time.perf_counter()-start, "metrics": summarize(rows), "cases": rows,
        "database": str(db_path.relative_to(ROOT))}
    (output_dir / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    (output_dir / "REPORT.md").write_text(report_markdown(result))
    with (output_dir / "metrics.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=result["metrics"][0].keys())
        writer.writeheader()
        writer.writerows(result["metrics"])
    if progress:
        progress(len(cases), len(cases), "Complete")
    return result, output_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, choices=range(1, 25), default=24)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    result, path = run_evaluation(args.limit, args.port,
        lambda i, n, label: print(f"[{i}/{n}] {label}", flush=True))
    print(report_markdown(result), flush=True)
    print(f"Artifacts: {path}", flush=True)


if __name__ == "__main__":
    main()
