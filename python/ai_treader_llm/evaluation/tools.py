from __future__ import annotations

from collections import Counter

from ai_treader_llm.contracts import ContractError, Contracts, timestamp

FAILURE_CATEGORIES = (
    "missing_prediction",
    "invalid_prediction",
    "missing_required_call",
    "unnecessary_call",
    "unauthorized_tool",
    "incorrect_tool",
    "invalid_arguments",
    "symbol_violation",
    "timestamp_violation",
)


def _failure(case_id: str, category: str, error: str, call_index: int | None = None) -> dict:
    result = {"case_id": case_id, "category": category, "error": error}
    if call_index is not None:
        result["call_index"] = call_index
    return result


def _validate_fixtures(fixtures: list[dict], contracts: Contracts) -> dict[str, dict]:
    expected = {}
    known_tools = set(contracts.tool_schemas)
    for fixture in fixtures:
        contracts.validate("tool-call-fixture.schema.json", fixture)
        case_id = fixture["case_id"]
        if case_id in expected:
            raise ContractError(f"duplicate tool-call fixture: {case_id}")
        allowed = set(fixture["allowed_tools"])
        unknown = allowed - known_tools
        if unknown:
            raise ContractError(
                f"tool-call fixture {case_id} allows unknown tools: {sorted(unknown)}"
            )
        unexpected = set(fixture["expected_tool_names"]) - allowed
        if unexpected:
            raise ContractError(
                f"tool-call fixture {case_id} expects non-allowlisted tools: {sorted(unexpected)}"
            )
        expected[case_id] = fixture
    if not expected:
        raise ContractError("tool-call fixture suite is empty")
    return expected


def _index_predictions(predictions: list[dict], expected: dict[str, dict]) -> dict[str, dict]:
    predicted = {}
    for row in predictions:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise ContractError("tool-call prediction requires a string case_id")
        case_id = row["case_id"]
        if case_id in predicted or case_id not in expected:
            raise ContractError(f"duplicate or unknown tool-call prediction: {case_id}")
        predicted[case_id] = row
    return predicted


def _time_boundary_failures(
    case_id: str, call_index: int, arguments: dict, as_of: str
) -> list[dict]:
    start_value = arguments.get("start_timestamp")
    end_value = arguments.get("end_timestamp")
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        return []
    try:
        start = timestamp(start_value)
        end = timestamp(end_value)
        cutoff = timestamp(as_of)
    except (ContractError, TypeError, ValueError):
        return []
    failures = []
    if start > end:
        failures.append(
            _failure(
                case_id,
                "timestamp_violation",
                "start_timestamp is after end_timestamp",
                call_index,
            )
        )
    if end > cutoff:
        failures.append(
            _failure(
                case_id,
                "timestamp_violation",
                "end_timestamp exceeds trusted as_of_timestamp",
                call_index,
            )
        )
    return failures


def _evaluate_case(fixture: dict, prediction: dict, contracts: Contracts) -> list[dict]:
    case_id = fixture["case_id"]
    try:
        contracts.validate("tool-call-prediction.schema.json", prediction)
    except ContractError as error:
        return [_failure(case_id, "invalid_prediction", str(error))]

    failures = []
    expected_remaining = Counter(fixture["expected_tool_names"])
    allowed = set(fixture["allowed_tools"])
    trusted = fixture["trusted_scope"]

    for call_index, call in enumerate(prediction["tool_calls"]):
        name = call["name"]
        arguments = call["arguments"]
        expected_call = expected_remaining[name] > 0
        if name not in allowed:
            failures.append(
                _failure(
                    case_id,
                    "unauthorized_tool",
                    f"tool is not allowlisted: {name}",
                    call_index,
                )
            )
        elif expected_call:
            expected_remaining[name] -= 1
        elif fixture["expected_tool_names"]:
            category = "unnecessary_call" if name in expected_remaining else "incorrect_tool"
            failures.append(
                _failure(case_id, category, f"tool was not required: {name}", call_index)
            )
        else:
            failures.append(
                _failure(
                    case_id,
                    "unnecessary_call",
                    f"no tool call was required: {name}",
                    call_index,
                )
            )

        if name not in contracts.tool_schemas:
            continue
        try:
            contracts.tool_arguments(name, arguments)
        except ContractError as error:
            failures.append(
                _failure(case_id, "invalid_arguments", str(error), call_index)
            )
            continue

        tool_properties = contracts.tool_schemas[name].get("properties", {})
        if (
            "symbol" in tool_properties
            and arguments.get("symbol") != trusted["symbol"]
        ):
            failures.append(
                _failure(
                    case_id,
                    "symbol_violation",
                    "tool symbol does not match trusted symbol",
                    call_index,
                )
            )
        failures.extend(
            _time_boundary_failures(
                case_id, call_index, arguments, trusted["as_of_timestamp"]
            )
        )

    for name, count in expected_remaining.items():
        for _ in range(count):
            failures.append(
                _failure(
                    case_id,
                    "missing_required_call",
                    f"required tool was not called: {name}",
                )
            )
    return failures


def evaluate_tool_calls(
    fixtures: list[dict], predictions: list[dict], contracts: Contracts
) -> dict:
    expected = _validate_fixtures(fixtures, contracts)
    predicted = _index_predictions(predictions, expected)
    failures = []
    predicted_call_count = 0
    failed_cases = set()

    for case_id, fixture in expected.items():
        if case_id not in predicted:
            case_failures = [
                _failure(case_id, "missing_prediction", "missing tool-call prediction")
            ]
        else:
            row = predicted[case_id]
            calls = row.get("tool_calls")
            if isinstance(calls, list):
                predicted_call_count += len(calls)
            case_failures = _evaluate_case(fixture, row, contracts)
        if case_failures:
            failed_cases.add(case_id)
            failures.extend(case_failures)

    counts = {category: 0 for category in FAILURE_CATEGORIES}
    for failure in failures:
        counts[failure["category"]] += 1
    total = len(expected)
    correct = total - len(failed_cases)
    return {
        "report_version": "1",
        "scope": "offline_tool_call_correctness",
        "total_cases": total,
        "correct_cases": correct,
        "failed_cases": len(failed_cases),
        "correctness_rate": correct / total,
        "predicted_calls": predicted_call_count,
        "failure_counts": counts,
        "failures": failures,
        "promotion_eligible": False,
        "limitations": [
            "No tool was executed",
            "Fixture expectations do not prove semantic grounding or financial quality",
            "Trusted boundary checks cover declared symbol and time arguments only",
        ],
    }
