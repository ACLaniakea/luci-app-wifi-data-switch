"""Optional root-only Linux integration test; isolated network namespaces, no production routes changed."""
import subprocess,time,os,importlib.util,json,pathlib,types,sys,shutil,tempfile
base=pathlib.Path(__file__).resolve().parents[1]/"files/usr/libexec/wifi-data-switch"
native_path=sys.argv[1] if len(sys.argv)>1 else str(base/"native.py")
quota_path=sys.argv[2] if len(sys.argv)>2 else str(base/"quota.py")
s=importlib.util.spec_from_file_location('native',native_path);native=importlib.util.module_from_spec(s);s.loader.exec_module(native)
prefix='wd'+str(os.getpid());names={k:prefix+k for k in 'rcwm'};created=[];procs=[];tempfiles=[];core_directory=None
def run(*args,ns=None,input=None):
 cmd=(['ip','netns','exec',names[ns]] if ns else [])+list(args)
 r=subprocess.run(cmd,input=input,text=True,capture_output=True,timeout=8)
 if r.returncode:raise RuntimeError(str(cmd)+' rc='+str(r.returncode)+' '+r.stdout+r.stderr)
 return r.stdout
try:
 for n in names.values():run('ip','netns','add',n);created.append(n)
 for tag,key,subnet in [('lan','c','10.255.0'),('wifi','w','192.0.2'),('cell','m','198.51.100')]:
  a=prefix+tag;b=a+'p';run('ip','link','add',a,'type','veth','peer','name',b)
  run('ip','link','set',a,'netns',names['r']);run('ip','link','set',b,'netns',names[key])
  run('ip','link','set',a,'name',tag,ns='r');run('ip','addr','add',subnet+'.1/24','dev',tag,ns='r');run('ip','link','set',tag,'up',ns='r')
  run('ip','link','set',b,'name','eth0',ns=key);run('ip','addr','add',subnet+'.2/24','dev','eth0',ns=key);run('ip','link','set','eth0','up',ns=key);run('ip','route','add','default','via',subnet+'.1',ns=key)
 for key in names:run('ip','link','set','lo','up',ns=key)
 for key in 'wm':run('ip','addr','add','203.0.113.1/32','dev','lo',ns=key)
 run('sysctl','-qw','net.ipv4.ip_forward=1',ns='r')
 for key in ['all','default','lan','wifi','cell']:run('sysctl','-qw','net.ipv4.conf.'+key+'.rp_filter=0',ns='r')
 run('ip','route','add','default','via','192.0.2.2','dev','wifi',ns='r')
 for mark,table,gw,dev in [('0x5752','202','192.0.2.2','wifi'),('0x5753','201','198.51.100.2','cell'),('0x5754','202','192.0.2.2','wifi')]:
  run('ip','rule','add','fwmark',mark,'lookup',table,ns='r');run('ip','route','replace','table',table,'default','via',gw,'dev',dev,ns='r')
 for key in 'wm':
  code="import socket,threading\ndef handle(c):\n try:\n  while c.recv(4096):c.sendall(b'HTTP/1.1 200 OK\\r\\nContent-Length: 1\\r\\n\\r\\n'+"+repr(key.encode())+")\n finally:c.close()\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',18080));s.listen()\nwhile True:\n c,a=s.accept();threading.Thread(target=handle,args=(c,),daemon=True).start()"
  procs.append(subprocess.Popen(['ip','netns','exec',names[key],'python3','-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
  udp="import socket,threading\ndef serve(port):\n s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('0.0.0.0',port))\n while True:\n  d,a=s.recvfrom(4096);s.sendto("+repr(key.encode())+",a)\nfor port in [443,444,47998]:threading.Thread(target=serve,args=(port,),daemon=True).start()\nthreading.Event().wait()"
  procs.append(subprocess.Popen(['ip','netns','exec',names[key],'python3','-c',udp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
 time.sleep(1.5)
 run('nft','-f','-',ns='r',input='table inet wds_native {\n set targets { type ipv4_addr; flags interval; elements = {203.0.113.1}; }\n set selected { type ipv4_addr; flags interval; }\n chain balance { type filter hook prerouting priority -140; policy accept; }\n chain quota_guard { type filter hook forward priority -6; policy accept; }\n}\n')
 s=importlib.util.spec_from_file_location('quota',quota_path);quota=importlib.util.module_from_spec(s);s.loader.exec_module(quota)
 def command(args,**kwargs):
  return subprocess.run(['ip','netns','exec',names['r']]+args,capture_output=True,text=True,**kwargs)
 c=types.SimpleNamespace(ROOT=pathlib.Path('/tmp'),command=command,read=lambda *args:{})
 quota.Meter(c).install();quota.enable_forward_meter(c)
 perf_path=str(pathlib.Path(native_path).with_name('performance.py'))
 s=importlib.util.spec_from_file_location('performance',perf_path);perf=importlib.util.module_from_spec(s);s.loader.exec_module(perf)
 run('nft','-f','-',ns='r',input=perf.meter_script())
 run('nft','flush','set','inet','wds_native','targets',ns='r')
 print('All-TCP test uses an empty DNS target set',flush=True)
 for mode,selected,expected in [('all','',True),('whitelist','10.255.0.2/32',True),('blacklist','10.255.0.2/32',False)]:
  run('nft','-f','-',ns='r',input=native.rules({'boost_device_mode':mode,'boost_devices':selected},'lan',True))
  rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(6)];print(mode,rows,flush=True)
  if set(rows)!=({'w','m'} if expected else {'w'}):raise RuntimeError('Incorrect routing')
 run('nft','-f','-',ns='r',input=native.rules({'boost_scope':'domains'},'lan',True))
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(4)]
 assert rows==['w']*4,rows
 print('Domain-only scope bypasses a nonmatching address:',rows,flush=True)
 run('nft','add','element','inet','wds_native','targets','{203.0.113.1}',ns='r')
 run('nft','-f','-',ns='r',input=native.rules({'boost_scope':'domains'},'lan',True))
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(4)]
 assert set(rows)=={'w','m'},rows
 print('Domain-only scope balances a matching address:',rows,flush=True)
 for share in [25,75]:
  run('nft','-f','-',ns='r',input=native.rules({'_mobile_share':share},'lan',True))
  rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(12)]
  assert rows.count('m')==12*share//100,rows
  print('Weighted native share',share,rows,flush=True)
 run('nft','-f','-',ns='r',input=native.rules({'_mobile_share':0},'lan',True))
 client="import socket,time\ns=socket.create_connection(('203.0.113.1',18080),timeout=3)\nfor i in range(2):\n s.sendall(b'GET / HTTP/1.1\\r\\nHost: test\\r\\n\\r\\n');print(s.recv(4096)[-1:].decode(),flush=True);time.sleep(1)\ns.close()"
 held=subprocess.Popen(['ip','netns','exec',names['c'],'python3','-u','-c',client],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);procs.append(held)
 assert held.stdout.readline().strip()=='w'
 run('nft','-f','-',ns='r',input=native.rules({'_mobile_share':100},'lan',True))
 out,err=held.communicate(timeout=5);assert held.returncode==0 and out.strip()=='w',(out,err)
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(4)]
 assert rows==['m']*4,rows
 print('Existing TCP flow stays on Wi-Fi while new connections switch to mobile',flush=True)
 data=json.loads(run('nft','-j','list','table','inet','wds_performance',ns='r'))
 counters={v['counter']['name']:v['counter']['bytes'] for v in data['nftables'] if 'counter' in v}
 assert all(counters.get(k,0)>0 for k in ('wifi_up','wifi_down','mobile_up','mobile_down')),counters
 print('Separate per-uplink acceleration packet counters:',counters,flush=True)
 udp_client="import socket,json\nrows=[]\nfor i in range(8):\n s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(2);pair=[]\n for j in range(2):s.sendto(b'test',('203.0.113.1',int(__import__('sys').argv[1])));pair.append(s.recv(32).decode())\n assert pair[0]==pair[1],pair\n rows.append(pair[0]);s.close()\nprint(json.dumps(rows))"
 for quic in [False,True]:
  run('nft','-f','-',ns='r',input=native.rules({'boost_quic':quic},'lan',True))
  for port in [443,444,47998]:
   rows=json.loads(run('python3','-c',udp_client,str(port),ns='c'))
   assert set(rows)==({'w','m'} if quic and port==443 else {'w'}),(quic,port,rows)
  print('Native UDP 443 enabled:',quic,'other UDP and existing sessions preserved',flush=True)
 data=json.loads(run('nft','-j','list','table','inet','wds_meter',ns='r'));counters={v['counter']['name']:v['counter']['bytes'] for v in data['nftables'] if 'counter' in v}
 assert counters['up']>0 and counters['down']>0,counters
 print('Native mobile accounting:',counters,flush=True)
 run('nft','-f','-',ns='r',input=native.rules({'boost_device_mode':'all'},'lan',False))
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(4)]
 assert rows==['w']*4,rows
 print('Quota/disabled acceleration sends new connections over Wi-Fi:',rows,flush=True)
 run('nft','delete','table','inet','wds_native',ns='r')
 run('nft','-f','-',ns='r',input='table inet fw4 {\n set china_ip_route { type ipv4_addr; flags interval; elements = {203.0.113.1}; }\n set china_ip_route_pass { type ipv4_addr; flags interval; }\n set wds_selected { type ipv4_addr; flags interval; }\n chain wds_balance { type filter hook prerouting priority -140; policy accept; }\n chain wds_quota_guard { type filter hook forward priority -6; policy accept; }\n}\n')
 run('nft','-f','-',ns='r',input=native.rules({'boost_scope':'all_tcp'},'lan',True,'fw4','wds_balance','wds_quota_guard','wds_selected',('ip daddr != @china_ip_route','ip daddr @china_ip_route_pass')))
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(6)]
 assert set(rows)=={'w','m'},rows
 print('OpenClash China-IP bypass uses both uplinks:',rows,flush=True)
 run('nft','add','element','inet','fw4','china_ip_route_pass','{203.0.113.1}',ns='r')
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(4)]
 assert rows==['w']*4,rows
 print('OpenClash bypass exceptions stay unmarked:',rows,flush=True)
 if pathlib.Path('/etc/openclash/clash').exists():
  config=pathlib.Path('/tmp',prefix+'-core.yaml');binary=pathlib.Path('/tmp',prefix+'-core');logpath=pathlib.Path('/tmp',prefix+'-core.log');tempfiles += [config,binary,logpath]
  ruby="require 'yaml';require ARGV[0];d={'mixed-port'=>17941,'external-controller'=>'127.0.0.1:17942','bind-address'=>'127.0.0.1','allow-lan'=>false,'log-level'=>'error','rules'=>['MATCH,DIRECT']};WifiDataBoost.apply(d,{'active'=>true,'quic'=>true,'scope'=>'all_tcp','devices'=>[],'domains'=>[]},{'wifi_device'=>'wifi','mobile_device'=>'cell'});d['proxy-groups'].each{|g|g['url']='http://203.0.113.1:18080' if g['type']=='load-balance'};File.write(ARGV[1],YAML.dump(d))"
  run('ruby','-e',ruby,str(pathlib.Path(native_path).with_name('boost.rb')),str(config))
  shutil.copyfile('/etc/openclash/clash',binary);binary.chmod(0o700)
  core_directory=tempfile.TemporaryDirectory(prefix=prefix+'-')
  with logpath.open('w') as log:
   procs.append(subprocess.Popen(['ip','netns','exec',names['r'],'env','SAFE_PATHS=/tmp:/etc/ssl',str(binary),'-d',core_directory.name,'-f',str(config)],stdout=log,stderr=log))
  for attempt in range(50):
   try:run('curl','--noproxy','*','--max-time','1','-sS','http://127.0.0.1:17942/version',ns='r');break
   except RuntimeError:
    if procs[-1].poll() is not None:raise RuntimeError(logpath.read_text()[-2400:])
    time.sleep(.2)
  else:raise RuntimeError('Isolated core startup timed out: '+logpath.read_text()[-2400:])
  for group,expected in [('BALANCED',8),('WIFI-BIAS',4),('MOBILE-BIAS',12)]:
   run('curl','--noproxy','*','--max-time','3','-sS','-X','PUT','-H','Content-Type: application/json','-d',json.dumps({'name':'WDS-BOOST-'+group}),'http://127.0.0.1:17942/proxies/WDS-BOOST-POOL',ns='r')
   rows=[run('curl','--proxy','http://127.0.0.1:17941','--noproxy','','--max-time','3','-sS','http://203.0.113.1:18080/',ns='r') for _ in range(16)]
   assert rows.count('m')==expected,(group,rows)
   print('Real Mihomo selector',group,rows,flush=True)
  run('curl','--noproxy','*','--max-time','3','-sS','-X','PUT','-H','Content-Type: application/json','-d',json.dumps({'name':'WDS-BOOST-BALANCED'}),'http://127.0.0.1:17942/proxies/WDS-BOOST-POOL',ns='r')
  socks="import socket,struct,json\nrows=[]\nfor i in range(8):\n t=socket.create_connection(('127.0.0.1',17941),timeout=2);t.sendall(b'\\x05\\x01\\x00');assert t.recv(2)==b'\\x05\\x00';t.sendall(b'\\x05\\x03\\x00\\x01'+b'\\x00'*6);r=t.recv(32);assert r[:2]==b'\\x05\\x00',r\n u=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);u.settimeout(3);p=int(__import__('sys').argv[1]);msg=b'\\x00\\x00\\x00\\x01'+socket.inet_aton('203.0.113.1')+struct.pack('!H',p)+b'test';u.sendto(msg,('127.0.0.1',struct.unpack('!H',r[-2:])[0]));rows.append(u.recv(4096)[-1:].decode());u.close();t.close()\nprint(json.dumps(rows))"
  for port in [443,444,47998]:
   rows=json.loads(run('python3','-c',socks,str(port),ns='r'))
   assert set(rows)==({'w','m'} if port==443 else {'w'}),(port,rows)
   print('Real Mihomo UDP path',port,rows,flush=True)
 print('Independent native forwarding test passed without OpenClash',flush=True)
finally:
 for p in procs:p.terminate()
 for p in procs:p.wait(timeout=3)
 for n in reversed(created):subprocess.run(['ip','netns','delete',n],capture_output=True)
 for p in tempfiles:p.unlink(missing_ok=True)
 if core_directory:core_directory.cleanup()
