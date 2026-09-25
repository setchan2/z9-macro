"""정지 화면에서 영역 고르기.

**왜 필요한가** — 툴팁처럼 커서를 올려야 뜨는 것은, 영역을 지정하는 동안 화면에
띄워 둘 수가 없다. 모서리를 클릭하려면 마우스를 움직여야 하고, 움직이는 순간
툴팁이 사라진다. 그래서 지금까지는 **툴팁이 없는 화면에서 기억으로** 모서리를
찍어야 했고, 읽을 때와 다른 자리를 잡기 쉬웠다.

여기서는 순서를 뒤집는다.

1. 프로그램이 **읽을 때와 똑같이** 커서를 올리고 기다린다
2. 그 상태의 게임 창을 통째로 찍는다
3. 커서를 원래 자리로 돌려놓는다
4. 찍어 둔 **정지 화면** 위에서 사각형을 끌게 한다

읽을 때 보는 것과 같은 화면에서 고르므로 어긋날 수가 없다. 고른 즉시 그 자리를
잘라 글자가 몇 개로 나뉘는지도 보여 준다 — 잘못 잡았으면 그 자리에서 알 수 있다.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .. import digits, pixel, sender
from . import theme

# 선택 영역 미리보기를 몇 배로 키울지.
PREVIEW_ZOOM = 3
# 미리보기 칸 크기.
PREVIEW_W, PREVIEW_H = 420, 90


def _to_photo(buf: bytes, w: int, h: int) -> tk.PhotoImage:
    """BGRA 캡처 버퍼를 Tk 이미지로. 1366x768 기준 약 0.12초.

    픽셀을 하나씩 옮기면 100만 번을 돌아야 한다. 슬라이스로 채널을 통째로
    옮기면 C 쪽에서 처리되어 6ms면 끝난다.
    """
    rgb = bytearray(w * h * 3)
    rgb[0::3] = buf[2::4]
    rgb[1::3] = buf[1::4]
    rgb[2::3] = buf[0::4]
    return tk.PhotoImage(
        data=f"P6 {w} {h} 255\n".encode() + bytes(rgb), format="ppm"
    )


def _sub_frame(buf: bytes, w: int, x: int, y: int, sw: int, sh: int) -> pixel.Frame:
    """찍어 둔 화면에서 한 조각만 떼어 낸다."""
    out = bytearray(sw * sh * 4)
    for row in range(sh):
        src = ((y + row) * w + x) * 4
        dst = row * sw * 4
        out[dst : dst + sw * 4] = buf[src : src + sw * 4]
    return pixel.Frame(bytes(out), x, y, sw, sh)


def grab_client(engine, hover: tuple[int, int] | None, wait_ms: int):
    """게임 창 클라이언트 영역을 통째로 찍는다. (버퍼, 폭, 높이) 또는 None.

    hover를 주면 읽을 때와 똑같이 커서를 올렸다가 **반드시 되돌린다.**
    """
    window = engine.window()
    if window is None:
        return None
    cw, ch = window.client_size()
    if cw <= 0 or ch <= 0:
        return None
    ox, oy = window.client_to_screen(0, 0)

    restore = None
    try:
        if hover is not None:
            restore = sender.cursor_pos()
            hx, hy = window.client_to_screen(hover[0], hover[1])
            sender.mouse_move(hx, hy)
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
        try:
            frame = pixel.capture_region(ox, oy, cw, ch)
        except pixel.CaptureError:
            return None
    finally:
        if restore is not None:
            try:
                sender.mouse_move(*restore)
            except OSError:
                pass
    return (frame.buf, cw, ch)


class RegionPicker(tk.Toplevel):
    """정지 화면 위에서 사각형을 끌어 고르는 창."""

    def __init__(self, parent, engine, hover=None, wait_ms=400, initial=None,
                 title="영역 고르기", show_digits=True):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.configure(background=theme.PALETTE["bg"])
        self.result: tuple[int, int, int, int] | None = None
        self.engine = engine
        self._show_digits = show_digits
        self._drag_from: tuple[int, int] | None = None
        self._rect_id: int | None = None
        self._preview_photo: tk.PhotoImage | None = None

        shot = grab_client(engine, hover, wait_ms)
        if shot is None:
            self._fail("게임 창을 찾지 못했습니다.")
            return
        self._buf, self._cw, self._ch = shot
        try:
            self._photo = _to_photo(self._buf, self._cw, self._ch)
        except tk.TclError as exc:
            self._fail(f"화면을 그리지 못했습니다: {exc}")
            return

        self._build(hover, wait_ms)
        if initial and initial[2] > 0 and initial[3] > 0:
            self._set_rect(*initial)
        self.grab_set()

    # ------------------------------------------------------------------
    def _fail(self, message: str) -> None:
        ttk.Label(self, text=message, padding=20, style="Danger.TLabel").pack()
        ttk.Button(self, text="닫기", command=self.destroy).pack(pady=(0, 16))

    def _build(self, hover, wait_ms) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        head = ttk.Frame(self, padding=(10, 8))
        head.grid(row=0, column=0, sticky="ew")
        note = (
            f"커서를 ({hover[0]}, {hover[1]})에 올린 채로 찍은 화면입니다. "
            "읽을 때 보는 것과 똑같습니다 — 여기서 끌어 고르세요."
            if hover
            else "게임 창을 찍은 화면입니다. 읽을 곳을 끌어 고르세요."
        )
        ttk.Label(head, text=note, style="Muted.TLabel").pack(side="left")
        ttk.Button(
            head, text="↻ 다시 찍기", style="Small.TButton",
            command=lambda: self._recapture(hover, wait_ms),
        ).pack(side="right")

        # -- 화면 --------------------------------------------------------
        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=10)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            body, highlightthickness=1, cursor="crosshair",
            highlightbackground=theme.PALETTE["border"],
            background=theme.PALETTE["surface"],
            width=min(self._cw, self.winfo_screenwidth() - theme.px(360)),
            height=min(self._ch, self.winfo_screenheight() - theme.px(320)),
            scrollregion=(0, 0, self._cw, self._ch),
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        xbar = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        xbar.grid(row=1, column=0, sticky="ew")
        ybar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        ybar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw", tags="shot")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Motion>", self._hover_move)

        # -- 오른쪽: 좌표와 미리보기 ---------------------------------------
        side = ttk.Frame(body, padding=(12, 0, 0, 0))
        side.grid(row=0, column=2, sticky="ns")

        self.at_var = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.at_var, style="Muted.TLabel").pack(anchor="w")

        box = ttk.LabelFrame(side, text="고른 영역 (창 기준)", padding=8)
        box.pack(fill="x", pady=(8, 0))
        self.vars = {}
        for index, (key, label) in enumerate(
            (("x", "왼쪽"), ("y", "위"), ("w", "폭"), ("h", "높이"))
        ):
            ttk.Label(box, text=label).grid(row=index, column=0, sticky="w", pady=2)
            var = tk.StringVar(value="0")
            self.vars[key] = var
            spin = ttk.Spinbox(
                box, textvariable=var, from_=0, to=9999, width=7,
                command=self._on_spin,
            )
            spin.grid(row=index, column=1, sticky="w", padx=(8, 0))
            spin.bind("<KeyRelease>", lambda _e: self._on_spin())
        ttk.Label(
            box, style="Faint.TLabel", wraplength=theme.px(200), justify="left",
            text="끌어서 고른 뒤 한두 칸씩 다듬을 수 있습니다.",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        preview = ttk.LabelFrame(side, text=f"고른 자리 ({PREVIEW_ZOOM}배)", padding=6)
        preview.pack(fill="x", pady=(10, 0))
        self.preview = tk.Canvas(
            preview, width=PREVIEW_W, height=PREVIEW_H, highlightthickness=1,
            highlightbackground=theme.PALETTE["border"],
            background=theme.PALETTE["surface"],
        )
        self.preview.pack()
        self.check_var = tk.StringVar(value="")
        ttk.Label(
            side, textvariable=self.check_var, style="Muted.TLabel",
            wraplength=theme.px(220), justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # -- 아래 --------------------------------------------------------
        foot = ttk.Frame(self, padding=(10, 10))
        foot.grid(row=2, column=0, sticky="ew")
        ttk.Button(
            foot, text="이 영역으로", style="Accent.TButton", command=self._accept
        ).pack(side="left")
        ttk.Button(foot, text="취소", command=self.destroy).pack(side="left", padx=6)

    # ------------------------------------------------------------------
    def _recapture(self, hover, wait_ms) -> None:
        shot = grab_client(self.engine, hover, wait_ms)
        if shot is None:
            self.check_var.set("✘ 다시 찍지 못했습니다.")
            return
        self._buf, self._cw, self._ch = shot
        self._photo = _to_photo(self._buf, self._cw, self._ch)
        self.canvas.itemconfigure("shot", image=self._photo)
        self._refresh()

    # -- 끌기 ----------------------------------------------------------
    def _at(self, event) -> tuple[int, int]:
        return (int(self.canvas.canvasx(event.x)), int(self.canvas.canvasy(event.y)))

    def _hover_move(self, event) -> None:
        x, y = self._at(event)
        if 0 <= x < self._cw and 0 <= y < self._ch:
            self.at_var.set(f"커서 ({x}, {y})")

    def _press(self, event) -> None:
        self._drag_from = self._at(event)
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            *self._drag_from, *self._drag_from,
            outline=theme.PALETTE["danger"], width=2,
        )

    def _motion(self, event) -> None:
        if self._drag_from is None or self._rect_id is None:
            return
        self.canvas.coords(self._rect_id, *self._drag_from, *self._at(event))

    def _release(self, event) -> None:
        if self._drag_from is None:
            return
        x0, y0 = self._drag_from
        x1, y1 = self._at(event)
        self._drag_from = None
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        if right - left < 2 or bottom - top < 2:
            return
        self._set_rect(left, top, right - left, bottom - top)

    def _on_spin(self) -> None:
        try:
            values = [max(0, int(self.vars[k].get() or 0)) for k in ("x", "y", "w", "h")]
        except ValueError:
            return
        self._set_rect(*values, from_spin=True)

    def _set_rect(self, x, y, w, h, from_spin: bool = False) -> None:
        x = max(0, min(x, self._cw - 1))
        y = max(0, min(y, self._ch - 1))
        w = max(1, min(w, self._cw - x))
        h = max(1, min(h, self._ch - y))
        if not from_spin:
            for key, value in zip(("x", "y", "w", "h"), (x, y, w, h)):
                self.vars[key].set(str(value))
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            x, y, x + w, y + h, outline=theme.PALETTE["danger"], width=2
        )
        self._rect = (x, y, w, h)
        self._refresh()

    # -- 미리보기 + 진단 -------------------------------------------------
    def _refresh(self) -> None:
        rect = getattr(self, "_rect", None)
        if rect is None:
            return
        x, y, w, h = rect
        frame = _sub_frame(self._buf, self._cw, x, y, w, h)

        self.preview.delete("all")
        try:
            photo = _to_photo(frame.buf, w, h)
        except tk.TclError:
            return
        zoom = max(1, min(PREVIEW_ZOOM, PREVIEW_W // max(w, 1)))
        self._preview_photo = photo.zoom(zoom) if zoom > 1 else photo
        self.preview.create_image(4, 4, image=self._preview_photo, anchor="nw")

        if not self._show_digits:
            self.check_var.set(f"{w} x {h}")
            return
        dark, threshold, glyphs, score = digits.autotune(frame)
        if score <= 0:
            self.check_var.set(
                f"{w} x {h} · ⚠ 글자로 나뉘지 않습니다. 숫자 줄에만 딱 맞게, "
                "테두리는 빼고 잡아 보세요."
            )
            return
        color = "밝은 배경에 어두운 글자" if dark else "어두운 배경에 밝은 글자"
        self.check_var.set(
            f"{w} x {h} · 글자 {len(glyphs)}개로 나뉩니다\n"
            f"자동 판단: {color} · 밝기 기준 {threshold}"
        )
        self.tuned = (dark, threshold)

    def _accept(self) -> None:
        rect = getattr(self, "_rect", None)
        if rect is None:
            self.check_var.set("✘ 먼저 영역을 끌어서 고르세요.")
            return
        self.result = rect
        self.destroy()


def pick(parent, engine, hover=None, wait_ms=400, initial=None,
         title="영역 고르기", show_digits=True):
    """영역 고르기 창을 띄우고 결과를 돌려준다.

    (x, y, w, h) 창 기준 좌표, 취소하면 None. 자동으로 판단한 글자 색·밝기
    기준이 있으면 tuned에 담겨 온다.
    """
    picker = RegionPicker(
        parent, engine, hover=hover, wait_ms=wait_ms, initial=initial,
        title=title, show_digits=show_digits,
    )
    parent.wait_window(picker)
    return (picker.result, getattr(picker, "tuned", None))
