"""Validated platform numeric exports as training/prediction rows.

Feature rows and labels stay separate artifacts: prediction loads the input manifest
only; training additionally reads labels pinned by their raw sha256.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ai_treader_llm import numeric
from ai_treader_llm.contracts import Contracts, timestamp
from ai_treader_llm.numeric import fail


@dataclass(frozen=True)
class Row:
    row_id: str
    listing_id: str
    decision: str          # decision session (date group)
    cutoff: datetime       # as_of_timestamp
    end_at: datetime       # label horizon close
    end_session: str
    x: tuple | None        # every feature, in feature-schema order; None when any is unavailable
    missing: str | None    # the unavailable features' reasons, sorted and comma-joined
    y: float | None = None
    label_reason: str | None = None


@dataclass(frozen=True)
class Export:
    path: Path
    inputs: dict
    calendar: dict
    feature_ids: tuple
    rows: tuple
    input_file_sha256: str
    labels_file_sha256: str | None = None
    target_definition_sha256: str | None = None


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_features(path: Path, contracts: Contracts) -> Export:
    inputs, calendar, feature_rows = numeric.load_input(path, contracts)
    ids = tuple(item['feature_id'] for item in inputs['feature_schema']['features'])
    by_row = {row['row_id']: row for row in feature_rows}
    rows = []
    for scope in inputs['expected_rows']:
        values = {item['feature_id']: item['value'] for item in by_row[scope['row_id']]['features']}
        missing = ','.join(sorted({values[key]['reason'] for key in ids if values[key]['status'] != 'available'})) or None
        horizon = scope['horizon']
        rows.append(Row(scope['row_id'], scope['listing_id'], horizon['decision_session'], timestamp(scope['as_of_timestamp']),
                        timestamp(horizon['end_at']), horizon['end_session'],
                        None if missing else tuple(float(values[key]['value']) for key in ids), missing))
    return Export(path, inputs, calendar, ids, tuple(rows), file_sha256(path))


def load_training(path: Path, labels: Path, labels_sha256: str, created: datetime, contracts: Contracts) -> Export:
    export = load_features(path, contracts)
    resolved = labels.resolve()
    if resolved in {path.resolve(), numeric.artifact_path(path, export.inputs['calendar']),
                    numeric.artifact_path(path, export.inputs['features'])}:
        fail('artifact_mismatch', 'labels must be a separate artifact from prediction inputs')
    data = resolved.read_bytes()
    if hashlib.sha256(data).hexdigest() != labels_sha256:
        fail('artifact_mismatch', 'labels raw bytes differ from the pinned sha256')
    try:
        lines = data.decode('utf-8').splitlines()
    except UnicodeError as error:
        raise numeric.NumericError('invalid_json', 'invalid UTF-8 JSONL') from error
    if not lines or any(not line.strip() for line in lines):
        fail('invalid_json', 'blank or empty labels JSONL')
    records = [numeric.loads(line) for line in lines]
    targets = {record.get('target_definition_sha256') for record in records}
    if len(targets) != 1:
        fail('provenance_mismatch', 'labels name more than one target definition')
    target = targets.pop()
    numeric.validate_labels(records, export.inputs, target, created, contracts)
    by_row = {record['row_id']: record['label'] for record in records}
    rows = []
    for row in export.rows:
        label = by_row[row.row_id]
        available = label['status'] == 'available'
        rows.append(Row(**{**row.__dict__, 'y': float(label['value']) if available else None,
                           'label_reason': None if available else label['reason']}))
    return Export(export.path, export.inputs, export.calendar, export.feature_ids, tuple(rows), export.input_file_sha256,
                  hashlib.sha256(data).hexdigest(), target)
