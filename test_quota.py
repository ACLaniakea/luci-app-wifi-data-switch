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

class NetworkTotalsTest(unittest.TestCase):
 def test_first_sample_baselines_preinstall_bytes(self):
  now=datetime.datetime(2026,11,16,12).timestamp();s={}
  quota.network_sample(s,{'up':1000000,'down':2000000},'boot','cell',now,1)
  self.assertEqual(quota.overall_summary(s,{},'mobile')['daily']['used'],0)
  quota.network_sample(s,{'up':1000100,'down':2000900},'boot','cell',now,1)
  self.assertEqual(quota.overall_summary(s,{},'mobile')['daily']['used'],1000)
 def test_total_cap_and_reboot_resume(self):
  now=datetime.datetime(2026,11,16,12).timestamp();s={}
  quota.network_sample(s,{'up':10,'down':20},'old','cell',now,1)
  quota.network_sample(s,{'up':10,'down':2097172},'old','cell',now,1)
  self.assertTrue(quota.overall_summary(s,{'mobile_daily_mib':1},'mobile')['exceeded'])
  self.assertFalse(quota.overall_summary(s,{'mobile_daily_mib':1},'wifi')['exceeded'])
  import json;s=json.loads(json.dumps(s))
  quota.network_sample(s,{'up':100,'down':100},'new','cell',now,1)
  self.assertEqual(quota.overall_summary(s,{},'mobile')['daily']['used'],2097352)
 def test_device_change_does_not_duplicate_counter(self):
  now=datetime.datetime(2026,11,16,12).timestamp();s={}
  quota.network_sample(s,{'up':100,'down':200},'boot','cell',now,1)
  quota.network_sample(s,{'up':200,'down':300},'boot','cell',now,1)
  quota.network_sample(s,{'up':999999,'down':999999},'boot','newcell',now,1)
  self.assertEqual(quota.overall_summary(s,{},'mobile')['daily']['used'],200)
