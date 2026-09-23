"""Replace a stale Universal Browser console still listening on loopback."""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PriorInstanceResult:
    stopped: bool
    message: str | None = None


def _meta_at(base_url: str, *, timeout: float = 1.5) -> dict[str, Any] | None:
    url = base_url.rstrip("/") + "/api/meta"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if not body.get("ok") or "meta" not in body:
        return None
    return body["meta"]


def _shutdown_at(base_url: str, *, timeout: float = 2.0) -> bool:
    url = base_url.rstrip("/") + "/api/shutdown"
    request = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return bool(body.get("ok"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def _command_line(pid: int) -> str:
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                text=True,
                errors="replace",
                timeout=8,
            )
            return output.strip()
        except subprocess.SubprocessError:
            return ""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
    except OSError:
        return ""


def _is_ub_console_commandline(command: str) -> bool:
    lowered = command.lower()
    if "invoke.py" in lowered and " ui" in lowered:
        return True
    return "browser_skill" in lowered and "console" in lowered


def _pids_listening_on_loopback(port: int) -> list[int]:
    pids: list[int] = []
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(
                ["netstat", "-ano"], text=True, errors="replace", timeout=10
            )
        except subprocess.SubprocessError:
            return []
        needle = f":{port}"
        for line in output.splitlines():
            if "LISTENING" not in line.upper() or needle not in line:
                continue
            parts = line.split()
            try:
                pid = int(parts[-1])
            except (IndexError, ValueError):
                continue
            if pid > 0:
                pids.append(pid)
        return sorted(set(pids))

    for command in (
        ["ss", "-ltnp", f"sport = :{port}"],
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
    ):
        try:
            output = subprocess.check_output(command, text=True, errors="replace", timeout=5)
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
        if command[0] == "lsof":
            for line in output.splitlines():
                if line.strip().isdigit():
                    pids.append(int(line.strip()))
            if pids:
                return sorted(set(pids))
        for match in re.finditer(r"pid=(\d+)", output):
            pids.append(int(match.group(1)))
        if pids:
            return sorted(set(pids))
    return sorted(set(pids))


def _wait_port_free(port: int, *, attempts: int = 40) -> bool:
    for _ in range(attempts):
        if not _pids_listening_on_loopback(port):
            return True
        time.sleep(0.1)
    return not _pids_listening_on_loopback(port)


def _terminate_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)


def stop_prior_console_on_port(host: str, port: int) -> PriorInstanceResult:
    if host not in {"127.0.0.1", "localhost", "::1"} or port == 0:
        return PriorInstanceResult(stopped=False)

    base = f"http://127.0.0.1:{port}/"
    meta = _meta_at(base)
    if meta is not None:
        old_version = meta.get("version", "?")
        if _shutdown_at(base) and _wait_port_free(port):
            return PriorInstanceResult(
                stopped=True,
                message=(
                    f"已关闭本机端口 {port} 上的旧控制台（v{old_version}），正在启动新版本。"
                ),
            )

    my_pid = os.getpid()
    for pid in _pids_listening_on_loopback(port):
        if pid == my_pid:
            continue
        command = _command_line(pid)
        if meta is not None or _is_ub_console_commandline(command):
            _terminate_pid(pid)
            if _wait_port_free(port):
                detail = f"（PID {pid}）" if pid else ""
                return PriorInstanceResult(
                    stopped=True,
                    message=(
                        f"已结束占用端口 {port} 的旧控制台进程{detail}。"
                        "请只保留本次打开的黑色窗口。"
                    ),
                )

    if meta is not None:
        return PriorInstanceResult(
            stopped=False,
            message=(
                f"端口 {port} 仍被旧控制台占用（v{meta.get('version', '?')}）。"
                "请关闭所有旧的黑色窗口后，再双击 open-console.bat。"
            ),
        )
    return PriorInstanceResult(stopped=False)


def ensure_loopback_port_free(host: str, port: int) -> PriorInstanceResult:
    if os.environ.get("UNIVERSAL_BROWSER_CONSOLE_KEEP_OLD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return PriorInstanceResult(stopped=False)
    return stop_prior_console_on_port(host, port)
