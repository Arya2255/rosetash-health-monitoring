"""Fetch official Windows broker/tunnel runtimes for the generic build (no secrets)."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'build' / 'windows-runtime'
MOSQUITTO_URL = 'https://mosquitto.org/files/binary/win64/mosquitto-2.1.2-install-windows-x64.exe'
MOSQUITTO_SHA = '58008ad7a22ada0b4073afa415801746e027c5f583e4fa52d0f4e9193b98d6aa'
CF_URL = 'https://github.com/cloudflare/cloudflared/releases/download/2026.11.0/cloudflared-windows-amd64.exe'
CF_SHA = 'd5c1d82031da6253dcdcff64c944cd0fe063016edeb2e4fd088075fc9bd52d0a'


def download(url, path, expected):
    with urllib.request.urlopen(url, timeout=60) as source, path.open('wb') as output:
        shutil.copyfileobj(source, output)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError('Download checksum mismatch: ' + path.name)


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    seven = shutil.which('7z') or r'C:\Program Files\7-Zip\7z.exe'
    with tempfile.TemporaryDirectory(prefix='roztash-runtime-') as temp:
        temp = Path(temp)
        installer = temp / 'mosquitto.exe'
        download(MOSQUITTO_URL, installer, MOSQUITTO_SHA)
        extracted = temp / 'extracted'
        subprocess.run([seven, 'x', str(installer), '-o' + str(extracted), '-y'],
                       check=True, stdout=subprocess.DEVNULL)
        broker = TARGET / 'mosquitto'
        broker.mkdir(exist_ok=True)
        allow = {'mosquitto.exe', 'mosquitto_sub.exe', 'mosquitto_pub.exe',
                 'mosquitto_passwd.exe', 'edl-v10', 'epl-v20', 'NOTICE.md', 'README-windows.txt'}
        for path in extracted.iterdir():
            if path.is_file() and (path.name in allow or path.suffix.lower() == '.dll'):
                shutil.copy2(path, broker / path.name)
        assert all((broker / name).is_file() for name in allow)
        # Ship VC runtime app-locally: do not run an installer or require admin.
        if os.name == 'nt':
            for name in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll'):
                dll = Path(os.environ['WINDIR']) / 'System32' / name
                if not dll.is_file():
                    raise FileNotFoundError('Runner missing VC runtime: ' + name)
                shutil.copy2(dll, broker / name)
        tunnel = TARGET / 'cloudflared.exe'
        download(CF_URL, tunnel, CF_SHA)
        license_url = 'https://raw.githubusercontent.com/cloudflare/cloudflared/2026.11.0/LICENSE'
        with urllib.request.urlopen(license_url, timeout=30) as response:
            (TARGET / 'LICENSE.cloudflared').write_bytes(response.read())
    manifest = {str(p.relative_to(TARGET)).replace('\\', '/'): {
        'size': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in TARGET.rglob('*') if p.is_file() and p.name != 'runtime-manifest.json'}
    (TARGET / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Verified Windows runtime files:', len(manifest))


if __name__ == '__main__':
    main()
