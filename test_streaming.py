import json,pathlib,subprocess,tempfile,unittest
from unittest import mock
from test_backend import controller
import streaming

class StreamingTest(unittest.TestCase):
    def test_policy_rejects_unsafe_values(self):
        for p in [{'domains':['x.com\nnftset=bad']},{'domains':['a.com'],'seed_hosts':['b.com']},
                  {'domains':['a.com'],'initial_ips':['192.168.1.1']}]:
            with self.assertRaises(ValueError):streaming.policy(p)

    def test_empty_policy_leaves_dns_and_firewall_untouched(self):
        c=mock.Mock(ROOT=pathlib.Path('/test'));c.read.return_value={}
        manager=streaming.Manager(c)
        try:
            with mock.patch.object(pathlib.Path,'glob',return_value=iter([])):
                self.assertEqual(manager.sync({'mode':'split','boost_enabled':True},True),[])
            c.command.assert_not_called()
        finally:manager.close()

    def test_dns_restart_failure_restores_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);path=root/'wifi-data-switch-prefer.conf';path.write_text('original\n')
            c=mock.Mock(ROOT=root,RUN=root)
            c.read.return_value={'domains':['bilivideo.com'],'initial_ips':['112.132.250.125']}
            def command(args,**kwargs):
                if args==['/etc/init.d/dnsmasq','restart'] and kwargs.get('check',True):
                    raise subprocess.CalledProcessError(1,args)
                return subprocess.CompletedProcess(args,0,'','')
            c.command.side_effect=command
            manager=streaming.Manager(c);manager.directory=root
            try:
                self.assertEqual(manager.sync({'mode':'split','boost_enabled':True},True),[])
                self.assertEqual(path.read_text(),'original\n')
                self.assertFalse(c.write.call_args.args[1]['ready'])
            finally:manager.close()

    def test_offline_or_manual_mobile_does_not_pin_video(self):
        c=mock.Mock(ROOT=pathlib.Path('/test'))
        c.read.return_value={'domains':['bilivideo.com']}
        manager=streaming.Manager(c)
        try:
            self.assertEqual(manager.sync({'mode':'mobile','boost_enabled':True},True),[])
            self.assertEqual(manager.sync({'mode':'split','boost_enabled':True},False),[])
            c.command.assert_not_called()
        finally:manager.close()
