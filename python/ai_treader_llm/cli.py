from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.error import URLError

from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.outcomes import validate_outcomes
from ai_treader_llm.datasets.samples import build_messages, read_jsonl, validate_dataset
from ai_treader_llm.evaluation.runner import evaluate
from ai_treader_llm.inference.client import smoke


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Treader offline LLM tooling")
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    commands = parser.add_subparsers(dest="command", required=True)
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
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("samples", type=Path)
    evaluation.add_argument("predictions", type=Path)
    health = commands.add_parser("smoke")
    health.add_argument("--base-url", default="http://127.0.0.1:18080")
    health.add_argument("--model", default="ai-treader-analyst")
    args = parser.parse_args()
    try:
        if args.command == "smoke":
            print(json.dumps(smoke(args.base_url, args.model), indent=2))
            return 0
        contracts = Contracts(args.contracts)
        if args.command == "validate-analysis":
            contracts.analysis(json.loads(args.analysis.read_text()), json.loads(args.context.read_text()))
            print('{"valid":true}')
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


if __name__ == "__main__":
    raise SystemExit(main())
