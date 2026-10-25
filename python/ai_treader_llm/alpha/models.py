"""Ridge and LightGBM fits on train-only standardized features.

Artifacts are JSON: floats as float.hex() strings (exact round trip), the LightGBM
booster as its model string. Prediction rebuilds the model from those bytes only.
"""
from __future__ import annotations

import lightgbm
import numpy as np


def hexes(values) -> list[str]:
    return [float(value).hex() for value in values]


def unhex(values) -> np.ndarray:
    return np.array([float.fromhex(value) for value in values], dtype=np.float64)


def scaler(x: np.ndarray) -> dict:
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1.0
    return {'mean': hexes(mean), 'scale': hexes(scale)}


def standardize(artifact: dict, x: np.ndarray) -> np.ndarray:
    return (x - unhex(artifact['scaler']['mean'])) / unhex(artifact['scaler']['scale'])


def lightgbm_params(config: dict, seed: int) -> dict:
    return {'objective': 'regression', 'num_leaves': config['num_leaves'], 'learning_rate': config['learning_rate'],
            'min_data_in_leaf': config['min_data_in_leaf'], 'feature_fraction': config['feature_fraction'],
            'lambda_l2': config['lambda_l2'], 'deterministic': True, 'num_threads': 1, 'seed': seed,
            'force_col_wise': True, 'verbosity': -1}


def fit(arm: str, config: dict, features: tuple, x: np.ndarray, y: np.ndarray, seed: int) -> dict:
    artifact = {'arm': arm, 'features': list(features), 'scaler': scaler(x)}
    z = standardize(artifact, x)
    if arm == 'R':
        center = float(y.mean())
        gram = z.T @ z + config['alpha'] * np.eye(z.shape[1])
        coef = np.linalg.solve(gram, z.T @ (y - center))
        return {**artifact, 'model': 'ridge', 'alpha': repr(float(config['alpha'])),
                'intercept': float(center).hex(), 'coef': hexes(coef)}
    booster = lightgbm.train(lightgbm_params(config, seed), lightgbm.Dataset(z, label=y, free_raw_data=True),
                             num_boost_round=config['n_estimators'])
    return {**artifact, 'model': 'lightgbm', 'booster': booster.model_to_string()}


def predict(artifact: dict, x: np.ndarray) -> np.ndarray:
    z = standardize(artifact, x)
    if artifact['model'] == 'ridge':
        return float.fromhex(artifact['intercept']) + z @ unhex(artifact['coef'])
    return lightgbm.Booster(model_str=artifact['booster']).predict(z, num_threads=1)
