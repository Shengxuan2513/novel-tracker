"""Package source corresponding to the APK, excluding build output and keys."""
from pathlib import Path
import subprocess
import zipfile
from prepare_reader_source import ROOT, SOURCE, BASE, PATCH

def main():
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    if revision != BASE:
        raise SystemExit("Unexpected reader source revision")
    subprocess.run(["git", "-C", str(SOURCE), "apply", "--reverse", "--check", str(PATCH)], check=True)
    paths = set(subprocess.check_output(["git", "-C", str(SOURCE), "ls-files"], text=True).splitlines())
    paths.update(line[6:] for line in PATCH.read_text(encoding="utf-8").splitlines() if line.startswith("+++ b/"))
    output = ROOT / "storage" / "reader-release"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "legado-epubfix-source.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("SOURCE-README.md", """# EPUB fix source bundle

legado/ contains the complete patched reader source, its licenses and regression tests.
novel-tracker/ contains the companion build scripts, patch and documentation.
To build without relying on the community mirror:
1. Move legado/ to novel-tracker/client/legado-source/.
2. In that source directory, run git init, git add ., and git -c user.name=SourceBundle -c user.email=source@example.invalid commit -m source-bundle.
   The upstream Gradle build requires a Git repository; one commit yields versionCode 10001.
3. From novel-tracker/, follow client/EPUB修复说明.md to prepare the Windows toolchain/SDK and run scripts/build_reader.ps1.
   Skip prepare_reader_source.py when using this extracted bundle.

The APK is signed with the publisher's local debug key; rebuilding generates/uses your own key and cannot guarantee overlay installation over the published APK. No private signing key is included.
Base: c290beb185172801040ac3d4c519ec07db867ae7 (community tag 3.26.100113).
""")
        for name in sorted(paths):
            source = SOURCE / name
            if source.is_file():
                z.write(source, "legado/" + name)
        for name in ["client/legado-epubfix.patch", "client/README.md", "client/EPUB修复说明.md", "client/LEGADO-LICENSE",
                     "scripts/build_reader.ps1", "scripts/prepare_reader_toolchain.py", "scripts/prepare_reader_source.py",
                     "scripts/package_reader_source.py", "client/reader-regression/build.gradle.kts",
                     "client/reader-regression/settings.gradle.kts", "client/reader-regression/.gitignore"]:
            z.write(ROOT / name, "novel-tracker/" + name)
    print(archive)

if __name__ == "__main__":
    main()
