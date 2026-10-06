"""Reconstruct the pinned community reader with the reviewed patch."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "client" / "legado-source"
BASE = "c290beb185172801040ac3d4c519ec07db867ae7"
TAG = "3.26.100113"
UPSTREAM = "https://github.com/huajideshutiao/legado.git"
PATCH = ROOT / "client" / "legado-epubfix.patch"

def git(*args, check=True):
    return subprocess.run(["git", "-C", str(SOURCE), *args], check=check, capture_output=True, text=True)

def main():
    if not SOURCE.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", TAG, UPSTREAM, str(SOURCE)], check=True)
    if git("rev-parse", "HEAD").stdout.strip() != BASE:
        raise SystemExit("Unexpected source revision; existing checkout was left untouched.")
    if git("apply", "--reverse", "--check", str(PATCH), check=False).returncode == 0:
        print("Pinned source already contains the patch.")
        return
    if git("status", "--porcelain").stdout.strip():
        raise SystemExit("Source has other changes; refusing to overwrite them.")
    git("apply", "--check", str(PATCH))
    git("apply", str(PATCH))
    print("Pinned source prepared:", SOURCE)

if __name__ == "__main__":
    main()
