"""Dedicated boost-mobile IPv4 packet accounting, independent of proxy traffic."""
import datetime,json,time

def limits(args):
    out={}
    for key in ('daily_mib','monthly_mib','billing_day','mobile_daily_mib','mobile_monthly_mib'):
        try:value=int(args.get(key,1 if key=='billing_day' else 0))
        except (ValueError,TypeError):raise ValueError('额度和结算日须为整数')
        if not (1<=value<=28 if key=='billing_day' else 0<=value<=100000000):raise ValueError('额度或结算日超出范围')
        out[key]=value
    return out

def periods(now,day):
    d=datetime.datetime.fromtimestamp(now);y,m=d.year,d.month
    if d.day<day:
        m-=1
        if not m:y-=1;m=12
    return d.strftime('%Y-%m-%d'),'%04d-%02d-%02d'%(y,m,day)

def accumulate(state,raw,boot,now,day):
    old=state.get('raw',{})
    delta=sum(raw[k]-old.get(k,0) if state.get('boot')==boot and raw[k]>=old.get(k,0) else raw[k] for k in raw)
    # Keep daily history so changing the billing day cannot erase cycle usage.
    date,_=periods(now,day)
    daily=state.setdefault('days',{});daily[date]=daily.get(date,0)+delta
    state.update(raw=dict(raw),boot=boot,sampled_at=now)
    return state

def summary(state,cfg):
    date,cycle=periods(state.get('sampled_at',time.time()),cfg.get('billing_day',1))
    days=state.get('days',{});out={}
    for name,key,used in [('daily',date,days.get(date,0)),('monthly',cycle,sum(v for k,v in days.items() if cycle<=k<=date))]:
        cap=int(cfg.get(name+'_mib',0))*1048576
        out[name]={'period':key,'used':used,'limit':cap,'warning':bool(cap and used>=cap*.8)}
    out['exceeded']=any(v['limit'] and v['used']>=v['limit'] for v in out.values())
    return out
def network_sample(state,raw,boot,device,now,day):
    # Start with a baseline, never attribute all pre-install interface bytes to today.
    if not state or state.get('device')!=device:
        state.update(raw=dict(raw),boot=boot,device=device,started_at=state.get('started_at',int(now)))
    return accumulate(state,raw,boot,now,day)

def overall_summary(state,cfg,label):
    caps={'billing_day':cfg.get('billing_day',1)}
    if label=='mobile':
        caps.update(daily_mib=cfg.get('mobile_daily_mib',0),monthly_mib=cfg.get('mobile_monthly_mib',0))
    out=summary(state,caps)
    out.update(started_at=state.get('started_at'),ready=True)
    return out

def select_policy(cfg,wifi,mobile,usage,choose):
    if usage.get('mobile_total_exceeded'):return True,True
    return choose(cfg,wifi,mobile)

def guard_script(device):
    return ('table inet wds_mobile_limit {\n chain tx {\n type filter hook output priority -5; policy accept;\n oifname '+json.dumps(device)+' reject with icmpx type admin-prohibited;\n }\n chain transit {\n type filter hook forward priority -5; policy accept;\n oifname '+json.dumps(device)+' reject with icmpx type admin-prohibited;\n }\n}\n')

def mobile_guard(c,device,blocked):
    exists=c.command(['nft','list','table','inet','wds_mobile_limit'],check=False).returncode==0
    if blocked and not exists:c.command(['nft','-f','-'],input=guard_script(device))
    if not blocked and exists:c.command(['nft','delete','table','inet','wds_mobile_limit'])

class Meter:
    def __init__(self,c):self.c=c;self.state=c.read(c.ROOT/'usage.json',{});self.saved=0
    def install(self):
        c=self.c
        if c.command(['nft','list','table','inet','wds_meter'],check=False).returncode==0:return
        script='table inet wds_meter { counter up {} counter down {} chain tx { type filter hook output priority -140; policy accept; meta mark 0x5753 ct mark set ct mark | 0x40000000; meta mark 0x5753 counter name up; } chain rx { type filter hook prerouting priority -140; policy accept; ct direction reply ct mark & 0x40000000 != 0 counter name down; } }'
        script=script.replace('{}','{ }\n').replace(';',';\n').replace('} chain','}\n chain').replace('} }','}\n }')+'\n'
        c.command(['nft','-f','-'],input=script)
    def sample(self,cfg):
        c=self.c;self.install()
        data=json.loads(c.command(['nft','-j','list','table','inet','wds_meter']).stdout)
        raw={'up':0,'down':0}
        for item in data['nftables']:
            v=item.get('counter',{})
            if v.get('name') in raw:raw[v['name']]=int(v['bytes'])
        boot=c.pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        now=time.time();self.state=accumulate(self.state,raw,boot,now,cfg.get('billing_day',1))
        result=summary(self.state,cfg);result.update(ready=True,sampled_at=int(now))
        hw=c.hardware() if hasattr(c,'hardware') else {'wifi_network':'wwan','mobile_network':'wan','wifi_device':'wlan-sta','mobile_device':'sipa_eth0'}
        networks=self.state.setdefault('networks',{});result['networks']={}
        for label in ('wifi','mobile'):
            info=c.iface(hw[label+'_network']);device=info.get('device') or hw[label+'_device']
            netraw={k:int(c.pathlib.Path('/sys/class/net',device,'statistics',v).read_text()) for k,v in [('up','tx_bytes'),('down','rx_bytes')]}
            entry=networks.setdefault(label,{})
            network_sample(entry,netraw,boot,device,now,cfg.get('billing_day',1))
            result['networks'][label]=overall_summary(entry,cfg,label)
        result['acceleration_exceeded']=result['exceeded']
        result['mobile_total_exceeded']=result['networks']['mobile']['exceeded']
        result['exceeded']=bool(result['exceeded'] or result['mobile_total_exceeded'])
        c.write(c.RUN/'usage-status.json',result)
        if now-self.saved>=60:self.flush();self.saved=now
        return result
    def flush(self):self.c.write(self.c.ROOT/'usage.json',self.state)
