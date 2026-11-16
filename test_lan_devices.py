import unittest
from test_backend import controller
class DeviceTest(unittest.TestCase):
 def test_merge_leases_and_neighbors(self):
  from lan_devices import collect
  rows=collect('192.0.2.2 lladdr 00:11:22:33:44:55 REACHABLE\n192.0.2.3 FAILED','200 00:11:22:33:44:55 192.0.2.2 pc *\n50 aa:bb:cc:dd:ee:ff 192.0.2.5 old *',100)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'pc');self.assertEqual(rows[0]['state'],'recent')
