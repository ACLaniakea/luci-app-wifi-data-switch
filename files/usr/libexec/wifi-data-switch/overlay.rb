#!/usr/bin/ruby
# Bind proxy nodes only; DIRECT continues to follow the routing policy.
require 'yaml'
require 'json'
path = ARGV.fetch(0)
iface_file = '/var/run/wifi-data-switch/proxy-interface'
settings_file = '/etc/wifi-data-switch/hardware.json'
hardware = File.exist?(settings_file) ? JSON.parse(File.read(settings_file)) : {}
mobile = hardware.fetch('mobile_device', 'sipa_eth0')
wifi = hardware.fetch('wifi_device', 'wlan-sta')
iface = File.exist?(iface_file) ? File.read(iface_file).strip : mobile
raise 'Invalid uplink interface' unless [mobile, wifi].include?(iface)
data = YAML.load_file(path, aliases: true)
mark = iface == mobile ? 22353 : 22354
apply = lambda do |proxy|
  next unless proxy.is_a?(Hash)
  next if ['direct', 'reject', 'dns'].include?(proxy['type'].to_s.downcase)
  proxy['interface-name'] = iface
  proxy['routing-mark'] = mark
  proxy['ip-version'] = 'ipv4'
end
(data['proxies'] || []).each { |proxy| apply.call(proxy) }
(data['proxy-providers'] || {}).each_value do |provider|
  next unless provider.is_a?(Hash)
  provider['override'] ||= {}
  provider['override']['interface-name'] = iface
  provider['override']['routing-mark'] = mark
  provider['override']['ip-version'] = 'ipv4'
  (provider['payload'] || []).each { |proxy| apply.call(proxy) }
end
tmp = path + '.wifi-data-new'
File.open(tmp, File::WRONLY | File::CREAT | File::TRUNC, 0600) { |file| file.write(YAML.dump(data)); file.flush; file.fsync }
File.rename(tmp, path)
