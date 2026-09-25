"""전역 저수준 키보드/마우스 훅.

훅은 설치한 스레드가 메시지 루프를 돌아야 콜백이 호출된다. 그래서 전용 스레드
하나가 WH_KEYBOARD_LL / WH_MOUSE_LL을 모두 설치하고 메시지를 펌프한다.

콜백은 반드시 빨라야 한다. Windows는 저수준 훅 콜백이 LowLevelHooksTimeout
(기본 300ms)을 넘기면 그 훅을 조용히 제거해 버린다. 따라서 리스너는 판단만
하고 실제 작업은 다른 스레드로 넘긴다.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Callable

from . import win32 as w

MOUSE_BUTTON_BY_MSG = {
    w.WM_LBUTTONDOWN: ("left", False),
    w.WM_LBUTTONUP: ("left", True),
    w.WM_RBUTTONDOWN: ("right", False),
    w.WM_RBUTTONUP: ("right", True),
    w.WM_MBUTTONDOWN: ("middle", False),
    w.WM_MBUTTONUP: ("middle", True),
}

KEY_DOWN_MSGS = {w.WM_KEYDOWN, w.WM_SYSKEYDOWN}
KEY_UP_MSGS = {w.WM_KEYUP, w.WM_SYSKEYUP}


@dataclass
class HookEvent:
    kind: str  # "key" | "button" | "move" | "wheel"
    t: float = field(default_factory=time.perf_counter)
    vk: int = 0
    scan: int = 0
    down: bool = False
    injected: bool = False
    x: int = 0
    y: int = 0
    button: str = ""
    wheel: int = 0


Listener = Callable[[HookEvent], bool]
"""리스너는 이벤트를 받고, True를 반환하면 그 입력을 삼킨다(게임에 전달 안 됨)."""


class HookManager:
    WATCHDOG_MS = 1000

    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self.listener_errors = 0
        self.on_listener_error: Callable[[str], None] | None = None
        self.on_hook_recovered: Callable[[], None] | None = None
        self.events_seen = 0
        self.reinstalls = 0
        self.hook_deaths = 0
        # 마우스 이동은 초당 수백 건씩 들어온다. 그때마다 파이썬 콜백으로 올라오면
        # 훅 스레드가 밀리고, Windows는 제한 시간 안에 응답하지 않는 저수준 훅을
        # 말없이 제거해 버린다(= 핫키와 비상 정지가 죽는다). 그래서 이동이 실제로
        # 필요한 동안(녹화 중)에만 켠다.
        self._move_subscribers = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._tid: int = 0
        self._ready = threading.Event()
        self._error: str | None = None
        # 콜백 객체는 훅이 살아있는 동안 GC되면 안 되므로 인스턴스에 붙들어 둔다.
        self._kb_proc: w.HOOKPROC | None = None
        self._ms_proc: w.HOOKPROC | None = None
        self._kb_hook = None
        self._ms_hook = None

    # -- 리스너 관리 -------------------------------------------------------
    def add_listener(self, fn: Listener) -> None:
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def remove_listener(self, fn: Listener) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    # -- 마우스 이동 구독 ---------------------------------------------------
    def acquire_mouse_moves(self) -> None:
        with self._lock:
            self._move_subscribers += 1

    def release_mouse_moves(self) -> None:
        with self._lock:
            self._move_subscribers = max(0, self._move_subscribers - 1)

    @property
    def wants_mouse_moves(self) -> bool:
        return self._move_subscribers > 0

    def _dispatch(self, event: HookEvent) -> bool:
        self.events_seen += 1
        with self._lock:
            listeners = list(self._listeners)
        suppress = False
        for fn in listeners:
            try:
                if fn(event):
                    suppress = True
            except Exception as exc:  # noqa: BLE001
                # 리스너 하나가 죽어도 훅 전체는 살려둔다. 다만 조용히 삼키면
                # "이벤트가 안 온다"로만 보여서 원인을 찾을 수 없으므로 남긴다.
                self.listener_errors += 1
                if self.on_listener_error is not None:
                    try:
                        self.on_listener_error(f"{getattr(fn, '__name__', fn)}: {exc!r}")
                    except Exception:  # noqa: BLE001
                        pass
        return suppress

    # -- 수명 주기 ---------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 3.0) -> None:
        if self.running:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="z9-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("훅 스레드가 시간 내에 준비되지 않았습니다.")
        if self._error:
            raise RuntimeError(self._error)

    def stop(self) -> None:
        if self._tid:
            w.user32.PostThreadMessageW(self._tid, w.WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._tid = 0

    # -- 훅 스레드 ---------------------------------------------------------
    def _run(self) -> None:
        self._tid = w.kernel32.GetCurrentThreadId()
        module = w.kernel32.GetModuleHandleW(None)

        self._kb_proc = w.HOOKPROC(self._on_keyboard)
        self._ms_proc = w.HOOKPROC(self._on_mouse)

        self._kb_hook = w.user32.SetWindowsHookExW(
            w.WH_KEYBOARD_LL, self._kb_proc, module, 0
        )
        self._ms_hook = w.user32.SetWindowsHookExW(
            w.WH_MOUSE_LL, self._ms_proc, module, 0
        )

        if not self._kb_hook or not self._ms_hook:
            err = ctypes.get_last_error()
            self._error = (
                f"전역 훅 설치 실패 (WinErr {err}). "
                "관리자 권한으로 실행 중인 다른 프로그램이 원인일 수 있습니다."
            )
            self._ready.set()
            self._cleanup_hooks()
            return

        self._ready.set()

        # 자가 복구 타이머. Windows는 저수준 훅이 제한 시간(LowLevelHooksTimeout,
        # 기본 300ms) 안에 응답하지 못했다고 판단하면 아무 통보 없이 훅을 제거한다.
        # GC나 일시적인 GIL 경합만으로도 걸릴 수 있고, 그 뒤로는 핫키와 비상 정지가
        # 조용히 먹통이 된다. 막을 방법이 없으므로 주기적으로 다시 건다.
        timer_id = w.user32.SetTimer(None, 0, self.WATCHDOG_MS, None)

        msg = wintypes.MSG()
        while True:
            ret = w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):  # WM_QUIT 또는 오류
                break
            if msg.message == w.WM_TIMER:
                self._reinstall(module)
                continue
            w.user32.TranslateMessage(ctypes.byref(msg))
            w.user32.DispatchMessageW(ctypes.byref(msg))

        if timer_id:
            w.user32.KillTimer(None, timer_id)
        self._cleanup_hooks()

    def _reinstall(self, module) -> None:
        """훅을 떼었다 다시 건다.

        UnhookWindowsHookEx가 실패하면 = 시스템이 이미 떼어간 상태였다는 뜻이라,
        그때만 경고를 남긴다.
        """
        was_dead = False
        if self._kb_hook and not w.user32.UnhookWindowsHookEx(self._kb_hook):
            was_dead = True
        if self._ms_hook and not w.user32.UnhookWindowsHookEx(self._ms_hook):
            was_dead = True

        self._kb_hook = w.user32.SetWindowsHookExW(
            w.WH_KEYBOARD_LL, self._kb_proc, module, 0
        )
        self._ms_hook = w.user32.SetWindowsHookExW(
            w.WH_MOUSE_LL, self._ms_proc, module, 0
        )
        self.reinstalls += 1

        if was_dead:
            self.hook_deaths += 1
            if self.on_hook_recovered is not None:
                try:
                    self.on_hook_recovered()
                except Exception:  # noqa: BLE001
                    pass

    def _cleanup_hooks(self) -> None:
        if self._kb_hook:
            w.user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None
        if self._ms_hook:
            w.user32.UnhookWindowsHookEx(self._ms_hook)
            self._ms_hook = None

    # -- 콜백 --------------------------------------------------------------
    def _on_keyboard(self, code: int, wparam: int, lparam: int) -> int:
        if code == w.HC_ACTION:
            data = ctypes.cast(lparam, ctypes.POINTER(w.KBDLLHOOKSTRUCT)).contents
            msg = wparam & 0xFFFFFFFF
            if msg in KEY_DOWN_MSGS or msg in KEY_UP_MSGS:
                event = HookEvent(
                    kind="key",
                    vk=data.vkCode,
                    scan=data.scanCode,
                    down=msg in KEY_DOWN_MSGS,
                    injected=bool(data.flags & w.LLKHF_INJECTED)
                    or data.dwExtraInfo == w.INJECT_SIGNATURE,
                )
                if self._dispatch(event):
                    return 1
        return w.user32.CallNextHookEx(None, code, wparam, lparam)

    def _on_mouse(self, code: int, wparam: int, lparam: int) -> int:
        if code == w.HC_ACTION:
            msg = wparam & 0xFFFFFFFF
            # 아무도 이동을 안 볼 때는 구조체 역참조조차 하지 않고 즉시 통과시킨다.
            if msg == w.WM_MOUSEMOVE and self._move_subscribers == 0:
                return w.user32.CallNextHookEx(None, code, wparam, lparam)
            data = ctypes.cast(lparam, ctypes.POINTER(w.MSLLHOOKSTRUCT)).contents
            injected = (
                bool(data.flags & w.LLMHF_INJECTED)
                or data.dwExtraInfo == w.INJECT_SIGNATURE
            )
            event: HookEvent | None = None

            if msg == w.WM_MOUSEMOVE:
                event = HookEvent(
                    kind="move", x=data.pt.x, y=data.pt.y, injected=injected
                )
            elif msg in MOUSE_BUTTON_BY_MSG:
                button, is_up = MOUSE_BUTTON_BY_MSG[msg]
                event = HookEvent(
                    kind="button",
                    button=button,
                    down=not is_up,
                    x=data.pt.x,
                    y=data.pt.y,
                    injected=injected,
                )
            elif msg in (w.WM_XBUTTONDOWN, w.WM_XBUTTONUP):
                which = (data.mouseData >> 16) & 0xFFFF
                event = HookEvent(
                    kind="button",
                    button="x1" if which == w.XBUTTON1 else "x2",
                    down=msg == w.WM_XBUTTONDOWN,
                    x=data.pt.x,
                    y=data.pt.y,
                    injected=injected,
                )
            elif msg == w.WM_MOUSEWHEEL:
                delta = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value
                event = HookEvent(
                    kind="wheel",
                    wheel=delta,
                    x=data.pt.x,
                    y=data.pt.y,
                    injected=injected,
                )

            if event is not None and self._dispatch(event):
                return 1
        return w.user32.CallNextHookEx(None, code, wparam, lparam)


HOOKS = HookManager()
