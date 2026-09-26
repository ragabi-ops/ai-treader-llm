from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.samples import context_for, validate_dataset


def evaluate(samples: list[dict], predictions: list[dict], contracts: Contracts) -> dict:
    validate_dataset(samples, contracts)
    expected = {sample["sample_id"]: sample for sample in samples}
    predicted = {}
    for row in predictions:
        if set(row) != {"sample_id", "analysis"} or not isinstance(row["sample_id"], str):
            raise ContractError("prediction requires only sample_id and analysis")
        identity = row["sample_id"]
        if identity in predicted or identity not in expected:
            raise ContractError(f"duplicate or unknown prediction: {identity}")
        predicted[identity] = row["analysis"]
    failures = []
    for identity, sample in expected.items():
        if identity not in predicted:
            failures.append({"sample_id": identity, "error": "missing prediction"})
            continue
        try:
            contracts.analysis(predicted[identity], context_for(sample))
        except ContractError as error:
            failures.append({"sample_id": identity, "error": str(error)})
    count = len(expected)
    return {
        "report_version": "1", "scope": "schema_and_reference_validity_only",
        "total": count, "valid": count - len(failures),
        "validity_rate": (count - len(failures)) / count,
        "failures": failures, "promotion_eligible": False,
        "limitations": ["No semantic grounding score", "No tool execution score",
                        "No performance or financial evaluation", "No outcome-window embargo validation"],
    }
