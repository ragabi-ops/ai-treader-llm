"""ALPHA02 CPU numeric jobs on a synthetic export. Needs the numeric extra (make test-numeric)."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import alpha_fixture
from ai_treader_llm import numeric
from ai_treader_llm.alpha import data, predict, protocol, provenance, train
from ai_treader_llm.contracts import Contracts

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


class AlphaJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / 'contracts')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.fixture = alpha_fixture.build(cls.dir / 'export')
        cls.protocol, cls.protocol_sha = alpha_fixture.protocol(cls.dir, cls.fixture)
        cls.params, _ = protocol.load(cls.protocol, cls.protocol_sha)
        cls.export = cls.load()
        cls.summary = train.run(cls.export, cls.params, cls.protocol_sha, '1m', '1', cls.dir / 'run-a')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def load(cls, **changes):
        args = {'path': cls.fixture['input'], 'labels': cls.fixture['labels'], 'labels_sha256': cls.fixture['labels_sha256'],
                'created': NOW, 'contracts': cls.contracts, **changes}
        return data.load_training(**args)

    def read(self, *parts):
        return json.loads((self.dir.joinpath(*parts)).read_text(encoding='utf-8'))

    def test_frozen_parameters_copy_and_trial_family(self):
        path = ROOT / 'configs/numeric/alpha03-parameters.json'
        self.assertEqual(protocol.PARAMETERS_SHA256, hashlib.sha256(path.read_bytes()).hexdigest())
        params, _ = protocol.load(path)
        draw = protocol.trials(params)
        self.assertEqual([5, 20], [sum(t['arm'] == arm for t in draw) for arm in 'RG'])
        self.assertEqual(list(range(1, 26)), [t['trial'] for t in draw])
        self.assertEqual(20, len({t['grid_index'] for t in draw if t['arm'] == 'G'}))
        self.assertEqual(draw, protocol.trials(params))
        with self.assertRaises(numeric.NumericError) as caught:
            protocol.load(self.protocol)
        self.assertEqual('provenance_mismatch', caught.exception.code)

    def test_training_records_every_trial_folds_and_exclusions(self):
        manifest = self.read('run-a', 'training-manifest.json')
        draw = self.read('run-a', 'trial-draw.json')
        self.assertEqual(manifest['draw']['sha256'], hashlib.sha256((self.dir / 'run-a/trial-draw.json').read_bytes()).hexdigest())
        self.assertEqual(5, len(draw['trials']))
        self.assertEqual({'fitted': 5, 'failed': 0}, {k: manifest['trial_family'][k] for k in ('fitted', 'failed')})
        self.assertEqual(5, len((self.dir / 'run-a/trials.jsonl').read_text().splitlines()))
        self.assertEqual({'not_available_at_cutoff': 3}, manifest['rows']['excluded_missing_features'])
        self.assertEqual({'provider_error': 2}, manifest['rows']['excluded_missing_labels'])
        self.assertEqual(360 - 5, manifest['rows']['usable'])
        self.assertTrue(all(fold['embargo_verified'] for fold in manifest['folds']))
        self.assertEqual([20, 32], [fold['train']['decisions'] for fold in manifest['folds']])
        self.assertEqual(manifest['export']['labels_file_sha256'], self.fixture['labels_sha256'])
        self.assertEqual('ranking_score', manifest['score_semantics']['kind'])
        selected = manifest['selection']['selected_trials']
        self.assertEqual({'R', 'G'}, set(selected))
        for arm in 'RG':
            best = max((t for t in manifest['trials'] if t['arm'] == arm), key=lambda t: float(t['mean_fold_ic']))
            self.assertEqual(best['trial'], selected[arm])
        self.assertGreater(float(manifest['trials'][selected['R'] - 1]['mean_fold_ic']), 0.3)

    def test_rerun_is_byte_identical_and_pins_provenance(self):
        again = train.run(self.load(), self.params, self.protocol_sha, '1m', '1', self.dir / 'run-b')
        for name in ('training-manifest.json', 'challengers.json', 'trial-draw.json', 'artifacts/R.json', 'artifacts/G.json'):
            self.assertEqual((self.dir / 'run-a' / name).read_bytes(), (self.dir / 'run-b' / name).read_bytes(), name)
        self.assertEqual(self.summary['training_manifest_sha256'], again['training_manifest_sha256'])
        challengers = self.read('run-a', 'challengers.json')
        for arm in 'RG':
            model = challengers['arms'][arm]['model']
            self.assertEqual(model['code_sha256'], provenance.code()['sha256'])
            self.assertEqual(model['runtime_sha256'], provenance.runtime()['sha256'])
            self.assertEqual(model['training_manifest_sha256'], self.summary['training_manifest_sha256'])
            artifact = (self.dir / 'run-a/artifacts' / f'{arm}.json').read_bytes()
            self.assertEqual(model['artifact_sha256'], hashlib.sha256(artifact).hexdigest())
        with self.assertRaises(FileExistsError):
            train.run(self.export, self.params, self.protocol_sha, '1m', '1', self.dir / 'run-a')

    def forecast(self, arm, mutate=None):
        challengers, entry, artifact = predict.load_challenger(self.dir / 'run-a/challengers.json', arm)
        export = data.load_features(self.fixture['input'], self.contracts)
        request = predict.build_request(challengers, entry, export, 'batch-1', f'attempt-{arm}', NOW, NOW + timedelta(minutes=5))
        if mutate:
            mutate(challengers, entry, request)
        return predict.predict(challengers, entry, artifact, export, request, NOW + timedelta(seconds=1), self.contracts)

    def test_feature_only_forecast_validates_with_typed_unavailable(self):
        for arm in 'RG':
            forecast = self.forecast(arm)
            unavailable = [row for row in forecast['results'] if row['score']['status'] != 'available']
            self.assertEqual(360, len(forecast['results']))
            self.assertEqual(3, len(unavailable))
            self.assertEqual({'missing_features'}, {row['score']['reason'] for row in unavailable})
            self.assertEqual(numeric.artifact_hash(forecast), forecast['forecast_sha256'])

    def test_forecast_reproduces_the_training_fit(self):
        artifact = json.loads((self.dir / 'run-a/artifacts/R.json').read_text())
        forecast = self.forecast('R')
        rows = {row.row_id: row for row in self.export.rows}
        sample = next(row for row in forecast['results'] if row['score']['status'] == 'available')
        expected = predict.models.predict(artifact, train.np.array([rows[sample['row_id']].x]))[0]
        self.assertEqual(predict.decimal_text(float(expected)), sample['score']['value'])

    def test_prediction_refuses_changed_pins(self):
        def model(challengers, entry, request):
            request['model']['config_sha256'] = '0' * 64

        def runtime(challengers, entry, request):
            entry['model']['runtime_sha256'] = request['model']['runtime_sha256'] = '0' * 64

        def semantics(challengers, entry, request):
            request['score_semantics']['kind'] = 'expected_excess_return'
            request['score_semantics']['unit'] = 'decimal_return'
        for mutate in (model, runtime, semantics):
            with self.subTest(mutate.__name__), self.assertRaises(numeric.NumericError) as caught:
                self.forecast('R', mutate)
            self.assertEqual('provenance_mismatch', caught.exception.code)

    def test_prediction_refuses_tampered_artifact(self):
        copied = self.dir / 'tampered'
        copied.mkdir()
        (copied / 'artifacts').mkdir()
        (copied / 'challengers.json').write_bytes((self.dir / 'run-a/challengers.json').read_bytes())
        artifact = json.loads((self.dir / 'run-a/artifacts/R.json').read_text())
        artifact['intercept'] = float(1).hex()
        (copied / 'artifacts/R.json').write_bytes(provenance.canonical(artifact))
        with self.assertRaises(numeric.NumericError) as caught:
            predict.load_challenger(copied / 'challengers.json', 'R')
        self.assertEqual('artifact_mismatch', caught.exception.code)

    def test_labels_are_pinned_and_separate(self):
        cases = ({'labels_sha256': '0' * 64}, {'labels': self.fixture['input'].parent / 'features.jsonl'})
        for changes in cases:
            with self.subTest(changes), self.assertRaises(numeric.NumericError) as caught:
                self.load(**changes)
            self.assertEqual('artifact_mismatch', caught.exception.code)
        with self.assertRaises(numeric.NumericError) as caught:
            self.load(created=datetime(2025, 1, 1, tzinfo=timezone.utc))
        self.assertEqual('generation_time', caught.exception.code)

    def test_protocol_windows_and_fence_are_enforced(self):
        def check(change, code):
            params = copy.deepcopy(self.params)
            change(params['windows']['1m'], params)
            with self.subTest(code), self.assertRaises(numeric.NumericError) as caught:
                train.run(self.export, params, self.protocol_sha, '1m', '1', self.dir / f'refused-{code}')
            self.assertEqual(code, caught.exception.code)
            self.assertFalse((self.dir / f'refused-{code}').exists())
        check(lambda w, p: w['development'].update(decisions=59), 'coverage')
        check(lambda w, p: w.update(label_end_before=self.fixture['decisions'][-1]), 'split_leakage')
        check(lambda w, p: w['validation_folds'][0]['validation'].update(first=self.fixture['decisions'][21], decisions=18), 'split_leakage')
        check(lambda w, p: p.update(universe=p['universe'][:5]), 'coverage')

    def test_failed_trials_stay_in_the_family(self):
        grid = {'feature_fraction': [1], 'lambda_l2': [0], 'learning_rate': [0.1], 'min_data_in_leaf': [100000],
                'n_estimators': [5, 10, 20], 'num_leaves': [3]}
        (self.dir / 'failing').mkdir()
        path, digest = alpha_fixture.protocol(self.dir / 'failing', self.fixture, g_grid=grid)
        params, _ = protocol.load(path, digest)
        with self.assertRaises(numeric.NumericError) as caught:
            train.run(self.export, params, digest, '1m', '1', self.dir / 'run-failing')
        self.assertEqual('coverage', caught.exception.code)
        trials = [json.loads(line) for line in (self.dir / 'run-failing/trials.jsonl').read_text().splitlines()]
        self.assertEqual(5, len(trials))
        self.assertEqual(['failed'] * 3, [t['status'] for t in trials if t['arm'] == 'G'])

    def test_spearman_uses_average_ranks(self):
        self.assertEqual([1.5, 1.5, 3.0], train.ranks([2.0, 2.0, 5.0]))
        self.assertAlmostEqual(1.0, train.spearman([1, 2, 3], [10, 20, 30]))
        self.assertIsNone(train.spearman([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(train.spearman([1], [1]))
        self.assertEqual('0', predict.decimal_text(-1e-17))
        self.assertIsNone(predict.decimal_text(float('nan')))


if __name__ == '__main__':
    unittest.main()
