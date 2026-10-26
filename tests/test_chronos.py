"""ALPHA03 Chronos-2 job logic on a synthetic series export with a fake forecaster (no torch needed)."""
import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import alpha_fixture
import chronos_fixture
from ai_treader_llm import numeric
from ai_treader_llm.chronos import challenger, coverage, predict, provenance, series
from ai_treader_llm.contracts import Contracts, timestamp

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
TARGET = {'kind': 'benchmark_excess_return', 'unit': 'decimal_return', 'benchmark_listing_id': '1',
          'entry_policy': 'next_session_open', 'exit_policy': 'horizon_close', 'definition_sha256': 'a' * 64}


class ChronosJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / 'contracts')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.fixture = chronos_fixture.build(cls.dir / 'export')
        cls.export = series.load(cls.fixture['input'], cls.contracts)
        chronos_fixture.fake_weights(cls.dir / 'weights')
        cls.freeze = challenger.freeze(cls.dir / 'weights', cls.export.inputs, '1m', TARGET, cls.dir / 'frozen')
        cls.challenger, cls.entry = challenger.load(cls.dir / 'frozen' / 'challenger.json')
        listing6 = sorted((row for row in cls.export.rows if row.listing_id == '6'), key=lambda row: row.decision)
        lengths = [series.available_lags(row) + 1 for row in listing6 if series.available_lags(row) >= 50]
        cls.fail_length, cls.nan_length = lengths[0], lengths[1]
        cls.forecaster = chronos_fixture.FakeForecaster([cls.fail_length], [cls.nan_length])
        cls.summary = cls.run_batch(cls.forecaster, 'run-a')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def request(cls, export=None, **changes):
        export = export or cls.export
        built = predict.build_request(cls.challenger, cls.entry, export, 'b1', 'a1', NOW, NOW + timedelta(hours=1))
        return {**built, **changes}

    @classmethod
    def run_batch(cls, forecaster, name, export=None, request=None, clock=None):
        export = export or cls.export
        kwargs = {'clock': clock} if clock else {'clock': lambda: NOW + timedelta(seconds=1)}
        return predict.run(cls.challenger, cls.entry, export, request or cls.request(export), forecaster,
                           cls.dir / name, cls.contracts, **kwargs)

    def read(self, *parts):
        return json.loads(self.dir.joinpath(*parts).read_text(encoding='utf-8'))

    def test_freeze_pins_weights_config_code_and_runtime(self):
        frozen = self.read('frozen', 'freeze-manifest.json')
        model = self.entry['model']
        self.assertEqual(self.freeze['weights_manifest_sha256'], model['artifact_sha256'])
        self.assertEqual(provenance.sha256((self.dir / 'frozen/freeze-manifest.json').read_bytes()), model['training_manifest_sha256'])
        self.assertEqual(provenance.code()['sha256'], model['code_sha256'])
        self.assertEqual(provenance.runtime(challenger.TORCH_THREADS)['sha256'], model['runtime_sha256'])
        config = self.entry['config']
        self.assertEqual({'univariate': True, 'cross_learning': False, 'batch_size': 1, 'covariates': 'none'}, config['mode'])
        self.assertEqual(32, config['prediction_length'])
        self.assertIn('pretraining_overlap', frozen['disclosure'])
        self.assertEqual('ranking_score', self.challenger['score_semantics']['kind'])
        self.assertEqual('total_return_adjusted', self.challenger['score_semantics']['target']['price_basis'])
        self.assertNotIn('alpha/', ' '.join(item['path'] for item in frozen['code']['files']))

    def test_freeze_refuses_existing_output_and_tampered_files(self):
        with self.assertRaises(FileExistsError):
            challenger.freeze(self.dir / 'weights', self.export.inputs, '1m', TARGET, self.dir / 'frozen')
        tampered = self.dir / 'tampered'
        tampered.mkdir()
        record = self.read('frozen', 'challenger.json')
        record['arms']['C']['config']['min_context_lags'] = 20
        (tampered / 'challenger.json').write_bytes(provenance.canonical(record))
        (tampered / 'freeze-manifest.json').write_bytes((self.dir / 'frozen/freeze-manifest.json').read_bytes())
        with self.assertRaises(numeric.NumericError) as caught:
            challenger.load(tampered / 'challenger.json')
        self.assertEqual('artifact_mismatch', caught.exception.code)

    def test_every_expected_row_has_a_score_or_typed_reason(self):
        forecast = self.read('run-a', 'forecast.json')
        expected = [scope['row_id'] for scope in self.export.inputs['expected_rows']]
        self.assertEqual(expected, [item['row_id'] for item in forecast['results']])
        reasons = self.summary['results']
        self.assertEqual(1, reasons['model_error'])
        self.assertEqual(1, reasons['non_finite_output'])
        stale = next(item for item in forecast['results'] if item['row_id'] == f'c5-{self.fixture["decisions"][4]}')
        self.assertEqual({'status': 'unavailable', 'reason': 'missing_features'}, stale['score'])
        short = [row for row in self.export.rows if row.listing_id == '6' and series.available_lags(row) < 50]
        self.assertTrue(short)
        self.assertEqual(len(short) + 1, reasons['missing_features'])
        self.assertEqual(len(expected), sum(reasons.values()))

    def test_score_is_median_ratio_minus_one_at_the_calendar_step(self):
        quantiles = [json.loads(line) for line in (self.dir / 'run-a/quantiles.jsonl').read_text().splitlines()]
        forecast = {item['row_id']: item['score'] for item in self.read('run-a', 'forecast.json')['results']}
        rows = {row.row_id: row for row in self.export.rows}
        self.assertEqual(self.summary['results']['available'], len(quantiles))
        for record in quantiles:
            row = rows[record['row_id']]
            self.assertEqual(row.steps, record['step'])
            self.assertTrue(18 <= row.steps <= 23)
            median = float(record['ratio_quantiles'][record['quantile_levels'].index('0.5')])
            self.assertAlmostEqual(median - 1, float(forecast[record['row_id']]['value']), places=12)
            path, _ = series.context(row, 50)
            self.assertEqual(len(path), record['context_points'])
            self.assertEqual(1.0, path[-1])

    def test_rerun_is_byte_identical_and_batch_invariant(self):
        self.run_batch(chronos_fixture.FakeForecaster([self.fail_length], [self.nan_length]), 'run-b')
        for name in ('forecast.json', 'quantiles.jsonl'):
            self.assertEqual((self.dir / 'run-a' / name).read_bytes(), (self.dir / 'run-b' / name).read_bytes())
        part = chronos_fixture.build(self.dir / 'export-part', decisions=10, skip=20)
        export = series.load(part['input'], self.contracts)
        self.run_batch(chronos_fixture.FakeForecaster(), 'run-part', export=export)
        whole = {item['row_id']: item['score'] for item in self.read('run-a', 'forecast.json')['results']}
        for item in self.read('run-part', 'forecast.json')['results']:
            self.assertEqual(whole[item['row_id']], item['score'])

    def test_refuses_changed_pins_semantics_and_runtime(self):
        model = {**self.entry['model'], 'seed': 1}
        semantics = copy.deepcopy(self.challenger['score_semantics'])
        semantics['target']['benchmark_listing_id'] = '2'
        for name, request in (('pins', self.request(model=model)), ('semantics', self.request(score_semantics=semantics))):
            with self.subTest(name), self.assertRaises(numeric.NumericError) as caught:
                self.run_batch(chronos_fixture.FakeForecaster(), f'refused-{name}', request=request)
            self.assertEqual('provenance_mismatch', caught.exception.code)
        entry = copy.deepcopy(self.entry)
        entry['model']['runtime_sha256'] = 'b' * 64
        request = predict.build_request(self.challenger, entry, self.export, 'b1', 'a1', NOW, NOW + timedelta(hours=1))
        with self.assertRaises(numeric.NumericError) as caught:
            predict.check(self.challenger, entry, self.export, request, self.contracts)
        self.assertIn('runtime', str(caught.exception))
        self.assertFalse((self.dir / 'refused-pins').exists())

    def test_deadline_types_remaining_rows_as_timeout(self):
        ticks = iter(range(10_000))
        clock = lambda: NOW + timedelta(seconds=3560 + min(next(ticks), 20))  # noqa: E731 - inside the reserve after ten reads
        summary = self.run_batch(chronos_fixture.FakeForecaster(), 'run-late', clock=clock)
        self.assertGreater(summary['results']['timeout'], 0)
        self.assertGreater(summary['results']['available'], 0)
        forecast = self.read('run-late', 'forecast.json')
        self.assertLessEqual(timestamp(forecast['generated_at']), NOW + timedelta(hours=1))

    def test_rejects_non_series_export(self):
        fixture = alpha_fixture.build(self.dir / 'daily', decisions=8)
        with self.assertRaises(numeric.NumericError) as caught:
            series.load(fixture['input'], self.contracts)
        self.assertEqual('provenance_mismatch', caught.exception.code)

    def test_realized_ratio_comes_from_a_later_row_view(self):
        realized = series.realized(self.export.rows, self.export.calendar)
        closes = self.fixture['closes']
        checked = 0
        for row in self.export.rows:
            if row.row_id in realized:
                expected = closes[row.listing_id][row.end_session] / closes[row.listing_id][row.decision]
                self.assertAlmostEqual(expected, realized[row.row_id], places=9)
                checked += 1
        self.assertGreater(checked, 150)
        last = max(self.fixture['decisions'])
        self.assertTrue(all(row.row_id not in realized for row in self.export.rows if row.decision == last))

    def params(self, last=None):
        decisions = self.fixture['decisions']
        last = last or decisions[-1]
        return {'windows': {'1m': {'development': {'first': decisions[0], 'last': last, 'decisions': len(decisions)},
                                   'label_end_before': (date.fromisoformat(max(r.end_session for r in self.export.rows))
                                                        + timedelta(days=1)).isoformat()}}}

    def test_coverage_reports_development_calibration_without_labels(self):
        report = coverage.run([self.fixture['input']], [self.dir / 'run-a'], self.params(), '1m',
                              self.dir / 'coverage.json', self.contracts)
        rows = report['rows']
        self.assertEqual(self.summary['results']['available'], rows['forecast'])
        self.assertGreater(rows['realized'], 0)
        self.assertGreater(rows['forecast_without_realized'], 0)
        self.assertEqual({'0.25-0.75', '0.1-0.9', '0.05-0.95', '0.01-0.99'}, set(report['intervals']))
        self.assertEqual(21, len(report['quantile_hit_rates']))
        self.assertIn('no label artifact read', report['realized_source'])

    def test_coverage_refuses_rows_past_the_development_window(self):
        with self.assertRaises(numeric.NumericError) as caught:
            coverage.run([self.fixture['input']], [self.dir / 'run-a'], self.params(last=self.fixture['decisions'][-2]), '1m',
                         self.dir / 'coverage-refused.json', self.contracts)
        self.assertEqual('split_leakage', caught.exception.code)
        self.assertFalse((self.dir / 'coverage-refused.json').exists())


if __name__ == '__main__':
    unittest.main()
