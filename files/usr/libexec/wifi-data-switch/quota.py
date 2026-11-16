"""Dedicated boost-mobile IPv4 packet accounting, independent of proxy traffic."""
import datetime,json,time

def limits(args):
    out={}
    for key in ('daily_mib','monthly_mib','billing_day'):
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
        c.write(c.RUN/'usage-status.json',result)
        if now-self.saved>=60:self.flush();self.saved=now
        return result
    def flush(self):self.c.write(self.c.ROOT/'usage.json',self.state)
