"""Optional DIRECT-domain preference, shared by core and native forwarding paths."""
import concurrent.futures
import ipaddress
import pathlib
import re
import socket
import time

SET='wds_wifi_direct'

def policy(raw):
    def hosts(key):
        values=raw.get(key,[])
        if not isinstance(values,list) or len(values)>64:raise ValueError('Invalid Wi-Fi domain policy')
        out=[]
        for value in values:
            if not isinstance(value,str) or len(value)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',value):
                raise ValueError('Invalid Wi-Fi domain')
            out.append(value.lower())
        return list(dict.fromkeys(out))
    domains=hosts('domains');seeds=hosts('seed_hosts')
    if any(not any(host==d or host.endswith('.'+d) for d in domains) for host in seeds):
        raise ValueError('Seed hostname is outside policy domains')
    addresses=[]
    for value in raw.get('initial_ips',[]):
        ip=ipaddress.IPv4Address(value)
        if not ip.is_global:raise ValueError('Only public seed addresses are supported')
        addresses.append(str(ip))
    return domains,seeds,addresses

def dns_text(domains,table):
    return 'nftset=/'+('/'.join(domains))+'/4#inet#'+table+'#'+SET+'\n'

def resolve(hosts):
    addresses=set()
    for host in hosts:
        try:addresses.update(v[4][0] for v in socket.getaddrinfo(host,443,socket.AF_INET,socket.SOCK_STREAM))
        except OSError:pass
    return sorted(v for v in addresses if ipaddress.IPv4Address(v).is_global)

class Manager:
    def __init__(self,c):
        self.c=c;self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.pending=None;self.last_seed=0;self.signature=None;self.directory=None

    def config_file(self):
        if self.directory is None:
            value=self.c.command(['uci','-q','get','dhcp.@dnsmasq[0].confdir'],check=False).stdout.strip()
            if not value:
                text=self.c.command(['uci','-X','show','dhcp']).stdout
                match=re.search(r'^dhcp\.([^.=]+)=dnsmasq$',text,re.M)
                if not match:raise RuntimeError('dnsmasq instance not found')
                value='/tmp/dnsmasq.'+match[1]+'.d'
            self.directory=pathlib.Path(value.split(',')[0])
            if not self.directory.is_absolute() or '..' in self.directory.parts:raise ValueError('Invalid DNS directory')
        return self.directory/'wifi-data-switch-prefer.conf'

    def sync(self,cfg,wifi):
        try:return self._sync(cfg,wifi)
        except Exception as error:
            self.c.write(self.c.RUN/'wifi-direct-status.json',{'ready':False,'error':type(error).__name__})
            return []

    def _sync(self,cfg,wifi):
        c=self.c
        domains,seeds,initial=policy(c.read(c.ROOT/'wifi-direct.json',{}))
        table='fw4' if cfg['mode']=='split' else 'wds_native' if cfg['mode']=='direct' else None
        if not domains:
            files=list(pathlib.Path('/tmp').glob('dnsmasq.*.d/wifi-data-switch-prefer.conf'))
            if self.directory:files.append(self.directory/'wifi-data-switch-prefer.conf')
            changed=False
            for file in set(files):
                if file.is_file():file.unlink();changed=True
            if changed:c.command(['/etc/init.d/dnsmasq','restart'],timeout=20)
            self.signature=None
            return []
        if table is None or not wifi or not cfg.get('boost_enabled'):
            return []
        exists=c.command(['nft','list','set','inet',table,SET],check=False).returncode==0
        if not exists:
            c.command(['nft','-f','-'],input='add set inet '+table+' '+SET+' { type ipv4_addr; flags timeout; timeout 2h; }\n')
            self.signature=None
        signature=(tuple(domains),tuple(seeds),tuple(initial),table)
        if self.signature!=signature:
            file=self.config_file();text=dns_text(domains,table)
            old=file.read_text() if file.exists() else None
            if old!=text:
                file.parent.mkdir(parents=True,exist_ok=True)
                stage=file.with_suffix('.new');stage.write_text(text);stage.chmod(0o644);stage.replace(file)
                try:c.command(['/etc/init.d/dnsmasq','restart'],timeout=20)
                except Exception:
                    if old is None:file.unlink(missing_ok=True)
                    else:file.write_text(old)
                    c.command(['/etc/init.d/dnsmasq','restart'],check=False,timeout=20)
                    raise
            if initial:c.command(['nft','add','element','inet',table,SET,'{ '+', '.join(initial)+' }'])
            self.signature=signature;self.last_seed=0
        if self.pending and self.pending[1].done():
            addresses=self.pending[1].result() if self.pending[0]==signature else [];self.pending=None
            if addresses:c.command(['nft','add','element','inet',table,SET,'{ '+', '.join(addresses)+' }'])
        if seeds and self.pending is None and time.monotonic()-self.last_seed>=300:
            self.pending=(signature,self.pool.submit(resolve,seeds));self.last_seed=time.monotonic()
        c.write(c.RUN/'wifi-direct-status.json',{'ready':True,'domains':domains,'table':table})
        return domains

    def close(self):self.pool.shutdown(wait=False,cancel_futures=True)
