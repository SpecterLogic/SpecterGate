#!/usr/bin/env python3
"""Move an installed panel behind HTTPS on a dedicated port and random URL path."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import time
import urllib.request


def domain(value):
    if len(value) > 253 or not re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}', value):
        raise argparse.ArgumentTypeError('Use an ASCII domain name without a scheme or port.')
    return value.lower()


def available_port():
    for _ in range(100):
        port = 30000 + secrets.randbelow(30000)
        with socket.socket() as probe:
            try:
                probe.bind(('0.0.0.0', port))
            except OSError:
                continue
        return port
    raise RuntimeError('No available panel port was found.')


def configure(host, port=None):
    if os.geteuid() != 0:
        raise RuntimeError('Run this command as root.')
    app = Path('/opt/spectergate')
    state_dir = Path('/etc/spectergate')
    state_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(state_dir, 0o700)
    record = state_dir / 'panel-access.json'
    previous = json.loads(record.read_text()) if record.exists() else None
    if previous and previous['domain'] != host:
        raise RuntimeError('The stored panel domain differs; configure a domain migration explicitly.')
    selected_port = port if port is not None else (previous['port'] if previous else available_port())
    if selected_port in {22, 80, 443, 8000, 10085} or not 1024 <= selected_port <= 65535:
        raise RuntimeError('Select a dedicated unused TCP port between 1024 and 65535.')
    key = previous['path'] if previous else secrets.token_urlsafe(24)
    if not re.fullmatch(r'[A-Za-z0-9_-]{24,96}', key):
        raise RuntimeError('The stored management path is invalid.')
    prefix = f'/{key}/'
    origin = f'https://{host}:{selected_port}'
    public_url = origin + prefix
    cert = Path('/etc/letsencrypt/live') / host
    if not (cert / 'fullchain.pem').is_file() or not (cert / 'privkey.pem').is_file():
        raise RuntimeError('Install a valid domain certificate before configuring private access.')

    environment = os.environ.copy()
    environment['VITE_API_BASE_URL'] = prefix.rstrip('/')
    subprocess.run(['npm', 'run', 'build', '--', '--base', prefix, '--outDir', 'dist-private'], cwd=app / 'frontend', env=environment, check=True)
    target = Path('/var/www/spectergate-admin') / key
    target.mkdir(parents=True, exist_ok=True, mode=0o755)
    shutil.copytree(app / 'frontend/dist-private', target, dirs_exist_ok=True)
    for item in [target.parent, target, *target.rglob('*')]:
        shutil.chown(item, user='root', group='www-data')
        os.chmod(item, 0o750 if item.is_dir() else 0o640)

    panel_site = Path('/etc/nginx/sites-available/spectergate')
    private_site = Path('/etc/nginx/sites-available/spectergate-private')
    private_link = Path('/etc/nginx/sites-enabled/spectergate-private')
    env_file = app / 'backend/.env'
    original_site = panel_site.read_text()
    original_env = env_file.read_text()
    original_private = private_site.read_text() if private_site.exists() else None
    if not (state_dir / 'original-panel-site.conf').exists():
        (state_dir / 'original-panel-site.conf').write_text(original_site)
        os.chmod(state_dir / 'original-panel-site.conf', 0o600)
    values = dict(line.split('=', 1) for line in original_env.splitlines() if line and not line.startswith('#') and '=' in line)
    values['SPECTERGATE_CORS_ORIGINS'] = origin
    values['SPECTERGATE_PANEL_BASE_PATH'] = prefix
    values['SPECTERGATE_PANEL_PUBLIC_PORT'] = str(selected_port)

    loopback = re.search(r'listen\s+127\.0\.0\.1:(\d+).*?;', original_site)
    if loopback:
        old_listen = f'listen 127.0.0.1:{loopback[1]} ssl'
        if 'proxy_protocol' in loopback[0]:
            old_listen += ' proxy_protocol'
        old_listen += ';'
    else:
        old_listen = 'listen 443 ssl;\n    listen [::]:443 ssl;'
    common_tls = f'''ssl_certificate {cert}/fullchain.pem;
    ssl_certificate_key {cert}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;'''
    retired = f'''limit_req_zone $binary_remote_addr zone=spectergate_login:10m rate=12r/m;
upstream spectergate_api {{ server 127.0.0.1:8000; keepalive 32; }}
server {{
    listen 80;
    server_name {host};
    location /.well-known/acme-challenge/ {{ root /var/www/html; }}
    location / {{ return 404; }}
}}
server {{
    {old_listen}
    server_name {host};
    {common_tls}
    root /var/www/spectergate;
    server_tokens off;
    location /sub/ {{
        proxy_pass http://spectergate_api;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
    }}
    location /assets/ {{ try_files $uri =404; }}
    location /s/ {{ try_files $uri /index.html; }}
    location = /index.html {{ internal; try_files $uri =404; }}
    location / {{ return 404; }}
}}
'''
    proxy_settings = f'''proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_cookie_path /api /{key}/api;
        proxy_read_timeout 90s;'''
    version = subprocess.run(['nginx', '-v'], capture_output=True, text=True, check=True)
    parsed = re.search(r'nginx/(\d+)\.(\d+)\.(\d+)', version.stderr)
    modern_http2 = parsed and tuple(map(int, parsed.groups())) >= (1, 25, 1)
    http2_flag = '' if modern_http2 else ' http2'
    private = f'''server {{
    listen {selected_port} ssl{http2_flag};
    listen [::]:{selected_port} ssl{http2_flag};
    {'http2 on;' if modern_http2 else ''}
    server_name {host};
    {common_tls}
    root /var/www/spectergate-admin;
    server_tokens off;
    client_max_body_size 1m;
    access_log off;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'" always;
    if ($host != {host}) {{ return 444; }}
    location ~ ^/{key}/api/auth/(login|token|session)$ {{
        limit_req zone=spectergate_login burst=8 nodelay;
        limit_req_status 429;
        rewrite ^/{key}(/.*)$ $1 break;
        proxy_pass http://spectergate_api;
        {proxy_settings}
    }}
    location /{key}/api/ {{
        proxy_pass http://spectergate_api/api/;
        {proxy_settings}
    }}
    location /{key}/sub/ {{
        proxy_pass http://spectergate_api/sub/;
        {proxy_settings}
        proxy_buffering off;
    }}
    location = /{key} {{ return 308 /{key}/; }}
    location /{key}/ {{ try_files $uri $uri/ /{key}/index.html; }}
    location / {{ return 404; }}
}}
'''
    try:
        panel_site.write_text(retired)
        private_site.write_text(private)
        os.chmod(private_site, 0o600)
        if not private_link.exists():
            private_link.symlink_to(private_site)
        env_file.write_text(''.join(f'{k}={v}\n' for k, v in values.items()))
        os.chmod(env_file, 0o600)
        subprocess.run(['nginx', '-t'], check=True)
        if shutil.which('ufw'):
            firewall = subprocess.run(['ufw', 'status'], capture_output=True, text=True, check=True)
            if 'Status: active' in firewall.stdout:
                subprocess.run(['ufw', 'allow', f'{selected_port}/tcp'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
        subprocess.run(['systemctl', 'restart', 'spectergate'], check=True)
        for attempt in range(30):
            try:
                with urllib.request.urlopen(public_url + 'api/health', timeout=3) as response:
                    if response.status == 200:
                        break
            except Exception:
                if attempt == 29:
                    raise RuntimeError('Private panel health check failed.') from None
                time.sleep(1)
    except Exception:
        panel_site.write_text(original_site)
        env_file.write_text(original_env)
        if original_private is None:
            private_link.unlink(missing_ok=True)
            private_site.unlink(missing_ok=True)
        else:
            private_site.write_text(original_private)
        subprocess.run(['nginx', '-t'], check=False)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=False)
        subprocess.run(['systemctl', 'restart', 'spectergate'], check=False)
        raise
    descriptor = os.open(record, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump({'domain': host, 'port': selected_port, 'path': key, 'url': public_url}, handle)
    os.chmod(record, 0o600)
    print('Private panel URL: ' + public_url)
    print('The username and password are unchanged. Root paths return 404.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', type=domain, required=True)
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    configure(args.domain, args.port)
