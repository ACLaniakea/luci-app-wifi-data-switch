# Scope only explicit DIRECT rules; preserve proxy rule order and targets.
module WifiDataBoost
  PREFIX='WDS-BOOST-'
  def self.apply(data,runtime,hw)
    return unless runtime['active']
    devices=runtime.fetch('devices',[]); domains=runtime.fetch('domains',[])
    wide=runtime.fetch('scope','all_tcp')=='all_tcp'
    return if !wide && domains.empty?
    mode=runtime.fetch('device_mode', devices.empty? ? 'all' : 'whitelist')
    original=Marshal.load(Marshal.dump(data))
    names=%w[WIFI MOBILE POOL BALANCED WIFI-BIAS MOBILE-BIAS].map { |v| PREFIX+v }
    raise 'Reserved boost name collision' if ((data['proxies'] || [])+(data['proxy-groups'] || [])).any? { |p| names.include?(p['name']) }
    key=PREFIX+'SCOPE'
    raise 'Reserved sub-rule name collision' if data.fetch('sub-rules',{}).key?(key)
    data['proxies'] ||= []
    [['WIFI',hw.fetch('wifi_device','wlan-sta'),22356],['MOBILE',hw.fetch('mobile_device','sipa_eth0'),22355]].each do |label,iface,mark|
      data['proxies'] << {'name'=>PREFIX+label,'type'=>'direct','udp'=>true,'ip-version'=>'ipv4','interface-name'=>iface,'routing-mark'=>mark}
    end
    data['proxy-groups'] ||= []
    [['BALANCED',['WIFI','MOBILE']],['WIFI-BIAS',['WIFI','BALANCED']],['MOBILE-BIAS',['MOBILE','BALANCED']]].each do |name,members|
      data['proxy-groups'] << {'name'=>PREFIX+name,'type'=>'load-balance','proxies'=>members.map { |v| PREFIX+v },'strategy'=>'round-robin','url'=>'http://connectivitycheck.platform.hicloud.com/generate_204','interval'=>60}
    end
    data['proxy-groups'] << {'name'=>PREFIX+'POOL','type'=>'select','proxies'=>%w[BALANCED WIFI-BIAS MOBILE-BIAS WIFI MOBILE].map { |v| PREFIX+v },'interrupt-exist-connections'=>false,'hidden'=>true}
    quic=runtime.fetch('quic',false)
    udp_gate=quic ? 'AND,((NETWORK,UDP),(NOT,((DST-PORT,443)))),DIRECT' : 'NETWORK,UDP,DIRECT'
    scope=[udp_gate,'DST-PORT,22,DIRECT','DST-PORT,3389,DIRECT','DST-PORT,47984-48010,DIRECT','DST-PORT,21115-21119,DIRECT']
    ['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/4'].each { |net| scope << "IP-CIDR,#{net},DIRECT,no-resolve" }
    runtime.fetch('wifi_domains',[]).each { |domain| scope << "DOMAIN-SUFFIX,#{domain},DIRECT" }
    domain_rules=wide ? ["MATCH,#{PREFIX}POOL"] : domains.map { |domain| "DOMAIN-SUFFIX,#{domain},#{PREFIX}POOL" } + ['MATCH,DIRECT']
    if mode=='whitelist'
      raise 'Whitelist cannot be empty' if devices.empty?
      devices.each { |ip| scope << "SUB-RULE,(SRC-IP-CIDR,#{ip}),#{PREFIX}DOMAINS" }
    else
      devices.each { |ip| scope << "SRC-IP-CIDR,#{ip},DIRECT" } if mode=='blacklist'
      scope.concat(wide ? domain_rules : domain_rules[0...-1])
    end
    scope << 'MATCH,DIRECT'
    kinds=%w[DOMAIN DOMAIN-SUFFIX DOMAIN-KEYWORD GEOSITE GEOIP IP-CIDR IP-CIDR6 RULE-SET SRC-IP-CIDR DST-PORT SRC-PORT NETWORK]
    rewrite=lambda do |rules|
      rules.map do |rule|
        next rule unless rule.is_a?(String)
        parts=rule.split(','); target=parts[-1]=='no-resolve' ? -2 : -1
        next rule unless parts[target]=='DIRECT'
        if parts[0]=='MATCH'
          quic ? "SUB-RULE,(OR,((NETWORK,TCP),(AND,((NETWORK,UDP),(DST-PORT,443))))),#{key}" : "SUB-RULE,(NETWORK,TCP),#{key}"
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
    raise 'Reserved domain sub-rule collision' if data['sub-rules'].key?(PREFIX+'DOMAINS')
    data['sub-rules'][PREFIX+'DOMAINS']=domain_rules if mode=='whitelist'
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
