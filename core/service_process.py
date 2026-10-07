"""Identify the project service before stopping a process on a shared port."""
import os
import sysconfig
from pathlib import Path
import psutil


def find_pid_by_port(port):
    try:
        for connection in psutil.net_connections(kind="inet"):
            if connection.laddr and connection.laddr.port == port and connection.status == psutil.CONN_LISTEN:
                return connection.pid
    except psutil.AccessDenied as error:
        raise RuntimeError("没有权限读取监听进程，无法安全停止服务。") from error
    return None


def is_project_service(process):
    root = Path(__file__).resolve().parent.parent
    script = root / "cli.py"
    server = root / "core" / "web_server.py"
    console = Path(sysconfig.get_path("scripts")) / ("novel-tracker.exe" if os.name == "nt" else "novel-tracker")
    try:
        arguments = process.cmdline()
        cwd = Path(process.cwd())
        for index, argument in enumerate(arguments):
            candidate = Path(argument)
            if not candidate.is_absolute():
                candidate = cwd / candidate
            candidate = candidate.resolve()
            if candidate == server:
                return True
            if candidate in (script, console):
                return any(command in arguments[index + 1:] for command in ("web", "legado", "reader"))
    except (psutil.Error, OSError, ValueError):
        return False
    return False


def stop_service(port):
    pid = find_pid_by_port(port)
    if pid is None:
        print(f"端口 {port} 上未发现运行中的服务。")
        return
    try:
        process = psutil.Process(pid)
        started = process.create_time()
        if not is_project_service(process):
            raise RuntimeError(f"端口 {port} 被其他程序占用；请更换端口，原进程未停止。")
        # Check identity again immediately before termination, including PID reuse.
        if process.create_time() != started or find_pid_by_port(port) != pid:
            raise RuntimeError("监听进程已变化，请重新执行；原进程未停止。")
        process.terminate()
        process.wait(timeout=3)
        print(f"已停止 NovelTracker 服务（PID {pid}，端口 {port}）。")
    except psutil.Error as error:
        raise RuntimeError(f"停止服务失败：{error}") from error
