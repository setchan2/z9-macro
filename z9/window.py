"""대상 게임 창 탐색 / 활성화 / 좌표 변환."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable

from . import win32 as w


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str


def _own_process_id() -> int:
    return w.kernel32.GetCurrentProcessId()


def _window_process_id(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    w.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def list_windows(
    pattern: str = "", visible_only: bool = True, exclude_own: bool = True
) -> list[WindowInfo]:
    """제목에 pattern이 포함된 최상위 창 목록. pattern이 비면 제목 있는 창 전부.

    exclude_own: 이 프로그램 자신의 창은 제외한다. 매크로 창 제목에 게임 이름이
    들어가 있으면 자기 자신을 대상으로 잡아버리기 때문이다.
    """
    needle = pattern.strip().lower()
    own_pid = _own_process_id() if exclude_own else 0
    found: list[WindowInfo] = []

    def _cb(hwnd: int, _lparam: int) -> bool:
        if visible_only and not w.user32.IsWindowVisible(hwnd):
            return True
        length = w.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        if own_pid and _window_process_id(hwnd) == own_pid:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        w.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if not needle or needle in title.lower():
            found.append(WindowInfo(hwnd=hwnd, title=title))
        return True

    w.user32.EnumWindows(w.WNDENUMPROC(_cb), 0)
    return found


def find_window(
    pattern: str, exclude_titles: Iterable[str] = ()
) -> WindowInfo | None:
    """패턴에 맞는 창 하나를 고른다.

    부분 일치만 쓰면 "Z9★ 온라인"이 "Z9★ 온라인 매크로 - 편집기" 같은 창에도
    걸린다. 그래서 우선순위를 둔다:
      1) 제목이 패턴과 정확히 같은 창
      2) 제목이 패턴으로 시작하는 창
      3) 나머지 중 제목이 가장 짧은 창 (군더더기가 적을수록 진짜일 확률이 높다)

    exclude_titles: 이 매크로 프로그램 자신의 창 제목. 자기 프로세스는 이미
    걸러지지만, 같은 프로그램을 두 개 띄웠다면 '다른 프로세스'라서 걸리지 않는다.
    게임이 꺼져 있을 때 자기 창에 입력을 쏘는 사고를 막는다.
    """
    matches = list_windows(pattern)
    blocked = {t.strip().lower() for t in exclude_titles if t}
    if blocked:
        matches = [i for i in matches if i.title.strip().lower() not in blocked]
    if not matches:
        return None
    needle = pattern.strip().lower()

    exact = [i for i in matches if i.title.strip().lower() == needle]
    if exact:
        return exact[0]

    prefixed = [i for i in matches if i.title.strip().lower().startswith(needle)]
    if prefixed:
        return min(prefixed, key=lambda i: len(i.title))

    return min(matches, key=lambda i: len(i.title))


class GameWindow:
    """HWND 하나를 감싸고 좌표 변환/활성화를 제공한다."""

    def __init__(self, hwnd: int, title: str = "") -> None:
        self.hwnd = hwnd
        self.title = title

    # -- 상태 -----------------------------------------------------------
    def is_alive(self) -> bool:
        return bool(w.user32.IsWindow(self.hwnd))

    def is_foreground(self) -> bool:
        return w.user32.GetForegroundWindow() == self.hwnd

    def client_size(self) -> tuple[int, int]:
        rect = wintypes.RECT()
        if not w.user32.GetClientRect(self.hwnd, ctypes.byref(rect)):
            return (0, 0)
        return (rect.right - rect.left, rect.bottom - rect.top)

    def client_origin(self) -> tuple[int, int]:
        """클라이언트 영역 (0,0)의 화면 좌표."""
        pt = wintypes.POINT(0, 0)
        if not w.user32.ClientToScreen(self.hwnd, ctypes.byref(pt)):
            return (0, 0)
        return (pt.x, pt.y)

    # -- 좌표 변환 --------------------------------------------------------
    # 창이 움직여도 어긋나지 않도록 호출할 때마다 실시간으로 변환한다.
    # 원점을 캐시해 두면 그 사이 창을 옮겼을 때 입력이 엉뚱한 곳으로 간다.
    # 직접 빼는 대신 Win32 변환 API를 쓰는 이유는 DPI 가상화나 RTL(좌우 반전)
    # 레이아웃까지 OS가 알아서 처리해 주기 때문이다.
    def client_to_screen(self, x: int, y: int) -> tuple[int, int]:
        pt = wintypes.POINT(x, y)
        if not w.user32.ClientToScreen(self.hwnd, ctypes.byref(pt)):
            return (x, y)
        return (pt.x, pt.y)

    def screen_to_client(self, x: int, y: int) -> tuple[int, int]:
        pt = wintypes.POINT(x, y)
        if not w.user32.ScreenToClient(self.hwnd, ctypes.byref(pt)):
            return (x, y)
        return (pt.x, pt.y)

    @property
    def minimized(self) -> bool:
        """최소화된 창은 화면에서 읽을 수 없다 (BitBlt이 빈 그림을 준다)."""
        return bool(w.user32.IsIconic(self.hwnd))

    # -- 활성화 -----------------------------------------------------------
    def activate(self, timeout: float = 1.5) -> bool:
        """창을 포그라운드로 올린다.

        SetForegroundWindow는 다른 프로세스가 포그라운드일 때 거부될 수 있어서
        AttachThreadInput으로 입력 큐를 붙인 뒤 재시도한다.
        """
        if not self.is_alive():
            return False
        if self.is_foreground():
            return True

        if w.user32.IsIconic(self.hwnd):
            w.user32.ShowWindow(self.hwnd, w.SW_RESTORE)

        target_tid = w.user32.GetWindowThreadProcessId(self.hwnd, None)
        current_tid = w.kernel32.GetCurrentThreadId()
        attached = False
        if target_tid and target_tid != current_tid:
            attached = bool(w.user32.AttachThreadInput(current_tid, target_tid, True))
        try:
            w.user32.BringWindowToTop(self.hwnd)
            w.user32.SetForegroundWindow(self.hwnd)
        finally:
            if attached:
                w.user32.AttachThreadInput(current_tid, target_tid, False)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_foreground():
                return True
            time.sleep(0.02)
        return self.is_foreground()


class WindowResolver:
    """패턴으로 창을 찾아 캐시하고, 죽으면 자동으로 다시 찾는다."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        # 이 프로그램 자신의 창 제목들. 자동 탐색에서만 제외한다.
        self.exclude_titles: set[str] = set()
        self._cached: GameWindow | None = None

    def set_pattern(self, pattern: str) -> None:
        if pattern != self.pattern:
            self.pattern = pattern
            self._cached = None

    def pin(self, hwnd: int, title: str = "") -> None:
        """사용자가 창 목록에서 직접 고른 창을 고정한다."""
        self._cached = GameWindow(hwnd, title)

    def get(self) -> GameWindow | None:
        if self._cached is not None and self._cached.is_alive():
            return self._cached
        info = find_window(self.pattern, exclude_titles=self.exclude_titles)
        if info is None:
            self._cached = None
            return None
        self._cached = GameWindow(info.hwnd, info.title)
        return self._cached
