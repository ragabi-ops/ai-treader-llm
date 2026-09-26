"""Structural and reference validation; factual correctness needs separate review."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class ContractError(ValueError):
    """An artifact fails the public contract or its trusted context."""


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ContractError("timestamp must include a timezone")
    return parsed


class Contracts:
    def __init__(self, directory: Path):
        self.schemas = {}
        self.tool_schemas = {}
        resources = []
        for path in directory.glob("*.schema.json"):
            contents = json.loads(path.read_text())
            Draft202012Validator.check_schema(contents)
            self.schemas[path.name] = contents
            resources.append((path.name, Resource.from_contents(contents)))
        if not self.schemas:
            raise ContractError(f"no schemas in {directory}")
        self.registry = Registry().with_resources(resources)
        for path in (directory / "tools").glob("*.schema.json"):
            contents = json.loads(path.read_text())
            Draft202012Validator.check_schema(contents)
            name = path.name.removesuffix(".schema.json")
            if name in self.tool_schemas:
                raise ContractError(f"duplicate tool schema: {name}")
            self.tool_schemas[name] = contents

    def validate(self, name: str, value: object) -> None:
        validator = Draft202012Validator(
            self.schemas[name], registry=self.registry, format_checker=FormatChecker()
        )
        errors = list(validator.iter_errors(value))
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            raise ContractError(f"{location}: {error.message}")

    def tool_arguments(self, name: str, value: object) -> None:
        if name not in self.tool_schemas:
            raise ContractError(f"unknown tool: {name}")
        validator = Draft202012Validator(
            self.tool_schemas[name], format_checker=FormatChecker()
        )
        errors = list(validator.iter_errors(value))
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            raise ContractError(f"{location}: {error.message}")

    def analysis(self, value: dict, context: dict) -> None:
        self.validate("analysis-context.schema.json", context)
        self.validate("analysis.schema.json", value)
        if value["symbol"] != context["symbol"]:
            raise ContractError("symbol does not match trusted request")
        if timestamp(value["as_of_timestamp"]) != timestamp(context["as_of_timestamp"]):
            raise ContractError("as_of_timestamp does not match trusted request")
        if timestamp(value["timestamp"]) < timestamp(value["as_of_timestamp"]):
            raise ContractError("generation timestamp precedes as_of_timestamp")
        evidence = set(context["evidence_ids"])
        metrics = set(context["metric_ids"])

        def visit(node):
            if isinstance(node, dict):
                if "evidence_ids" in node and not set(node["evidence_ids"]) <= evidence:
                    raise ContractError("unknown evidence reference")
                if "metric_refs" in node and not set(node["metric_refs"]) <= metrics:
                    raise ContractError("unknown metric reference")
                for child in node.values():
                    visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)

        visit(value)
