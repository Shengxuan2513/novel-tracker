"""Download portable official build tools into ignored storage (no system changes)."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import zipfile
import httpx

ROOT = Path(__file__).resolve().parents[1] / 'storage' / 'reader-toolchain'
ROOT.mkdir(parents=True, exist_ok=True)

def download(name, url, digest=None):
    target = ROOT / name
    if not target.exists():
        with httpx.stream('GET', url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with target.with_suffix('.part').open('wb') as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
        target.with_suffix('.part').replace(target)
    if digest and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError(f'Checksum mismatch: {name}')
    destination = ROOT / name.removesuffix('.zip')
    if not destination.exists():
        destination.mkdir()
        with zipfile.ZipFile(target) as archive:
            archive.extractall(destination)
    print(destination, flush=True)

if __name__ == '__main__':
    assets = httpx.get('https://api.adoptium.net/v3/assets/latest/21/hotspot',
        params={'architecture': 'x64', 'image_type': 'jdk', 'os': 'windows'}, timeout=60).json()
    package = assets[0]['binary']['package']
    java17 = httpx.get('https://api.adoptium.net/v3/assets/latest/17/hotspot',
        params={'architecture': 'x64', 'image_type': 'jdk', 'os': 'windows'}, timeout=60).json()[0]['binary']['package']
    checksum_response = httpx.get('https://services.gradle.org/distributions/gradle-9.6.0-bin.zip.sha256',
        follow_redirects=True, timeout=60)
    checksum_response.raise_for_status()
    gradle_checksum = checksum_response.text.strip()
    tasks = [('jdk21.zip', package['link'], package['checksum']),
        ('jdk17.zip', java17['link'], java17['checksum']),
        ('gradle.zip', 'https://services.gradle.org/distributions/gradle-9.6.0-bin.zip', gradle_checksum),
        ('android-tools.zip', 'https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip',
         '90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a')]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(lambda args: download(*args), tasks):
            pass
