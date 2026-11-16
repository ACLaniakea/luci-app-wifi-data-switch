require 'yaml'
require_relative 'files/usr/libexec/wifi-data-switch/boost'
def check(value); raise 'Boost regression failed' unless value; end
original={'proxies'=>[{'name'=>'proxy','type'=>'socks5','server'=>'127.0.0.1','port'=>1080}], 'proxy-groups'=>[], 'rules'=>['DOMAIN,proxy.example,proxy','DOMAIN-SUFFIX,example.com,DIRECT','IP-CIDR,192.0.2.0/24,DIRECT,no-resolve','MATCH,DIRECT']}
data=Marshal.load(Marshal.dump(original))
runtime={'active'=>true,'strategy'=>'round-robin','devices'=>[],'domains'=>['example.com']}
WifiDataBoost.apply(data,runtime,{})
check(data['rules'][0]==original['rules'][0])
check(data['rules'][1]=='SUB-RULE,(DOMAIN-SUFFIX,example.com),WDS-BOOST-SCOPE')
check(data['sub-rules']['WDS-BOOST-SCOPE'].first=='NETWORK,UDP,DIRECT')
check(data['proxy-groups'].last['strategy']=='round-robin')
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
check(legacy['proxy-groups'].find { |g| g['name']=='WDS-BOOST-POOL' }['strategy']=='round-robin')
puts 'Legacy sticky setting normalized to round-robin'
