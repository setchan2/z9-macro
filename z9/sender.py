"""SendInput 기반 입력 전송.

정확도 관련 핵심 두 가지:
1. 키는 가상키가 아니라 **스캔코드**로 보낸다. 구형/DirectInput 계열 클라이언트는
   가상키 이벤트를 무시하는 경우가 많다.
2. keyup에도 반드시 KEYEVENTF_SCANCODE를 함께 OR 해야 한다. 빼먹으면 게임이
   키가 계속 눌린 상태로 인식하는 '키 고착' 현상이 생긴다.
"""

from __future__ import annotations

import ctypes
import time

from . import win32 as w
from .keys import EXTENDED_VKS, MOUSE_VKS

BUTTON_FLAGS = {
    "left": (w.MOUSEEVENTF_LEFTDOWN, w.MOUSEEVENTF_LEFTUP, 0),
    "right": (w.MOUSEEVENTF_RIGHTDOWN, w.MOUSEEVENTF_RIGHTUP, 0),
    "middle": (w.MOUSEEVENTF_MIDDLEDOWN, w.MOUSEEVENTF_MIDDLEUP, 0),
    "x1": (w.MOUSEEVENTF_XDOWN, w.MOUSEEVENTF_XUP, w.XBUTTON1),
    "x2": (w.MOUSEEVENTF_XDOWN, w.MOUSEEVENTF_XUP, w.XBUTTON2),
}


def _send(inputs: list[w.INPUT]) -> int:
    if not inputs:
        return 0
    arr = (w.INPUT * len(inputs))(*inputs)
    sent = w.user32.SendInput(len(inputs), arr, ctypes.sizeof(w.INPUT))
    if sent != len(inputs):
        err = ctypes.get_last_error()
        raise OSError(f"SendInput 실패 (보냄 {sent}/{len(inputs)}, WinErr {err})")
    return sent


def _key_input(vk: int, up: bool, use_scancode: bool = True) -> w.INPUT:
    scan = w.user32.MapVirtualKeyW(vk, w.MAPVK_VK_TO_VSC)
    flags = w.KEYEVENTF_KEYUP if up else 0
    if use_scancode and scan:
        # 스캔코드 모드: wVk는 0, wScan에 스캔코드. keyup에도 SCANCODE 유지.
        flags |= w.KEYEVENTF_SCANCODE
        if vk in EXTENDED_VKS:
            flags |= w.KEYEVENTF_EXTENDEDKEY
        wvk = 0
    else:
        wvk = vk
    inp = w.INPUT(type=w.INPUT_KEYBOARD)
    inp.ki = w.KEYBDINPUT(
        wVk=wvk,
        wScan=scan,
        dwFlags=flags,
        time=0,
        dwExtraInfo=w.INJECT_SIGNATURE,
    )
    return inp


def key_down(vk: int, use_scancode: bool = True) -> None:
    _send([_key_input(vk, up=False, use_scancode=use_scancode)])


def key_up(vk: int, use_scancode: bool = True) -> None:
    _send([_key_input(vk, up=True, use_scancode=use_scancode)])


def key_tap(vk: int, hold_ms: int = 30, use_scancode: bool = True) -> None:
    key_down(vk, use_scancode)
    if hold_ms > 0:
        precise_sleep(hold_ms / 1000.0)
    key_up(vk, use_scancode)


def key_combo(vks: list[int], hold_ms: int = 30, use_scancode: bool = True) -> None:
    """수정자를 포함한 조합키. 누른 역순으로 뗀다."""
    for vk in vks:
        key_down(vk, use_scancode)
    if hold_ms > 0:
        precise_sleep(hold_ms / 1000.0)
    for vk in reversed(vks):
        key_up(vk, use_scancode)


def release_all(vks: list[int] | None = None, use_scancode: bool = True) -> list[int]:
    """실제로 눌려 있는 키를 강제로 뗀다. 매크로 중단 후 '키 고착' 복구용.

    반환값: 실제로 떼어낸 VK 목록.
    """
    if vks is None:
        # 수정자 + 방향키 + 알파벳/숫자/F키 등 흔히 쓰는 범위만 훑는다.
        vks = (
            [0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C]
            + list(range(0x20, 0x2F))
            + list(range(0x30, 0x3A))
            + list(range(0x41, 0x5B))
            + list(range(0x60, 0x70))
            + list(range(0x70, 0x88))
            + [0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xDB, 0xDC, 0xDD, 0xDE]
        )
    released: list[int] = []
    batch: list[w.INPUT] = []
    for vk in vks:
        if vk in MOUSE_VKS:
            continue
        if w.user32.GetAsyncKeyState(vk) & 0x8000:
            batch.append(_key_input(vk, up=True, use_scancode=use_scancode))
            released.append(vk)
    if batch:
        _send(batch)
    return released


