import unittest,datetime
from files import __name__ as unused
import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).parent/'files/usr/libexec/wifi-data-switch'))
import quota
class QuotaTest(unittest.TestCase):
 def test_deltas_reset_and_restart(self):
  now=datetime.datetime(2026,11,16,12).timestamp();s={}
  quota.accumulate(s,{'up':10,'down':100},'boot',now,1)
  quota.accumulate(s,{'up':20,'down':200},'boot',now,1)
  self.assertEqual(quota.summary(s,{})['daily']['used'],220)
  import json;s=json.loads(json.dumps(s))
  quota.accumulate(s,{'up':30,'down':300},'boot',now,1)
  self.assertEqual(quota.summary(s,{})['daily']['used'],330)
  quota.accumulate(s,{'up':1,'down':9},'newboot',now,1)
  self.assertEqual(quota.summary(s,{})['daily']['used'],340)
 def test_quota_and_billing_history(self):
  now=datetime.datetime(2026,11,16,12).timestamp();s={}
  quota.accumulate(s,{'up':0,'down':2097152},'boot',now,1)
  self.assertTrue(quota.summary(s,{'daily_mib':1})['exceeded'])
  self.assertEqual(quota.summary(s,{'billing_day':15})['monthly']['used'],2097152)
  self.assertFalse(quota.summary(s,{'daily_mib':0})['exceeded'])
 def test_invalid_limits(self):
  for a in [{'daily_mib':-1},{'billing_day':29},{'monthly_mib':'abc'}]:
   with self.assertRaises(ValueError):quota.limits(a)
