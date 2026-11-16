"""Passive LAN inventory; lease/cache presence is not proof of being online."""
import ipaddress,time
DOWNLOAD_GROUPS={
 '系统与浏览器更新':['download.windowsupdate.com','dl.delivery.mp.microsoft.com','download.microsoft.com','officecdn.microsoft.com','officecdn.microsoft.com.edgesuite.net','dl.google.com','edgedl.me.gvt1.com'],
 '软件与开发工具':['download.jetbrains.com','download-cdn.jetbrains.com','vscode.download.prss.microsoft.com','release-assets.githubusercontent.com','objects.githubusercontent.com','codeload.github.com','registry.npmjs.org','files.pythonhosted.org'],
 '开源镜像':['mirrors.tuna.tsinghua.edu.cn','mirrors.ustc.edu.cn','mirrors.aliyun.com','mirrors.cloud.tencent.com','mirrors.huaweicloud.com','dlcdn.apache.org'],
 'Steam 下载':['steamcontent.com','steamserver.net','client-download.steampowered.com','cdn.cloudflare.steamstatic.com'],
 'Epic 下载':['download.epicgames.com','download2.epicgames.com','download3.epicgames.com','download4.epicgames.com','epicgames-download1.akamaized.net','fastly-download.epicgames.com'],
 '其他游戏下载':['gamedl.qq.com','down.qq.com','dlied1.qq.com','dlied4.myapp.com','gph.nie.netease.com','download.163.com','adl.netease.com','download.ubisoft.com','uplaypc-s-ubisoft.cdn.ubi.com','patches.rockstargames.com','blzddist1-a.akamaihd.net','blzddist2-a.akamaihd.net','dist.blizzard.com'],
 '米哈游国服':['autopatchcn.yuanshen.com','autopatchcn.bhsr.com','autopatchcn.juequling.com','autopatchcn.bh3.com'],
 '米哈游国际服':['autopatchhk.yuanshen.com','autopatchos.starrails.com','autopatchos.zenlesszonezero.com','autopatchglb.honkaiimpact3.com','autopatchjp.honkaiimpact3.com','autopatchkr.honkaiimpact3.com','autopatchos.honkaiimpact3.com','autopatchasia.honkaiimpact3.com']
}
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