# --------------------------------------------------------------------------
# 마우스
# --------------------------------------------------------------------------
def _abs_coords(x: int, y: int) -> tuple[int, int]:
    vx, vy, vw, vh = w.virtual_screen()
    vw = max(vw, 1)
    vh = max(vh, 1)
    nx = int(round((x - vx) * 65535.0 / max(vw - 1, 1)))
    ny = int(round((y - vy) * 65535.0 / max(vh - 1, 1)))
    return (max(0, min(65535, nx)), max(0, min(65535, ny)))


def _mouse_input(flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> w.INPUT:
    inp = w.INPUT(type=w.INPUT_MOUSE)
    inp.mi = w.MOUSEINPUT(
        dx=dx,
        dy=dy,
        mouseData=data,
        dwFlags=flags,
        time=0,
        dwExtraInfo=w.INJECT_SIGNATURE,
    )
    return inp


def mouse_move(x: int, y: int) -> None:
    """화면 절대좌표로 커서 이동."""
    nx, ny = _abs_coords(x, y)
    flags = (
        w.MOUSEEVENTF_MOVE
        | w.MOUSEEVENTF_ABSOLUTE
        | w.MOUSEEVENTF_VIRTUALDESK
        | w.MOUSEEVENTF_MOVE_NOCOALESCE
    )
    _send([_mouse_input(flags, nx, ny)])


def mouse_button(button: str, up: bool) -> None:
    down_flag, up_flag, data = BUTTON_FLAGS.get(button, BUTTON_FLAGS["left"])
    _send([_mouse_input(up_flag if up else down_flag, data=data)])


def mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    hold_ms: int = 30,
    settle_ms: int = 15,
) -> None:
    if x is not None and y is not None:
        mouse_move(x, y)
        # 이동 직후 바로 클릭하면 게임이 이전 좌표에서 클릭을 받는 경우가 있다.
        if settle_ms > 0:
            precise_sleep(settle_ms / 1000.0)
    mouse_button(button, up=False)
    if hold_ms > 0:
        precise_sleep(hold_ms / 1000.0)
    mouse_button(button, up=True)


def mouse_wheel(delta: int) -> None:
    _send([_mouse_input(w.MOUSEEVENTF_WHEEL, data=delta & 0xFFFFFFFF)])


def cursor_pos() -> tuple[int, int]:
    pt = w.wintypes.POINT()
    w.user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


# --------------------------------------------------------------------------
# 정밀 대기
# --------------------------------------------------------------------------
def precise_sleep(seconds: float, stop_check=None, poll: float = 0.005) -> bool:
    """중단 가능한 정밀 sleep. 중단되면 False, 끝까지 잤으면 True.

    스핀(busy-wait)은 절대 쓰지 않는다. 파이썬 스핀 루프는 GIL을 붙잡고 있어서
    전역 훅 콜백 스레드를 굶기고, Windows는 제한 시간(기본 300ms) 안에 응답하지
    않는 저수준 훅을 말없이 제거해 버린다. 그러면 비상 정지 핫키가 먹통이 된다.

    대신 시간을 잘게 나눠 자되, 남은 시간은 매번 **절대 종료 시각**에서 다시
    계산한다. 이러면 sleep 오차가 누적되지 않고 마지막 1회분만 남는다.
    파이썬 3.11+의 time.sleep은 Windows 고해상도 타이머를 쓰므로 그 오차도 1ms
    수준이다.
    """
    if seconds <= 0:
        return not (stop_check and stop_check())
    end = time.perf_counter() + seconds
    while True:
        remaining = end - time.perf_counter()
        if remaining <= 0:
            return True
        if stop_check is None:
            time.sleep(remaining)
            return True
        if stop_check():
            return False
        time.sleep(min(poll, remaining))
