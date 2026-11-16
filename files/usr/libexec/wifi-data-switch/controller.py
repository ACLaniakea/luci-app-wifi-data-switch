#!/usr/bin/python3
"""Dual-uplink supervisor and restricted LuCI RPC backend.

No default route, modem attach state, LAN address or DHCP topology is changed.
Health-gated policy rules select Wi-Fi for DIRECT and bind proxy nodes to the
other uplink. Wi-Fi keys stay in UCI and are never passed in process arguments.
"""
import lan_devices
import hashlib
import native
import quota
import fcntl
import ipaddress
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time

ROOT=pathlib.Path('/etc/wifi-data-switch')
RUN=pathlib.Path('/var/run/wifi-data-switch')
BASE=pathlib.Path('/usr/libexec/wifi-data-switch')
MARK_CELL='0x5751'
MARK_WIFI='0x5752'
def command(args,check=True,timeout=12,input=None):
    return subprocess.run(args,input=input,capture_output=True,text=True,timeout=timeout,check=check)
def ensure_dirs():
    for path in (ROOT,RUN):path.mkdir(mode=0o700,parents=True,exist_ok=True);path.chmod(0o700)
def read(path,default):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default
def write(path,value):
    ensure_dirs();tmp=path.with_suffix('.new');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def config():
    return read(ROOT/'settings.json',{'mode':'mobile','failover':True,'ssid':'','encryption':'none'})
