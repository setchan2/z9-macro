"""권한(UIPI) 확인과 관리자 재실행.

이 프로그램에서 가장 흔한 "아무 반응 없음"의 원인이다.

Windows의 UIPI(User Interface Privilege Isolation)는 낮은 권한 프로세스가 높은
권한 프로세스의 창에 입력을 주입하는 것을 막는다. 문제는 **막힐 때 오류가 나지
않는다**는 점이다. SendInput은 "정상적으로 N개 보냈다"고 반환하고, 입력은 조용히
버려진다. 저수준 훅에도 잡히지 않는다 — 애초에 입력 큐에 들어가지 않기 때문이다.

Z9 클라이언트(Z9Star.exe)는 관리자 권한으로 실행되므로, 이 도구도 관리자
권한으로 실행하지 않으면 게임 창이 활성화된 동안 매크로가 전혀 동작하지 않는다.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from . import win32 as w


def _token_elevation(handle) -> bool | None:
    token = wintypes.HANDLE()
    if not w.advapi32.OpenProcessToken(handle, w.TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        elevation = wintypes.DWORD()
        size = wintypes.DWORD()
        ok = w.advapi32.GetTokenInformation(
            token,
            w.TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(size),
        )
        return bool(elevation.value) if ok else None
    finally:
        w.kernel32.CloseHandle(token)


def is_elevated() -> bool:
    """이 프로세스가 관리자 권한인가."""
    result = _token_elevation(w.kernel32.GetCurrentProcess())
    return bool(result)


def process_elevated(pid: int) -> bool | None:
    """다른 프로세스가 관리자 권한인가. 확인 불가면 None.

    권한이 더 높은 프로세스는 열지 못해 None이 나오기도 하는데, 이 경우 자체가
    "상대가 더 높다"는 신호에 가깝다.
    """
    handle = w.kernel32.OpenProcess(w.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _token_elevation(handle)
    finally:
        w.kernel32.CloseHandle(handle)


def process_name(pid: int) -> str:
    handle = w.kernel32.OpenProcess(w.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if w.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1]
        return "?"
    finally:
        w.kernel32.CloseHandle(handle)


def window_process_id(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    w.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def relaunch_as_admin() -> bool:
    """관리자 권한으로 자기 자신을 다시 실행한다. 성공하면 True.

    UAC 프롬프트가 뜨고, 사용자가 거부하면 False.
    """
    executable = sys.executable
    script = sys.argv[0]
    params = " ".join(f'"{a}"' for a in [script, *sys.argv[1:]])
    result = w.shell32.ShellExecuteW(
        None, "runas", executable, params, None, w.SW_SHOWNORMAL
    )
    # ShellExecuteW는 성공 시 32보다 큰 값을 반환한다 (역사적 규약).
    return int(result) > 32
