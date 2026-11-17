"""Native dnsmasq+nftables balancing; no OpenClash core needed in this mode."""
import contextlib,fcntl,ipaddress,json,pathlib,re,subprocess,sys,time
TABLE='wds_native'
DNS_KEYS=('server','noresolv')

def rules(cfg,lan,enabled,table=TABLE,chain='balance',guard='quota_guard',selected='selected',qualifiers=()):
    prefix='inet '+table+' '
    lines=['flush chain '+prefix+chain,'flush chain '+prefix+guard,'flush set '+prefix+selected]
    if not enabled:lines.append('add rule '+prefix+guard+' meta mark 0x5753 reject with icmpx type admin-prohibited')
    devices=[str(v) for v in ipaddress.collapse_addresses(ipaddress.IPv4Network(v,strict=False) for v in cfg.get('boost_devices','').split())]
    if devices:lines.append('add element '+prefix+selected+' { '+', '.join(devices)+' }')
    base='add rule '+prefix+chain+' '
    lines += [base+'iifname != '+json.dumps(lan)+' return',base+'ct direction reply return',
              base+'ip daddr { 0.0.0.0/8,10.0.0.0/8,100.64.0.0/10,127.0.0.0/8,169.254.0.0/16,172.16.0.0/12,192.168.0.0/16,198.18.0.0/15,224.0.0.0/4,240.0.0.0/4 } return',
              base+'ct mark & 0xffff { 0x5752, 0x5753, 0x5755 } meta mark set ct mark & 0xffff return',
              base+'ct state established,related return']
    if enabled:
        if cfg.get('boost_quic',False):
            lines += [base+'meta l4proto != { tcp, udp } return',base+'meta l4proto udp udp dport != 443 return']
        else:lines += [base+'meta l4proto != tcp return']
        lines += [base+'tcp dport { 22,3389,47984-48010,21115-21119 } return']
        mode=cfg.get('boost_device_mode','whitelist' if devices else 'all')
        if mode=='whitelist':lines.append(base+'ip saddr != @'+selected+' return')
        if mode=='blacklist':lines.append(base+'ip saddr @'+selected+' return')
        lines.extend(base+q+' return' for q in qualifiers)
        if cfg.get('_wifi_direct_domains'):
            lines.append(base+'ip daddr @wds_wifi_direct meta mark set 0x5755 ct mark set (ct mark & 0xffff0000) | meta mark return')
        match='ip daddr @targets ' if cfg.get('boost_scope','all_tcp')=='domains' else 'meta nfproto ipv4 '
        share=cfg.get('_mobile_share',50)
        if share not in (0,25,50,75,100):raise ValueError('Invalid mobile connection share')
        marks=['0x5753' if i < share//25 else '0x5752' for i in range(4)]
        mapping=', '.join(str(i)+' : '+mark for i,mark in enumerate(marks))
        lines += [base+match+'meta mark set numgen inc mod 4 map { '+mapping+' } ct mark set (ct mark & 0xffff0000) | meta mark']
    return '\n'.join(lines)+'\n'

def dns_text(domains):
    return ''.join('nftset=/'+domain+'/4#inet#wds_native#targets\n' for domain in domains)

class Manager:
    def __init__(self,c):self.c=c;self.path=c.ROOT/'native-state.json';self.signature=None;self.bypass_signature=None
    def state(self):return self.c.read(self.path,{})
    @contextlib.contextmanager
    def locked(self):
        with open(self.c.ROOT/'native.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield
    def boot(self):return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    def service(self,action):
        if not pathlib.Path('/etc/init.d/openclash').exists():return False
        return self.c.command(['/etc/init.d/openclash',action],check=False,timeout=50).returncode==0
    def uci(self,key):
        r=self.c.command(['uci','-q','get','dhcp.@dnsmasq[0].'+key],check=False)
        return r.stdout.strip() if r.returncode==0 else None
    def preflight(self):
        c=self.c
        if not re.search(r'(?<!\S)nftset(?!\S)',c.command(['dnsmasq','--version']).stdout):raise ValueError('仅双网加速需要支持 nftset 的 dnsmasq，请先安装对应的 dnsmasq-full。')
        if c.command(['uci','-q','get','firewall.@defaults[0].flow_offloading'],check=False).stdout.strip()=='1':
            raise ValueError('仅双网加速的流量计量需要关闭防火墙流量分载，请先关闭后再应用。')
    def enter(self,cfg,state=None):
        c=self.c
        # Preflight before touching the running proxy or DNS service.
        self.preflight()
        existing=c.command(['nft','list','table','inet',TABLE],check=False).returncode==0
        if existing:c.command(['nft','delete','table','inet',TABLE])
        c.command(['nft','-f','-'],input='table inet wds_native {\n set targets { type ipv4_addr; flags interval; }\n set selected { type ipv4_addr; flags interval; }\n chain balance { type filter hook prerouting priority -140; policy accept; }\n chain quota_guard { type filter hook forward priority -6; policy accept; }\n}\n')
        section=c.command(['uci','-X','show','dhcp'],check=False).stdout
        match=re.search(r'^dhcp\.([^.=]+)=dnsmasq$',section,re.M)
        if not match:raise RuntimeError('dnsmasq instance not found')
        directory=self.uci('confdir') or '/tmp/dnsmasq.'+match[1]+'.d'
        directory=pathlib.Path(directory.split(',')[0])
        if not directory.is_absolute() or '..' in directory.parts:raise RuntimeError('Invalid dnsmasq config directory')
        file=directory/'wifi-data-switch-native.conf'
        prior=c.read(c.RUN/'status.json',{}).get('mode','split')
        running=self.service('status')
        if not state:
            state={'dns':{key:self.uci(key) for key in DNS_KEYS},'openclash_running':running,'openclash_enabled':self.service('enabled'),'prior_mode':prior}
        else:pathlib.Path(state['file']).unlink(missing_ok=True)
        state.update(phase='entering',file=str(file),started=int(time.time()),boot=self.boot())
        c.write(self.path,state)
        subprocess.Popen([sys.executable,c.__file__,'native-watchdog'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        # Do not allow a boot-time OpenClash instance to take over native DNS.
        if state.get('openclash_enabled'):self.service('disable')
        if running:
            if not self.service('stop'):raise RuntimeError('Could not stop OpenClash')
        c.command(['uci','-q','delete','dhcp.@dnsmasq[0].server'],check=False)
        for server in ('223.5.5.5','119.29.29.29'):c.command(['uci','add_list','dhcp.@dnsmasq[0].server='+server])
        c.command(['uci','set','dhcp.@dnsmasq[0].noresolv=1'])
        c.command(['uci','commit','dhcp'])
        domains=cfg.get('boost_domains','').split()
        file.parent.mkdir(parents=True,exist_ok=True);file.write_text(dns_text(domains));file.chmod(0o644)
        state['domains']=domains;c.write(self.path,state)
        c.command(['/etc/init.d/dnsmasq','restart'],timeout=20)
        self.signature=None
    def sync(self,cfg):
        with self.locked():
            if cfg['mode']!='split':self.cleanup_bypass()
            state=self.state()
            if cfg['mode']=='direct':
                table=self.c.command(['nft','list','table','inet',TABLE],check=False).returncode==0
                if not state or state.get('boot')!=self.boot() or not table or not pathlib.Path(state['file']).exists():
                    prior=state.get('prior_mode') or self.c.read(self.c.RUN/'status.json',{}).get('mode','split')
                    if prior=='direct':prior='wifi'
                    try:self.enter(cfg,state or None)
                    except Exception:
                        saved=self.state()
                        self._restore()
                        cfg['mode']=saved.get('prior_mode',prior);self.c.write(self.c.ROOT/'settings.json',cfg)
                        raise
                    return True
                # Recover after an external/manual OpenClash restart as well.
                if self.service('status'):
                    if not self.service('stop'):raise RuntimeError('Could not stop OpenClash')
                    self.c.command(['/etc/init.d/dnsmasq','restart'],timeout=20)
            elif state:self._restore();return True
        return False
    def cleanup_bypass(self):
        if self.c.command(['nft','list','chain','inet','fw4','wds_balance'],check=False).returncode:
            self.bypass_signature=None;return
        self.c.command(['nft','-f','-'],input='delete chain inet fw4 wds_balance\ndelete chain inet fw4 wds_quota_guard\ndelete set inet fw4 wds_selected\n')
        self.bypass_signature=None
    def bypass(self,cfg,wifi,mobile,usage):
        """Balance only IPv4 flows already exempted by OpenClash's China-IP bypass."""
        c=self.c
        if cfg['mode']!='split':return
        chain=c.command(['nft','list','chain','inet','fw4','openclash'],check=False).stdout
        available=any('ip daddr @china_ip_route ip daddr != @china_ip_route_pass' in row and 'return' in row for row in chain.splitlines())
        exists=c.command(['nft','list','chain','inet','fw4','wds_balance'],check=False).returncode==0
        if not available:
            if exists:self.cleanup_bypass()
            return
        if not exists:
            # Stay in fw4 so both China-IP sets refer to the exact sets OpenClash uses.
            c.command(['nft','-f','-'],input='add set inet fw4 wds_selected { type ipv4_addr; flags interval; }\nadd chain inet fw4 wds_balance { type filter hook prerouting priority -140; policy accept; }\nadd chain inet fw4 wds_quota_guard { type filter hook forward priority -6; policy accept; }\n')
            self.bypass_signature=None
        offload=c.command(['uci','-q','get','firewall.@defaults[0].flow_offloading'],check=False).stdout.strip()=='1'
        enabled=bool(not offload and cfg.get('boost_enabled') and cfg.get('boost_scope','all_tcp')=='all_tcp' and wifi and mobile and usage.get('ready') and not usage.get('exceeded'))
        hw=c.hardware() if hasattr(c,'hardware') else {'lan_device':'br-lan'}
        if enabled:
            import quota
            quota.enable_forward_meter(c)
        signature=json.dumps([cfg.get('boost_devices',''),cfg.get('boost_device_mode','all'),cfg.get('_mobile_share',50),cfg.get('boost_quic',False),cfg.get('_wifi_direct_domains',[]),enabled])
        if self.bypass_signature!=signature:
            c.command(['nft','-f','-'],input=rules({**cfg,'boost_scope':'all_tcp'},hw['lan_device'],enabled,'fw4','wds_balance','wds_quota_guard','wds_selected',('ip daddr != @china_ip_route','ip daddr @china_ip_route_pass')))
            self.bypass_signature=signature
    def apply(self,cfg,wifi,mobile,usage):
        with self.locked():return self._apply(cfg,wifi,mobile,usage)
    def _apply(self,cfg,wifi,mobile,usage):
        c=self.c;state=self.state()
        if not state:raise RuntimeError('Native mode not initialized')
        if usage.get('ready'):
            import quota
            quota.enable_forward_meter(c)
        enabled=bool(cfg.get('boost_enabled') and wifi and mobile and usage.get('ready') and not usage.get('exceeded'))
        hw=c.hardware() if hasattr(c,'hardware') else {'lan_device':'br-lan'}
        signature=json.dumps([cfg.get('boost_device_mode','all'),cfg.get('boost_devices',''),cfg.get('boost_domains',''),cfg.get('boost_scope','all_tcp'),cfg.get('_mobile_share',50),cfg.get('boost_quic',False),cfg.get('_wifi_direct_domains',[]),enabled])
        if signature!=self.signature:
            c.command(['nft','-f','-'],input=rules(cfg,hw['lan_device'],enabled))
            domains=cfg.get('boost_domains','').split()
            if domains!=state.get('domains'):
                c.command(['nft','flush','set','inet',TABLE,'targets'])
                file=pathlib.Path(state['file']);file.write_text(dns_text(domains));file.chmod(0o644)
                state['domains']=domains;c.command(['/etc/init.d/dnsmasq','restart'],timeout=20)
            self.signature=signature
        if state.get('phase')!='active' and usage.get('ready') and (wifi or mobile):
            state['phase']='active'
        if state!=self.state():c.write(self.path,state)
        return True

    def restore(self):
        with self.locked():self._restore()
    def _restore(self):
        c=self.c;state=self.state()
        if not state:return
        pathlib.Path(state['file']).unlink(missing_ok=True)
        c.command(['nft','delete','table','inet',TABLE],check=False)
        for key,value in state['dns'].items():
            c.command(['uci','-q','delete','dhcp.@dnsmasq[0].'+key],check=False)
            if value is not None:
                if key=='server':
                    for server in value.split():c.command(['uci','add_list','dhcp.@dnsmasq[0].server='+server])
                else:c.command(['uci','set','dhcp.@dnsmasq[0].'+key+'='+value])
        c.command(['uci','commit','dhcp'])
        if state.get('openclash_enabled'):self.service('enable')
        if state.get('openclash_running') and not self.service('start'):raise RuntimeError('Could not restart OpenClash')
        c.command(['/etc/init.d/dnsmasq','restart'],timeout=20)
        self.path.unlink(missing_ok=True)
        (c.RUN/'binding-signature').unlink(missing_ok=True)
        self.signature=None

def watchdog(c):
    time.sleep(120)
    manager=Manager(c)
    with manager.locked():
        state=manager.state()
        if state.get('phase')=='entering' and time.time()-state.get('started',0)>=115:
            manager._restore();cfg=c.config();cfg['mode']=state.get('prior_mode','split');c.write(c.ROOT/'settings.json',cfg)
