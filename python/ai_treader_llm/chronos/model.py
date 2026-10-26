"""The torch side: load the pinned Chronos-2 pipeline on CPU and forecast one series at a time."""
from __future__ import annotations

import math
from pathlib import Path


class Forecaster:
    """Univariate quantile forecasts; batch_size 1 and no cross-learning, so a row never sees another."""

    def __init__(self, weights: Path, config: dict):
        import torch
        from chronos import Chronos2Pipeline

        torch.set_num_threads(config['torch_threads'])
        torch.manual_seed(config['seed'])
        torch.use_deterministic_algorithms(True)
        self.torch = torch
        self.pipeline = Chronos2Pipeline.from_pretrained(str(weights), device_map='cpu', dtype=torch.float32)
        self.levels = [float(level) for level in config['quantile_levels']]
        self.prediction_length = config['prediction_length']
        if list(self.pipeline.quantiles) != self.levels:
            raise ValueError(f'model quantiles {self.pipeline.quantiles} differ from the frozen levels')

    def __call__(self, path: list[float], step: int) -> list[float]:
        """The frozen quantile levels of close[t+step]/close[t] for one oldest-first context."""
        with self.torch.inference_mode():
            quantiles, _ = self.pipeline.predict_quantiles(
                [self.torch.tensor(path, dtype=self.torch.float32)], prediction_length=self.prediction_length,
                quantile_levels=self.levels, batch_size=1, cross_learning=False)
        out = [float(value) for value in quantiles[0][0, step - 1, :].tolist()]
        if not all(math.isfinite(value) for value in out):
            raise ArithmeticError('non_finite_output')
        return out
