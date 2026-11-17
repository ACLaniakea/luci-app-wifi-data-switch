import unittest,tempfile,pathlib,json,subprocess
from unittest import mock
from test_backend import controller
import native
class NativeTest(unittest.TestCase):
 def test_no_proxy_mode_policy(self):
  cfg={'mode':'direct','failover':True,'boost_enabled':True}
  self.assertEqual(controller.choose_uplinks(cfg,True,True),(True,False))
  self.assertEqual(controller.choose_uplinks(cfg,False,True),(False,False))
  self.assertTrue(controller.boost_runtime(cfg,True,True)['active'])
 def test_rule_scope_and_connection_persistence(self):
  cfg={'boost_device_mode':'whitelist','boost_devices':'192.0.2.2/32','boost_domains':'example.com','boost_scope':'domains'}
  text=native.rules(cfg,'test-lan',True)
  self.assertIn('iifname != "test-lan" return',text)
  self.assertIn('ip saddr != @selected return',text)
  self.assertIn('ct state established,related return',text)
  self.assertIn('numgen inc mod 4',text)
  self.assertNotIn('numgen',native.rules(cfg,'test-lan',False))
  self.assertIn('0x5753',text)
  self.assertEqual(native.dns_text(['example.com']),'nftset=/example.com/4#inet#wds_native#targets\n')
 def test_all_tcp_works_without_dns_match(self):
  text=native.rules({'boost_scope':'all_tcp'},'lan',True)
  self.assertIn('meta nfproto ipv4 meta mark set numgen',text)
  self.assertNotIn('@targets',text)
  self.assertIn('meta l4proto != tcp return',text)
  self.assertIn('47984-48010',text)
 def test_split_bypass_respects_openclash_ip_exceptions(self):
  text=native.rules({'boost_scope':'all_tcp'},'lan',True,'fw4','wds_balance','wds_quota_guard','wds_selected',('ip daddr != @china_ip_route','ip daddr @china_ip_route_pass'))
  self.assertIn('ip daddr != @china_ip_route return',text)
  self.assertIn('ip daddr @china_ip_route_pass return',text)
  self.assertLess(text.index('ip daddr @china_ip_route_pass return'),text.index('numgen'))
  self.assertIn('ct direction reply return',text)
  self.assertIn('198.18.0.0/15',text)
 def test_dns_backup_restored_and_proxy_stopped_before_switch(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);calls=[]
   class Fake:
    ROOT=root;RUN=root;__file__='/test/controller.py'
    def command(self,args,**kw):
     calls.append(args)
     values={('dnsmasq','--version'):'nftset',('uci','-X','show','dhcp'):'dhcp.cfgtest=dnsmasq',('uci','-q','get','dhcp.@dnsmasq[0].server'):'127.0.0.1#7874',('uci','-q','get','dhcp.@dnsmasq[0].noresolv'):'1',('uci','-q','get','dhcp.@dnsmasq[0].confdir'):str(root/'dns')}
     return subprocess.CompletedProcess(args,1 if args[:3]==['nft','list','table'] else 0,values.get(tuple(args),''),'')
    def read(self,p,default):return json.loads(p.read_text()) if p.exists() else default
    def write(self,p,data):p.write_text(json.dumps(data))
   c=Fake();manager=native.Manager(c)
   with mock.patch.object(native.subprocess,'Popen'),mock.patch.object(manager,'service',side_effect=lambda action: c.command(['/etc/init.d/openclash',action]).returncode==0):
    manager.enter({'boost_domains':'example.com'})
    state=manager.state();self.assertEqual(state['dns']['server'],'127.0.0.1#7874')
    self.assertLess(calls.index(['/etc/init.d/openclash','stop']),calls.index(['uci','-q','delete','dhcp.@dnsmasq[0].server']))
    manager.restore()
   self.assertIn(['uci','add_list','dhcp.@dnsmasq[0].server=127.0.0.1#7874'],calls)
   self.assertIn(['/etc/init.d/openclash','start'],calls)
   self.assertFalse(manager.state())
 def test_reboot_preserves_original_dns_backup(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);dns=root/'native.conf';dns.write_text('old')
   state={'boot':'old','phase':'active','file':str(dns),'dns':{'server':'original'},'openclash_running':True,'openclash_enabled':True,'prior_mode':'split'}
   c=mock.Mock(ROOT=root);c.command.return_value=subprocess.CompletedProcess([],0,'','');c.read.side_effect=lambda *args:state
   manager=native.Manager(c)
   with mock.patch.object(manager,'enter') as enter:
    self.assertTrue(manager.sync({'mode':'direct'}));enter.assert_called_once_with({'mode':'direct'},state)
 def test_failed_transition_restores_previous_mode(self):
  with tempfile.TemporaryDirectory() as d:
   state={'phase':'entering','prior_mode':'wifi'};c=mock.Mock(ROOT=pathlib.Path(d))
   c.read.side_effect=lambda *args:state;c.command.return_value=subprocess.CompletedProcess([],1,'','')
   manager=native.Manager(c)
   with mock.patch.object(manager,'enter',side_effect=RuntimeError('DNS failed')),mock.patch.object(manager,'_restore') as restore:
    with self.assertRaises(RuntimeError):manager.sync({'mode':'direct'})
   restore.assert_called_once();self.assertEqual(c.write.call_args.args[1]['mode'],'wifi')
 def test_quota_disables_new_mobile_connections_and_rejects_existing(self):
  text=native.rules({'boost_device_mode':'all'},'lan',False)
  self.assertNotIn('numgen',text)
  self.assertIn('quota_guard meta mark 0x5753 reject',text)
  self.assertIn('ct mark & 0xffff',text)
 def test_meter_has_forward_and_reply_accounting(self):
  import quota
  c=mock.Mock(ROOT=pathlib.Path('/tmp'));c.command.return_value=subprocess.CompletedProcess([],1,'','')
  quota.Meter(c).install();quota.enable_forward_meter(c)
  scripts='\n'.join(call.kwargs.get('input','') for call in c.command.call_args_list)
  self.assertIn('ct direction reply',scripts)
  self.assertIn('hook forward',scripts)
  self.assertIn('counter name up',scripts)
