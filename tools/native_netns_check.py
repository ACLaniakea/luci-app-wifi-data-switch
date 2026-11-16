"""Optional root-only Linux integration test; isolated network namespaces, no production routes changed."""
import subprocess,time,os,importlib.util,json,pathlib,types,sys
base=pathlib.Path(__file__).resolve().parents[1]/"files/usr/libexec/wifi-data-switch"
native_path=sys.argv[1] if len(sys.argv)>1 else str(base/"native.py")
quota_path=sys.argv[2] if len(sys.argv)>2 else str(base/"quota.py")
s=importlib.util.spec_from_file_location('native',native_path);native=importlib.util.module_from_spec(s);s.loader.exec_module(native)
prefix='wd'+str(os.getpid());names={k:prefix+k for k in 'rcwm'};created=[];procs=[]
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
 for mark,table,gw,dev in [('0x5752','202','192.0.2.2','wifi'),('0x5753','201','198.51.100.2','cell')]:
  run('ip','rule','add','fwmark',mark,'lookup',table,ns='r');run('ip','route','add','table',table,'default','via',gw,'dev',dev,ns='r')
 for key in 'wm':
  code="import socket\ns=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('0.0.0.0',18080));s.listen()\nwhile True:\n c,a=s.accept();c.recv(4096);c.sendall(b'HTTP/1.0 200 OK\\r\\nContent-Length: 1\\r\\n\\r\\n'+"+repr(key.encode())+");c.close()"
  procs.append(subprocess.Popen(['ip','netns','exec',names[key],'python3','-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
 time.sleep(1.5)
 run('nft','-f','-',ns='r',input='table inet wds_native {\n set targets { type ipv4_addr; flags interval; elements = {203.0.113.1}; }\n set selected { type ipv4_addr; flags interval; }\n chain balance { type filter hook prerouting priority -140; policy accept; }\n chain quota_guard { type filter hook forward priority -6; policy accept; }\n}\n')
 s=importlib.util.spec_from_file_location('quota',quota_path);quota=importlib.util.module_from_spec(s);s.loader.exec_module(quota)
 def command(args,**kwargs):
  return subprocess.run(['ip','netns','exec',names['r']]+args,capture_output=True,text=True,**kwargs)
 c=types.SimpleNamespace(ROOT=pathlib.Path('/tmp'),command=command,read=lambda *args:{})
 quota.Meter(c).install();quota.enable_forward_meter(c)
 for mode,selected,expected in [('all','',True),('whitelist','10.255.0.2/32',True),('blacklist','10.255.0.2/32',False)]:
  run('nft','-f','-',ns='r',input=native.rules({'boost_device_mode':mode,'boost_devices':selected},'lan',True))
  rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(6)];print(mode,rows,flush=True)
  if set(rows)!=({'w','m'} if expected else {'w'}):raise RuntimeError('Incorrect routing')
 data=json.loads(run('nft','-j','list','table','inet','wds_meter',ns='r'));counters={v['counter']['name']:v['counter']['bytes'] for v in data['nftables'] if 'counter' in v}
 assert counters['up']>0 and counters['down']>0,counters
 print('Native mobile accounting:',counters,flush=True)
 run('nft','-f','-',ns='r',input=native.rules({'boost_device_mode':'all'},'lan',False))
 rows=[run('curl','--noproxy','*','--max-time','3','-sS','http://203.0.113.1:18080/',ns='c') for _ in range(4)]
 assert rows==['w']*4,rows
 print('Quota/disabled acceleration sends new connections over Wi-Fi:',rows,flush=True)
 print('Independent native forwarding test passed without OpenClash',flush=True)
finally:
 for p in procs:p.terminate()
 for p in procs:p.wait(timeout=3)
 for n in reversed(created):subprocess.run(['ip','netns','delete',n],capture_output=True)
