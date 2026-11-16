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
