"""Real Chronos-2 smoke: pinned weights on CPU (make test-chronos; skipped without torch or CHRONOS_WEIGHTS)."""
import importlib.util
import os
import unittest
from pathlib import Path

from ai_treader_llm.chronos import challenger, weights

WEIGHTS = os.environ.get('CHRONOS_WEIGHTS')


@unittest.skipUnless(importlib.util.find_spec('torch') and WEIGHTS, 'needs the chronos runtime and CHRONOS_WEIGHTS')
class ChronosModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ai_treader_llm.chronos import model

        manifest, _ = weights.verify(Path(WEIGHTS))
        config = challenger.config_record('1m', manifest, '0' * 64)
        cls.config = config
        cls.forecaster = model.Forecaster(Path(WEIGHTS), config)
        cls.reload = model.Forecaster(Path(WEIGHTS), config)

    def path(self, points=257):
        return [1 + 0.1 * ((k * 37) % 11 - 5) / 50 for k in range(points - 1)] + [1.0]

    def test_quantiles_are_finite_monotone_and_reproducible(self):
        for points, step in ((257, 21), (51, 1), (120, self.config['prediction_length'])):
            with self.subTest(points=points, step=step):
                quantiles = self.forecaster(self.path(points), step)
                self.assertEqual(len(self.config['quantile_levels']), len(quantiles))
                self.assertEqual(sorted(quantiles), quantiles)
                self.assertEqual(quantiles, self.forecaster(self.path(points), step))
                self.assertEqual(quantiles, self.reload(self.path(points), step))


if __name__ == '__main__':
    unittest.main()
