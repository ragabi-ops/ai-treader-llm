from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from ai_treader_llm import contracts_v2, numeric
from ai_treader_llm.contracts import ContractError, Contracts, timestamp
from ai_treader_llm.datasets.manifests import validate_manifest
from ai_treader_llm.datasets.outcomes import validate_outcomes
from ai_treader_llm.datasets.reviews import validate_source_review
from ai_treader_llm.datasets.samples import build_messages, read_jsonl, validate_dataset
from ai_treader_llm.datasets.targets import validate_data_targets
from ai_treader_llm.evaluation.runner import evaluate

# The frozen ALPHA03 parameters (alpha/protocol.py); repeated so the Chronos commands
# never import the ALPHA02 package, which pins BLAS/OpenMP to one thread.
ALPHA03_PARAMETERS_SHA256 = "5cba481a9204dbc66fe6c7771c4a82e808ae068303c78c2e95cd3d196afacac5"


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
    chronos_fetch = commands.add_parser("chronos-fetch", help="download pinned Chronos-2 weights (chronos runtime)")
    chronos_fetch.add_argument("--revision", required=True, help="full Hugging Face commit sha")
    chronos_fetch.add_argument("--out", type=Path, required=True, help="new directory; refused when it exists")
    chronos_freeze = commands.add_parser("chronos-freeze", help="freeze a Chronos-2 challenger before any score is read")
    chronos_freeze.add_argument("--weights", type=Path, required=True)
    chronos_freeze.add_argument("--input", type=Path, required=True, help="a platform-daily-series-v1 export of the horizon")
    chronos_freeze.add_argument("--horizon", choices=("1m", "3m"), required=True)
    chronos_freeze.add_argument("--benchmark-listing-id", required=True)
    chronos_freeze.add_argument("--target-definition-sha256", required=True, help="platform-label-v1 definition the score ranks")
    chronos_freeze.add_argument("--out", type=Path, required=True, help="new directory; refused when it exists")
    chronos_request = commands.add_parser("chronos-request", help="build a request naming a frozen Chronos challenger's pins")
    chronos_request.add_argument("--challenger", type=Path, required=True)
    chronos_request.add_argument("--input", type=Path, required=True)
    chronos_request.add_argument("--batch-id", required=True)
    chronos_request.add_argument("--attempt-id", required=True)
    chronos_request.add_argument("--deadline-seconds", type=int, default=3600)
    chronos_request.add_argument("--out", type=Path, required=True)
    chronos_predict = commands.add_parser("chronos-predict", help="feature-only Chronos-2 batch forecast (chronos runtime)")
    chronos_predict.add_argument("--challenger", type=Path, required=True)
    chronos_predict.add_argument("--input", type=Path, required=True)
    chronos_predict.add_argument("--request", type=Path, required=True)
    chronos_predict.add_argument("--out", type=Path, required=True, help="new directory: forecast.json, quantiles.jsonl, run.json")
    chronos_coverage = commands.add_parser("chronos-coverage", help="quantile coverage on development decisions; reads no labels")
    chronos_coverage.add_argument("--input", type=Path, action="append", required=True)
    chronos_coverage.add_argument("--run", type=Path, action="append", required=True, help="chronos-predict output, one per --input")
    chronos_coverage.add_argument("--horizon", choices=("1m", "3m"), required=True)
    chronos_coverage.add_argument("--protocol", type=Path, default=Path("configs/numeric/alpha03-parameters.json"))
    chronos_coverage.add_argument("--protocol-sha256", default=ALPHA03_PARAMETERS_SHA256)
    chronos_coverage.add_argument("--out", type=Path, required=True)
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
    args = parser.parse_args()
    try:
        contracts = Contracts(args.contracts)
        if args.command == "numeric-hash":
            print(numeric.artifact_hash(numeric.read_json(args.artifact)))
            return 0
        if args.command.startswith("alpha-"):
            return alpha_command(args, contracts)
        if args.command.startswith("chronos-"):
            return chronos_command(args, contracts)
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
    except (ContractError, OSError, ValueError, KeyError, TypeError) as error:
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


def chronos_command(args, contracts: Contracts) -> int:
    import hashlib
    import time
    from datetime import datetime, timezone

    from ai_treader_llm.chronos import challenger, coverage, predict, provenance, series, weights

    if args.command == "chronos-fetch":
        print(json.dumps(weights.fetch(args.revision, args.out), indent=2))
        return 0
    if args.command == "chronos-coverage":
        data = args.protocol.read_bytes()
        if hashlib.sha256(data).hexdigest() != args.protocol_sha256:
            raise numeric.NumericError("provenance_mismatch", "protocol parameters differ from the pinned sha256")
        report = coverage.run(args.input, args.run, json.loads(data), args.horizon, args.out, contracts)
        print(json.dumps(provenance.plain({"coverage": str(args.out), "rows": report["rows"],
                                           "intervals": report["intervals"]}), indent=2))
        return 0
    export = series.load(args.input, contracts)
    if args.command == "chronos-freeze":
        target = {"kind": "benchmark_excess_return", "unit": "decimal_return",
                  "benchmark_listing_id": args.benchmark_listing_id, "entry_policy": "next_session_open",
                  "exit_policy": "horizon_close", "definition_sha256": args.target_definition_sha256}
        print(json.dumps(challenger.freeze(args.weights, export.inputs, args.horizon, target, args.out), indent=2))
        return 0
    frozen, entry = challenger.load(args.challenger)
    if args.out.exists():
        raise ValueError(f"{args.out} exists; outputs are immutable")
    if args.command == "chronos-request":
        now = datetime.now(timezone.utc)
        request = predict.build_request(frozen, entry, export, args.batch_id, args.attempt_id,
                                        now, now + timedelta(seconds=args.deadline_seconds))
        args.out.write_bytes(provenance.canonical(request))
        print(json.dumps({"request": str(args.out), "batch_id": args.batch_id}))
        return 0
    from ai_treader_llm.chronos import model

    request = numeric.read_json(args.request)
    predict.check(frozen, entry, export, request, contracts)
    began = time.monotonic()
    forecaster = model.Forecaster(Path(frozen["weights_path"]), entry["config"])
    print(json.dumps(predict.run(frozen, entry, export, request, forecaster, args.out, contracts,
                                 load_seconds=time.monotonic() - began), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
