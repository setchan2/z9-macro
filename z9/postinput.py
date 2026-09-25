"""창 메시지로 입력 보내기 — 이른바 '배경 입력'.

SendInput은 **포그라운드 창**으로 간다. 그래서 게임이 앞에 나와 있어야 하고,
그동안 사용자는 마우스·키보드를 건드릴 수 없다. PostMessage는 특정 창의 메시지
큐에 직접 넣으므로 그 창이 뒤에 있어도, 최소화돼 있어도 전달된다.

다만 **게임이 받아들인다는 보장은 없다.** 창 메시지를 읽는 방식으로 만든
프로그램에는 통하지만, 다음 경우에는 아무 일도 일어나지 않는다:

  - DirectInput / Raw Input 으로 입력을 받는 게임
  - GetAsyncKeyState 로 키 상태를 직접 훑는 게임
  - 포그라운드가 아니면 스스로 입력을 무시하도록 만든 게임

어느 쪽인지는 코드로 알아낼 방법이 없다. 실제로 넣어 보고 게임이 반응하는지
봐야 한다(engine.background_input_test 참고). 그래서 이 방식은 기본값이 아니라
설정에서 켜는 선택지로 둔다.

좌표는 전부 **클라이언트 기준**이다. 화면 절대좌표가 아니다 — 창이 뒤에 있거나
최소화돼 있으면 화면 좌표라는 개념 자체가 의미가 없기 때문이다.
"""

from __future__ import annotations

from . import win32 as w
from .keys import EXTENDED_VKS

BUTTON_MESSAGES = {
    "left": (w.WM_LBUTTONDOWN, w.WM_LBUTTONUP, w.MK_LBUTTON),
    "right": (w.WM_RBUTTONDOWN, w.WM_RBUTTONUP, w.MK_RBUTTON),
    "middle": (w.WM_MBUTTONDOWN, w.WM_MBUTTONUP, w.MK_MBUTTON),
}


class PostError(OSError):
    """창에 메시지를 넣지 못했다 (창이 사라졌거나 권한이 모자람)."""


def _post(hwnd: int, message: int, wparam: int, lparam: int) -> None:
    if not w.user32.PostMessageW(hwnd, message, wparam, lparam):
        raise PostError(f"PostMessage 실패 (message=0x{message:04X})")


def _key_lparam(vk: int, up: bool) -> int:
    """WM_KEYDOWN/WM_KEYUP의 lParam.

    비트 배치는 Windows가 정해 둔 것이다:
      0-15  반복 횟수      16-23 스캔코드      24    확장 키
      29    ALT 눌림       30    직전 상태     31    전이 상태(뗌=1)
    직전 상태와 전이 상태를 제대로 채워야, 이 둘을 보고 눌림/뗌을 구분하는
    프로그램에서도 오작동하지 않는다.
    """
    scan = w.user32.MapVirtualKeyW(vk, w.MAPVK_VK_TO_VSC) & 0xFF
    lparam = 1 | (scan << 16)
    if vk in EXTENDED_VKS:
        lparam |= 1 << 24
    if up:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


def _xy(cx: int, cy: int) -> int:
    # 음수 좌표도 그대로 실어야 한다. 16비트 두 칸에 나눠 담는다.
    return ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)


# --------------------------------------------------------------------------
def key(hwnd: int, vk: int, down: bool) -> None:
    message = w.WM_KEYDOWN if down else w.WM_KEYUP
    _post(hwnd, message, vk, _key_lparam(vk, not down))


def move(hwnd: int, cx: int, cy: int, buttons: int = 0) -> None:
    _post(hwnd, w.WM_MOUSEMOVE, buttons, _xy(cx, cy))


def button(hwnd: int, name: str, down: bool, cx: int, cy: int) -> None:
    entry = BUTTON_MESSAGES.get(name)
    if entry is None:
        raise PostError(f"알 수 없는 버튼: {name}")
    down_msg, up_msg, flag = entry
    # 누르는 동안에는 그 버튼이 눌려 있다고 알려야 드래그가 성립한다.
    _post(hwnd, down_msg if down else up_msg, flag if down else 0, _xy(cx, cy))


def wheel(hwnd: int, delta: int, screen_x: int, screen_y: int) -> None:
    """WM_MOUSEWHEEL만은 lParam이 **화면 좌표**다 (Windows 규칙)."""
    _post(hwnd, w.WM_MOUSEWHEEL, (delta & 0xFFFF) << 16, _xy(screen_x, screen_y))


__all__ = ["key", "move", "button", "wheel", "PostError", "BUTTON_MESSAGES"]
