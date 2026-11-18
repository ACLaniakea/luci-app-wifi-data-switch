import pathlib
import subprocess
import unittest
from unittest import mock
from test_backend import controller
import admission


class AdmissionTest(unittest.TestCase):
    def test_unsupported_kernel_does_not_enable_core_hints(self):
        c=mock.Mock(RUN=pathlib.Path('/test'))
        c.command.side_effect=[subprocess.CompletedProcess([],1,'',''),RuntimeError('unsupported')]
        self.assertFalse(admission.Manager(c).sync({'mode':'split','boost_enabled':True}))
        c.rule.assert_not_called()
        self.assertFalse(c.write.call_args.args[1]['ready'])

    def test_existing_table_is_retained_for_live_sockets(self):
        c=mock.Mock(RUN=pathlib.Path('/test'))
        c.command.return_value=subprocess.CompletedProcess([],0,'','')
        manager=admission.Manager(c)
        self.assertTrue(manager.sync({'mode':'split','boost_enabled':True}))
        c.command.assert_called_once_with(['nft','list','table','inet',admission.TABLE],check=False)
        c.command.reset_mock()
        self.assertFalse(manager.sync({'mode':'wifi','boost_enabled':False}))
        c.command.assert_not_called()

    def test_native_preflight_detects_missing_connlimit_before_changing_network(self):
        import native
        c=mock.Mock(ROOT=pathlib.Path('/test'))
        def command(args,**kw):
            return subprocess.CompletedProcess(args,1 if args[0]=='nft' else 0,'nftset' if args[0]=='dnsmasq' else '','')
        c.command.side_effect=command
        with self.assertRaisesRegex(ValueError,'并发连接计数'):
            native.Manager(c).preflight()
        self.assertFalse(any(call.args[0][0]=='/etc/init.d/openclash' for call in c.command.call_args_list))
