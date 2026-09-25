"""낚시 설정을 위한 그림 고르기 창들.

**색을 손으로 적게 하지 않는다.** 화면을 한 장 찍어 놓고 눌러서 고른다.
'#f0c419'를 알아내는 것은 사람이 할 일이 아니다.

처음 만든 것은 "누르면 색, 끌면 범위"였는데 실제로 써 보니 그대로 망가졌다.
막대 위에서 끌면 **막대 폭만큼**이 트랙 범위가 되어, 저 멀리 있는 물고기는
영원히 못 찾는다. 색을 찍는다는 게 무슨 뜻인지도 화면에 안 적혀 있어서, 막대에서
두 번 찍고는 "물고기 색"이라고 저장하게 된다.

그래서 두 가지를 바꿨다.

1. **지금 무엇을 하는 중인지 화면에 적는다.** [색 찍기]를 누르면 "막대의 색을
   찍으세요"가 뜨고, 찍을 때까지 그 상태로 있는다. 끌기도 마찬가지다.
2. **색을 찍으면 범위를 대신 잡아 준다.** 그 색이 판 어디에 있는지 훑어서
   테두리를 구한다. 좌우로 움직이는 것(막대·물고기)은 x를 판 전체로 열어 두고,
   제자리에 있는 것(체력·시간)은 찾은 자리로 좁힌다. 사람이 범위를 손으로
   맞출 일이 거의 없어진다.

여기에 돋보기를 붙였다. 커서 밑 픽셀을 열 배로 키워 보여 준다 — 1픽셀짜리
테두리를 짚으려면 이게 없으면 안 된다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import fishing, pixel
from ..model import ColorSpot, FishingSetup
from . import region_picker, theme
from .widgets import ColorSwatch, ScrollFrame, get_int, int_entry

# 돋보기가 보여 줄 칸 수(홀수여야 가운데가 생긴다)와 배율.
LENS = 11
LENS_ZOOM = 9

# 항목마다 쓰는 색. 오버레이와 목록에서 같은 색을 쓴다.
MARKS = {
    "track": "#ffffff",
    "bar": "#ffd400",
    "fish": "#4ec9ff",
    "health": "#ff5555",
    "time": "#7cf07c",
}
NAMES = {
    "track": "움직이는 범위",
    "bar": "트랙 막대",
    "fish": "물고기",
    "health": "체력 게이지",
    "time": "남은 시간",
}
ROLES = ("track", "bar", "fish", "health", "time")
# 좌우로 움직이는가. 움직이는 것은 **가로를 [움직이는 범위]에서 가져온다.**
# 지금 서 있는 자리로 좁히면 반대편으로 간 순간 놓친다.
MOVING = {"track": False, "bar": True, "fish": True,
          "health": False, "time": False}
# 색을 고르는 항목인가. [움직이는 범위]는 자리만 말해 주는 것이라 색이 없다.
HAS_COLOR = {"track": False, "bar": True, "fish": True,
             "health": True, "time": True}
COLOR_FIELD = {"bar": "bar_color", "fish": "fish_color",
               "health": "health_color", "time": "time_color"}


def to_photo(frame) -> tk.PhotoImage:
    return region_picker._to_photo(frame.buf, frame.w, frame.h)


def color_at(frame, x: int, y: int):
    return frame.at(frame.x + x, frame.y + y)


# 찍은 자리에서 위아래로 번져 나갈 때, 이어졌다고 볼 최소 진하기.
# 시작한 줄의 이 비율만큼은 걸려야 같은 덩어리로 본다.
EDGE = 0.2


def row_counts(frame, rgb, tol: int, box=None):
    """줄마다 그 색이 몇 칸인지. box는 (x0, x1, y0, y1) 또는 None(판 전체)."""
    buf, w, h = frame.buf, frame.w, frame.h
    x0, x1, y0, y1 = box if box else (0, w, 0, h)
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    tr, tg, tb = rgb
    rows = {}
    for y in range(y0, y1):
        base = y * w * 4
        hits = []
        for x in range(x0, x1):
            i = base + x * 4
            if (abs(buf[i + 2] - tr) <= tol and abs(buf[i + 1] - tg) <= tol
                    and abs(buf[i] - tb) <= tol):
                hits.append(x)
        if hits:
            rows[y] = hits
    return rows


def count_in(frame, rgb, tol: int, box=None) -> int:
    """그 범위 안에서 그 색이 몇 칸이나 보이는지."""
    return sum(len(v) for v in row_counts(frame, rgb, tol, box).values())


def bounds_at(frame, rgb, tol: int, at, box=None):
    """**찍은 자리에서 이어지는** 덩어리의 테두리. (x0, x1, y0, y1, 칸 수).

    판 전체에서 가장 진한 곳을 찾으면 안 된다. 물고기의 희끄무레한 색은 판
    테두리와 물방울에도 묻어 있고, **테두리는 한 줄이 판 폭만큼이라 늘 그쪽이
    이긴다.** 실제로 그래서 트랙 띠가 y 0~142(판 전체)로 부풀었다.

    그래서 사람이 찍은 줄에서 시작해 위아래로 번져 나가며, 색이 끊기는 데서
    멈춘다. 찍은 것과 이어져 있지 않은 것은 아무리 진해도 안 딸려 온다.
    """
    rows = row_counts(frame, rgb, tol, box)
    if not rows:
        return None
    _cx, cy = at
    start = cy
    if start not in rows:
        # 한두 줄 빗나가 찍었을 수 있다. 바로 옆 줄까지만 봐준다.
        near = [y for y in rows if abs(y - cy) <= 3]
        if not near:
            return None
        start = min(near, key=lambda y: abs(y - cy))

    floor = max(1, int(len(rows[start]) * EDGE))
    keep = {start}
    for step in (-1, 1):
        y = start + step
        while y in rows and len(rows[y]) >= floor:
            keep.add(y)
            y += step
    ys = sorted(keep)
    xs = [x for y in ys for x in rows[y]]
    return (min(xs), max(xs) + 1, ys[0], ys[-1] + 1, len(xs))


def too_close(a: str, b: str, tol: int) -> bool:
    """두 색이 서로 구별이 안 될 만큼 가까운가."""
    one, two = pixel.from_hex(a), pixel.from_hex(b)
    if one is None or two is None:
        return False
    return all(abs(one[i] - two[i]) <= tol for i in range(3))


class Lens(ttk.Frame):
    """커서 밑을 크게 보여 주는 돋보기."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        side = LENS * LENS_ZOOM
        self.canvas = tk.Canvas(self, width=side, height=side,
                                highlightthickness=1, highlightbackground="#888")
        self.canvas.pack()
        self._img = tk.PhotoImage(width=LENS, height=LENS)
        self._shown = self._img.zoom(LENS_ZOOM, LENS_ZOOM)
        self._item = self.canvas.create_image(0, 0, anchor="nw",
                                              image=self._shown)
        mid = LENS // 2 * LENS_ZOOM
        self.canvas.create_rectangle(
            mid, mid, mid + LENS_ZOOM, mid + LENS_ZOOM,
            outline="#ff0000", width=2)

    def show(self, frame, cx: int, cy: int) -> None:
        half = LENS // 2
        rows = []
        for dy in range(-half, half + 1):
            row = []
            for dx in range(-half, half + 1):
                got = color_at(frame, cx + dx, cy + dy)
                row.append(pixel.to_hex(got) if got else "#000000")
            rows.append("{" + " ".join(row) + "}")
        self._img.put(" ".join(rows), to=(0, 0))
        # zoom()은 그때그때 새 이미지를 만든다. 참조를 붙들고 있어야 안 지워진다.
        self._shown = self._img.zoom(LENS_ZOOM, LENS_ZOOM)
        self.canvas.itemconfigure(self._item, image=self._shown)


