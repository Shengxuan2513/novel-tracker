"""Immutable on-disk snapshots for versioned remote book reads."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import threading

_LOCK = threading.Lock()


def file_version(stat):
    return f"{stat.st_mtime_ns}-{stat.st_size}"


class StaleDownload(Exception):
    pass


def snapshot_file(path, version):
    """Copy once per version; never send the mutable source through FileResponse.

    Writers must update modification time when replacing content. Before/after
    checks detect writes during copying; atomic replacement is recommended.
    Snapshots remain until explicitly removed while the server is stopped.
    """
    path = Path(path)
    with _LOCK:
        current = path.stat()
        if file_version(current) != version:
            raise StaleDownload
        cache = path.parent / ".download-snapshots"
        cache.mkdir(exist_ok=True)
        key = hashlib.sha256((str(path.resolve()) + ":" + version).encode()).hexdigest()
        target = cache / (key + path.suffix)
        if target.is_file():
            return target
        temporary = None
        try:
            with path.open("rb") as source:
                before = os.fstat(source.fileno())
                if file_version(before) != version:
                    raise StaleDownload
                with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                    temporary = Path(output.name)
                    shutil.copyfileobj(source, output)
                after = os.fstat(source.fileno())
            latest = path.stat()
            identity = lambda st: (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
            # Windows may report a different inode through fstat than stat.
            if (identity(before) != identity(after)
                    or identity(current) != identity(latest)
                    or file_version(latest) != version):
                raise StaleDownload
            if temporary.stat().st_size != before.st_size:
                raise StaleDownload
            os.utime(temporary, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(temporary, target)
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
