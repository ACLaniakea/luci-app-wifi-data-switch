#!/usr/bin/env python3
"""Run on the router to install files without altering network topology."""
import datetime
import os
import pathlib
import shutil
import subprocess


def main():
    if os.geteuid() != 0 or not pathlib.Path('/etc/openwrt_release').exists():
        raise SystemExit('Run as root on an OpenWrt router, after installing dependencies.')
    source = pathlib.Path(__file__).resolve().parent / 'files'
    backup = pathlib.Path('/root/wifi-data-switch-backups') / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True, mode=0o700)
    # Backups may contain Wi-Fi keys or subscription secrets. Never upload them.
    for name in ('network', 'wireless', 'firewall', 'dhcp'):
        path = pathlib.Path('/etc/config', name)
        if path.exists():
            shutil.copy2(path, backup / name)
            (backup / name).chmod(0o600)
    hook = pathlib.Path('/etc/openclash/custom/openclash_custom_overwrite.sh')
    if hook.exists():
        shutil.copy2(hook, backup / 'openclash_custom_overwrite.sh')
        (backup / 'openclash_custom_overwrite.sh').chmod(0o600)
    for src in source.rglob('*'):
        if not src.is_file() or '__pycache__' in src.parts or src.suffix == '.pyc':
            continue
        relative = src.relative_to(source)
        dst = pathlib.Path('/') / relative
        if dst.exists():
            saved = backup / 'files' / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, saved)
            saved.chmod(0o600)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        dst.chmod(0o755 if str(relative).startswith(('etc/init.d/', 'usr/libexec/')) else 0o644)
    subprocess.run(['python3', '/usr/libexec/wifi-data-switch/maintenance.py', 'setup'], check=True)
    subprocess.run(['/etc/init.d/rpcd', 'reload'], check=True)
    for cache in pathlib.Path('/tmp').glob('luci-indexcache*'):
        if cache.is_file():
            cache.unlink()
    print('Installed. Backup:', backup)
    print('No service was started or enabled. Follow README to review interfaces and activate.')


if __name__ == '__main__':
    main()