class BoardPicker(tk.Toplevel):
    """미니게임 판을 찍어 놓고 무엇을 어디서 볼지 정하는 창."""

    def __init__(self, parent, engine, setup: FishingSetup) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setup = setup
        self.result = False
        self._photo = None
        self._frame = None
        self._mode = None  # None | ("pick", role) | ("drag", role)
        self._drag = None
        self._zoom = 2

        self.hint_var = tk.StringVar(value="")
        self.cursor_var = tk.StringVar(value="")
        self.read_var = tk.StringVar(value="")
        self.rows: dict[str, dict] = {}

        self.title("판 살펴보기 — 무엇을 어디서 볼지 정하기")
        self.transient(parent)
        self.grab_set()

        outer = ttk.Frame(self, padding=theme.pad(10))
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)
        # 목록은 폭이 모자라면 통째로 잘려 나간다. 최소 폭을 못 박아 둔다.
        outer.columnconfigure(1, minsize=theme.px(280))

        ttk.Label(
            outer, style="Faint.TLabel", justify="left", wraplength=theme.px(980),
            text=("미니게임이 떠 있는 상태에서 [다시 찍기]를 누르세요. 그 다음 "
                  "오른쪽 목록에서 항목마다 [색 찍기]를 누르고 그림에서 그 색을 "
                  "찍으면, 볼 범위까지 알아서 잡아 줍니다. 범위가 마음에 안 들면 "
                  "[영역 끌기]로 직접 끌어 주세요."),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._build_toolbar(outer)

        left = ttk.Frame(outer)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(left, background="#101010", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar = ttk.Scrollbar(left, orient="horizontal", command=self.canvas.xview)
        hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        self._build_items(outer)

        ttk.Label(outer, textvariable=self.read_var, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        foot = ttk.Frame(outer)
        foot.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(foot, text="확인", style="Accent.TButton",
                   command=self._ok).pack(side="left")
        ttk.Button(foot, text="취소", command=self.destroy).pack(side="left", padx=6)

        self.geometry(theme.scale_geometry("1380x780", parent))
        self._arm(None)
        self._grab()

    # -- 위쪽 줄 -----------------------------------------------------------
    def _build_toolbar(self, outer) -> None:
        bar = ttk.Frame(outer)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(bar, text="다시 찍기", style="Small.TButton",
                   command=self._grab).pack(side="left")
        ttk.Label(bar, text="배율").pack(side="left", padx=(12, 4))
        self.zoom_var = tk.StringVar(value="2배")
        box = ttk.Combobox(bar, textvariable=self.zoom_var, state="readonly",
                           width=6, values=["1배", "2배", "3배", "4배"])
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda _e: self._on_zoom())
        ttk.Button(bar, text="지금 읽어 보기", style="Small.TButton",
                   command=self._probe).pack(side="left", padx=(12, 0))

        self.lens = Lens(bar)
        self.lens.pack(side="right", padx=(10, 0))
        ttk.Label(bar, textvariable=self.cursor_var, style="Faint.TLabel").pack(
            side="right")
        ttk.Label(bar, textvariable=self.hint_var, style="Heading.TLabel").pack(
            side="left", padx=(20, 0))

    # -- 오른쪽 목록 -------------------------------------------------------
    def _build_items(self, outer) -> None:
        # 항목이 다섯이라 글꼴이 조금만 커져도 마지막 칸이 창 밖으로 나간다.
        # 굴릴 수 있게 두면 배율이 어떻든 다 닿는다.
        holder = ScrollFrame(outer)
        holder.grid(row=2, column=1, sticky="nsew")
        panel = holder.inner
        panel.columnconfigure(0, weight=1)
        for index, role in enumerate(ROLES):
            box = ttk.LabelFrame(panel, text=NAMES[role], padding=theme.pad(8))
            box.grid(row=index, column=0, sticky="ew", pady=(0, 8))
            state = {}
            self.rows[role] = state
            row = 0

            if HAS_COLOR[role]:
                line = ttk.Frame(box)
                line.grid(row=row, column=0, columnspan=3, sticky="w")
                state["swatch"] = ColorSwatch(line, size=theme.px(18))
                state["swatch"].pack(side="left", padx=(0, 6))
                state["color"] = tk.StringVar(value="")
                ttk.Label(line, textvariable=state["color"], width=10).pack(
                    side="left")
                ttk.Label(line, text="허용차").pack(side="left", padx=(8, 3))
                state["tol"] = tk.StringVar(value="30")
                int_entry(line, state["tol"], width=4).pack(side="left")
                state["tol"].trace_add(
                    "write", lambda *_a, r=role: self._on_tol(r))
                row += 1

            state["range"] = tk.StringVar(value="")
            ttk.Label(box, textvariable=state["range"],
                      style="Faint.TLabel").grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(4, 4))
            row += 1

            column = 0
            if HAS_COLOR[role]:
                ttk.Button(box, text="색 찍기", style="Small.TButton",
                           command=lambda r=role: self._arm(("pick", r))).grid(
                    row=row, column=0, sticky="w")
                column = 1
            ttk.Button(box, text="영역 끌기", style="Small.TButton",
                       command=lambda r=role: self._arm(("drag", r))).grid(
                row=row, column=column, sticky="w", padx=(0 if column == 0 else 4))
            ttk.Button(box, text="지우기", style="Small.TButton",
                       command=lambda r=role: self._clear(r)).grid(
                row=row, column=column + 1, sticky="w", padx=4)
            row += 1

            hint = {
                "track": "막대와 물고기가 **왔다 갔다 하는 사각형**입니다. "
                         "지금 서 있는 자리가 아니라 오가는 범위 전체를 "
                         "잡아 주세요. 둘은 이 가로 범위를 함께 씁니다.",
                "bar": "막대의 색과 **세로 범위**만 정합니다. 가로는 위 "
                       "[움직이는 범위]를 따릅니다.",
                "fish": "물고기의 색과 **세로 범위**만 정합니다. 가로는 위 "
                        "[움직이는 범위]를 따릅니다.",
                "health": "게이지는 깎이면 짧아집니다. 남은 길이를 비율로 재려면 "
                          "깎이기 전 **전체 길이**를 [영역 끌기]로 잡아 주세요.",
                "time": "없어도 됩니다. 정해 두면 숫자를 읽지는 않지만 "
                        "'미니게임이 떠 있다'를 가장 확실하게 알 수 있습니다.",
            }[role].replace("**", "")
            ttk.Label(box, style="Faint.TLabel", justify="left",
                      wraplength=theme.px(230), text=hint).grid(
                row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))

    # ------------------------------------------------------------------
    # 화면
    # ------------------------------------------------------------------
    def _on_zoom(self) -> None:
        self._zoom = int(self.zoom_var.get()[0])
        self._redraw()

    def _grab(self) -> None:
        window = self.engine.window()
        s = self.setup
        if window is None:
            messagebox.showwarning("게임 창 없음", "게임 창을 찾지 못했습니다.",
                                   parent=self)
            return
        rect = s.board_rect(window)
        if rect is None:
            messagebox.showwarning(
                "판 영역이 없습니다",
                "먼저 [영역 지정]으로 미니게임 판의 자리를 정해 주세요.",
                parent=self)
            return
        try:
            self._frame = pixel.capture_region(*rect)
        except pixel.CaptureError as exc:
            messagebox.showwarning("찍지 못했습니다", str(exc), parent=self)
            return
        fit = max(1, min(4, theme.px(1000) // max(1, self._frame.w)))
        self._zoom = fit
        self.zoom_var.set(f"{fit}배")
        self._sync_rows()
        self._redraw()
        self._probe()

    def _redraw(self) -> None:
        if self._frame is None:
            return
        frame = self._frame
        zoom = self._zoom
        self._photo = to_photo(frame)
        if zoom > 1:
            self._photo = self._photo.zoom(zoom, zoom)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, frame.w * zoom, frame.h * zoom))

        self._overlay()
        self._sync_rows()

    def _overlay(self) -> None:
        s = self.setup
        self._box("track", *s.track_box(), "움직이는 범위")
        if s.bar_y1 > s.bar_y0:
            self._box("bar", *s.bar_box(), "막대 세로")
        if s.fish_y1 > s.fish_y0:
            self._box("fish", *s.fish_box(), "물고기 세로")
        self._box("health", *s.health_box(), "체력")
        if s.time_color:
            self._box("time", *s.time_box(), "시간")
        self._marks()

    # 사각형이 겹쳐 놓이므로 이름표도 겹친다. 항목마다 가로로 밀어 둔다.
    LABEL_SHIFT = {"track": 4, "bar": 150, "fish": 300, "health": 4, "time": 4}

    def _box(self, role, x0, x1, y0, y1, label) -> None:
        if x1 <= x0 or y1 <= y0:
            return
        z = self._zoom
        color = MARKS[role]
        self.canvas.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z,
                                     outline=color, width=2, tags="overlay")
        at = min(x0 * z + self.LABEL_SHIFT.get(role, 4), max(x0 * z, x1 * z - 60))
        self.canvas.create_text(at, y0 * z - 8, anchor="w", text=label,
                                fill=color, tags="overlay")

    def _marks(self) -> None:
        """지금 설정으로 찾아지는 자리를 그림 위에 표시한다."""
        if self._frame is None:
            return
        s = self.setup
        z = self._zoom
        for role, hexed, tol, box in (
            ("bar", s.bar_color, s.bar_tol, s.bar_box()),
            ("fish", s.fish_color, s.fish_tol, s.fish_box()),
        ):
            rgb = pixel.from_hex(hexed)
            x0, x1, y0, y1 = box
            if rgb is None or x1 <= x0 or y1 <= y0:
                continue
            got, count = fishing.scan_band(self._frame.buf, self._frame.w, rgb,
                                           tol, x0, x1, y0, y1)
            if got is None or count < s.track_min_px:
                continue
            self.canvas.create_line(got * z, (y0 - 6) * z, got * z, (y1 + 6) * z,
                                    fill=MARKS[role], width=3, tags="overlay")

    # ------------------------------------------------------------------
    # 고르기
    # ------------------------------------------------------------------
    def _arm(self, mode) -> None:
        self._mode = mode
        if mode is None:
            self.hint_var.set("")
            self.canvas.configure(cursor="")
            return
        kind, role = mode
        if kind == "pick":
            self.hint_var.set(f"→ 그림에서 {NAMES[role]}의 색을 **찍으세요**"
                              .replace("**", ""))
            self.canvas.configure(cursor="dotbox")
        else:
            self.hint_var.set(f"→ {NAMES[role]}를 볼 영역을 **끌어서** 잡으세요"
                              .replace("**", ""))
            self.canvas.configure(cursor="crosshair")

    def _at(self, event) -> tuple[int, int] | None:
        if self._frame is None:
            return None
        z = self._zoom
        x = int(self.canvas.canvasx(event.x)) // z
        y = int(self.canvas.canvasy(event.y)) // z
        if not (0 <= x < self._frame.w and 0 <= y < self._frame.h):
            return None
        return (x, y)

    def _on_move(self, event) -> None:
        spot = self._at(event)
        if spot is None:
            return
        color = color_at(self._frame, *spot)
        self.cursor_var.set(
            f"({spot[0]}, {spot[1]})  {pixel.to_hex(color) if color else '?'}  ")
        self.lens.show(self._frame, *spot)

    def _on_press(self, event) -> None:
        self._drag = self._at(event)

    def _on_drag(self, event) -> None:
        self._on_move(event)
        if self._drag is None or self._mode is None or self._mode[0] != "drag":
            return
        spot = self._at(event)
        if spot is None:
            return
        z = self._zoom
        self.canvas.delete("dragbox")
        x0, x1 = sorted((self._drag[0], spot[0]))
        y0, y1 = sorted((self._drag[1], spot[1]))
        self.canvas.create_rectangle(
            x0 * z, y0 * z, x1 * z, y1 * z, outline=MARKS[self._mode[1]],
            width=2, dash=(4, 2), tags="dragbox")

    def _on_release(self, event) -> None:
        start, self._drag = self._drag, None
        spot = self._at(event)
        if start is None or spot is None or self._mode is None:
            return
        self.canvas.delete("dragbox")
        kind, role = self._mode

        if kind == "drag":
            x0, x1 = sorted((start[0], spot[0]))
            y0, y1 = sorted((start[1], spot[1]))
            if x1 - x0 < 2 or y1 - y0 < 2:
                self.engine.log("영역이 너무 작습니다. 좀 더 크게 끌어 주세요.")
                return
            self._set_range(role, x0, x1 + 1, y0, y1 + 1)
        else:
            color = color_at(self._frame, *spot)
            if color is None:
                return
            self._set_color(role, color, spot)

        self._arm(None)
        self._redraw()
        self._probe()

    def _box_of(self, role: str):
        s = self.setup
        return {
            "track": s.track_box,
            "bar": s.bar_box,
            "fish": s.fish_box,
            "health": s.health_box,
            "time": s.time_box,
        }[role]()

    def _has_box(self, role: str) -> bool:
        """그 항목이 **자기 범위**를 이미 갖고 있는가.

        막대와 물고기는 가로를 [움직이는 범위]에서 빌려 오므로, 자기 것이라고
        할 수 있는 것은 세로뿐이다. 그것이 없으면 색을 찍을 때 대신 잡아 준다.
        """
        s = self.setup
        if role == "bar":
            return s.bar_y1 > s.bar_y0
        if role == "fish":
            return s.fish_y1 > s.fish_y0
        x0, x1, y0, y1 = self._box_of(role)
        return x1 > x0 and y1 > y0

    def _set_color(self, role: str, rgb, at) -> None:
        """색을 정한다. 범위는 **아직 없을 때만** 대신 잡아 준다.

        예전에는 색을 찍을 때마다 범위를 다시 계산해서 기존 것과 합쳤다. 그런데
        물고기의 흰색은 물방울·테두리·글자에도 묻어 있어서, 찍는 순간 띠가 판
        전체로 부풀고 **애써 끌어 둔 영역이 통째로 망가졌다.** 합치기는 되돌릴
        수도 없었다 — 넓어지기만 하고 좁아지지 않으니까.

        그래서 규칙을 단순하게 바꿨다. **색 찍기는 색만 바꾼다.** 범위를 고칠
        때는 [영역 끌기]를 쓴다. 처음 한 번, 아직 아무 범위도 없을 때만 대신
        잡아 준다.
        """
        s = self.setup
        hexed = pixel.to_hex(rgb)
        tol = get_int(self.rows[role]["tol"], 30)
        setattr(s, COLOR_FIELD[role], hexed)

        # 막대와 물고기 색이 서로 구별이 안 되면 둘 다 엉뚱한 것을 잡는다.
        other = ("fish", s.fish_color) if role == "bar" else (
            ("bar", s.bar_color) if role == "fish" else None)
        if other and other[1] and too_close(hexed, other[1], tol):
            self.engine.log(
                f"⚠ {NAMES[role]}({hexed})와 {NAMES[other[0]]}({other[1]}) 색이 "
                "거의 같습니다. 서로 다른 색을 찍어야 구별할 수 있습니다 — "
                "물고기는 흰 몸통, 막대는 노란/주황 막대입니다.")

        if self._has_box(role):
            # 이미 잡아 둔 범위는 건드리지 않는다. 대신 그 안에서 이 색이
            # 얼마나 보이는지 알려 준다 — 안 보이면 범위나 색이 틀린 것이다.
            box = self._box_of(role)
            seen = count_in(self._frame, rgb, tol, box)
            if not seen:
                self.engine.log(
                    f"⚠ {NAMES[role]} 색 {hexed} — 지금 영역 안에서는 안 보입니다. "
                    "[영역 끌기]로 범위를 다시 잡거나, 허용차를 올려 보세요.")
                return
            note = f"{NAMES[role]} 색 {hexed} — 지금 영역 안에서 {seen}칸 보입니다."
            whole = bounds_at(self._frame, rgb, tol, at)
            if whole is not None and (whole[2] < box[2] or whole[3] > box[3]):
                note += (f" 다만 이 색은 y {whole[2]}~{whole[3]}에 걸쳐 있어 "
                         f"지금 범위(y {box[2]}~{box[3]})를 벗어납니다. "
                         "필요하면 [영역 끌기]로 넓히세요.")
            self.engine.log(note)
            return

        found = bounds_at(self._frame, rgb, tol, at)
        if found is None:
            self.engine.log(f"{NAMES[role]}: {hexed}를 판에서 못 찾았습니다. "
                            "허용차를 올려 보세요.")
            return
        x0, x1, y0, y1, count = found
        pad = 2
        y0, y1 = max(0, y0 - pad), min(self._frame.h, y1 + pad)

        if MOVING[role]:
            # 세로만 이 물체 몫이다. 가로는 [움직이는 범위]에서 빌려 온다 —
            # 지금 서 있는 자리로 좁히면 반대편으로 간 순간 놓친다.
            setattr(s, role + "_y0", y0)
            setattr(s, role + "_y1", y1)
            note = f"{NAMES[role]} 색 {hexed} ({count}칸) — 세로 {y0}~{y1}."
            if s.track_x1 <= s.track_x0:
                # 아직 오가는 범위를 안 정했다. 판 전체로 열어 두고 알린다.
                s.track_x0, s.track_x1 = 0, self._frame.w
                s.track_y0, s.track_y1 = y0, y1
                note += (" [움직이는 범위]가 아직 없어 판 전체로 열어 뒀습니다. "
                         "파란 사각형에 맞게 끌어 주세요.")
            elif y0 < s.track_y0 or y1 > s.track_y1:
                note += (f" 다만 [움직이는 범위](y {s.track_y0}~{s.track_y1})를 "
                         "벗어납니다. 그쪽을 넓혀 주세요.")
            self.engine.log(note)
            return
        if role == "health":
            s.health_y0, s.health_y1 = y0, y1
            s.health_x0, s.health_x1 = x0, x1
            self.engine.log(
                f"체력 게이지 색 {hexed} ({count}칸) — 지금 보이는 만큼만 "
                "잡았습니다. 깎이기 전 전체 길이를 [영역 끌기]로 다시 잡아 "
                "주세요.")
            return
        s.time_x0, s.time_x1 = max(0, x0 - pad), min(self._frame.w, x1 + pad)
        s.time_y0, s.time_y1 = y0, y1
        # 문턱은 **잡은 영역 안에서** 몇 칸 보이는지로 정해야 한다. 판 전체에서
        # 센 값을 그대로 쓰면 영역이 가진 칸 수보다 커질 수 있고, 그러면 아무리
        # 잘 보여도 못 봤다고 하게 된다.
        inside = count_in(self._frame, rgb, tol, s.time_box())
        room = (s.time_x1 - s.time_x0) * (s.time_y1 - s.time_y0)
        s.time_min_px = max(4, min(inside // 3, room // 4))
        self.engine.log(f"{NAMES[role]} 색 {hexed} ({count}칸 보임)")

    def _set_range(self, role: str, x0, x1, y0, y1) -> None:
        """끌어서 정한 범위를 넣는다.

        막대와 물고기는 **세로만** 받는다. 가로까지 받으면 물체가 지금 서 있는
        자리로 좁혀지고, 반대편으로 간 순간 못 찾는다 — 실제로 그렇게 망가졌다.
        """
        s = self.setup
        if role == "track":
            s.track_x0, s.track_x1, s.track_y0, s.track_y1 = x0, x1, y0, y1
            self.engine.log(f"움직이는 범위 x {x0}~{x1} · y {y0}~{y1}")
            return
        if MOVING[role]:
            setattr(s, role + "_y0", y0)
            setattr(s, role + "_y1", y1)
            note = (f"{NAMES[role]} 세로 {y0}~{y1} "
                    "(가로는 [움직이는 범위]를 따릅니다)")
            if s.track_x1 <= s.track_x0:
                s.track_x0, s.track_x1 = 0, self._frame.w
                s.track_y0, s.track_y1 = y0, y1
                note += " — [움직이는 범위]가 없어 판 전체로 열어 뒀습니다."
            self.engine.log(note)
            return
        if role == "health":
            s.health_x0, s.health_x1, s.health_y0, s.health_y1 = x0, x1, y0, y1
        else:
            s.time_x0, s.time_x1, s.time_y0, s.time_y1 = x0, x1, y0, y1
        self.engine.log(f"{NAMES[role]} 영역 x {x0}~{x1} · y {y0}~{y1}")

    def _clear(self, role: str) -> None:
        """그 항목이 가진 것을 비운다. 다른 항목은 건드리지 않는다."""
        s = self.setup
        if role == "track":
            s.track_x0 = s.track_x1 = s.track_y0 = s.track_y1 = 0
        elif role in ("bar", "fish"):
            setattr(s, COLOR_FIELD[role], "")
            setattr(s, role + "_y0", 0)
            setattr(s, role + "_y1", 0)
        elif role == "health":
            s.health_color = ""
            s.health_x0 = s.health_x1 = s.health_y0 = s.health_y1 = 0
        else:
            s.time_color = ""
            s.time_x0 = s.time_x1 = s.time_y0 = s.time_y1 = 0
        self._redraw()
        self._probe()

    def _on_tol(self, role: str) -> None:
        value = max(1, min(150, get_int(self.rows[role]["tol"], 30)))
        setattr(self.setup, role + "_tol", value)
        self._probe()

    # ------------------------------------------------------------------
    def _sync_rows(self) -> None:
        s = self.setup
        for role, state in self.rows.items():
            if HAS_COLOR[role]:
                hexed = getattr(s, COLOR_FIELD[role])
                state["color"].set(hexed or "안 정함")
                state["swatch"].set_color(pixel.from_hex(hexed) or (40, 40, 40))
                tol = getattr(s, role + "_tol")
                if get_int(state["tol"], -1) != tol:
                    state["tol"].set(str(tol))
            state["range"].set(self._range_text(role))

    def _range_text(self, role: str) -> str:
        s = self.setup
        if MOVING[role]:
            # 가로는 [움직이는 범위]에서 빌려 오므로 세로만 이 항목 몫이다.
            y0, y1 = getattr(s, role + "_y0"), getattr(s, role + "_y1")
            if y1 <= y0:
                return ("세로 안 정함 — 움직이는 범위 전체를 봅니다"
                        if s.track_y1 > s.track_y0 else "아직 아무것도 안 정함")
            return f"세로 {y0}~{y1} · 가로는 움직이는 범위"
        x0, x1, y0, y1 = self._box_of(role)
        if x1 <= x0 or y1 <= y0:
            return "영역 안 정함"
        return f"x {x0}~{x1} · y {y0}~{y1}"

    def _probe(self) -> None:
        """지금 설정으로 이 판을 읽으면 무엇이 보이는지."""
        if self._frame is None:
            return
        from ..fishtask import LiveBoard

        board = LiveBoard.reader(self.setup)
        got = board.look(self._frame)
        self.read_var.set("지금 설정으로 읽으면 →  " + got.describe(self.setup.hit_px))
        self.canvas.delete("overlay")
        self._overlay()
        self._sync_rows()

    def _ok(self) -> None:
        missing = self.setup.problems()
        blocking = [m for m in missing
                    if m in ("움직이는 범위", "막대 색", "물고기 색", "체력 게이지")]
        if blocking and not messagebox.askyesno(
            "아직 덜 골랐습니다",
            "아직 못 고른 것: " + ", ".join(blocking) + "\n\n이대로 닫을까요?",
            parent=self,
        ):
            return
        self.result = True
        self.destroy()


class SpotPicker(tk.Toplevel):
    """작은 사각형 하나에서 색을 고르는 창. 찌와 낚는 모션에 쓴다."""

    def __init__(self, parent, engine, spot: ColorSpot, title: str) -> None:
        super().__init__(parent)
        self.engine = engine
        self.spot = spot
        self.result = False
        self._frame = None
        self._photo = None
        self._zoom = 3

        self.cursor_var = tk.StringVar(value="")
        self.read_var = tk.StringVar(value="")

        self.title(f"{title} — 색 고르기")
        self.transient(parent)
        self.grab_set()

        outer = ttk.Frame(self, padding=theme.pad(10))
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        ttk.Label(
            outer, style="Faint.TLabel", justify="left", wraplength=theme.px(640),
            text=(f"{title}이(가) 화면에 **보이는 상태**에서 [다시 찍기]를 "
                  "누르고, 그림에서 그 색을 클릭하세요. 아래 [보이는 칸]이 "
                  "충분히 크면 잘 잡힌 것입니다.").replace("**", ""),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        bar = ttk.Frame(outer)
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(bar, text="다시 찍기", style="Small.TButton",
                   command=self._grab).pack(side="left")
        ttk.Label(bar, text="허용차").pack(side="left", padx=(12, 4))
        self.tol_var = tk.StringVar(value=str(spot.tol))
        int_entry(bar, self.tol_var, width=5).pack(side="left")
        self.tol_var.trace_add("write", lambda *_a: self._probe())
        ttk.Label(bar, text="최소 칸").pack(side="left", padx=(12, 4))
        self.min_var = tk.StringVar(value=str(spot.min_px))
        int_entry(bar, self.min_var, width=6).pack(side="left")
        self.swatch = ColorSwatch(bar, size=theme.px(18))
        self.swatch.pack(side="left", padx=(12, 4))
        self.hex_var = tk.StringVar(value=spot.color or "안 정함")
        ttk.Label(bar, textvariable=self.hex_var).pack(side="left")
        self.lens = Lens(bar)
        self.lens.pack(side="right", padx=(10, 0))
        ttk.Label(bar, textvariable=self.cursor_var, style="Faint.TLabel").pack(
            side="right")

        wrap = ttk.Frame(outer)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, background="#101010", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.canvas.bind("<Motion>", self._on_move)
        self.canvas.bind("<Button-1>", self._on_click)

        ttk.Label(outer, textvariable=self.read_var).grid(
            row=3, column=0, sticky="w", pady=(8, 0))

        foot = ttk.Frame(outer)
        foot.grid(row=4, column=0, sticky="e", pady=(10, 0))
        ttk.Button(foot, text="확인", style="Accent.TButton",
                   command=self._ok).pack(side="left")
        ttk.Button(foot, text="취소", command=self.destroy).pack(side="left", padx=6)

        self.geometry(theme.scale_geometry("760x560", parent))
        self._grab()

    def _grab(self) -> None:
        window = self.engine.window()
        if window is None:
            messagebox.showwarning("게임 창 없음", "게임 창을 찾지 못했습니다.",
                                   parent=self)
            return
        if self.spot.w <= 0 or self.spot.h <= 0:
            messagebox.showwarning(
                "영역이 없습니다", "먼저 [영역 지정]으로 자리를 정해 주세요.",
                parent=self)
            return
        sx, sy = window.client_to_screen(self.spot.x, self.spot.y)
        try:
            self._frame = pixel.capture_region(sx, sy, self.spot.w, self.spot.h)
        except pixel.CaptureError as exc:
            messagebox.showwarning("찍지 못했습니다", str(exc), parent=self)
            return
        self._zoom = max(1, min(6, theme.px(560) // max(1, self._frame.w)))
        self._redraw()
        self._probe()

    def _redraw(self) -> None:
        if self._frame is None:
            return
        self._photo = to_photo(self._frame)
        if self._zoom > 1:
            self._photo = self._photo.zoom(self._zoom, self._zoom)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(
            0, 0, self._frame.w * self._zoom, self._frame.h * self._zoom))

    def _at(self, event):
        if self._frame is None:
            return None
        x = int(self.canvas.canvasx(event.x)) // self._zoom
        y = int(self.canvas.canvasy(event.y)) // self._zoom
        if not (0 <= x < self._frame.w and 0 <= y < self._frame.h):
            return None
        return (x, y)

    def _on_move(self, event) -> None:
        spot = self._at(event)
        if spot is None:
            return
        color = color_at(self._frame, *spot)
        self.cursor_var.set(
            f"({spot[0]}, {spot[1]})  {pixel.to_hex(color) if color else '?'}  ")
        self.lens.show(self._frame, *spot)

    def _on_click(self, event) -> None:
        spot = self._at(event)
        if spot is None:
            return
        color = color_at(self._frame, *spot)
        if color is None:
            return
        self.spot.color = pixel.to_hex(color)
        self.hex_var.set(self.spot.color)
        self.swatch.set_color(color)
        self._probe()

    def _probe(self) -> None:
        if self._frame is None:
            return
        rgb = pixel.from_hex(self.spot.color)
        self.swatch.set_color(rgb or (40, 40, 40))
        if rgb is None:
            self.read_var.set("아직 색을 안 골랐습니다.")
            return
        tol = max(1, min(150, get_int(self.tol_var, 30)))
        _cx, count = fishing.scan_band(self._frame.buf, self._frame.w, rgb, tol,
                                       0, self._frame.w, 0, self._frame.h)
        need = max(1, get_int(self.min_var, 40))
        verdict = "보인다고 판단합니다" if count >= need else "못 봤다고 판단합니다"
        self.read_var.set(
            f"보이는 칸 {count}개 (문턱 {need}) → {verdict}")

    def _ok(self) -> None:
        self.spot.tol = max(1, min(150, get_int(self.tol_var, 30)))
        self.spot.min_px = max(1, get_int(self.min_var, 40))
        self.result = True
        self.destroy()
