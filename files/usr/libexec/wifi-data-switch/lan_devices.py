"""Passive LAN inventory; lease/cache presence is not proof of being online."""
import ipaddress,time
DOWNLOAD_GROUPS={
 'Windows 更新':['download.windowsupdate.com','dl.delivery.mp.microsoft.com'],
 '开源软件镜像':['mirrors.tuna.tsinghua.edu.cn','mirrors.ustc.edu.cn'],
 'Steam 游戏下载':['steamcontent.com'],
 'Epic 游戏下载':['download.epicgames.com','download2.epicgames.com','download3.epicgames.com','download4.epicgames.com','epicgames-download1.akamaized.net'],
 '米哈游国服更新':['autopatchcn.yuanshen.com','autopatchcn.bhsr.com','autopatchcn.juequling.com','autopatchcn.bh3.com'],
 'HoYoverse 国际服更新':['autopatchhk.yuanshen.com','autopatchos.starrails.com','autopatchos.zenlesszonezero.com','autopatchglb.honkaiimpact3.com','autopatchjp.honkaiimpact3.com','autopatchkr.honkaiimpact3.com','autopatchos.honkaiimpact3.com','autopatchasia.honkaiimpact3.com']
}
DOWNLOAD_GROUPS={'Windows 更新': ['download.windowsupdate.com', 'dl.delivery.mp.microsoft.com'], '开源镜像': ['mirrors.tuna.tsinghua.edu.cn', 'mirrors.ustc.edu.cn'], 'Steam 下载': ['steamcontent.com'], 'Epic 下载': ['download.epicgames.com', 'download2.epicgames.com', 'download3.epicgames.com', 'download4.epicgames.com', 'epicgames-download1.akamaized.net'], '米哈游国服': ['autopatchcn.yuanshen.com', 'autopatchcn.bhsr.com', 'autopatchcn.juequling.com', 'autopatchcn.bh3.com'], '米哈游国际服': ['autopatchhk.yuanshen.com', 'autopatchos.starrails.com', 'autopatchos.zenlesszonezero.com', 'autopatchglb.honkaiimpact3.com', 'autopatchjp.honkaiimpact3.com', 'autopatchkr.honkaiimpact3.com', 'autopatchos.honkaiimpact3.com', 'autopatchasia.honkaiimpact3.com']}
RECOMMENDED_DOMAINS=[domain for domains in DOWNLOAD_GROUPS.values() for domain in domains]

def collect(neighbors,leases,now):
    rows={}
    for line in leases.splitlines():
        parts=line.split()
        if len(parts)<4:continue
        expiry,mac,ip,name=parts[:4]
        try:
            ipaddress.IPv4Address(ip)
            if int(expiry) and int(expiry)<now:continue
        except ValueError:continue
        rows[ip]={'ip':ip,'mac':mac,'name':name if name!='*' else '', 'state':'lease'}
    for line in neighbors.splitlines():
        parts=line.split()
        if not parts:continue
        try:ipaddress.IPv4Address(parts[0])
        except ValueError:continue
        if parts[-1] in ('FAILED','INCOMPLETE'):continue
        ip=parts[0];entry=rows.setdefault(ip,{'ip':ip,'mac':'','name':''})
        if 'lladdr' in parts:entry['mac']=parts[parts.index('lladdr')+1]
        entry['state']='recent' if parts[-1] in ('REACHABLE','DELAY','PROBE') else 'cache'
    return sorted(rows.values(),key=lambda v:ipaddress.IPv4Address(v['ip']))
def devices(c):
    hw=c.hardware() if hasattr(c,'hardware') else {'lan_device':'br-lan'}
    neighbors=c.command(['ip','-4','neigh','show','dev',hw['lan_device']],check=False).stdout
    path=c.pathlib.Path('/tmp/dhcp.leases')
    return {'devices':collect(neighbors,path.read_text() if path.exists() else '',time.time())}
