"""재사용 위젯과 캡처 다이얼로그.

핫키/좌표 캡처는 tkinter의 키 이벤트가 아니라 전역 훅을 쓴다. tkinter는 창이
포커스를 가져야만 키를 받고 F키/사이드버튼 처리도 제각각이라, 게임 화면 위에서
좌표를 찍는 용도로는 훅이 훨씬 정확하다.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from .. import pixel
from ..hooks import HOOKS, HookEvent
from ..hotkeys import current_mods
from ..keys import MODIFIER_VKS, format_hotkey
from ..window import GameWindow
from . import theme


class ScrollFrame(ttk.Frame):
    """세로로 넘치면 스크롤되는 칸.

    담을 위젯은 .inner 안에 넣는다. 분할선으로 좁혀 놓아도 아래쪽 설정이
    잘려서 못 쓰게 되지 않도록, 넘칠 때만 스크롤바가 나온다.
    """

    def __init__(self, parent: tk.Misc, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            self, highlightthickness=0, borderwidth=0,
            background=theme.PALETTE["bg"], takefocus=0,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._bar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._bar_shown = False

        self.inner = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._canvas.configure(yscrollcommand=self._on_scroll)

        self.inner.bind("<Configure>", self._sync_region)
        self._canvas.bind("<Configure>", self._sync_width)
        # 휠은 커서가 이 칸 안에 있을 때만 가로챈다. bind_all을 계속 걸어 두면
        # 목록(Treeview) 위에서 굴린 휠까지 여기로 끌려온다.
        self._canvas.bind("<Enter>", self._grab_wheel)
        self._canvas.bind("<Leave>", self._release_wheel)

    # ------------------------------------------------------------------
    def _sync_region(self, _event: object = None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _sync_width(self, event: tk.Event) -> None:
        # 안쪽 내용은 늘 칸 너비를 꽉 채운다 (가로 스크롤은 쓰지 않는다).
        self._canvas.itemconfigure(self._window, width=event.width)

    def _on_scroll(self, first: str, last: str) -> None:
        self._bar.set(first, last)
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self._bar_shown:
            self._bar.grid(row=0, column=1, sticky="ns")
            self._bar_shown = True
        elif not needed and self._bar_shown:
            self._bar.grid_remove()
            self._bar_shown = False

    def _grab_wheel(self, _event: object = None) -> None:
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _release_wheel(self, _event: object = None) -> None:
        self._canvas.unbind_all("<MouseWheel>")

    # 휠로 값이 바뀌는 위젯 위에서는 스크롤을 넘겨주지 않는다.
    _WHEEL_OWNERS = ("TCombobox", "TSpinbox", "Spinbox", "Listbox", "Treeview")

    def _on_wheel(self, event: tk.Event) -> None:
        if not self._bar_shown:  # 다 보이는데 굴리면 아무 일도 없어야 한다
            return
        try:
            if event.widget.winfo_class() in self._WHEEL_OWNERS:
                return
        except (AttributeError, tk.TclError):
            pass
        self._canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")


class _CaptureState:
    def __init__(self) -> None:
        self.result: object = None
        self.done = threading.Event()
        self.cancelled = False


def _modal(parent: tk.Misc, title: str, message: str) -> tk.Toplevel:
    top = tk.Toplevel(parent)
    top.title(title)
    top.resizable(False, False)
    top.attributes("-topmost", True)
    ttk.Label(top, text=message, justify="left", padding=(18, 14)).pack()
    top.update_idletasks()
    # 부모 창 중앙에 띄운다
    px = parent.winfo_rootx() + parent.winfo_width() // 2 - top.winfo_width() // 2
    py = parent.winfo_rooty() + parent.winfo_height() // 2 - top.winfo_height() // 2
    top.geometry(f"+{max(px, 0)}+{max(py, 0)}")
    return top


def _run_capture(
    parent: tk.Misc,
    title: str,
    message: str,
    listener: Callable[[HookEvent], bool],
    state: _CaptureState,
    timeout_s: int = 15,
):
    """훅 리스너를 붙이고 모달을 띄운 뒤, 캡처가 끝날 때까지 폴링한다."""
    top = _modal(parent, title, message)
    HOOKS.add_listener(listener)

    finished = threading.Event()

    def _cancel() -> None:
        state.cancelled = True
        state.done.set()

    top.protocol("WM_DELETE_WINDOW", _cancel)

    deadline = [timeout_s * 1000]

    def _poll() -> None:
        if state.done.is_set() or deadline[0] <= 0:
            HOOKS.remove_listener(listener)
            finished.set()
            try:
                top.grab_release()
            except tk.TclError:
                pass
            top.destroy()
            return
        deadline[0] -= 50
        top.after(50, _poll)

    try:
        top.grab_set()
    except tk.TclError:
        pass
    top.after(50, _poll)
    parent.wait_window(top)

    if state.cancelled:
        return None
    return state.result


# --------------------------------------------------------------------------
# 핫키 캡처
# --------------------------------------------------------------------------
_MOUSE_HOTKEY_VK = {"x1": 0x05, "x2": 0x06}


def capture_hotkey(parent: tk.Misc) -> str | None:
    """다음에 누르는 키 조합을 핫키 문자열로 반환. Esc면 취소."""
    state = _CaptureState()

    def listener(event: HookEvent) -> bool:
        if event.injected or state.done.is_set():
            return False
        if event.kind == "button" and event.button in _MOUSE_HOTKEY_VK:
            if event.down:
                state.result = format_hotkey(
                    current_mods(), _MOUSE_HOTKEY_VK[event.button]
                )
                state.done.set()
            return True
        if event.kind != "key":
            return False
        if event.vk in MODIFIER_VKS:
            return False  # 수정자 단독은 통과시켜 조합키를 계속 받는다
        if not event.down:
            return True
        if event.vk == 0x1B:  # Esc
            state.cancelled = True
        else:
            state.result = format_hotkey(current_mods(), event.vk)
        state.done.set()
        return True

    result = _run_capture(
        parent,
        "핫키 지정",
        "사용할 키를 누르세요.\n수정자(Ctrl/Shift/Alt)를 함께 눌러도 됩니다.\n\nEsc = 취소",
        listener,
        state,
    )
    return result if isinstance(result, str) else None


class HotkeyField(ttk.Frame):
    """핫키 입력 필드 + [지정] [지우기]."""

    def __init__(self, parent: tk.Misc, width: int = 16, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, state="readonly")
        self.entry.pack(side="left")
        ttk.Button(self, text="지정", width=5, command=self._assign).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(self, text="✕", width=3, command=lambda: self.var.set("")).pack(
            side="left", padx=(2, 0)
        )

    def _assign(self) -> None:
        hotkey = capture_hotkey(self.winfo_toplevel())
        if hotkey:
            self.var.set(hotkey)

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str) -> None:
        self.var.set(value or "")


# --------------------------------------------------------------------------
# 좌표 / 색 캡처
# --------------------------------------------------------------------------
def capture_click_point(
    parent: tk.Misc, window: GameWindow | None
) -> tuple[int, int, tuple[int, int, int]] | None:
    """게임 화면에서 클릭한 지점의 (클라이언트x, 클라이언트y, RGB)를 돌려준다."""
    state = _CaptureState()

    def listener(event: HookEvent) -> bool:
        if event.injected or state.done.is_set():
            return False
        if event.kind == "key" and event.vk == 0x1B and event.down:
            state.cancelled = True
            state.done.set()
            return True
        if event.kind == "button" and event.button == "left":
            if event.down:
                state.result = (event.x, event.y)
            else:
                state.done.set()
            return True  # 클릭이 게임에 전달되지 않게 삼킨다
        return False

    raw = _run_capture(
        parent,
        "좌표 캡처",
        "게임 화면에서 원하는 지점을 왼쪽 클릭하세요.\n"
        "(클릭은 게임에 전달되지 않습니다)\n\nEsc = 취소",
        listener,
        state,
        timeout_s=30,
    )
    if not isinstance(raw, tuple):
        return None

    sx, sy = raw
    try:
        color = pixel.get_pixel(sx, sy)
    except pixel.CaptureError:
        color = (0, 0, 0)

    if window is not None and window.is_alive():
        cx, cy = window.screen_to_client(sx, sy)
    else:
        cx, cy = sx, sy
    return (cx, cy, color)


class ColorSwatch(ttk.Frame):
    """색 미리보기 사각형."""

    def __init__(self, parent: tk.Misc, size: int = 22) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(
            self, width=size, height=size, highlightthickness=1, highlightbackground="#888"
        )
        self.canvas.pack()
        self._rect = self.canvas.create_rectangle(
            0, 0, size, size, fill="#000000", outline=""
        )

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        self.canvas.itemconfig(self._rect, fill=pixel.to_hex(rgb))


def labeled(parent: tk.Misc, text: str, row: int, widget: tk.Widget, pad: int = 4):
    ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", pady=pad, padx=(0, 8))
    widget.grid(row=row, column=1, sticky="w", pady=pad)
    return widget


def int_entry(parent: tk.Misc, var: tk.Variable, width: int = 8) -> ttk.Entry:
    def _validate(value: str) -> bool:
        return value == "" or value == "-" or value.lstrip("-").isdigit()

    vcmd = (parent.register(_validate), "%P")
    return ttk.Entry(parent, textvariable=var, width=width, validate="key", validatecommand=vcmd)


def get_int(var: tk.Variable, default: int = 0) -> int:
    try:
        return int(str(var.get()).strip())
    except (ValueError, tk.TclError):
        return default


def get_float(var: tk.Variable, default: float = 1.0) -> float:
    try:
        return float(str(var.get()).strip())
    except (ValueError, tk.TclError):
        return default
