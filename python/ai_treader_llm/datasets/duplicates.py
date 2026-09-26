from __future__ import annotations

import unicodedata
from collections import Counter

from ai_treader_llm.contracts import ContractError


NEAR_DUPLICATE_MIN_TOKENS = 20
NEAR_DUPLICATE_THRESHOLD = 0.90
SPLITS = ("train", "validation", "test")


def _tokens(content: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", content).casefold()
    return "".join(character if character.isalnum() else " " for character in normalized).split()


def _multiset_jaccard(left: Counter, right: Counter) -> float:
    intersection = sum((left & right).values())
    union = sum((left | right).values())
    return intersection / union if union else 1.0


def validate_cross_split_duplicates(samples: list[dict]) -> None:
    """Reject exact and high-confidence near-duplicate sample inputs across splits."""
    inputs = {split: [] for split in SPLITS}
    for sample in samples:
        source_tokens = [_tokens(source["content"]) for source in sample["sources"]]
        tokens = [token for source in source_tokens for token in source]
        inputs[sample["split"]].append(
            {
                "sample_id": sample["sample_id"],
                # Sorting makes exact comparison independent of source order while
                # retaining boundaries between source texts.
                "normalized": "\x1f".join(sorted(" ".join(source) for source in source_tokens)),
                "tokens": Counter(tokens),
                "token_count": len(tokens),
            }
        )

    for earlier_index, earlier_split in enumerate(SPLITS):
        for later_split in SPLITS[earlier_index + 1 :]:
            for earlier in inputs[earlier_split]:
                for later in inputs[later_split]:
                    if earlier["normalized"] == later["normalized"]:
                        _raise_duplicate(earlier, later, 1.0)
                    shorter = min(earlier["token_count"], later["token_count"])
                    longer = max(earlier["token_count"], later["token_count"])
                    if shorter < NEAR_DUPLICATE_MIN_TOKENS:
                        continue
                    # Jaccard cannot exceed the token-count ratio. Avoid the more
                    # expensive Counter operations when the threshold is impossible.
                    if shorter / longer < NEAR_DUPLICATE_THRESHOLD:
                        continue
                    similarity = _multiset_jaccard(earlier["tokens"], later["tokens"])
                    if similarity >= NEAR_DUPLICATE_THRESHOLD:
                        _raise_duplicate(earlier, later, similarity)


def _raise_duplicate(earlier: dict, later: dict, similarity: float) -> None:
    raise ContractError(
        "cross-split duplicate samples: "
        f"{earlier['sample_id']} and {later['sample_id']} "
        f"(similarity {similarity:.3f})"
    )
