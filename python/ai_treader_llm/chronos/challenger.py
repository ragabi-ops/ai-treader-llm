"""Freeze a Chronos-2 challenger: the inference config and pins, fixed before any score is read.

Nothing is fitted. The freeze manifest stands where ALPHA02 has a training manifest,
and the weights manifest hash is the artifact pin. Choices are frozen here, not tuned:
median score, univariate, development-only coverage (operator, 2026-10-27).
"""
from __future__ import annotations

import copy
from pathlib import Path

from ai_treader_llm import numeric
from ai_treader_llm.chronos import provenance, series, weights
from ai_treader_llm.numeric import fail

CHALLENGER_VERSION = 'chronos-challenger-v1'
FREEZE_VERSION = 'chronos-freeze-manifest-v1'
ARM = 'C'
SEED = 20261023
TORCH_THREADS = 8
MIN_CONTEXT_LAGS = 50          # the platform-daily-v1 warm-up (trend_sma_20_50), so both see the same active rows
PREDICTION_LENGTH = {'1m': 32, '3m': 80}   # fixed per horizon so a row's output never depends on its batch
QUANTILE_LEVELS = ('0.01', '0.05', '0.1', '0.15', '0.2', '0.25', '0.3', '0.35', '0.4', '0.45', '0.5', '0.55',
                   '0.6', '0.65', '0.7', '0.75', '0.8', '0.85', '0.9', '0.95', '0.99')
DISCLOSURE = {
    'fine_tuning': 'none; zero-shot pretrained weights',
    'pretraining_overlap': 'Chronos-2 was published 2025-10-30. Its pretraining corpus is not enumerated here, so any '
                           'price history up to then may have been seen, including the ALPHA03 development (2021-2024) and '
                           'retrospective (2025) windows. Historical scores are diagnostic only; ALPHA09 forward '
                           'observation after the freeze is the uncontaminated evidence.',
    'target_mismatch': 'Chronos forecasts the total-return-adjusted close-to-close ratio over h sessions from the decision '
                       'close; the label is next-open to horizon-close return in excess of the benchmark. The benchmark term '
                       'is common to a decision date, so the cross-sectional ranking is what the score claims.',
    'information': 'Chronos sees up to 256 sessions of the close path only; R/G see six platform-daily-v1 features over at '
                   'most 50 sessions. Both are cut at the same pre-open-v1 cutoff from the same point-in-time view.',
}


def config_record(horizon: str, manifest: dict, feature_schema_sha256: str) -> dict:
    return {
        'arm': ARM, 'horizon': horizon,
        'model': {'repository': manifest['repository'], 'revision': manifest['revision'], 'pipeline': 'Chronos2Pipeline'},
        'feature_version': series.FEATURE_VERSION, 'feature_schema_sha256': feature_schema_sha256, 'lags': series.LAGS,
        'context': 'close_ratio_lag_k for the contiguous available k = 1..m, oldest first, then 1.0 for the decision close',
        'min_context_lags': MIN_CONTEXT_LAGS, 'prediction_length': PREDICTION_LENGTH[horizon],
        'step_rule': 'h = XNYS calendar sessions after the decision session through end_session',
        'score': 'quantile 0.5 of close[t+h]/close[t], minus 1',
        'quantile_levels': list(QUANTILE_LEVELS),
        'mode': {'univariate': True, 'cross_learning': False, 'batch_size': 1, 'covariates': 'none'},
        'device': 'cpu', 'dtype': 'float32', 'torch_threads': TORCH_THREADS, 'seed': SEED,
    }


def freeze(weights_dir: Path, inputs: dict, horizon: str, target: dict, out: Path) -> dict:
    """Write freeze-manifest.json and challenger.json into a new directory."""
    manifest, manifest_sha = weights.verify(weights_dir)
    schema = inputs['feature_schema']
    if schema['version'] != series.FEATURE_VERSION:
        fail('provenance_mismatch', f'freeze needs a {series.FEATURE_VERSION} export')
    if any(scope['horizon']['label'] != horizon for scope in inputs['expected_rows']):
        fail('identity_mismatch', f'export horizon is not {horizon}')
    target = {**target, 'price_basis': inputs['corporate_action_basis']}
    semantics = {'kind': 'ranking_score', 'unit': 'unitless', 'direction': 'higher_is_better', 'target': target}
    numeric.validate_semantics(semantics)
    config = config_record(horizon, manifest, schema['feature_schema_sha256'])
    code, runtime = provenance.code(), provenance.runtime(TORCH_THREADS)
    out.mkdir(parents=True, exist_ok=False)
    freeze_record = {'schema_version': FREEZE_VERSION, 'horizon': horizon, 'weights': manifest,
                     'weights_manifest_sha256': manifest_sha, 'config': config, 'score_semantics': semantics,
                     'feature_schema': schema, 'disclosure': DISCLOSURE, 'code': code, 'runtime': runtime}
    freeze_sha = provenance.write(out / 'freeze-manifest.json', freeze_record)
    challenger = {'schema_version': CHALLENGER_VERSION, 'freeze_manifest_sha256': freeze_sha, 'horizon': horizon,
                  'feature_version': series.FEATURE_VERSION, 'feature_schema_sha256': schema['feature_schema_sha256'],
                  'weights_path': str(weights_dir.resolve()), 'score_semantics': semantics, 'arms': {ARM: {
                      'config': config, 'model': {
                          'artifact_sha256': manifest_sha, 'training_manifest_sha256': freeze_sha,
                          'config_sha256': provenance.sha256(provenance.canonical(config)),
                          'code_sha256': code['sha256'], 'runtime_sha256': runtime['sha256'], 'seed': SEED}}}}
    challenger_sha = provenance.write(out / 'challenger.json', challenger)
    return {'horizon': horizon, 'challenger_sha256': challenger_sha, 'freeze_manifest_sha256': freeze_sha,
            'weights_manifest_sha256': manifest_sha, 'revision': manifest['revision'], 'code_sha256': code['sha256'],
            'runtime_sha256': runtime['sha256']}


def load(path: Path) -> tuple[dict, dict]:
    """The challenger and its arm entry, with the freeze manifest and config pins re-checked."""
    challenger = numeric.read_json(path)
    if challenger.get('schema_version') != CHALLENGER_VERSION or ARM not in challenger.get('arms', {}):
        fail('schema', f'not a {CHALLENGER_VERSION} file')
    entry = challenger['arms'][ARM]
    freeze_bytes = (path.resolve().parent / 'freeze-manifest.json').read_bytes()
    if {provenance.sha256(freeze_bytes), challenger['freeze_manifest_sha256']} != {entry['model']['training_manifest_sha256']}:
        fail('artifact_mismatch', 'freeze manifest bytes differ from the challenger pin')
    if provenance.sha256(provenance.canonical(entry['config'])) != entry['model']['config_sha256']:
        fail('artifact_mismatch', 'config differs from its frozen sha256')
    return challenger, copy.deepcopy(entry)
