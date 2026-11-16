#!/usr/bin/python3
"""Install/remove only this plugin's OpenClash hook and routing rules."""
import pathlib
import re
import subprocess
import sys

import controller

BEGIN = '# BEGIN wifi-data-switch'
END = '# END wifi-data-switch'
HOOK = pathlib.Path('/etc/openclash/custom/openclash_custom_overwrite.sh')


def edit_hook(remove=False):
    if not HOOK.exists():
        return
    text = HOOK.read_text()
    text = re.sub(r'(?m)^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?', '', text, flags=re.S)
    if not remove:
        block = BEGIN + '\n[ ! -x /usr/libexec/wifi-data-switch/overlay.rb ] || /usr/libexec/wifi-data-switch/overlay.rb "$1"\n' + END + '\n'
        # A stock/user hook may finish with exit 0. Insert before that exit.
        match = re.search(r'(?m)^\s*exit\s+0\s*$', text)
        position = match.start() if match else len(text)
        text = text[:position].rstrip() + '\n' + block + text[position:]
    HOOK.write_text(text)
    HOOK.chmod(0o755)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action == 'setup':
        controller.ensure_dirs()
        settings = controller.ROOT / 'settings.json'
        if not settings.exists():
            hw = controller.hardware()
            def uci(key, default):
                value = controller.command(['uci', '-q', 'get', key], check=False).stdout.strip()
                return value or default
            controller.write(settings, {'mode': 'mobile' if HOOK.exists() else 'direct', 'failover': True,
                'ssid': uci('wireless.' + hw['station'] + '.ssid', ''),
                'encryption': uci('wireless.' + hw['station'] + '.encryption', 'none'),
                'band': uci('wireless.' + hw['radio'] + '.band', '5g')})
        edit_hook()
        print('Setup complete; OpenClash hook installed when present. Service not started; review hardware.json before enabling.')
    elif action == 'cleanup':
        subprocess.run(['/etc/init.d/wifi-data-switch', 'stop'], check=False)
        subprocess.run(['/etc/init.d/wifi-data-switch', 'disable'], check=False)
        controller.native.Manager(controller).cleanup_bypass()
        edit_hook(remove=True)
        for priority in (10510, 10511, 10512, 10513, 10520, 10521, 31020):
            controller.rule(priority, [], False)
        for table in ('201', '202'):
            controller.command(['ip', '-4', 'route', 'flush', 'table', table], check=False)
        controller.command(['nft', 'delete', 'table', 'inet', 'wifi_data_switch'], check=False)
        controller.command(['nft','delete','table','inet','wds_meter'],check=False)
        controller.command(['nft','delete','table','inet','wds_mobile_limit'],check=False)
        print('Routing and hook removed. Refresh your original OpenClash subscription/configuration before restarting OpenClash; see README rollback instructions.')
    else:
        raise SystemExit('Usage: maintenance.py setup|cleanup')


if __name__ == '__main__':
    main()
