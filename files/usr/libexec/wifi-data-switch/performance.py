"""Bounded background probes, packet-based boost rates and conservative scheduling.

No capacity is inferred from idle interface counters. Congestion feedback changes
only new connections, never moves a live socket and never claims byte fairness.
"""
import concurrent.futures
import json
import pathlib
import subprocess
import threading
import time

ENDPOINTS = ('http://connectivitycheck.platform.hicloud.com/generate_204',
             'http://connect.rom.miui.com/generate_204')
GROUPS = {0: 'WIFI', 25: 'WIFI-BIAS', 50: 'BALANCED', 75: 'MOBILE-BIAS', 100: 'MOBILE'}


def probe(c, device):
    if not device or not pathlib.Path('/sys/class/net', device).exists():
        return {'success': False, 'reason': 'link_down'}
    reason = 'unreachable'
    for url in ENDPOINTS:
        try:
            r = c.command(['curl', '-4', '--interface', device, '--noproxy', '*',
                '--connect-timeout', '2', '--max-time', '4', '--silent', '--output', '/dev/null',
                '--write-out', '%{http_code} %{time_namelookup} %{time_connect}', url],
                check=False, timeout=5)
            fields = r.stdout.split()
            if r.returncode == 0 and fields and fields[0] == '204':
                return {'success': True, 'endpoint': url,
                        'connect_ms': round(max(0, float(fields[2])-float(fields[1]))*1000, 2),
                        'reason': 'online'}
            if r.returncode == 6:
                reason = 'dns_error'
            elif fields and fields[0].startswith('3'):
                reason = 'portal'
        except (subprocess.SubprocessError, ValueError, IndexError):
            pass
    return {'success': False, 'reason': reason}


class Probes:
    def __init__(self, c):
        self.c = c
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.pending = {}
        self.due = {}
        self.details = {}
        self.identities = {}

    def poll(self, infos, scores, now=None):
        now = time.monotonic() if now is None else now
        changed = False
        for label, info in infos.items():
            identity = (info.get('device'), tuple(info.get('addresses', [])))
            old_online = scores[label]['online']
            if label in self.identities and self.identities[label] != identity:
                scores[label].update(good=0, bad=0, online=False)
                self.details.pop(label, None)
                self.due[label] = 0
            self.identities[label] = identity
            pending = self.pending.get(label)
            if pending and pending[0].done():
                future, submitted_identity = self.pending.pop(label)
                if info.get('up') and submitted_identity == identity:
                    try:
                        result = future.result()
                    except Exception:
                        result = {'success': False, 'reason': 'probe_error'}
                    self.c.health_sample(scores[label], result['success'], True)
                    self.details[label] = {**result, 'sampled_at': time.time(), 'identity': repr(identity)}
            if not info.get('up'):
                self.c.health_sample(scores[label], False, False)
                self.details[label] = {'success': False, 'reason': 'link_down'}
            elif label not in self.pending and now >= self.due.get(label, 0):
                self.pending[label] = (self.pool.submit(probe, self.c, info['device']), identity)
                self.due[label] = now + 10
            changed |= old_online != scores[label]['online']
        return changed

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def meter_script():
    text = 'table inet wds_performance {\n'
    for label in ('wifi_up', 'wifi_down', 'mobile_up', 'mobile_down'):
        text += ' counter '+label+' {}\n'
    for chain, hook in [('local_tx', 'output'), ('forward_tx', 'forward')]:
        text += ' chain '+chain+' { type filter hook '+hook+' priority -139; policy accept;\n'
        wifi_mark = '0x5754' if hook == 'output' else '0x5752'
        for label, mark, bit in [('wifi', wifi_mark, '0x20000000'), ('mobile', '0x5753', '0x40000000')]:
            text += ' ct direction original meta mark '+mark+' ct mark set ct mark | '+bit+' counter name '+label+'_up\n'
        text += ' }\n'
    text += ' chain replies { type filter hook prerouting priority -139; policy accept;\n'
    for label, bit in [('wifi', '0x20000000'), ('mobile', '0x40000000')]:
        text += ' ct direction reply ct mark & '+bit+' != 0 counter name '+label+'_down\n'
    return text+' }\n}\n'


def rates(previous, raw, now):
    old_time, old_raw = previous if previous else (now, raw)
    dt = now-old_time
    return {key: round(max(0, value-old_raw.get(key, value))*8/dt/1e6, 3)
            if dt > 0 and value >= old_raw.get(key, value) else 0.0 for key, value in raw.items()}


