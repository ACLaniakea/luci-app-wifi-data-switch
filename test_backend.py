import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).parent/'files/usr/libexec/wifi-data-switch'))
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BASE = pathlib.Path(__file__).parent / 'files/usr/libexec/wifi-data-switch'
spec = importlib.util.spec_from_file_location('controller', BASE / 'controller.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)
sys.modules['controller'] = controller
spec = importlib.util.spec_from_file_location('maintenance', BASE / 'maintenance.py')
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


class BackendTest(unittest.TestCase):
    def test_public_rpc_surface_has_no_portal_actions(self):
        self.assertEqual(set(controller.METHODS), {'status', 'scan', 'configure', 'apply', 'devices'})
        acl = json.loads((BASE.parents[1] / 'share/rpcd/acl.d/luci-app-wifi-data-switch.json').read_text())
        entry = acl['luci-app-wifi-data-switch']
        self.assertEqual(entry['write']['ubus']['wifi-data-switch'], ['configure', 'apply'])

    def test_save_stages_without_changing_network(self):
        cfg={'mode':'split','ssid':'Example','encryption':'none','failover':True}
        with mock.patch.object(controller,'config',return_value=cfg), mock.patch.object(controller,'command') as command, mock.patch.object(controller,'write') as write:
            result=controller.configure({'daily_mib':'1536'})
        self.assertTrue(result['ok'])
        command.assert_not_called()
        self.assertEqual(write.call_args.args[0].name,'pending.json')
        self.assertEqual(write.call_args.args[1]['daily_mib'],1536)
        self.assertNotIn('daily_mib',cfg)

    def test_lan_routes_follow_configured_lan(self):
        calls = []
        def command(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 1 if args[:3] == ['nft', 'list', 'table'] else 0, '', '')
        wifi = {'up': True, 'gateway': '192.0.2.1', 'device': 'wifi0', 'addresses': ['192.0.2.2']}
        cell = {'up': True, 'gateway': '198.51.100.1', 'device': 'cell0', 'addresses': ['198.51.100.2']}
        with mock.patch.object(controller, 'command', side_effect=command), \
             mock.patch.object(controller, 'rule'), \
             mock.patch.object(controller, 'ubus', return_value={'ipv4-address': [{'address': '10.9.8.1', 'mask': 24}]}):
            controller.setup_routes(wifi, cell, True)
        routes = [args for args, _ in calls if args[:3] == ['ip', '-4', 'route']]
        self.assertIn(['ip', '-4', 'route', 'replace', 'table', '202', 'throw', '10.9.8.0/24'], routes)
        self.assertIn(['ip', '-4', 'route', 'replace', 'table', '201', 'default', 'via', '198.51.100.1', 'dev', 'cell0'], routes)

    def test_reject_invalid_interface_name(self):
        with mock.patch.object(controller, 'read', return_value={'mobile_device': 'cell0"; bad'}):
            with self.assertRaises(ValueError):
                controller.hardware()

    def test_password_cannot_inject_uci_batch(self):
        with mock.patch.object(controller, 'config', return_value={'mode': 'mobile', 'ssid': 'Example', 'encryption': 'psk2'}), \
             mock.patch.object(controller, 'command') as command:
            with self.assertRaises(ValueError):
                controller.configure({'wifi_key': 'password\nset something=bad'})
            command.assert_not_called()

    def test_status_omits_saved_wifi_key(self):
        with mock.patch.object(controller, 'config', return_value={'ssid': 'Example', 'wifi_key': 'example-only', 'password': 'example-only'}), \
             mock.patch.object(controller, 'read', side_effect=lambda path, default: default), \
             mock.patch.object(controller, 'iface', return_value={'device': '', 'up': False}), \
             mock.patch.object(controller, 'command', return_value=subprocess.CompletedProcess([], 0, '', '')):
            status = controller.status()
        self.assertEqual(status['settings'], {'ssid': 'Example'})
        self.assertNotIn('credentials_saved', status)


class HookTest(unittest.TestCase):
    def test_menu_points_to_a_fresh_readable_ui_module(self):
        menu_file=BASE.parents[1]/'share/luci/menu.d/luci-app-wifi-data-switch.json'
        entry=json.loads(menu_file.read_text())['admin/network/wifi-data-switch']['action']['path'].split('/')[-1]
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            (root/'settings.js').write_text('new release module')
            with mock.patch.object(maintenance,'UI_ROOT',root),mock.patch.object(maintenance,'MENU_FILE',menu_file):
                maintenance.publish_ui()
            self.assertEqual((root/(entry+'.js')).read_text(),'new release module')
            self.assertTrue((root/(entry+'.js')).stat().st_mode & 0o444)
        makefile=(BASE.parents[3]/'Makefile').read_text()
        self.assertIn(entry+'.js',makefile)
    def test_missing_openclash_does_not_prevent_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            hook = pathlib.Path(directory) / 'missing-hook.sh'
            with mock.patch.object(maintenance, 'HOOK', hook):
                maintenance.edit_hook()
            self.assertFalse(hook.exists())
    def test_install_is_idempotent_and_remove_preserves_existing_hook(self):
        original = '#!/bin/sh\n# user rules\necho custom\nexit 0\n'
        with tempfile.TemporaryDirectory() as directory:
            hook = pathlib.Path(directory) / 'hook.sh'
            hook.write_text(original)
            with mock.patch.object(maintenance, 'HOOK', hook):
                maintenance.edit_hook()
                once = hook.read_text()
                maintenance.edit_hook()
                self.assertEqual(hook.read_text(), once)
                self.assertLess(once.index(maintenance.BEGIN), once.index('exit 0'))
                maintenance.edit_hook(remove=True)
                self.assertEqual(hook.read_text(), original)


if __name__ == '__main__':
    unittest.main()
