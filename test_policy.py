import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).parent/'files/usr/libexec/wifi-data-switch'))
import importlib.util
import pathlib
import unittest

path=pathlib.Path(__file__).parent/'files/usr/libexec/wifi-data-switch/controller.py'
spec=importlib.util.spec_from_file_location('uplink',path)
uplink=importlib.util.module_from_spec(spec);spec.loader.exec_module(uplink)

class PolicyTest(unittest.TestCase):
    def test_default_split_and_failover(self):
        cfg={'mode':'split','failover':True}
        self.assertEqual(uplink.choose_uplinks(cfg,True,True),(True,False))
        self.assertEqual(uplink.choose_uplinks(cfg,False,True),(False,False))
        self.assertEqual(uplink.choose_uplinks(cfg,True,False),(True,True))
        self.assertEqual(uplink.choose_uplinks(cfg,False,False),(False,False))
    def test_manual_modes_and_optional_fallback(self):
        for mode,normal in [('wifi',(True,True)),('mobile',(False,False))]:
            cfg={'mode':mode,'failover':True}
            self.assertEqual(uplink.choose_uplinks(cfg,True,True),normal)
            self.assertEqual(uplink.choose_uplinks(cfg,False,True),(False,False))
            self.assertEqual(uplink.choose_uplinks(cfg,True,False),(True,True))
        self.assertEqual(uplink.choose_uplinks({'mode':'mobile','failover':False},True,False),(False,False))
        self.assertEqual(uplink.choose_uplinks({'mode':'split','failover':False},True,False),(True,False))
    def test_transient_failures_do_not_flap(self):
        s={'good':0,'bad':0,'online':True}
        for _ in range(2):uplink.health_sample(s,False)
        self.assertTrue(s['online'])
        uplink.health_sample(s,True);self.assertTrue(s['online'])
        for _ in range(3):uplink.health_sample(s,False)
        self.assertFalse(s['online'])
        uplink.health_sample(s,True);self.assertFalse(s['online'])
        uplink.health_sample(s,True);self.assertTrue(s['online'])
    def test_detached_link_fails_immediately(self):
        s={'good':10,'bad':0,'online':True}
        uplink.health_sample(s,False,False)
        self.assertFalse(s['online'])

if __name__=='__main__':unittest.main()
