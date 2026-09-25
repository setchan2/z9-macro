"""그림 감지(IconWatch) 하나를 편집하는 공용 패널.

조건 탭과 버프 탭이 같은 것을 쓴다. 화면이 한 벌이라 인식률을 여기서 한 번
맞춰 두면 두 곳 모두에서 같게 동작한다.

**왜 마스크 편집이 화면 한복판에 있나** — 버프 아이콘 위에는 남은 시간 숫자가
겹쳐 그려진다. 그 칸은 1분마다 다른 그림이 되므로 비교에 넣으면 무슨 짓을 해도
맞지 않는다. 숫자 칸을 끌어서 빼 두는 것이 이 기능에서 인식률을 좌우하는 단 하나의
설정이라, 눈에 가장 잘 띄는 자리에 두었다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import icons as icons_mod
from .. import imagematch
from ..model import IconWatch, MaskRect
from . import theme
from .widgets import capture_click_point, get_int, int_entry

# 미리보기 확대 배율. 아이콘이 30픽셀 남짓이라 이 정도는 키워야 숫자 칸을
# 손으로 짚을 수 있다.
ZOOM = 8
# 미리보기 칸의 최대 크기(px). 큰 그림은 배율을 줄여서 담는다.
PREVIEW_MAX = 320

EXPECT_LABELS = {"present": "그림이 있을 때", "absent": "그림이 없을 때"}
EXPECT_BY_LABEL = {v: k for k, v in EXPECT_LABELS.items()}


class IconWatchPanel(ttk.Frame):
    """IconWatch 하나를 고치는 칸.

    값을 곧바로 대상 객체에 쓰지 않는다. load()로 채우고 save()로 거둔다 —
    편집 도중의 반쯤 채운 값이 감시 중인 판정에 새어 들어가면 안 된다.
    """

    def __init__(
        self,
        parent: tk.Misc,
        engine,
        show_expect: bool = True,
        on_change=None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self._on_change = on_change
        self._watch = IconWatch()
        self._photo: tk.PhotoImage | None = None
        self._zoom = ZOOM
        self._drag_start: tuple[int, int] | None = None
        self._drag_id: int | None = None

        self.columnconfigure(1, weight=1)

        self.icon_var = tk.StringVar(value="")
        self.area_var = tk.StringVar(value="지정 안 함 (창 전체 — 느립니다)")
        self.tol_var = tk.StringVar(value="22")
        self.level_var = tk.BooleanVar(value=True)
        self.expect_var = tk.StringVar(value=EXPECT_LABELS["present"])
        self.result_var = tk.StringVar(value="")

        # -- 그림 ---------------------------------------------------------
        ttk.Label(self, text="그림").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        picker = ttk.Frame(self)
        picker.grid(row=0, column=1, sticky="ew", pady=3)
        self.icon_box = ttk.Combobox(
            picker, textvariable=self.icon_var, width=24, state="readonly"
        )
        self.icon_box.pack(side="left")
        self.icon_box.bind("<<ComboboxSelected>>", lambda _e: self._on_icon_pick())
        ttk.Button(
            picker, text="화면에서 잘라내기", style="Small.TButton",
            command=self._capture_icon,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            picker, text="PNG 불러오기", style="Small.TButton", command=self._import_png
        ).pack(side="left", padx=4)

        # -- 찾을 영역 ------------------------------------------------------
        ttk.Label(self, text="찾을 영역").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        area = ttk.Frame(self)
        area.grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Button(
            area, text="영역 지정 (두 모서리 클릭)", style="Small.TButton",
            command=self._capture_area,
        ).pack(side="left")
        ttk.Button(
            area, text="지우기", style="Small.TButton", command=self._clear_area
        ).pack(side="left", padx=4)
        ttk.Label(area, textvariable=self.area_var, style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )

        # -- 판정 값 --------------------------------------------------------
        ttk.Label(self, text="허용 오차").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        judge = ttk.Frame(self)
        judge.grid(row=2, column=1, sticky="ew", pady=3)
        int_entry(judge, self.tol_var, width=6).pack(side="left")
        ttk.Label(
            judge, text="작을수록 깐깐 (0=완전 일치)", style="Faint.TLabel"
        ).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(
            judge, text="반투명하게 밝기가 밀려도 같은 그림으로 보기",
            variable=self.level_var,
        ).pack(side="left", padx=(14, 0))

        if show_expect:
            ttk.Label(self, text="성립 조건").grid(
                row=3, column=0, sticky="w", padx=(0, 6), pady=3
            )
            ttk.Combobox(
                self, textvariable=self.expect_var,
                values=list(EXPECT_LABELS.values()), width=16, state="readonly",
            ).grid(row=3, column=1, sticky="w", pady=3)

        # -- 미리보기 + 마스크 ----------------------------------------------
        box = ttk.LabelFrame(self, text="숫자 칸 가리기 (그림 위에서 끌어 주세요)", padding=8)
        box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        box.columnconfigure(1, weight=1)

        self.canvas = tk.Canvas(
            box, width=PREVIEW_MAX, height=120, highlightthickness=1,
            highlightbackground=theme.PALETTE["border"],
            background=theme.PALETTE["surface"], cursor="crosshair",
        )
        self.canvas.grid(row=0, column=0, rowspan=2, sticky="w")
        self.canvas.bind("<ButtonPress-1>", self._mask_press)
        self.canvas.bind("<B1-Motion>", self._mask_motion)
        self.canvas.bind("<ButtonRelease-1>", self._mask_release)

        side = ttk.Frame(box)
        side.grid(row=0, column=1, sticky="nw", padx=(12, 0))
        ttk.Label(
            side,
            style="Faint.TLabel",
            justify="left",
            wraplength=300,
            text="남은 시간 숫자처럼 계속 바뀌는 칸을 끌어서 덮으세요. 덮은 칸은 "
            "비교에서 빠집니다.\n\n가리지 않으면 1분마다 다른 그림이 되는 셈이라 "
            "허용 오차를 아무리 키워도 인식률이 오르지 않습니다.",
        ).pack(anchor="w")
        self.mask_var = tk.StringVar(value="가린 칸 없음")
        ttk.Label(side, textvariable=self.mask_var, style="Muted.TLabel").pack(
            anchor="w", pady=(8, 0)
        )
        mask_buttons = ttk.Frame(side)
        mask_buttons.pack(anchor="w", pady=(6, 0))
        ttk.Button(
            mask_buttons, text="마지막 것 취소", style="Small.TButton",
            command=self._undo_mask,
        ).pack(side="left")
        ttk.Button(
            mask_buttons, text="전부 지우기", style="Small.TButton",
            command=self._clear_masks,
        ).pack(side="left", padx=4)

        # -- 시험 -----------------------------------------------------------
        test = ttk.Frame(self)
        test.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(test, text="지금 확인", command=self._test_once).pack(side="left")
        ttk.Button(
            test, text="20회 측정 (허용 오차 정하기)", command=self._measure
        ).pack(side="left", padx=6)
        ttk.Label(
            self, textvariable=self.result_var, style="Muted.TLabel",
            justify="left", wraplength=620,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._refresh_icon_list()

    # ------------------------------------------------------------------
    # 값 오가기
    # ------------------------------------------------------------------
    def load(self, watch: IconWatch) -> None:
        self._watch = watch
        self._refresh_icon_list()
        self.icon_var.set(watch.icon)
        self.tol_var.set(str(watch.tolerance))
        self.level_var.set(bool(watch.level))
        self.expect_var.set(EXPECT_LABELS.get(watch.expect, EXPECT_LABELS["present"]))
        self.result_var.set("")
        self._sync_area()
        self._redraw()

    def save(self, watch: IconWatch | None = None) -> None:
        target = watch if watch is not None else self._watch
        target.icon = self.icon_var.get().strip()
        target.tolerance = max(0, min(255, get_int(self.tol_var, 22)))
        target.level = bool(self.level_var.get())
        target.expect = EXPECT_BY_LABEL.get(self.expect_var.get(), "present")
        # 영역과 마스크는 버튼/드래그로 곧바로 _watch에 들어간다.
        if target is not self._watch:
            target.area_x = self._watch.area_x
            target.area_y = self._watch.area_y
            target.area_w = self._watch.area_w
            target.area_h = self._watch.area_h
            target.masks = list(self._watch.masks)

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # ------------------------------------------------------------------
    # 그림 고르기
    # ------------------------------------------------------------------
    def _refresh_icon_list(self) -> None:
        names = icons_mod.list_icons(self.engine.library_root)
        self.icon_box.configure(values=names)

    def _on_icon_pick(self) -> None:
        self._watch.icon = self.icon_var.get().strip()
        # 다른 그림에는 이 마스크가 맞지 않는다. 그대로 두면 엉뚱한 데를 가린 채
        # "왜 안 잡히지"로 이어진다.
        if self._watch.masks:
            self._watch.masks = []
            self.engine.log("그림을 바꿔서 가린 칸을 지웠습니다. 다시 지정해 주세요.")
        self._redraw()
        self._changed()

    def _capture_icon(self) -> None:
        """화면에서 두 모서리를 눌러 그 사각형을 그림으로 저장한다."""
        window = self.engine.window()
        if window is None:
            messagebox.showwarning(
                "게임 창 없음", "먼저 게임 창을 찾아야 합니다.", parent=self
            )
            return
        messagebox.showinfo(
            "그림 잘라내기",
            "버프 아이콘의 **왼쪽 위**와 **오른쪽 아래**를 차례로 클릭하세요.\n\n"
            "숫자까지 포함해서 넉넉히 잘라도 됩니다 — 숫자 칸은 다음 단계에서 "
            "끌어서 가립니다.",
            parent=self,
        )
        first = capture_click_point(self.winfo_toplevel(), window)
        if first is None:
            return
        second = capture_click_point(self.winfo_toplevel(), window)
        if second is None:
            return

        x1, y1 = min(first[0], second[0]), min(first[1], second[1])
        x2, y2 = max(first[0], second[0]), max(first[1], second[1])
        w, h = x2 - x1, y2 - y1
        if w < 4 or h < 4:
            messagebox.showwarning(
                "너무 작음", f"잘라낸 크기가 {w}x{h}입니다. 조금 더 넓게 잡아 주세요.",
                parent=self,
            )
            return

        sx, sy = window.client_to_screen(x1, y1)
        try:
            template = imagematch.capture_template(sx, sy, w, h)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("잘라내기 실패", str(exc), parent=self)
            return

        name = self._ask_name(f"{w}x{h}")
        if not name:
            return
        filename = icons_mod.safe_filename(name)
        try:
            path = icons_mod.save_template(self.engine.library_root, filename, template)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return

        icons_mod.TEMPLATES.clear()
        self._refresh_icon_list()
        self.icon_var.set(filename)
        self._watch.icon = filename
        self._watch.masks = []
        self._redraw()
        self._changed()
        self.engine.log(f"감지 그림 저장: {path.name} ({w}x{h})")

    def _ask_name(self, hint: str) -> str:
        top = tk.Toplevel(self)
        top.title("그림 이름")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.configure(background=theme.PALETTE["bg"])
        ttk.Label(top, text=f"이 그림({hint})을 무엇으로 저장할까요?", padding=12).pack()
        var = tk.StringVar(value="")
        entry = ttk.Entry(top, textvariable=var, width=30)
        entry.pack(padx=12)
        entry.focus_set()
        result: dict[str, str] = {}

        def ok(_event=None) -> None:
            result["name"] = var.get().strip()
            top.destroy()

        buttons = ttk.Frame(top, padding=12)
        buttons.pack()
        ttk.Button(buttons, text="저장", style="Accent.TButton", command=ok).pack(side="left")
        ttk.Button(buttons, text="취소", command=top.destroy).pack(side="left", padx=6)
        entry.bind("<Return>", ok)
        top.grab_set()
        self.wait_window(top)
        return result.get("name", "")

    def _import_png(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="아이콘 PNG 고르기", filetypes=[("PNG 그림", "*.png")]
        )
        if not path:
            return
        from pathlib import Path

        from ..png import PngError, read_rgb

        try:
            width, height, rgb = read_rgb(path)
        except (PngError, OSError) as exc:
            messagebox.showerror("읽기 실패", str(exc), parent=self)
            return
        filename = icons_mod.safe_filename(Path(path).stem)
        try:
            icons_mod.save_template(
                self.engine.library_root, filename,
                imagematch.Template(width, height, rgb),
            )
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return
        icons_mod.TEMPLATES.clear()
        self._refresh_icon_list()
        self.icon_var.set(filename)
        self._watch.icon = filename
        self._watch.masks = []
        self._redraw()
        self._changed()

    # ------------------------------------------------------------------
    # 찾을 영역
    # ------------------------------------------------------------------
    def _capture_area(self) -> None:
        window = self.engine.window()
        if window is None:
            messagebox.showwarning(
                "게임 창 없음", "먼저 게임 창을 찾아야 합니다.", parent=self
            )
            return
        messagebox.showinfo(
            "찾을 영역",
            "버프 아이콘들이 **늘어설 수 있는 범위 전체**의 왼쪽 위와 오른쪽 아래를 "
            "차례로 클릭하세요.\n\n버프가 끝나면 뒤엣것이 앞으로 당겨지므로, 한 칸이 "
            "아니라 줄 전체를 잡아야 합니다.",
            parent=self,
        )
        first = capture_click_point(self.winfo_toplevel(), window)
        if first is None:
            return
        second = capture_click_point(self.winfo_toplevel(), window)
        if second is None:
            return
        x1, y1 = min(first[0], second[0]), min(first[1], second[1])
        x2, y2 = max(first[0], second[0]), max(first[1], second[1])
        self._watch.area_x, self._watch.area_y = x1, y1
        self._watch.area_w, self._watch.area_h = x2 - x1, y2 - y1
        self._sync_area()
        self._changed()
        self.engine.log(
            f"찾을 영역: ({x1}, {y1}) {self._watch.area_w}x{self._watch.area_h}"
        )

    def _clear_area(self) -> None:
        self._watch.area_w = self._watch.area_h = 0
        self._sync_area()
        self._changed()

    def _sync_area(self) -> None:
        w = self._watch
        if w.area_w > 0 and w.area_h > 0:
            self.area_var.set(f"({w.area_x}, {w.area_y}) {w.area_w}x{w.area_h}")
        else:
            self.area_var.set("지정 안 함 (창 전체 — 느립니다)")

    # ------------------------------------------------------------------
    # 미리보기 + 마스크 드래그
    # ------------------------------------------------------------------
    def _template_path(self):
        name = self.icon_var.get().strip()
        if not name:
            return None
        return icons_mod.icon_path(self.engine.library_root, name)

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._photo = None
        path = self._template_path()
        if path is None or not path.exists():
            self.canvas.configure(width=PREVIEW_MAX, height=120)
            self.canvas.create_text(
                PREVIEW_MAX // 2, 60, text="그림을 먼저 고르세요",
                fill=theme.PALETTE["faint"],
            )
            self._sync_mask_label()
            return

        try:
            image = tk.PhotoImage(file=str(path))
        except tk.TclError:
            self.canvas.create_text(
                PREVIEW_MAX // 2, 60, text="그림을 읽지 못했습니다",
                fill=theme.PALETTE["danger"],
            )
            return

        # 큰 그림도 칸 안에 담기도록 배율을 줄인다. 최소 2배는 유지한다 —
        # 1배로는 숫자 칸을 손으로 짚을 수 없다.
        longest = max(image.width(), image.height(), 1)
        self._zoom = max(2, min(ZOOM, PREVIEW_MAX // longest))
        self._photo = image.zoom(self._zoom)
        self.canvas.configure(width=self._photo.width(), height=self._photo.height())
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")

        for rect in self._watch.masks:
            self._draw_mask(rect)
        self._sync_mask_label()

    def _draw_mask(self, rect: MaskRect) -> None:
        z = self._zoom
        self.canvas.create_rectangle(
            rect.x * z, rect.y * z, (rect.x + rect.w) * z, (rect.y + rect.h) * z,
            outline=theme.PALETTE["danger"], width=2,
            fill=theme.PALETTE["danger"], stipple="gray50",
        )

    def _sync_mask_label(self) -> None:
        masks = self._watch.masks
        if not masks:
            self.mask_var.set("가린 칸 없음")
            return
        path = self._template_path()
        total = ""
        if path is not None and path.exists():
            template = icons_mod.TEMPLATES.masked(
                path, tuple((m.x, m.y, m.w, m.h) for m in masks)
            )
            if template is not None:
                kept = template.used_count
                whole = template.pixel_count
                total = f" — 비교에 쓰는 픽셀 {kept}/{whole} ({kept * 100 // max(whole, 1)}%)"
        self.mask_var.set(f"가린 칸 {len(masks)}개{total}")

    def _mask_press(self, event: tk.Event) -> None:
        if self._photo is None:
            return
        self._drag_start = (event.x, event.y)
        self._drag_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline=theme.PALETTE["danger"], width=2, dash=(3, 2),
        )

    def _mask_motion(self, event: tk.Event) -> None:
        if self._drag_start is None or self._drag_id is None:
            return
        x0, y0 = self._drag_start
        self.canvas.coords(self._drag_id, x0, y0, event.x, event.y)

    def _mask_release(self, event: tk.Event) -> None:
        if self._drag_start is None:
            return
        x0, y0 = self._drag_start
        self._drag_start = None
        if self._drag_id is not None:
            self.canvas.delete(self._drag_id)
            self._drag_id = None
        if self._photo is None:
            return

        z = self._zoom
        # 확대해서 그린 것을 원본 픽셀 좌표로 되돌린다. 걸친 칸은 통째로 가린다 —
        # 반쯤 걸친 픽셀을 남겨 두면 거기서 오차가 새어 나온다.
        left, right = sorted((x0, event.x))
        top, bottom = sorted((y0, event.y))
        rx = max(0, left // z)
        ry = max(0, top // z)
        rw = -(-right // z) - rx  # 올림 나눗셈
        rh = -(-bottom // z) - ry
        if rw <= 0 or rh <= 0:
            return
        self._watch.masks.append(MaskRect(x=int(rx), y=int(ry), w=int(rw), h=int(rh)))
        self._redraw()
        self._changed()

    def _undo_mask(self) -> None:
        if self._watch.masks:
            self._watch.masks.pop()
            self._redraw()
            self._changed()

    def _clear_masks(self) -> None:
        if self._watch.masks:
            self._watch.masks.clear()
            self._redraw()
            self._changed()

    # ------------------------------------------------------------------
    # 시험 / 측정
    # ------------------------------------------------------------------
    def _snapshot(self) -> IconWatch:
        """지금 화면에 입력된 값으로 임시 감시 설정을 만든다."""
        probe = IconWatch()
        self.save(probe)
        return probe

    def _test_once(self) -> None:
        watch = self._snapshot()
        window = self.engine.window()
        report = icons_mod.look(watch, self.engine.library_root, window, max_hits=4)
        if report.error:
            self.result_var.set(f"✘ {report.error}")
            return
        if report.found:
            spots = ", ".join(f"({m.x}, {m.y}) 점수 {m.score:.0f}" for m in report.matches)
            self.result_var.set(
                f"✔ 찾음 — {len(report.matches)}곳: {spots}   [{report.elapsed_ms:.0f}ms]"
            )
        else:
            self.result_var.set(
                f"✘ 못 찾음 — 허용 오차 {watch.tolerance} 안에 드는 곳이 없습니다. "
                f"[{report.elapsed_ms:.0f}ms]  ↓ [20회 측정]으로 실제 점수를 재 보세요."
            )

    def _measure(self) -> None:
        """허용 오차를 무시하고 지금 화면의 실제 점수를 여러 번 잰다.

        "몇으로 맞춰야 하나"를 감으로 정하면 반드시 틀린다. 버프가 **걸려 있는
        동안** 한 번, **끝난 뒤** 한 번 재서 두 값 사이를 고르면 된다.
        """
        watch = self._snapshot()
        if not watch.icon:
            self.result_var.set("✘ 그림을 먼저 고르세요.")
            return
        window = self.engine.window()
        self.result_var.set("측정 중…")
        self.update_idletasks()

        scores: list[float] = []
        spread: set[tuple[int, int]] = set()
        for _ in range(20):
            report = icons_mod.look(
                watch, self.engine.library_root, window, measure_tolerance=255
            )
            if report.error:
                self.result_var.set(f"✘ {report.error}")
                return
            if report.matches:
                best = report.matches[0]
                scores.append(best.score)
                spread.add((best.x, best.y))

        if not scores:
            self.result_var.set("✘ 아무것도 재지 못했습니다.")
            return
        low, high = min(scores), max(scores)
        avg = sum(scores) / len(scores)
        suggest = int(high) + 6
        where = f"{len(spread)}곳" if len(spread) > 1 else "같은 자리"
        self.result_var.set(
            f"지금 화면의 가장 닮은 점수 — 최소 {low:.0f} / 평균 {avg:.0f} / 최대 {high:.0f} "
            f"({where})\n"
            f"· 지금 버프가 **걸려 있는 중**이라면 허용 오차를 {suggest} 쯤으로 두세요.\n"
            f"· 지금 버프가 **끝난 상태**라면 허용 오차는 이 값({low:.0f})보다 "
            f"확실히 작아야 합니다."
        )
