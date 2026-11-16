# Scope only explicit DIRECT rules; preserve proxy rule order and targets.
module WifiDataBoost
  PREFIX='WDS-BOOST-'
  def self.apply(data,runtime,hw)
    return unless runtime['active']
    devices=runtime.fetch('devices',[]); domains=runtime.fetch('domains',[])
    return if devices.empty? && domains.empty?
    original=Marshal.load(Marshal.dump(data))
    names=[PREFIX+'WIFI',PREFIX+'MOBILE',PREFIX+'POOL']
    raise 'Reserved boost name collision' if ((data['proxies'] || [])+(data['proxy-groups'] || [])).any? { |p| names.include?(p['name']) }
    key=PREFIX+'SCOPE'
    raise 'Reserved sub-rule name collision' if data.fetch('sub-rules',{}).key?(key)
    data['proxies'] ||= []
    [['WIFI',hw.fetch('wifi_device','wlan-sta'),22354],['MOBILE',hw.fetch('mobile_device','sipa_eth0'),22355]].each do |label,iface,mark|
      data['proxies'] << {'name'=>PREFIX+label,'type'=>'direct','udp'=>true,'ip-version'=>'ipv4','interface-name'=>iface,'routing-mark'=>mark}
    end
    data['proxy-groups'] ||= []
    data['proxy-groups'] << {'name'=>PREFIX+'POOL','type'=>'load-balance','proxies'=>[PREFIX+'WIFI',PREFIX+'MOBILE'],'strategy'=>runtime.fetch('strategy','sticky-sessions'),'url'=>'http://connectivitycheck.platform.hicloud.com/generate_204','interval'=>60}
    scope=['NETWORK,UDP,DIRECT','DST-PORT,22,DIRECT','DST-PORT,3389,DIRECT','DST-PORT,47984-48010,DIRECT','DST-PORT,21115-21119,DIRECT']
    ['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4'].each { |net| scope << "IP-CIDR,#{net},DIRECT,no-resolve" }
    devices.each { |ip| scope << "SRC-IP-CIDR,#{ip},#{PREFIX}POOL" }
    domains.each { |domain| scope << "DOMAIN-SUFFIX,#{domain},#{PREFIX}POOL" }
    scope << 'MATCH,DIRECT'
    kinds=%w[DOMAIN DOMAIN-SUFFIX DOMAIN-KEYWORD GEOSITE GEOIP IP-CIDR IP-CIDR6 RULE-SET SRC-IP-CIDR DST-PORT SRC-PORT NETWORK]
    rewrite=lambda do |rules|
      rules.map do |rule|
        next rule unless rule.is_a?(String)
        parts=rule.split(','); target=parts[-1]=='no-resolve' ? -2 : -1
        next rule unless parts[target]=='DIRECT'
        if parts[0]=='MATCH'
          "SUB-RULE,(NETWORK,TCP),#{key}"
        elsif kinds.include?(parts[0]) && parts.length.between?(3,4)
          matcher=parts[0,2]; matcher << 'no-resolve' if parts[-1]=='no-resolve'
          "SUB-RULE,(#{matcher.join(',')}),#{key}"
        else
          rule
        end
      end
    end
    data['rules']=rewrite.call(data.fetch('rules',[]))
    data['sub-rules'] ||= {}
    data['sub-rules'].keys.each { |name| data['sub-rules'][name]=rewrite.call(data['sub-rules'][name]) }
    data['sub-rules'][key]=scope
    data['x-wifi-data-switch-original']={'rules'=>original.fetch('rules',[]),'sub-rules'=>original.fetch('sub-rules',{})}
  end
  def self.restore(data)
    original=data.delete('x-wifi-data-switch-original')
    return unless original
    data['rules']=original['rules'];data['sub-rules']=original['sub-rules']
    ['proxies','proxy-groups'].each { |k| data[k]=(data[k] || []).reject { |v| v['name'].to_s.start_with?(PREFIX) } }
  end
end
