import json
import subprocess
import time
import types
import unittest
from unittest import mock
from test_backend import controller
import performance


class PerformanceTest(unittest.TestCase):
    def test_congestion_needs_distinct_samples_and_recovers_slowly(self):
        manager = performance.Manager(mock.Mock())
        def detail(ms, stamp):
            return {'mobile': {'success': True, 'connect_ms': ms, 'sampled_at': stamp,
                               'endpoint': 'a', 'identity': 'mobile'}}
        self.assertEqual(manager.recommend({}, detail(20, 1), 0), 50)
        for now in (10, 20, 30):
            self.assertEqual(manager.recommend({}, detail(150, 2), now), 50)
        self.assertEqual(manager.recommend({}, detail(150, 3), 40), 50)
        self.assertEqual(manager.recommend({}, detail(150, 4), 50), 25)
        for stamp in (5, 6, 7):
            self.assertEqual(manager.recommend({}, detail(20, stamp), 50+stamp), 25)
        # Four good samples are still subject to the 45s minimum hold.
        self.assertEqual(manager.recommend({}, detail(20, 8), 70), 25)
        self.assertEqual(manager.recommend({}, detail(20, 9), 100), 50)

    def test_endpoint_or_address_changes_do_not_compare_unrelated_baselines(self):
        m = performance.Manager(mock.Mock())
        for i, (endpoint, address, ms) in enumerate([('a', 'old', 1), ('b', 'old', 400),
                                                   ('b', 'new', 800), ('b', 'new', 810)]):
            self.assertEqual(m.recommend({}, {'wifi': {'endpoint': endpoint, 'identity': address,
                'success': True, 'sampled_at': i+1, 'connect_ms': ms}}, i*10), 50)

    def test_disabling_adaptation_restores_equal_distribution(self):
        m = performance.Manager(mock.Mock())
        m.share = 25
        self.assertEqual(m.recommend({'boost_adaptive': False}, {}, 10), 50)
        self.assertEqual(performance.rates((1, {'wifi_down': 100}), {'wifi_down': 1000100}, 3)['wifi_down'], 4)
        self.assertEqual(performance.rates((1, {'wifi_down': 100}), {'wifi_down': 1}, 3)['wifi_down'], 0)

    def test_wifi_proxy_mark_is_not_counted_as_boost(self):
        script = performance.meter_script()
        output_chain = script.split('chain local_tx', 1)[1].split('chain forward_tx', 1)[0]
        self.assertIn('meta mark 0x5754', output_chain)
        self.assertNotIn('meta mark 0x5752', output_chain)

    def test_probe_rejects_redirect_and_preserves_dns_error(self):
        c = mock.Mock()
        c.command.return_value = subprocess.CompletedProcess([], 0, '302 0.01 0.03', '')
        with mock.patch.object(performance.pathlib.Path, 'exists', return_value=True):
            self.assertEqual(performance.probe(c, 'wifi')['reason'], 'portal')
            c.command.return_value = subprocess.CompletedProcess([], 6, '000 0 0', '')
            self.assertEqual(performance.probe(c, 'wifi')['reason'], 'dns_error')
            c.command.return_value = subprocess.CompletedProcess([], 0, '204 0.01 0.035', '')
            self.assertEqual(performance.probe(c, 'wifi')['connect_ms'], 25)

    def test_selector_uses_local_api_without_config_reload(self):
        c = mock.Mock()
        c.active_clash.return_value = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(st_mtime_ns=1, st_size=3))
        c.clash_info.return_value = ['127.0.0.1:9090', 'private-test-token']
        c.command.side_effect = [subprocess.CompletedProcess([], 0, '{"now":"WDS-BOOST-BALANCED"}\n200', ''),
                                 subprocess.CompletedProcess([], 0, '\n204', '')]
        m = performance.Manager(c)
        self.assertTrue(m.select_clash(25))
        calls = c.command.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn('WDS-BOOST-WIFI-BIAS', calls[1].kwargs['input'])
        for call in calls:
            self.assertEqual(call.args[0], ['curl', '--noproxy', '*', '--config', '-'])
            self.assertNotIn('private-test-token', ' '.join(call.args[0]))
            self.assertNotIn('/configs', call.kwargs['input'])

    def test_sampler_keeps_working_while_probe_is_blocked(self):
        import pathlib
        import threading
        release = threading.Event()
        sampled = threading.Event()
        calls = []
        c = mock.Mock(RUN=pathlib.Path('/tmp'), health_sample=controller.health_sample)
        c.config.return_value = {}
        c.hardware.return_value = {'mobile_device': 'cell'}
        c.read.return_value = {}
        scores = {k: {'good': 0, 'bad': 0, 'online': False} for k in ('wifi', 'mobile')}
        def delayed(*args):
            release.wait(timeout=3)
            return {'success': True}
        def sample(*args):
            calls.append(1)
            sampled.set()
            return {'ready': True, 'exceeded': False}
        with mock.patch('performance.probe', side_effect=delayed), mock.patch('quota.Meter') as meter, mock.patch('quota.mobile_guard'):
            meter.return_value.sample.side_effect = sample
            probes = performance.Probes(c)
            sampler = performance.Sampler(c, mock.Mock())
            try:
                probes.poll({k: {'up': True, 'device': k} for k in scores}, scores)
                sampler.start()
                self.assertTrue(sampled.wait(timeout=1))
                self.assertEqual(len(calls), 1)
                self.assertTrue(all(not v[0].done() for v in probes.pending.values()))
            finally:
                release.set()
                sampler.close()
                probes.close()


if __name__ == '__main__':
    unittest.main()
