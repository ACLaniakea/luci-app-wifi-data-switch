require 'yaml'
require_relative 'files/usr/libexec/wifi-data-switch/boost'
def check(value); raise 'Boost regression failed' unless value; end
original={'proxies'=>[{'name'=>'proxy','type'=>'socks5','server'=>'127.0.0.1','port'=>1080}], 'proxy-groups'=>[], 'rules'=>['DOMAIN,proxy.example,proxy','DOMAIN-SUFFIX,example.com,DIRECT','IP-CIDR,192.0.2.0/24,DIRECT,no-resolve','MATCH,DIRECT']}
data=Marshal.load(Marshal.dump(original))
runtime={'active'=>true,'strategy'=>'round-robin','scope'=>'domains','devices'=>[],'domains'=>['example.com']}
WifiDataBoost.apply(data,runtime,{})
check(data['rules'][0]==original['rules'][0])
check(data['rules'][1]=='SUB-RULE,(DOMAIN-SUFFIX,example.com),WDS-BOOST-SCOPE')
check(data['sub-rules']['WDS-BOOST-SCOPE'].first=='NETWORK,UDP,DIRECT')
check(data['proxy-groups'].last['type']=='select')
check(data['proxy-groups'].last['proxies'].first=='WDS-BOOST-BALANCED')
check(data['proxy-groups'].last['interrupt-exist-connections']==false)
File.write(ARGV[0],YAML.dump(data)) if ARGV[0]
WifiDataBoost.restore(data)
check(data['rules']==original['rules'])
check(data['proxies']==original['proxies'])
check(data['proxy-groups']==original['proxy-groups'])
WifiDataBoost.apply(data,runtime,{})
WifiDataBoost.restore(data)
check(data['rules']==original['rules'])
puts 'Boost rule scope and restore checks passed'

%w[all whitelist blacklist].each do |mode|
  cfg=Marshal.load(Marshal.dump(original))
  rt=runtime.merge('device_mode'=>mode,'devices'=>['192.0.2.2/32'])
  WifiDataBoost.apply(cfg,rt,{})
  scope=cfg['sub-rules']['WDS-BOOST-SCOPE']
  if mode=='whitelist'
    check(scope.include?('SUB-RULE,(SRC-IP-CIDR,192.0.2.2/32),WDS-BOOST-DOMAINS'))
    check(cfg['sub-rules']['WDS-BOOST-DOMAINS'].include?('DOMAIN-SUFFIX,example.com,WDS-BOOST-POOL'))
  elsif mode=='blacklist'
    check(scope.index('SRC-IP-CIDR,192.0.2.2/32,DIRECT') < scope.index('DOMAIN-SUFFIX,example.com,WDS-BOOST-POOL'))
  else
    check(!scope.any? { |rule| rule.include?('192.0.2.2') })
  end
  File.write(ARGV[0]+'.'+mode,YAML.dump(cfg)) if ARGV[0]
  WifiDataBoost.restore(cfg)
  check(cfg['rules']==original['rules'])
end
puts 'All devices, whitelist and blacklist domain gates passed'

legacy=Marshal.load(Marshal.dump(original))
WifiDataBoost.apply(legacy,runtime.merge('strategy'=>'sticky-sessions'),{})
check(legacy['proxy-groups'].find { |g| g['name']=='WDS-BOOST-BALANCED' }['strategy']=='round-robin')
puts 'Legacy sticky setting normalized to round-robin'

%w[all whitelist blacklist].each do |mode|
  cfg=Marshal.load(Marshal.dump(original))
  WifiDataBoost.apply(cfg,runtime.merge('scope'=>'all_tcp','domains'=>[],'device_mode'=>mode,'devices'=>['192.0.2.2/32']),{})
  check(cfg['rules'][0]==original['rules'][0])
  scope=cfg['sub-rules']['WDS-BOOST-SCOPE']
  check(scope.include?('DST-PORT,47984-48010,DIRECT'))
  if mode=='whitelist'
    check(cfg['sub-rules']['WDS-BOOST-DOMAINS']==['MATCH,WDS-BOOST-POOL'])
    check(scope.last=='MATCH,DIRECT')
  else
    check(scope.include?('MATCH,WDS-BOOST-POOL'))
    check(scope.index('SRC-IP-CIDR,192.0.2.2/32,DIRECT') < scope.index('MATCH,WDS-BOOST-POOL')) if mode=='blacklist'
  end
  File.write(ARGV[0]+'.wide.'+mode,YAML.dump(cfg)) if ARGV[0]
  WifiDataBoost.restore(cfg);check(cfg['rules']==original['rules'])
end
puts 'All DIRECT TCP scope and device exclusions passed'

cfg=Marshal.load(Marshal.dump(original))
WifiDataBoost.apply(cfg,runtime.merge('scope'=>'all_tcp','wifi_domains'=>['bilivideo.com']),{})
scope=cfg['sub-rules']['WDS-BOOST-SCOPE']
check(cfg['rules'][0]==original['rules'][0])
check(scope.index('DOMAIN-SUFFIX,bilivideo.com,DIRECT')<scope.index('MATCH,WDS-BOOST-POOL'))
puts 'Preferred DIRECT video domains preserve unrelated proxy rules'

cfg=Marshal.load(Marshal.dump(original))
WifiDataBoost.apply(cfg,runtime.merge('scope'=>'all_tcp','smart'=>true),{})
adapters=cfg['proxies'].select { |p| [WifiDataBoost::PREFIX+'WIFI',WifiDataBoost::PREFIX+'MOBILE'].include?(p['name']) }
check(adapters.map { |p| p['routing-mark'] }==[22358,22359])
check(adapters.none? { |p| p.key?('interface-name') })
check(cfg['proxies'].first==original['proxies'].first)
WifiDataBoost.restore(cfg);check(cfg['rules']==original['rules'])
puts 'Smart DIRECT adapters use only dedicated routing hints; original proxies preserved'
