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
from http import HTTPStatus
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
    except urllib.error.HTTPError:
        return None
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if not body.get("ok") or "meta" not in body:
        return None
    return body["meta"]


def _legacy_token_console_at(base_url: str, *, timeout: float = 1.5) -> bool:
    """Pre-0.3.6 consoles required a token for every /api/* call including /api/meta."""
    url = base_url.rstrip("/") + "/api/meta"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        return exc.code == HTTPStatus.UNAUTHORIZED
    except (OSError, TimeoutError, urllib.error.URLError):
        return False
    else:
        return False


def _legacy_ui_at(base_url: str, *, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(base_url, timeout=timeout) as response:
            chunk = response.read(16000)
    except (OSError, TimeoutError, urllib.error.URLError):
        return False
    text = chunk.decode("utf-8", errors="replace")
    return "tokenGate" in text or "__UB_CONSOLE_TOKEN__" in text


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


def _terminate_listeners(port: int, *, except_pid: int | None = None) -> list[int]:
    stopped: list[int] = []
    for pid in _pids_listening_on_loopback(port):
        if except_pid is not None and pid == except_pid:
            continue
        _terminate_pid(pid)
        stopped.append(pid)
    return stopped


def stop_prior_console_on_port(host: str, port: int) -> PriorInstanceResult:
    if host not in {"127.0.0.1", "localhost", "::1"} or port == 0:
        return PriorInstanceResult(stopped=False)

    base = f"http://127.0.0.1:{port}/"
    listeners = _pids_listening_on_loopback(port)
    if not listeners:
        return PriorInstanceResult(stopped=False)

    legacy = _legacy_token_console_at(base) or _legacy_ui_at(base)
    meta = _meta_at(base)
    my_pid = os.getpid()

    if meta is not None:
        old_version = meta.get("version", "?")
        if _shutdown_at(base) and _wait_port_free(port):
            return PriorInstanceResult(
                stopped=True,
                message=(
                    f"已关闭本机端口 {port} 上的旧控制台（v{old_version}），正在启动新版本。"
                ),
            )

    should_clear = legacy or meta is not None
    if not should_clear:
        should_clear = any(
            _is_ub_console_commandline(_command_line(pid))
            for pid in listeners
            if pid != my_pid
        )

    if not should_clear:
        return PriorInstanceResult(
            stopped=False,
            message=(
                f"端口 {port} 已被其它程序占用。"
                "请关闭占用该端口的程序后，再双击 open-console.bat。"
            ),
        )

    stopped_pids = _terminate_listeners(port, except_pid=my_pid)
    if _wait_port_free(port):
        if legacy:
            return PriorInstanceResult(
                stopped=True,
                message=(
                    f"已结束端口 {port} 上仍要求 token 的旧控制台"
                    f"（进程 {stopped_pids[0] if stopped_pids else '?'}），"
                    "正在启动无 token 的新版本。请关闭浏览器里旧的 127.0.0.1 标签页。"
                ),
            )
        if meta is not None:
            return PriorInstanceResult(
                stopped=True,
                message=(
                    f"已结束占用端口 {port} 的旧控制台（v{meta.get('version', '?')}）。"
                    "请只保留本次打开的黑色窗口。"
                ),
            )
        return PriorInstanceResult(
            stopped=True,
            message=(
                f"已结束占用端口 {port} 的旧控制台进程。"
                "请只保留本次打开的黑色窗口。"
            ),
        )

    if legacy or meta is not None:
        return PriorInstanceResult(
            stopped=False,
            message=(
                f"端口 {port} 仍被旧控制台占用"
                f"{'（旧版需 token）' if legacy else ''}。"
                "请手动关闭所有黑色窗口后重试。"
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
