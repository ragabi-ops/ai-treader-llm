from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.error import URLError

from ai_treader_llm import contracts_v2, numeric
from ai_treader_llm.benchmark import measure_recovery, run_benchmark, write_report
from ai_treader_llm.contracts import ContractError, Contracts, timestamp
from ai_treader_llm.datasets.manifests import validate_manifest
from ai_treader_llm.datasets.outcomes import validate_outcomes
from ai_treader_llm.datasets.reviews import validate_source_review
from ai_treader_llm.datasets.samples import build_messages, read_jsonl, validate_dataset
from ai_treader_llm.datasets.targets import validate_data_targets
from ai_treader_llm.evaluation.runner import evaluate
from ai_treader_llm.inference.client import smoke


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Treader offline LLM tooling")
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    commands = parser.add_subparsers(dest="command", required=True)
    numeric_input = commands.add_parser("validate-numeric-input")
    numeric_input.add_argument("manifest", type=Path)
    numeric_dataset = commands.add_parser("validate-numeric-dataset")
    numeric_dataset.add_argument("manifest", type=Path)
    forecast = commands.add_parser("validate-alpha")
    forecast.add_argument("forecast", type=Path)
    forecast.add_argument("--request", type=Path, required=True)
    forecast.add_argument("--input", type=Path, required=True)
    numeric_hash = commands.add_parser("numeric-hash")
    numeric_hash.add_argument("artifact", type=Path)
    alpha_train = commands.add_parser("alpha-train", help="ALPHA03 ridge/LightGBM fit (needs the numeric extra)")
    alpha_train.add_argument("--input", type=Path, required=True, help="platform numeric-input-v1 manifest")
    alpha_train.add_argument("--labels", type=Path, required=True, help="the export's separate labels.jsonl")
    alpha_train.add_argument("--labels-sha256", required=True, help="raw sha256 the platform recorded for labels.jsonl")
    alpha_train.add_argument("--benchmark-listing-id", required=True)
    alpha_train.add_argument("--horizon", choices=("1m", "3m"), required=True)
    alpha_train.add_argument("--protocol", type=Path, default=Path("configs/numeric/alpha03-parameters.json"))
    alpha_train.add_argument("--protocol-sha256", help="defaults to the frozen ALPHA03 parameters hash")
    alpha_train.add_argument("--out", type=Path, required=True, help="new directory; refused when it exists")
    alpha_request = commands.add_parser("alpha-request", help="build a request naming a frozen challenger's pins")
    alpha_request.add_argument("--challengers", type=Path, required=True)
    alpha_request.add_argument("--arm", choices=("R", "G"), required=True)
    alpha_request.add_argument("--input", type=Path, required=True)
    alpha_request.add_argument("--batch-id", required=True)
    alpha_request.add_argument("--attempt-id", required=True)
    alpha_request.add_argument("--deadline-seconds", type=int, default=600)
    alpha_request.add_argument("--out", type=Path, required=True)
    alpha_predict = commands.add_parser("alpha-predict", help="feature-only batch forecast (needs the numeric extra)")
    alpha_predict.add_argument("--challengers", type=Path, required=True)
    alpha_predict.add_argument("--arm", choices=("R", "G"), required=True)
    alpha_predict.add_argument("--input", type=Path, required=True)
    alpha_predict.add_argument("--request", type=Path, required=True)
    alpha_predict.add_argument("--out", type=Path, required=True)
    analysis = commands.add_parser("validate-analysis")
    analysis.add_argument("analysis", type=Path)
    analysis.add_argument("--context", type=Path, required=True)
    for name in ("validate-dataset", "build-inputs"):
        command = commands.add_parser(name)
        command.add_argument("samples", type=Path)
    outcomes = commands.add_parser("validate-outcomes")
    outcomes.add_argument("samples", type=Path)
    outcomes.add_argument("outcomes", type=Path)
    outcomes.add_argument("--embargo-days", type=int, default=0)
    manifest = commands.add_parser("validate-manifest")
    manifest.add_argument("manifest", type=Path)
    manifest.add_argument(
        "--evaluation-boundary",
        help="UTC embargoed boundary: every cutoff and label interval must end before it",
    )
    source_review = commands.add_parser("validate-source-review")
    source_review.add_argument("review", type=Path)
    source_review.add_argument(
        "--source-root",
        type=Path,
        help="optional source-bundle directory; verifies compressed and decoded bytes",
    )
    source_review.add_argument(
        "--platform-root",
        type=Path,
        help="optional platform repository; verifies identity and calendar source files",
    )
    data_targets = commands.add_parser("validate-data-targets")
    data_targets.add_argument("manifest", type=Path)
    data_targets.add_argument(
        "--platform-root",
        type=Path,
        help="optional platform repository; verifies identity and calendar source files",
    )
    context_hash = commands.add_parser("context-hash")
    context_hash.add_argument("context", type=Path)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("samples", type=Path)
    evaluation.add_argument("predictions", type=Path)
    health = commands.add_parser("smoke")
    health.add_argument("--base-url", default="http://127.0.0.1:18080")
    health.add_argument("--model", default="ai-treader-analyst")
    benchmark = commands.add_parser("benchmark-endpoint")
    benchmark.add_argument("workload", type=Path)
    benchmark.add_argument("--base-url", default="http://127.0.0.1:18080")
    benchmark.add_argument("--telemetry-url", default="http://127.0.0.1:18090/api/v1/status")
    benchmark.add_argument("--timeout", type=float, default=120)
    benchmark.add_argument("--status-file", type=Path)
    benchmark.add_argument("--output", type=Path, required=True)
    recovery = commands.add_parser("benchmark-recovery")
    recovery.add_argument("--base-url", default="http://127.0.0.1:18080")
    recovery.add_argument("--ssh-host", default="ai-treader-llm")
    recovery.add_argument("--container", default="ai-treader-llm-inference-1")
    recovery.add_argument("--model", default="ai-treader-analyst")
    recovery.add_argument("--timeout", type=float, default=120)
    recovery.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "smoke":
            print(json.dumps(smoke(args.base_url, args.model), indent=2))
            return 0
        if args.command == "benchmark-endpoint":
            report = run_benchmark(
                args.workload,
                args.base_url,
                args.telemetry_url or None,
                args.timeout,
                args.status_file,
            )
            write_report(report, args.output)
            print(json.dumps({
                "status": report["status"],
                "run_id": report["run_id"],
                "workload_id": report["workload_id"],
                "output": str(args.output),
                "duration_seconds": report["duration_seconds"],
            }, indent=2))
            return 0 if report["status"] == "succeeded" else 1
        if args.command == "benchmark-recovery":
            report = measure_recovery(
                args.base_url,
                args.ssh_host,
                args.container,
                args.model,
                args.timeout,
            )
            write_report(report, args.output)
            print(json.dumps({
                "status": "succeeded" if report["completion"]["ok"] else "failed",
                "ready_after_ms": report["ready_after_ms"],
                "first_completion_after_restart_ms": report["first_completion_after_restart_ms"],
                "output": str(args.output),
            }, indent=2))
            return 0 if report["completion"]["ok"] else 1
        contracts = Contracts(args.contracts)
        if args.command == "numeric-hash":
            print(numeric.artifact_hash(numeric.read_json(args.artifact)))
            return 0
        if args.command.startswith("alpha-"):
            return alpha_command(args, contracts)
        if args.command == "validate-numeric-input":
            inputs, _, rows = numeric.load_input(args.manifest, contracts)
            print(json.dumps({"valid": True, "dataset_id": inputs["dataset_id"], "features": len(rows)}))
            return 0
        if args.command == "validate-numeric-dataset":
            print(json.dumps({"valid": True, **numeric.load_dataset(args.manifest, contracts)}))
            return 0
        if args.command == "validate-alpha":
            inputs, calendar, rows = numeric.load_input(args.input, contracts)
            value, request = numeric.read_json(args.forecast), numeric.read_json(args.request)
            numeric.validate_forecast(value, request, inputs, calendar, rows, contracts)
            available = sum(row["score"]["status"] == "available" for row in value["results"])
            print(json.dumps({"valid": True, "results": len(value["results"]), "available": available,
                              "unavailable": len(value["results"]) - available}))
            return 0
        if args.command == "validate-analysis":
            analysis, context = json.loads(args.analysis.read_text()), json.loads(args.context.read_text())
            if context.get("schema_version") == "2":
                contracts_v2.validate_analysis(analysis, context, contracts)
            else:
                contracts.analysis(analysis, context)
            print('{"valid":true}')
            return 0
        if args.command == "context-hash":
            print(contracts_v2.context_hash(json.loads(args.context.read_text())))
            return 0
        if args.command == "validate-manifest":
            boundary = args.evaluation_boundary
            summary = validate_manifest(
                args.manifest,
                contracts,
                evaluation_boundary=timestamp(boundary) if boundary else None,
            )
            print(json.dumps({"valid": True, **summary}))
            return 0
        if args.command == "validate-source-review":
            summary = validate_source_review(
                args.review,
                contracts,
                source_root=args.source_root,
                platform_root=args.platform_root,
            )
            print(json.dumps({"valid": True, **summary}))
            return 0
        if args.command == "validate-data-targets":
            summary = validate_data_targets(
                args.manifest,
                contracts,
                platform_root=args.platform_root,
            )
            print(json.dumps({"valid": True, **summary}))
            return 0
        samples = read_jsonl(args.samples)
        validate_dataset(samples, contracts)
        if args.command == "validate-outcomes":
            outcome_rows = read_jsonl(args.outcomes)
            validate_outcomes(
                samples,
                outcome_rows,
                contracts,
                embargo=timedelta(days=args.embargo_days),
            )
            print(json.dumps({"valid": True, "samples": len(samples), "outcomes": len(outcome_rows)}))
        elif args.command == "validate-dataset":
            print(json.dumps({"valid": True, "samples": len(samples)}))
        elif args.command == "build-inputs":
            for sample in samples:
                print(json.dumps({"sample_id": sample["sample_id"], "messages": build_messages(sample, contracts)}))
        else:
            report = evaluate(samples, read_jsonl(args.predictions), contracts)
            print(json.dumps(report, indent=2))
            return 1 if report["failures"] else 0
        return 0
    except (ContractError, OSError, URLError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def alpha_command(args, contracts: Contracts) -> int:
    from datetime import datetime, timezone

    from ai_treader_llm.alpha import data, predict, protocol, provenance, train

    if args.command == "alpha-train":
        params, digest = protocol.load(args.protocol, args.protocol_sha256 or protocol.PARAMETERS_SHA256)
        export = data.load_training(args.input, args.labels, args.labels_sha256, datetime.now(timezone.utc), contracts)
        print(json.dumps(train.run(export, params, digest, args.horizon, args.benchmark_listing_id, args.out), indent=2))
        return 0
    challengers, entry, artifact = predict.load_challenger(args.challengers, args.arm)
    export = data.load_features(args.input, contracts)
    if args.out.exists():
        raise ValueError(f"{args.out} exists; outputs are immutable")
    if args.command == "alpha-request":
        now = datetime.now(timezone.utc)
        request = predict.build_request(challengers, entry, export, args.batch_id, args.attempt_id,
                                        now, now + timedelta(seconds=args.deadline_seconds))
        args.out.write_bytes(provenance.canonical(request))
        print(json.dumps({"request": str(args.out), "batch_id": args.batch_id, "arm": args.arm}))
        return 0
    request = numeric.read_json(args.request)
    forecast = predict.predict(challengers, entry, artifact, export, request, datetime.now(timezone.utc), contracts)
    args.out.write_bytes(provenance.canonical(forecast))
    available = sum(row["score"]["status"] == "available" for row in forecast["results"])
    print(json.dumps({"forecast": str(args.out), "forecast_sha256": forecast["forecast_sha256"],
                      "results": len(forecast["results"]), "available": available,
                      "unavailable": len(forecast["results"]) - available}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
