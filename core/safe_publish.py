"""Stage complete outputs, keep backups and restore originals on publish failure."""
import json
import hashlib
import os
import shutil
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager, ExitStack
from pathlib import Path
from functools import wraps

_GUARD = threading.Lock()
_LOCKS = {}


class ConcurrentBookChange(RuntimeError):
    pass


def file_state(path):
    try:
        stat = os.stat(path)
        return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    except FileNotFoundError:
        return None


def _temporary(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".novel-stage-", suffix=target.suffix, dir=target.parent)
    os.close(descriptor)
    return Path(name)


def _validate(path):
    if path.stat().st_size == 0:
        raise ValueError("导出文件为空，原文件未修改。")
    if path.suffix.lower() == ".epub":
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None or archive.read("mimetype") != b"application/epub+zip":
                raise ValueError("EPUB 校验失败，原文件未修改。")
            archive.read("META-INF/container.xml")
            archive.read("OEBPS/content.opf")
            for name in archive.namelist():
                if name.endswith((".xml", ".opf", ".xhtml", ".ncx")):
                    ET.fromstring(archive.read(name))
    elif path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as file:
            json.load(file)


@contextmanager
def _process_lock(target):
    directory = target.parent / ".novel-locks"
    directory.mkdir(exist_ok=True)
    path = directory / (hashlib.sha256(str(target).encode()).hexdigest() + ".lock")
    with path.open("a+b") as lockfile:
        lockfile.seek(0, os.SEEK_END)
        if lockfile.tell() == 0:
            lockfile.write(b"0")
            lockfile.flush()
        lockfile.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ConcurrentBookChange("另一任务正在发布此书，请稍后重试。") from error
        try:
            yield
        finally:
            lockfile.seek(0)
            if os.name == "nt":
                msvcrt.locking(lockfile.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lockfile, fcntl.LOCK_UN)


@contextmanager
def publish_outputs(paths, expected=None):
    """Expose temporary output paths; publish only after every export validates.

    Each replacement is atomic. An ordinary exception rolls the whole batch back.
    A power loss between replacements can leave mixed versions; .bak files retain
    the previous versions for recovery. Expected states reject stale concurrent jobs.
    """
    targets = [Path(path).resolve() for path in paths]
    if len(set(targets)) != len(targets):
        raise ValueError("重复的导出目标。")
    staged, originals, backups = {}, {}, {}
    replaced = []
    try:
        for target in targets:
            staged[target] = _temporary(target)
        yield {str(target): str(staged[target]) for target in targets}
        for path in staged.values():
            _validate(path)
        with ExitStack() as locks:
            for target in sorted(targets):
                with _GUARD:
                    lock = _LOCKS.setdefault(str(target), threading.RLock())
                locks.enter_context(lock)
                locks.enter_context(_process_lock(target))
            if expected is not None:
                for target in targets:
                    if file_state(target) != expected[str(target)]:
                        raise ConcurrentBookChange("书籍已被另一任务更新，请重新执行；本次未覆盖文件。")
            for target in targets:
                if target.exists():
                    original = _temporary(target)
                    originals[target] = original
                    shutil.copyfile(target, original)
                    backup = _temporary(target)
                    backups[target] = backup
                    shutil.copyfile(original, backup)
            for target, backup in backups.items():
                os.replace(backup, str(target) + ".bak")
            try:
                for target, path in staged.items():
                    os.replace(path, target)
                    replaced.append(target)
            except BaseException:
                for target in reversed(replaced):
                    if target in originals:
                        os.replace(originals[target], target)
                    else:
                        target.unlink(missing_ok=True)
                raise
    finally:
        for path in list(staged.values()) + list(originals.values()) + list(backups.values()):
            path.unlink(missing_ok=True)


def capture_states(paths):
    return {str(Path(path).resolve()): file_state(path) for path in paths}


def atomic_export(function):
    """Make standalone formatter calls safe, preserving outer batch staging."""
    @wraps(function)
    def wrapped(output_path, *args, **kwargs):
        path = Path(output_path).resolve()
        if path.name.startswith(".novel-stage-"):
            return function(output_path, *args, **kwargs)
        with publish_outputs([str(path)], expected=capture_states([path])) as staged:
            function(staged[str(path)], *args, **kwargs)
        return output_path
    return wrapped