class Manager:
    def __init__(self, c):
        self.c = c
        self.previous = None
        self.telemetry = {'ready': False}
        self.baselines = {}
        self.quality = {}
        self.share = 50
        self.last_change = float('-inf')
        self.reason = '观察链路状态'
        self.api_identity = None
        self.api_credentials = None

    def sample(self):
        c = self.c
        try:
            if c.command(['nft', 'list', 'table', 'inet', 'wds_performance'], check=False).returncode:
                c.command(['nft', '-f', '-'], input=meter_script())
                self.previous = None
            data = json.loads(c.command(['nft', '-j', 'list', 'table', 'inet', 'wds_performance']).stdout)
            raw = {x['counter']['name']: int(x['counter']['bytes']) for x in data['nftables'] if 'counter' in x}
            now = time.monotonic()
            first = self.previous is None
            self.telemetry = {'ready': not first, 'sampled_at': int(time.time()), 'rates': rates(self.previous, raw, now)}
            self.previous = (now, raw)
        except Exception:
            self.previous = None
            self.telemetry = {'ready': False, 'reason': '加速速率暂不可用'}
        return self.telemetry

    def recommend(self, cfg, details, now=None):
        now = time.monotonic() if now is None else now
        for label, detail in details.items():
            key = (label, detail.get('identity'), detail.get('endpoint'))
            q = self.quality.setdefault(label, {'bad': 0, 'good': 0, 'congested': False})
            if q.get('stamp') == detail.get('sampled_at'):
                continue
            q['stamp'] = detail.get('sampled_at')
            if not detail.get('success') or 'connect_ms' not in detail:
                continue
            if q.get('key') != repr(key):
                q.update(key=repr(key), bad=0, good=0, congested=False)
            ms = detail['connect_ms']
            base, started = self.baselines.get(key, (ms, now))
            # Refresh an old minimum periodically, rather than remembering one fast sample forever.
            if now-started > 1200:
                base, started = ms, now
            base = min(base, ms)
            self.baselines[key] = (base, started)
            bad = ms > max(base*2, base+35)
            q['bad'] = q['bad']+1 if bad else 0
            q['good'] = 0 if bad else q['good']+1
            if q['bad'] >= 3:
                q['congested'] = True
            if q['good'] >= 4:
                q['congested'] = False
            q.update(connect_ms=ms, baseline_ms=round(base, 2))
        wifi_busy = self.quality.get('wifi', {}).get('congested', False)
        mobile_busy = self.quality.get('mobile', {}).get('congested', False)
        adaptive = cfg.get('boost_adaptive', True)
        target = 25 if mobile_busy and not wifi_busy else 75 if wifi_busy and not mobile_busy else 50
        if not adaptive:
            self.share = 50
        elif target != self.share and now-self.last_change >= 45:
            self.share += 25 if target > self.share else -25
            self.last_change = now
        self.reason = ('固定分担' if not adaptive else '移动出口拥塞，减少新连接' if self.share == 25
                       else 'Wi-Fi 出口拥塞，减少新连接' if self.share == 75 else '两条出口共同承担')
        return self.share

    def select_clash(self, share):
        """Select only our group through the local API; never reload the config."""
        c = self.c
        try:
            path = c.active_clash()
            if path is None:
                return False
            stat = path.stat()
            identity = (str(path), stat.st_mtime_ns, stat.st_size)
            if identity != self.api_identity:
                controller, secret, *_ = c.clash_info(path)
                self.api_credentials = (int(controller.rsplit(':', 1)[-1]), secret)
                self.api_identity = identity
            port, secret = self.api_credentials
            url = 'http://127.0.0.1:'+str(port)+'/proxies/WDS-BOOST-POOL'
            def request(method, body=None):
                spec = 'url = '+json.dumps(url)+'\nrequest = '+json.dumps(method)+'\nheader = '+json.dumps('Authorization: Bearer '+secret)+'\n'
                if body is not None:
                    spec += 'header = "Content-Type: application/json"\ndata = '+json.dumps(json.dumps(body))+'\n'
                spec += 'silent\nmax-time = 2\nwrite-out = "\\n%{http_code}"\n'
                r = c.command(['curl', '--noproxy', '*', '--config', '-'], input=spec, timeout=3)
                payload, code = r.stdout.rsplit('\n', 1)
                if code not in ('200', '204'):
                    raise RuntimeError('Boost selector unavailable')
                return json.loads(payload) if payload else {}
            target = 'WDS-BOOST-'+GROUPS[share]
            current = request('GET')
            if current.get('now') != target:
                request('PUT', {'name': target})
            return True
        except Exception:
            return False

    def publish(self, enabled, core_ready=True):
        self.c.write(self.c.RUN/'performance.json', {
            'adaptive': enabled, 'mobile_share': self.share, 'reason': self.reason,
            'core_ready': core_ready, 'quality': self.quality})


class Sampler:
    """Own quota state in one worker; slow probes/config validation cannot stall it."""
    def __init__(self, c, manager):
        import quota
        self.c = c
        self.manager = manager
        self.meter = quota.Meter(c)
        self.usage = {'ready': False, 'exceeded': True,
                      'mobile_total_exceeded': c.read(c.RUN/'usage-status.json', {}).get('mobile_total_exceeded', False)}
        self.stop_event = threading.Event()
        self.first_sample = threading.Event()
        self.thread = threading.Thread(target=self.run, name='wds-meter', daemon=True)

    def start(self):
        self.thread.start()
        self.first_sample.wait(timeout=5)

    def run(self):
        import quota
        try:
            while not self.stop_event.is_set():
                try:
                    cfg = self.c.config()
                    usage = self.meter.sample(cfg)
                except Exception:
                    usage = {'ready': False, 'exceeded': True,
                             'mobile_total_exceeded': self.usage.get('mobile_total_exceeded', False)}
                    self.c.write(self.c.RUN/'usage-status.json', usage)
                try:
                    hw = self.c.hardware()
                    quota.mobile_guard(self.c, hw['mobile_device'], usage.get('mobile_total_exceeded', False))
                    self.c.write(self.c.RUN/'traffic.json', self.manager.sample())
                except Exception:
                    usage = {**usage, 'ready': False, 'exceeded': True}
                self.usage = usage
                self.first_sample.set()
                self.stop_event.wait(2)
        finally:
            self.meter.flush()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=30)
