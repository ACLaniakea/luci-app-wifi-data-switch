"""Keep the first two concurrent connections on Wi-Fi, before load balancing.

Native forwarding counts each client/peer separately. Mihomo outbound sockets
share the router's identity, so that path counts per peer, protocol and port.
Connection count is a conservative heuristic, not application/thread detection.
"""
TABLE = 'wds_admission'
SET = 'wds_parallel'


def native_set(table):
    return ('add set inet '+table+' '+SET+' { type ipv4_addr . ipv4_addr . inet_proto . inet_service; '
            'flags dynamic; size 8192; }\n')


def gate():
    return 'add @'+SET+' { ip saddr . ip daddr . meta l4proto . th dport ct count over 2 } '


def local_script():
    # Both socket hints initially route through Wi-Fi. The route OUTPUT hook
    # changes only these dedicated hints, before accounting and NAT. Removing
    # interface binding from these two DIRECT adapters permits the reroute.
    return '''table inet wds_admission {
 set peers { type ipv4_addr . inet_proto . inet_service; flags dynamic; size 8192; }
 counter wifi_first { }
 counter parallel { }
 chain select {
  type route hook output priority -150; policy accept;
  meta nfproto != ipv4 return
  meta mark != { 0x5756, 0x5757 } return
  ct direction reply return
  ct mark & 0xffff { 0x5753, 0x5754 } meta mark set ct mark & 0xffff return
  ct state established,related return
  meta l4proto != { tcp, udp } return
  add @peers { ip daddr . meta l4proto . th dport ct count over 2 } counter name parallel meta mark set meta mark map { 0x5756 : 0x5754, 0x5757 : 0x5753 } ct mark set (ct mark & 0xffff0000) | meta mark return
  counter name wifi_first meta mark set 0x5754 ct mark set (ct mark & 0xffff0000) | meta mark
 }
}
'''


class Manager:
    def __init__(self, c):
        self.c = c

    def sync(self, cfg):
        c = self.c
        # Keep this small table while disabled: established marked sockets must
        # retain their original route. Cleanup removes it after core restoration.
        if cfg['mode'] != 'split' or not cfg.get('boost_enabled'):
            return False
        try:
            if c.command(['nft','list','table','inet',TABLE],check=False).returncode:
                c.command(['nft','-f','-'],input=local_script())
            for priority, mark in ((10506,'0x5756'),(10507,'0x5757')):
                c.rule(priority,['fwmark',mark,'lookup','202'])
            c.write(c.RUN/'admission-status.json',{'ready':True,'wifi_first':2})
            return True
        except Exception as error:
            c.write(c.RUN/'admission-status.json',{'ready':False,'error':type(error).__name__})
            return False