def hardware():
    defaults={'wifi_network':'wwan','mobile_network':'wan','lan_network':'lan',
              'wifi_device':'wlan-sta','mobile_device':'sipa_eth0','lan_device':'br-lan',
              'radio':'radio0','station':'uplink','clash_mark':'0x162','restart_services':[]}
    defaults.update(read(ROOT/'hardware.json',{}))
    for key in ('wifi_network','mobile_network','lan_network','wifi_device','mobile_device','lan_device','radio','station'):
        if not isinstance(defaults[key],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}',defaults[key]):
            raise ValueError('Invalid hardware interface name: '+key)
    if not re.fullmatch(r'0x[0-9a-fA-F]{1,8}',defaults['clash_mark']):raise ValueError('Invalid Clash routing mark')
    if not isinstance(defaults['restart_services'],list) or any(not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',v) for v in defaults['restart_services']):
        raise ValueError('Invalid restart service list')
    return defaults
def health_sample(state,success,link_up=True):
    state['good']=state['good']+1 if success else 0
    state['bad']=0 if success else state['bad']+1
    if state['good']>=2:state['online']=True
    if state['bad']>=3 or not link_up:state['online']=False
def choose_uplinks(cfg,wifi_online,mobile_online):
    fallback=cfg.get('failover',True)
    if not fallback:return cfg['mode'] in ('split','wifi','direct'),cfg['mode']=='wifi'
    direct_wifi=wifi_online and (cfg['mode'] in ('split','wifi','direct') or fallback and not mobile_online)
    proxy_wifi=wifi_online and (cfg['mode']=='wifi' or fallback and not mobile_online)
    return bool(direct_wifi),bool(proxy_wifi)
def ubus(name):
    try:return json.loads(command(['ubus','call',name,'status'],timeout=4).stdout)
    except (subprocess.SubprocessError,ValueError):return {}
def iface(name):
    s=ubus('network.interface.'+name)
    return {'up':bool(s.get('up')),'device':s.get('l3_device',''),'addresses':[v['address'] for v in s.get('ipv4-address',[])],'gateway':next((r.get('nexthop','') for r in s.get('route',[]) if r.get('target')=='0.0.0.0'),''),'dns':s.get('inactive',{}).get('dns-server',[]) or s.get('dns-server',[])}
def probe(device):
    if not device or not pathlib.Path('/sys/class/net',device).exists():return False
    # No redirect following: a captive portal is never accepted as Internet.
    for url in ['http://connectivitycheck.platform.hicloud.com/generate_204','http://connectivitycheck.gstatic.com/generate_204']:
        try:
            r=command(['curl','--interface',device,'--noproxy','*','--connect-timeout','2','--max-time','4','--silent','--output','/dev/null','--write-out','%{http_code}',url],check=False,timeout=5)
            if r.returncode==0 and r.stdout.strip()=='204':return True
        except subprocess.SubprocessError:pass
    return False
def rule(priority,args,enabled=True,family='-4'):
    rows=command(['ip',family,'rule','show'],check=False).stdout.splitlines()
    exists=any(r.startswith(str(priority)+':') for r in rows)
    if enabled and not exists:command(['ip',family,'rule','add','priority',str(priority)]+args)
    if not enabled and exists:command(['ip',family,'rule','del','priority',str(priority)],check=False)
def setup_routes(wifi,cell,active):
    if cell['up'] and cell['device']:
        route=['ip','-4','route','replace','table','201','default']
        if cell['gateway']:route+=['via',str(ipaddress.IPv4Address(cell['gateway']))]
        command(route+['dev',cell['device']])
        rule(10510,['fwmark',MARK_CELL,'lookup','201'])
        rule(10511,['oif',cell['device'],'lookup','201'])
        # Preserve already established local mobile connections during rollout.
        if cell['addresses']:
            rule(10512,[],False)
            rule(10512,['from',str(ipaddress.IPv4Address(cell['addresses'][0]))+'/32','lookup','201'])
    if wifi['up'] and wifi['gateway'] and wifi['device']:
        ipaddress.IPv4Address(wifi['gateway'])
        command(['ip','-4','route','replace','table','202','default','via',wifi['gateway'],'dev',wifi['device'],'onlink'])
        lan=ubus('network.interface.'+hardware()['lan_network'])
        subnets={str(ipaddress.IPv4Network((v['address'],v['mask']),strict=False)) for v in lan.get('ipv4-address',[])}
        subnets.update(['127.0.0.0/8','100.64.0.0/10'])
        for subnet in sorted(subnets):
            command(['ip','-4','route','replace','table','202','throw',subnet])
        rule(10520,['fwmark',MARK_WIFI,'lookup','202'])
        rule(10521,['oif',wifi['device'],'lookup','202'])
    # Keep OpenClash TPROXY packets on their own routing table.
    rule(10513,['fwmark','0x5753','lookup','201'])
    rule(31020,['not','fwmark',hardware()['clash_mark'],'lookup','202'],active)
    has_table=command(['nft','list','table','inet','wifi_data_switch'],check=False).returncode==0
    if active and not has_table:
        hw=hardware()
        script='table inet wifi_data_switch {\n chain ipv6_guard {\n type filter hook forward priority -5; policy accept;\n iifname '+json.dumps(hw['lan_device'])+' oifname '+json.dumps(hw['mobile_device'])+' meta nfproto ipv6 reject with icmpv6 type no-route;\n }\n}\n'
        command(['nft','-f','-'],input=script)
    if not active and has_table:command(['nft','delete','table','inet','wifi_data_switch'],check=False)
def active_clash():
    p=command(['pidof','clash'],check=False).stdout.split()
    if not p:return None
    argv=pathlib.Path('/proc',p[0],'cmdline').read_bytes().decode().split('\0')
    return pathlib.Path(argv[argv.index('-f')+1])
def clash_info(path):
    # Return only the selected YAML scalars; never log the controller secret.
    script="require 'yaml'; d=YAML.load_file(ARGV[0], aliases:true); puts d['external-controller']; puts d['secret']; puts(d['mixed-port'] || 7893); puts((d['authentication'] || [])[0])"
    values=command(['ruby','-e',script,str(path)]).stdout.splitlines()
    values+=['']*4
    return values[:4]
def acceleration(args):
    enabled=str(args.get('boost_enabled',False)).lower() in ('true','1','yes','on')
    requested=args.get('boost_strategy','round-robin')
    strategy='round-robin'
    if requested not in ('sticky-sessions','round-robin'):raise ValueError('无效加速策略')
    def entries(name):
        value=args.get(name,'')
        if not isinstance(value,str) or len(value)>8192:raise ValueError('加速范围格式不正确')
        return list(dict.fromkeys(v for v in re.split(r'[\s,]+',value.strip()) if v))
    devices=entries('boost_devices');domains=entries('boost_domains')
    mode=args.get('boost_device_mode','whitelist' if devices else 'all')
    if mode not in ('all','whitelist','blacklist'):raise ValueError('无效设备范围')
    for v in devices:ipaddress.IPv4Network(v,strict=False)
    for v in domains:
        if len(v)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',v):raise ValueError('域名格式不正确')
    if enabled and not domains:raise ValueError('开启加速前请填写下载域名')
    if enabled and mode=='whitelist' and not devices:raise ValueError('请选择至少一台加速设备')
    return {'boost_enabled':enabled,'boost_strategy':strategy,'boost_device_mode':mode,'boost_devices':'\n'.join(devices),'boost_domains':'\n'.join(v.lower() for v in domains)}
def boost_runtime(cfg,wifi,mobile):
    enabled=cfg.get('boost_enabled',False)
    return {'enabled':enabled,'active':bool(enabled and cfg['mode'] in ('split','direct') and wifi and mobile),
            'strategy':'round-robin','device_mode':cfg.get('boost_device_mode','whitelist' if cfg.get('boost_devices') else 'all'),'devices':cfg.get('boost_devices','').split(),'domains':cfg.get('boost_domains','').split()}
def bind_clash(device):
    ensure_dirs();path=active_clash()
    if path is None:return False
    old=(RUN/'proxy-interface').read_text().strip() if (RUN/'proxy-interface').exists() else None
    signature=hashlib.sha256((device+json.dumps(read(RUN/'boost.json',{}),sort_keys=True)).encode()).hexdigest()
    if old==device and (RUN/'clash-ready').exists() and (RUN/'binding-signature').exists() and (RUN/'binding-signature').read_text()==signature:return True
    (RUN/'proxy-interface').write_text(device+'\n');(RUN/'proxy-interface').chmod(0o600)
    backup=ROOT/'clash-before-binding.yaml'
    if not backup.exists():
        backup.write_bytes(path.read_bytes());backup.chmod(0o600)
    previous=path.read_bytes();stage='overlay'
    try:
        command(['ruby',str(BASE/'overlay.rb'),str(path)])
        argv=pathlib.Path('/proc',command(['pidof','clash']).stdout.split()[0],'cmdline').read_bytes().decode().split('\0')
        directory=argv[argv.index('-d')+1] if '-d' in argv else '/etc/openclash'
        stage='validation'
        test=command(['env','SAFE_PATHS=/usr/share/openclash:/etc/ssl','/etc/openclash/clash','-t','-d',directory,'-f',str(path)],check=False,timeout=40)
        if test.returncode:raise RuntimeError('Clash configuration validation failed')
        controller,secret,*_=clash_info(path);port=int(controller.rsplit(':',1)[-1])
        # The bearer token is only passed on stdin, never in argv or logs.
        stage='reload'
        spec='url = '+json.dumps('http://127.0.0.1:'+str(port)+'/configs?force=true')+'\nrequest = "PUT"\nheader = '+json.dumps('Authorization: Bearer '+secret)+'\nheader = "Content-Type: application/json"\ndata = '+json.dumps(json.dumps({'path':str(path)}))+'\nsilent\nshow-error\nmax-time = 20\nwrite-out = "%{http_code}"\n'
        r=command(['curl','--noproxy','*','--config','-'],input=spec,timeout=23)
        if not r.stdout.endswith(('204','200')):raise RuntimeError('Clash reload failed')
        (RUN/'binding-signature').write_text(signature);(RUN/'clash-ready').touch();(RUN/'clash-error.json').unlink(missing_ok=True);return True
    except Exception as error:
        path.write_bytes(previous);path.chmod(0o600)
        if old:(RUN/'proxy-interface').write_text(old+'\n')
        (RUN/'clash-ready').unlink(missing_ok=True)
        write(RUN/'clash-error.json',{'stage':stage,'type':type(error).__name__,'time':int(time.time())})
        return False
def status():
    s=read(RUN/'status.json',{'ready':False,'direct':'mobile','proxy':'mobile'});cfg=config();hw=hardware()
    pending=read(ROOT/'pending.json',None)
    s['pending']=pending is not None
    s['settings']={k:v for k,v in (pending if pending is not None else cfg).items() if k not in ('password','wifi_key')}
    wifi=iface(hw['wifi_network']);s['wifi']=wifi;s['mobile']=iface(hw['mobile_network'])
    try:
        link=command(['iw','dev',hw['wifi_device'],'link'],check=False,timeout=3).stdout
        for name,pattern in [('ssid',r'SSID: (.+)'),('signal',r'signal: (-?\d+)'),('frequency',r'freq: (\d+)'),('tx_bitrate',r'tx bitrate: (.+)'),('rx_bitrate',r'rx bitrate: (.+)')]:
            m=re.search(pattern,link)
            if m:wifi[name]=m[1].strip()
    except subprocess.SubprocessError:pass
    for info in [wifi,s['mobile']]:
        try:info['counters']={k:int(pathlib.Path('/sys/class/net',info['device'],'statistics',k).read_text()) for k in ['rx_bytes','tx_bytes']}
        except (KeyError,OSError,ValueError):info['counters']={}
    s['last_error']=read(RUN/'error.json',{})
    s['recommended_domains']=lan_devices.RECOMMENDED_DOMAINS
    s['download_groups']=lan_devices.DOWNLOAD_GROUPS
    s['usage']=read(RUN/'usage-status.json',{})
    s['boost']=read(RUN/'boost.json',{'active':False})
    s['last_switch']=read(RUN/'last-switch.json',{})
    return s
def configure(args,apply=False):
    hw=hardware();station='wireless.'+hw['station'];radio='wireless.'+hw['radio']
    cfg=config();mode=args.get('mode',cfg['mode']);ssid=args.get('ssid',cfg['ssid']);enc=args.get('encryption',cfg['encryption']);band=args.get('band',cfg.get('band','5g'))
    if mode not in ('split','mobile','wifi','direct') or enc not in ('none','psk2','sae','sae-mixed'):raise ValueError('无效模式或加密方式。')
    if band not in ('2g','5g'):raise ValueError('无效无线频段。')
    if not isinstance(ssid,str) or not 1<=len(ssid.encode())<=32 or '\x00' in ssid:raise ValueError('Wi-Fi 名称长度须为1–32字节。')
    key=args.get('wifi_key','')
    if not isinstance(key,str) or any(c in key for c in ('\n','\r','\x00')):raise ValueError('Wi-Fi 密码不能包含换行或空字符。')
    if key and not(8<=len(key)<=63 or len(key)==64 and re.fullmatch('[0-9a-fA-F]+',key)):raise ValueError('Wi-Fi 密码长度不正确。')
    boost=acceleration(args);boost.update(quota.limits(args))
    if not apply:
        draft={**cfg,**args,**boost}
        draft['failover']=str(args.get('failover',cfg.get('failover',True))).lower() in ('true','1','yes','on')
        write(ROOT/'pending.json',draft)
        return {'ok':True,'message':'已保存，尚未生效。点击应用已保存设置后生效。'}
    if mode=='direct':native.Manager(sys.modules[__name__]).preflight()
    oldssid=command(['uci','-q','get',station+'.ssid'],check=False).stdout.strip();oldenc=command(['uci','-q','get',station+'.encryption'],check=False).stdout.strip()
    if enc!='none' and not key and not command(['uci','-q','get',station+'.key'],check=False).stdout.strip():raise ValueError('请填写无线密码。')
    oldband=command(['uci','-q','get',radio+'.band'],check=False).stdout.strip()
    changed=ssid!=oldssid or enc!=oldenc or bool(key) or band!=oldband
    if changed:
        for k,v in [('ssid',ssid),('encryption',enc)]:command(['uci','set',station+'.'+k+'='+v])
        command(['uci','set',radio+'.band='+band])
        command(['uci','set',radio+'.htmode='+('HT20' if band=='2g' else 'VHT80')])
        if key:
            # UCI accepts a batch on stdin; do not expose Wi-Fi keys in argv.
            escaped=key.replace('\\','\\\\').replace("'","'\\''")
            command(['uci','batch'],input="set "+station+".key='"+escaped+"'\n")
        elif enc=='none':command(['uci','-q','delete',station+'.key'],check=False)
        command(['uci','commit','wireless']);os.chmod('/etc/config/wireless',0o600)
        subprocess.Popen(['/sbin/wifi','reload',hw['radio']],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    flag=lambda k,default: str(args.get(k,default)).lower() in ('1','true','on','yes')
    cfg.update({'mode':mode,'ssid':ssid,'encryption':enc,'band':band,'failover':flag('failover',True)})
    cfg.update(boost)
    write(ROOT/'settings.json',cfg)
    return {'ok':True,'message':'设置已保存，将在下一次检测时应用。'}
def daemon():
    ensure_dirs();lock=open(RUN/'daemon.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    scores={'wifi':{'good':0,'bad':0,'online':False},'mobile':{'good':0,'bad':0,'online':False}}
    native_manager=native.Manager(sys.modules[__name__])
    meter=quota.Meter(sys.modules[__name__])
    running=True;last_selection=None
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while running:
            try:
                cfg=config();changed=native_manager.sync(cfg)
                if changed:scores={'wifi':{'good':0,'bad':0,'online':False},'mobile':{'good':0,'bad':0,'online':False}}
                hw=hardware();wifi=iface(hw['wifi_network']);cell=iface(hw['mobile_network'])
                setup_routes(wifi,cell,False if not read(RUN/'status.json',{}).get('wifi_direct') else True)
                for label,info in [('mobile',cell),('wifi',wifi)]:
                    success=bool(info['up'] and probe(info['device']));s=scores[label]
                    health_sample(s,success,info['up'])
                w=scores['wifi']['online'];c=scores['mobile']['online']
                try:
                    usage=meter.sample(cfg)
                except Exception:
                    usage={'ready':False,'exceeded':True,'mobile_total_exceeded':read(RUN/'usage-status.json',{}).get('mobile_total_exceeded',False)}
                    write(RUN/'usage-status.json',usage)
                total_blocked=bool(usage.get('mobile_total_exceeded'))
                quota.mobile_guard(sys.modules[__name__],hw['mobile_device'],total_blocked)
                direct_wifi,proxy_wifi=quota.select_policy(cfg,w,c,usage,choose_uplinks)
                device=hw['wifi_device'] if proxy_wifi else hw['mobile_device']
                boost=boost_runtime(cfg,w,c)
                boost['reason']='加速已关闭' if not boost['enabled'] else ('请切换至分流或仅双网加速模式' if cfg['mode'] not in ('split','direct') else ('等待两条出口联网' if not (w and c) else ('流量统计未就绪，暂停加速' if not usage['ready'] else ('已达到移动总流量额度' if usage.get('mobile_total_exceeded') else '已达到加速流量额度' if usage['exceeded'] else '双网加速已就绪'))))
                boost['active']=bool(boost['active'] and usage['ready'] and not usage['exceeded'])
                if read(RUN/'boost.json',{})!=boost:write(RUN/'boost.json',boost)
                clash_ok=native_manager.apply(cfg,w,c,usage) if cfg['mode']=='direct' else bind_clash(device)
                # Never send DIRECT to Wi-Fi before proxy binding is confirmed.
                use_wifi=bool(total_blocked or direct_wifi and clash_ok)
                setup_routes(wifi,cell,use_wifi)
                selection=('wifi' if use_wifi else 'mobile','none' if cfg['mode']=='direct' else ('wifi' if total_blocked or proxy_wifi and clash_ok else 'mobile'))
                if selection!=last_selection:
                    command(['logger','-t','wifi-data-switch','direct='+selection[0]+' proxy='+selection[1]],check=False)
                    write(RUN/'last-switch.json',{'time':int(time.time()),'direct':selection[0],'proxy':selection[1]})
                    if last_selection is not None and selection[0]!=last_selection[0]:
                        for name in hw['restart_services']:
                            service=pathlib.Path('/etc/init.d',name)
                            if service.exists() and command([str(service),'enabled'],check=False).returncode==0:
                                subprocess.Popen([str(service),'restart'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                    last_selection=selection
                write(RUN/'status.json',{'ready':True,'time':int(time.time()),'wifi_direct':use_wifi,'direct':selection[0],'proxy':selection[1],'health':scores,'clash_bound':clash_ok,'mode':cfg['mode'],'native_mode':cfg['mode']=='direct','mobile_blocked':total_blocked,'quota_wifi_only':total_blocked})
                (RUN/'error.json').unlink(missing_ok=True)
            except Exception as error:
                rule(31020,[],False)
                write(RUN/'error.json',{'time':int(time.time()),'error_type':type(error).__name__})
                command(['logger','-t','wifi-data-switch','supervisor error: '+type(error).__name__],check=False)
            for _ in range(10):
                if not running:break
                time.sleep(1)
    finally:
        if native_manager.state():native_manager.restore()
        meter.flush()
        blocked=read(RUN/'usage-status.json',{}).get('mobile_total_exceeded',False)
        if not blocked:
            quota.mobile_guard(sys.modules[__name__],hardware()['mobile_device'],False)
            rule(31020,[],False)
        command(['nft','delete','table','inet','wifi_data_switch'],check=False)
        # Keep explicit bound-uplink routes for already established sockets.
        write(RUN/'status.json',{'ready':False,'direct':'wifi' if blocked else 'mobile','proxy':'wifi' if blocked else 'mobile','wifi_direct':bool(blocked),'mobile_blocked':bool(blocked)})
METHODS={'status':{},'configure':{'mode':'String','ssid':'String','encryption':'String','wifi_key':'String','failover':'String','band':'String','boost_enabled':'String','boost_strategy':'String','boost_devices':'String','boost_domains':'String','daily_mib':'String','monthly_mib':'String','billing_day':'String','mobile_daily_mib':'String','mobile_monthly_mib':'String','boost_device_mode':'String'},'scan':{},'devices':{},'apply':{}}
def main():
    ensure_dirs()
    if len(sys.argv)>1 and sys.argv[1]=='native-watchdog':native.watchdog(sys.modules[__name__]);return
    if len(sys.argv)>1 and sys.argv[1]=='daemon':daemon();return
    if len(sys.argv)>1 and sys.argv[1]=='list':print(json.dumps(METHODS));return
    method=sys.argv[2] if len(sys.argv)>2 and sys.argv[1]=='call' else 'status'
    args=json.load(sys.stdin) if method not in ('status',) else {}
    if method=='status':result=status()
    elif method=='configure':result=configure(args)
    elif method=='apply':
        draft=read(ROOT/'pending.json',None)
        if draft is None:result={'ok':True,'message':'没有待应用的设置。'}
        else:
            result=configure(draft,apply=True)
            (ROOT/'pending.json').unlink(missing_ok=True)
    elif method=='devices':result=lan_devices.devices(sys.modules[__name__])
    elif method=='scan':
        result=json.loads(command(['ubus','call','iwinfo','scan',json.dumps({'device':hardware()['wifi_device']})],timeout=20).stdout)
    else:raise ValueError('Unknown method')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    try:
        main()
    except Exception as e:print(json.dumps({'ok':False,'message':str(e) if isinstance(e,ValueError) else '操作未完成：'+type(e).__name__},ensure_ascii=False));sys.exit(1)
