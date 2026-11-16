import unittest
from test_backend import controller
class BoostTest(unittest.TestCase):
    def test_empty_scope_rejected(self):
        with self.assertRaises(ValueError):controller.acceleration({'boost_enabled':'true'})
    def test_invalid_scope_rejected(self):
        for args in [{'boost_devices':'not-an-ip'},{'boost_domains':'example.com;DIRECT'}]:
            with self.assertRaises(ValueError):controller.acceleration(args)
    def test_health_and_mode_gate(self):
        cfg={'mode':'split',**controller.acceleration({'boost_enabled':'true','boost_domains':'example.com'})}
        self.assertTrue(controller.boost_runtime(cfg,True,True)['active'])
        for w,m in [(False,True),(True,False),(False,False)]:self.assertFalse(controller.boost_runtime(cfg,w,m)['active'])
        cfg['mode']='wifi';self.assertFalse(controller.boost_runtime(cfg,True,True)['active'])
    def test_default_disabled(self):
        self.assertFalse(controller.boost_runtime({'mode':'split'},True,True)['active'])

    def test_whitelist_requires_device_and_domain(self):
        with self.assertRaises(ValueError):controller.acceleration({'boost_enabled':'true','boost_device_mode':'whitelist','boost_domains':'example.com'})
        cfg=controller.acceleration({'boost_enabled':'true','boost_domains':'example.com'})
        self.assertEqual(cfg['boost_device_mode'],'all')
        cfg=controller.acceleration({'boost_enabled':'true','boost_device_mode':'blacklist','boost_domains':'example.com'})
        self.assertEqual(cfg['boost_device_mode'],'blacklist')

    def test_legacy_strategy_always_uses_round_robin(self):
        cfg=controller.acceleration({'boost_strategy':'sticky-sessions'})
        self.assertEqual(cfg['boost_strategy'],'round-robin')
        self.assertEqual(controller.boost_runtime({'mode':'split','boost_enabled':True,'boost_strategy':'sticky-sessions'},True,True)['strategy'],'round-robin')
