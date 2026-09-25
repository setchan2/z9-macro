"""전역 핫키 — HookManager 위에 올린다.

주입된 입력(우리가 SendInput으로 보낸 것)은 무시한다. 안 그러면 매크로가
자기 핫키를 다시 눌러 무한 재귀에 빠진다.
"""

from __future__ import annotations

import threading
from typing import Callable

from . import win32 as w
from .hooks import HOOKS, HookEvent
from .keys import MODIFIER_VKS, parse_hotkey

_MOD_VKS = {
    "Ctrl": (0x11, 0xA2, 0xA3),
    "Shift": (0x10, 0xA0, 0xA1),
    "Alt": (0x12, 0xA4, 0xA5),
    "Win": (0x5B, 0x5C),
}


def _mod_held(name: str) -> bool:
    return any(w.user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MOD_VKS[name])


def current_mods() -> frozenset[str]:
    """지금 눌려 있는 수정자 집합. 핫키 캡처 UI에서도 쓴다."""
    return frozenset(name for name in _MOD_VKS if _mod_held(name))


class HotkeyManager:
    def __init__(self, on_error: Callable[[str], None] | None = None) -> None:
        self._bindings: dict[tuple[frozenset[str], int], Callable[[], None]] = {}
        self._lock = threading.Lock()
        self._on_error = on_error
        self._attached = False
        # 눌린 채 유지되는 키에서 콜백이 연속 발생하지 않게 down 상태를 추적
        self._active: set[tuple[frozenset[str], int]] = set()

    def attach(self) -> None:
        if not self._attached:
            HOOKS.add_listener(self._on_event)
            self._attached = True

    def detach(self) -> None:
        if self._attached:
            HOOKS.remove_listener(self._on_event)
            self._attached = False

    # -- 등록 --------------------------------------------------------------
    def clear(self) -> None:
        with self._lock:
            self._bindings.clear()

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        parsed = parse_hotkey(hotkey)
        if parsed is None:
            return False
        with self._lock:
            self._bindings[parsed] = callback
        return True

    def unregister(self, hotkey: str) -> None:
        parsed = parse_hotkey(hotkey)
        if parsed is None:
            return
        with self._lock:
            self._bindings.pop(parsed, None)

    def conflicts(self, hotkey: str) -> bool:
        parsed = parse_hotkey(hotkey)
        if parsed is None:
            return False
        with self._lock:
            return parsed in self._bindings

    # -- 훅 콜백 -----------------------------------------------------------
    def _on_event(self, event: HookEvent) -> bool:
        if event.injected:
            return False

        if event.kind == "key":
            vk = event.vk
        elif event.kind == "button":
            vk = {"left": 0x01, "right": 0x02, "middle": 0x04, "x1": 0x05, "x2": 0x06}[
                event.button
            ]
        else:
            return False

        if vk in MODIFIER_VKS:
            return False

        mods = frozenset(name for name in _MOD_VKS if _mod_held(name))
        key = (mods, vk)

        if not event.down:
            self._active.discard(key)
            # keyup도 함께 삼켜야 게임이 반쪽짜리 입력을 받지 않는다.
            with self._lock:
                return key in self._bindings

        with self._lock:
            callback = self._bindings.get(key)
        if callback is None:
            return False

        if key in self._active:
            return True  # 키 반복(auto-repeat) 무시, 하지만 계속 삼킨다
        self._active.add(key)

        # 훅 콜백을 붙잡고 있으면 Windows가 훅을 떼어버린다. 작업은 따로 돌린다.
        threading.Thread(
            target=self._safe_call, args=(callback,), daemon=True
        ).start()
        return True

    def _safe_call(self, callback: Callable[[], None]) -> None:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            if self._on_error:
                self._on_error(f"핫키 실행 중 오류: {exc}")
