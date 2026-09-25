"""숫자 조건(NumberWatch) 하나를 편집하는 칸.

피로도처럼 **숫자 자체가 조건인 것**을 다룬다. 하는 일이 셋이다.

1. **어디를 읽나** — 커서를 올려야 뜨는 툴팁이면 그 자리와, 숫자가 적힌 영역
2. **숫자 읽기** — 확인만 한다. 모양은 프로그램이 이미 알고 있다
3. **무엇과 견주나** — 앞 값이 뒤 값에 닿으면 / 앞 값이 얼마 이상이면 …

예전에는 숫자 열 개를 사람이 하나하나 익혀 줘야 했다. 게임 상태창 글씨가 늘
같은 점글씨라 프로그램이 그냥 알고 있으면 될 일이었다(digits.BUILTIN_5X7).
익히기는 글씨체가 유별난 게임을 위해 '손으로 맞추기' 안에 접어 두었다.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .. import digits as digits_mod
from .. import numprobe
from .. import sender
from . import region_picker
from ..model import (
    NUM_AT_LEAST,
    NUM_AT_MAX,
    NUM_AT_MOST,
    NUM_CURRENT,
    NUM_LEFT,
    NUM_MAX,
    NUM_PERCENT,
    NumberWatch,
)
from . import theme
from .widgets import capture_click_point, get_float, get_int, int_entry

TARGET_LABELS = {
    NUM_AT_MAX: "앞 값이 뒤 값에 닿으면 (가득 참)",
    NUM_PERCENT: "비율(%)",
    NUM_CURRENT: "앞 값",
    NUM_LEFT: "남은 양 (뒤 − 앞)",
    NUM_MAX: "뒤 값",
}
TARGET_BY_LABEL = {v: k for k, v in TARGET_LABELS.items()}

COMPARE_LABELS = {NUM_AT_LEAST: "이상일 때", NUM_AT_MOST: "이하일 때"}
COMPARE_BY_LABEL = {v: k for k, v in COMPARE_LABELS.items()}

INK_LABELS = {True: "밝은 배경에 어두운 글자", False: "어두운 배경에 밝은 글자"}
INK_BY_LABEL = {v: k for k, v in INK_LABELS.items()}

# 익히기 미리보기에서 글자를 몇 배로 키울지.
LEARN_ZOOM = 6
PREVIEW_W = 620


class NumberWatchPanel(ttk.Frame):
    """NumberWatch 하나를 고치는 칸."""

    def __init__(self, parent: tk.Misc, engine, on_change=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._on_change = on_change
        self._watch = NumberWatch()
        self._photo: tk.PhotoImage | None = None
        self._glyphs: list = []

        self.columnconfigure(1, weight=1)

        self.hover_var = tk.StringVar(value="안 올림 (늘 보이는 숫자)")
        self.wait_var = tk.StringVar(value="400")
        self.area_var = tk.StringVar(value="지정 안 함")
        self.font_var = tk.StringVar(value=digits_mod.AUTO_FONT)
        self.ink_var = tk.StringVar(value=INK_LABELS[True])
        self.threshold_var = tk.StringVar(value="128")
        self.target_var = tk.StringVar(value=TARGET_LABELS[NUM_AT_MAX])
        self.compare_var = tk.StringVar(value=COMPARE_LABELS[NUM_AT_LEAST])
        self.value_var = tk.StringVar(value="100")
        self.learn_var = tk.StringVar(value="")
        self.result_var = tk.StringVar(value="")
        self.glyph_var = tk.StringVar(value="")

        row = 0
        # -- 어디를 읽나 ---------------------------------------------------
        where = ttk.LabelFrame(self, text="① 어디를 읽나", padding=8)
        where.grid(row=row, column=0, columnspan=2, sticky="ew")
        where.columnconfigure(1, weight=1)

        ttk.Label(where, text="커서 올릴 자리").grid(row=0, column=0, sticky="w", padx=(0, 6))
        hover = ttk.Frame(where)
        hover.grid(row=0, column=1, sticky="ew")
        ttk.Button(
            hover, text="화면에서 찍기", style="Small.TButton", command=self._pick_hover
        ).pack(side="left")
        ttk.Button(
            hover, text="안 올림", style="Small.TButton", command=self._clear_hover
        ).pack(side="left", padx=4)
        ttk.Label(hover, textvariable=self.hover_var, style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(hover, text="뜰 때까지(ms)").pack(side="left", padx=(14, 4))
        int_entry(hover, self.wait_var, width=6).pack(side="left")

        ttk.Label(where, text="숫자 영역").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        area = ttk.Frame(where)
        area.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        ttk.Button(
            area, text="영역 고르기 (정지 화면에서)", style="Small.TButton",
            command=self._pick_area,
        ).pack(side="left")
        ttk.Label(area, textvariable=self.area_var, style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )

        ttk.Label(
            where,
            style="Faint.TLabel",
            justify="left",
            wraplength=PREVIEW_W,
            text="[영역 고르기]를 누르면 읽을 때와 똑같이 커서를 올린 채 화면을 찍어 "
            "보여 줍니다. 그 정지 화면 위에서 끌어 고르면 됩니다 — 툴팁이 사라질 "
            "걱정 없이 정확히 잡을 수 있습니다.\n"
            "영역은 숫자 줄만 감싸도록 좁게, 상자 테두리는 빼고 잡으세요.",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # -- 글꼴 ------------------------------------------------------------
        row += 1
        learn = ttk.LabelFrame(self, text="② 숫자 읽기", padding=8)
        learn.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        learn.columnconfigure(1, weight=1)

        ttk.Label(
            learn, style="Faint.TLabel", justify="left", wraplength=PREVIEW_W,
            text="숫자 모양은 프로그램이 이미 알고 있습니다 — 익힐 것이 없습니다. "
                 "글자 색·밝기도 읽을 때마다 스스로 맞춥니다.\n"
                 "아래 [지금 읽어 보기]로 확인만 하면 됩니다. 글씨체가 유별나서 "
                 "안 읽힐 때만 '손으로 맞추기'를 펴세요.",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.manual_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            learn, text="손으로 맞추기 · 글꼴 익히기 (보통은 안 해도 됩니다)",
            variable=self.manual_var, command=self._sync_manual,
        ).grid(row=1, column=0, columnspan=2, sticky="w")

        self.manual = ttk.Frame(learn)
        self.manual.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.manual.columnconfigure(1, weight=1)

        top = ttk.Frame(self.manual)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(top, text="글꼴 이름").pack(side="left", padx=(0, 6))
        self.font_box = ttk.Combobox(top, textvariable=self.font_var, width=18)
        self.font_box.pack(side="left")
        self.font_box.bind("<<ComboboxSelected>>", lambda _e: self._on_font_pick())
        self.font_box.bind("<FocusOut>", lambda _e: self._on_font_pick())
        self.font_box.bind("<Return>", lambda _e: self._on_font_pick())
        ttk.Button(
            top, text="자동 맞추기", style="Small.TButton", command=self._autotune
        ).pack(side="left", padx=(10, 0))

        ttk.Label(top, text="글자 색").pack(side="left", padx=(14, 6))
        ink_box = ttk.Combobox(
            top, textvariable=self.ink_var, values=list(INK_LABELS.values()),
            width=22, state="readonly",
        )
        ink_box.pack(side="left")
        ink_box.bind("<<ComboboxSelected>>", lambda _e: self._changed())

        ttk.Label(top, text="밝기 기준").pack(side="left", padx=(14, 6))
        int_entry(top, self.threshold_var, width=5).pack(side="left")

        ttk.Button(
            self.manual, text="지금 화면 잘라 보기", command=self._preview
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(self.manual, textvariable=self.glyph_var, style="Muted.TLabel").grid(
            row=1, column=1, sticky="w", pady=(8, 0), padx=(10, 0)
        )

        self.canvas = tk.Canvas(
            self.manual, width=PREVIEW_W, height=70, highlightthickness=1,
            highlightbackground=theme.PALETTE["border"],
            background=theme.PALETTE["surface"],
        )
        self.canvas.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        typing = ttk.Frame(self.manual)
        typing.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(typing, text="위에 보이는 대로 적으세요").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(typing, textvariable=self.learn_var, width=28)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._learn())
        ttk.Button(
            typing, text="익히기", style="Accent.TButton", command=self._learn
        ).pack(side="left", padx=6)

        ttk.Label(
            self.manual,
            style="Faint.TLabel",
            justify="left",
            wraplength=PREVIEW_W,
            text="글꼴 이름은 **아무렇게나** 지으면 됩니다 — 익힌 숫자 모양을 담아 둘 "
            "폴더 이름일 뿐입니다(예: 피로도). 같은 이름을 여러 조건에서 함께 쓸 수 "
            "있습니다.\n"
            "적을 때는 띄어쓰기 없이, 잘린 글자 개수와 똑같이 적어야 짝이 맞습니다. "
            "한 번에 열 자를 다 볼 수는 없으니, 값이 달라졌을 때 다시 눌러 "
            "모르는 숫자를 채워 나가면 됩니다.",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.known_var = tk.StringVar(value="")
        ttk.Label(self.manual, textvariable=self.known_var,
                  style="Muted.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        # -- 판정 ------------------------------------------------------------
        row += 1
        judge = ttk.LabelFrame(self, text="③ 언제 성립하나", padding=8)
        judge.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        ttk.Label(judge, text="무엇을").grid(row=0, column=0, sticky="w", padx=(0, 6))
        target_box = ttk.Combobox(
            judge, textvariable=self.target_var, values=list(TARGET_LABELS.values()),
            width=28, state="readonly",
        )
        target_box.grid(row=0, column=1, sticky="w")
        target_box.bind("<<ComboboxSelected>>", lambda _e: self._on_target_change())

        self.value_entry = ttk.Entry(judge, textvariable=self.value_var, width=10)
        self.value_entry.grid(row=0, column=2, sticky="w", padx=(12, 6))
        self.compare_box = ttk.Combobox(
            judge, textvariable=self.compare_var, values=list(COMPARE_LABELS.values()),
            width=10, state="readonly",
        )
        self.compare_box.grid(row=0, column=3, sticky="w")
        self.compare_box.bind("<<ComboboxSelected>>", lambda _e: self._changed())

        self.judge_hint = ttk.Label(
            judge, style="Faint.TLabel", justify="left", wraplength=PREVIEW_W
        )
        self.judge_hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))

        # -- 시험 ------------------------------------------------------------
        row += 1
        test = ttk.Frame(self)
        test.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(test, text="지금 읽어 보기", command=self._test).pack(side="left")
        row += 1
        ttk.Label(
            self, textvariable=self.result_var, style="Muted.TLabel",
            justify="left", wraplength=PREVIEW_W,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._refresh_fonts()
        self._sync_target()

    # ------------------------------------------------------------------
    def load(self, watch: NumberWatch) -> None:
        self._watch = watch
        self._refresh_fonts()
        known = digits_mod.list_fonts(self.engine.library_root)
        if watch.font and watch.font not in known:
            # 익힌 적 없는 이름이 적혀 있으면(폴더를 옮겼거나 이름만 적어 둔 경우)
            # 그대로 두면 읽기가 통째로 실패한다. 내장 모양으로 읽게 돌려놓는다.
            watch.font = ""
        self.font_var.set(watch.font or digits_mod.AUTO_FONT)
        self.manual_var.set(bool(watch.font))
        self.wait_var.set(str(watch.hover_wait_ms))
        self.ink_var.set(INK_LABELS[bool(watch.dark_text)])
        self.threshold_var.set(str(watch.threshold))
        self.target_var.set(TARGET_LABELS.get(watch.target, TARGET_LABELS[NUM_AT_MAX]))
        self.compare_var.set(
            COMPARE_LABELS.get(watch.compare, COMPARE_LABELS[NUM_AT_LEAST])
        )
        self.value_var.set(f"{watch.value:g}")
        self.learn_var.set("")
        self.result_var.set("")
        self.glyph_var.set("")
        self._glyphs = []
        self.canvas.delete("all")
        self._photo = None
        self._sync_hover()
        self._sync_area()
        self._sync_target()
        self._sync_known()
        self._sync_manual()

    def save(self, watch: NumberWatch | None = None) -> None:
        target = watch if watch is not None else self._watch
        picked = self.font_var.get().strip()
        target.font = "" if picked == digits_mod.AUTO_FONT else picked
        target.hover_wait_ms = max(0, get_int(self.wait_var, 400))
        target.dark_text = INK_BY_LABEL.get(self.ink_var.get(), True)
        target.threshold = max(0, min(255, get_int(self.threshold_var, 128)))
        target.target = TARGET_BY_LABEL.get(self.target_var.get(), NUM_AT_MAX)
        target.compare = COMPARE_BY_LABEL.get(self.compare_var.get(), NUM_AT_LEAST)
        target.value = get_float(self.value_var, 100.0)
        if target is not self._watch:
            for field in ("hover_x", "hover_y", "area_x", "area_y", "area_w", "area_h"):
                setattr(target, field, getattr(self._watch, field))

    def _changed(self) -> None:
        self._sync_target()
        if self._on_change is not None:
            self._on_change()

    def _snapshot(self) -> NumberWatch:
        probe = NumberWatch()
        self.save(probe)
        return probe

    # ------------------------------------------------------------------
    # 어디를 읽나
    # ------------------------------------------------------------------
    def _window(self):
        window = self.engine.window()
        if window is None:
            messagebox.showwarning(
                "게임 창 없음", "먼저 게임 창을 찾아야 합니다.", parent=self
            )
        return window

    def _pick_hover(self) -> None:
        window = self._window()
        if window is None:
            return
        messagebox.showinfo(
            "커서 올릴 자리",
            "숫자를 띄우려면 커서를 올려야 하는 자리를 클릭하세요.\n\n"
            "읽을 때마다 커서가 잠깐 그 자리로 갔다가 원래 자리로 돌아옵니다.",
            parent=self,
        )
        got = capture_click_point(self.winfo_toplevel(), window)
        if got is None:
            return
        self._watch.hover_x, self._watch.hover_y = got[0], got[1]
        self._sync_hover()
        self._changed()
        self.engine.log(f"커서 올릴 자리: ({got[0]}, {got[1]})")

    def _clear_hover(self) -> None:
        self._watch.hover_x = self._watch.hover_y = -1
        self._sync_hover()
        self._changed()

    def _sync_hover(self) -> None:
        w = self._watch
        if w.hovers:
            self.hover_var.set(f"({w.hover_x}, {w.hover_y})")
        else:
            self.hover_var.set("안 올림 (늘 보이는 숫자)")

    def _pick_area(self) -> None:
        """읽을 때와 똑같이 커서를 올린 채 찍은 **정지 화면**에서 고른다.

        예전에는 화면을 두 번 클릭하게 했는데, 툴팁은 마우스를 움직이는 순간
        사라진다. 그래서 정작 툴팁이 없는 화면에서 기억으로 모서리를 찍게 되고,
        읽을 때와 다른 자리를 잡기 쉬웠다.
        """
        window = self._window()
        if window is None:
            return
        w = self._watch
        hover = (w.hover_x, w.hover_y) if w.hovers else None
        initial = (w.area_x, w.area_y, w.area_w, w.area_h) if w.area_w > 0 else None
        rect, tuned = region_picker.pick(
            self.winfo_toplevel(), self.engine,
            hover=hover, wait_ms=max(0, get_int(self.wait_var, 400)),
            initial=initial, title="숫자 영역 고르기",
        )
        if rect is None:
            return
        w.area_x, w.area_y, w.area_w, w.area_h = rect
        if tuned is not None:
            # 고르는 화면에서 이미 색과 밝기를 알아냈다. 사용자가 다시 고르게
            # 하면 반대로 고르기 쉽고, 그러면 배경이 통째로 한 글자가 된다.
            dark, threshold = tuned
            self.ink_var.set(INK_LABELS[dark])
            self.threshold_var.set(str(threshold))
        self._sync_area()
        self._changed()
        self.engine.log(f"숫자 영역: ({rect[0]}, {rect[1]}) {rect[2]}x{rect[3]}")

    def _sync_area(self) -> None:
        w = self._watch
        if w.area_w > 0 and w.area_h > 0:
            self.area_var.set(f"({w.area_x}, {w.area_y}) {w.area_w}x{w.area_h}")
        else:
            self.area_var.set("지정 안 함")

    # ------------------------------------------------------------------
    # 글꼴 익히기
    # ------------------------------------------------------------------
    def _refresh_fonts(self) -> None:
        names = [digits_mod.AUTO_FONT] + digits_mod.list_fonts(self.engine.library_root)
        self.font_box.configure(values=names)

    def _sync_manual(self) -> None:
        """'손으로 맞추기'를 접었다 폈다."""
        if self.manual_var.get():
            self.manual.grid()
        else:
            self.manual.grid_remove()

    def _on_font_pick(self) -> None:
        self._watch.font = self.font_var.get().strip()
        self._sync_known()
        self._changed()

    def _sync_known(self) -> None:
        name = self.font_var.get().strip()
        if not name or name == digits_mod.AUTO_FONT:
            self.known_var.set(
                "'자동' — 프로그램에 들어 있는 숫자 모양으로 읽습니다. 익힐 것 없습니다."
            )
            return
        font = digits_mod.find_font(self.engine.library_root, name)
        if not font:
            self.known_var.set(
                f"'{name}' — 익힌 것이 없어 내장 숫자 모양으로 읽습니다."
            )
            return
        missing = font.digits_missing
        text = f"'{name}' — 익힌 숫자 {font.digits_known or '없음'}"
        if missing:
            text += f"   (모르는 숫자 {missing}은(는) 내장 모양으로 읽습니다)"
        else:
            text += "   ✔ 0~9 전부 익혔습니다"
        other = "".join(c for c in font.shapes if not c.isdigit())
        if other:
            text += f"   (그 밖에: {other})"
        self.known_var.set(text)

    def _autotune(self) -> None:
        """글자 색과 밝기 기준을 대신 찾아 준다.

        사람이 고르게 두면 반대로 고르기 쉽고, 그러면 배경이 통째로 한 글자로
        잡혀 "1개를 잘랐습니다"가 된다. 경우의 수가 열몇 개뿐이라 전부 해 보는
        편이 빠르고 확실하다.
        """
        frame = self._grab_area()
        if frame is None:
            return
        dark, threshold, glyphs, score = digits_mod.autotune(frame)
        if score <= 0:
            self.glyph_var.set(
                "어떤 설정으로도 글자가 나뉘지 않습니다 — 영역을 숫자 줄에만 "
                "맞게 다시 잡아 보세요."
            )
            return
        self.ink_var.set(INK_LABELS[dark])
        self.threshold_var.set(str(threshold))
        self._glyphs = glyphs
        self._draw_glyphs()
        self.glyph_var.set(
            f"자동 맞춤: {INK_LABELS[dark]} · 밝기 기준 {threshold} → "
            f"글자 {len(glyphs)}개"
        )
        self._guess_typed()
        self._changed()

    def _grab_area(self):
        """지금 설정으로 숫자 영역만 찍어 온다. 못 찍으면 None.

        읽을 때와 똑같이 커서를 올렸다가 **반드시 되돌린다.**
        """
        from .. import pixel

        if self._watch.area_w <= 0:
            self.glyph_var.set("숫자 영역을 먼저 지정하세요.")
            return None
        window = self.engine.window()
        if window is None:
            self.glyph_var.set("게임 창을 찾지 못했습니다.")
            return None
        area = self._watch.area(window)
        if area is None:
            self.glyph_var.set("읽을 영역이 잘못되었습니다.")
            return None

        restore = None
        try:
            if self._watch.hovers:
                restore = sender.cursor_pos()
                hx, hy = window.client_to_screen(
                    self._watch.hover_x, self._watch.hover_y
                )
                sender.mouse_move(hx, hy)
                wait = max(0, get_int(self.wait_var, 400)) / 1000.0
                if wait:
                    time.sleep(wait)
            return pixel.capture_region(*area)
        except pixel.CaptureError as exc:
            self.glyph_var.set(str(exc))
            return None
        finally:
            if restore is not None:
                try:
                    sender.mouse_move(*restore)
                except OSError:
                    pass

    def _guess_typed(self) -> None:
        """이미 익힌 글꼴이 있으면 적을 칸을 미리 채워 준다."""
        font = digits_mod.Font.load(self.engine.library_root, self.font_var.get().strip())
        if font and self._glyphs:
            guess, _scores = font.read(self._glyphs)
            if "?" not in guess:
                self.learn_var.set(guess)

    def _preview(self) -> None:
        """지금 화면을 잘라 글자 상자들을 보여 준다."""
        watch = self._snapshot()
        if watch.area_w <= 0:
            self.glyph_var.set("숫자 영역을 먼저 지정하세요.")
            return
        window = self.engine.window()
        if window is None:
            self.glyph_var.set("게임 창을 찾지 못했습니다.")
            return

        # 익히기 단계에서는 글꼴 없이도 잘라 보기만 한다.
        probe = NumberWatch(**{**watch.to_dict(), "font": ""})
        for field in ("hover_x", "hover_y", "area_x", "area_y", "area_w", "area_h"):
            setattr(probe, field, getattr(self._watch, field))
        reading = digits_mod.grab(probe, self.engine.library_root, window)
        self._glyphs = reading.glyphs
        self._draw_glyphs()

        if not reading.glyphs:
            self.glyph_var.set(
                "글자를 하나도 찾지 못했습니다 — [자동 맞추기]를 눌러 보세요."
            )
            return
        # 지금 설정이 최선인지 확인한다. "3개를 잘랐습니다"처럼 그럴듯해 보여도
        # 사실은 배경이 뭉쳐 있는 경우가 있어서, 개수만 보고는 알 수 없다.
        better = self._better_setting(reading.glyphs)
        if better is not None:
            dark, threshold, count = better
            self.glyph_var.set(
                f"⚠ 지금 설정으로는 {len(reading.glyphs)}개로만 나뉩니다. "
                f"[{INK_LABELS[dark]} · 밝기 {threshold}]로 하면 {count}개로 나뉩니다 "
                "— [자동 맞추기]를 눌러 보세요."
            )
            return
        self.glyph_var.set(
            f"글자 {len(reading.glyphs)}개를 잘랐습니다 — 아래 칸에 "
            f"{len(reading.glyphs)}자를 그대로 적으세요."
        )
        self._guess_typed()

    def _better_setting(self, glyphs):
        """지금보다 눈에 띄게 잘 나뉘는 설정이 있으면 (색, 기준, 개수).

        개수만으로 판단하지 않는다. 배경이 뭉쳐 있으면 그럴듯한 개수가 나오기도
        한다. 그래서 '글자 한 줄처럼 보이는 정도'를 재서 견준다.
        """
        frame = self._grab_area()
        if frame is None:
            return None
        watch = self._snapshot()
        mine = digits_mod.quality(glyphs, frame.w, frame.h)
        dark, threshold, best, score = digits_mod.autotune(frame)
        if (dark, threshold) == (watch.dark_text, watch.threshold):
            return None
        # 어중간하게 나은 정도로는 사용자를 흔들지 않는다.
        if score <= mine + 1.5 or len(best) <= len(glyphs):
            return None
        return (dark, threshold, len(best))

    def _draw_glyphs(self) -> None:
        """잘라낸 글자들을 키워서 한 줄로 그린다."""
        self.canvas.delete("all")
        self._photo = None
        if not self._glyphs:
            self.canvas.create_text(
                PREVIEW_W // 2, 35, text="[지금 화면 잘라 보기]를 누르세요",
                fill=theme.PALETTE["faint"],
            )
            return

        gap = 2
        width = sum(g.w for g in self._glyphs) + gap * (len(self._glyphs) - 1)
        height = max(g.h for g in self._glyphs)
        image = tk.PhotoImage(width=max(width, 1), height=max(height, 1))
        image.put("#FFFFFF", to=(0, 0, width, height))
        x = 0
        for glyph in self._glyphs:
            for gy in range(glyph.h):
                run = []
                for gx in range(glyph.w):
                    run.append("#202020" if glyph.at(gx, gy) else "#FFFFFF")
                image.put("{" + " ".join(run) + "}", to=(x, gy))
            x += glyph.w + gap
        zoom = max(1, min(LEARN_ZOOM, PREVIEW_W // max(width, 1)))
        self._photo = image.zoom(zoom)
        self.canvas.configure(height=max(self._photo.height() + 8, 40))
        self.canvas.create_image(4, 4, image=self._photo, anchor="nw")

    def _learn(self) -> None:
        name = self.font_var.get().strip()
        if name == digits_mod.AUTO_FONT:
            messagebox.showinfo(
                "익힐 것 없습니다",
                "'자동'은 프로그램에 들어 있는 숫자 모양으로 읽습니다.\n\n"
                "그래도 이 게임 글씨를 따로 익히려면, 글꼴 이름을 '자동'이 아닌 "
                "다른 이름(예: 피로도)으로 적고 다시 누르세요.",
                parent=self,
            )
            return
        if not name:
            messagebox.showwarning("글꼴 이름", "글꼴 이름을 먼저 적으세요.", parent=self)
            return
        if not self._glyphs:
            messagebox.showwarning(
                "잘라낸 글자 없음", "먼저 [지금 화면 잘라 보기]를 누르세요.", parent=self
            )
            return
        typed = self.learn_var.get().strip()
        if len(typed) != len(self._glyphs):
            extra = ""
            if len(self._glyphs) <= 2 < len(typed):
                extra = (
                    "\n\n글자가 한 덩어리로 잡힌 것 같습니다. 배경이나 테두리를 "
                    "글자로 보고 있을 때 이렇게 됩니다 — [자동 맞추기]를 먼저 "
                    "눌러 보세요."
                )
            messagebox.showwarning(
                "글자 수가 다릅니다",
                f"잘린 글자는 {len(self._glyphs)}개인데 {len(typed)}자를 적으셨습니다.\n\n"
                "띄어쓰기 없이, 보이는 글자 수와 똑같이 적어 주세요." + extra,
                parent=self,
            )
            return

        font = digits_mod.Font.load(self.engine.library_root, name)
        font.name = name
        added = 0
        for glyph, char in zip(self._glyphs, typed):
            if char in digits_mod.LEARNABLE:
                font.learn(char, glyph)
                added += 1
        if not added:
            messagebox.showwarning(
                "익힐 것이 없습니다",
                f"익힐 수 있는 글쇠는 {digits_mod.LEARNABLE} 뿐입니다.",
                parent=self,
            )
            return
        try:
            folder = font.save(self.engine.library_root)
        except OSError as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return
        digits_mod.FONTS.clear()
        self._refresh_fonts()
        self._watch.font = name
        self._sync_known()
        self._changed()
        self.engine.log(f"숫자 글꼴 '{name}': {added}자 익힘 → {folder}")

    # ------------------------------------------------------------------
    # 판정
    # ------------------------------------------------------------------
    def _on_target_change(self) -> None:
        self._sync_target()
        self._changed()

    def _sync_target(self) -> None:
        target = TARGET_BY_LABEL.get(self.target_var.get(), NUM_AT_MAX)
        at_max = target == NUM_AT_MAX
        state = "disabled" if at_max else "normal"
        self.value_entry.configure(state=state)
        self.compare_box.configure(state="disabled" if at_max else "readonly")
        if at_max:
            self.judge_hint.configure(
                text="예: 피로도 10502 / 540000 → 앞 값이 540000이 되는 순간 성립합니다. "
                "최대값을 어디에도 적어 두지 않으므로, 최대값이 달라지는 날에도 "
                "그대로 맞습니다."
            )
        else:
            self.judge_hint.configure(text=self._snapshot().describe() + " 성립합니다.")

    def _test(self) -> None:
        watch = self._snapshot()
        for field in ("hover_x", "hover_y", "area_x", "area_y", "area_w", "area_h"):
            setattr(watch, field, getattr(self._watch, field))
        window = self.engine.window()
        reading = digits_mod.grab(watch, self.engine.library_root, window)
        self._glyphs = reading.glyphs
        self._draw_glyphs()

        if not reading.ok and not reading.error and watch.target != NUM_AT_MAX:
            # 글자가 섞여 있어도 숫자 낱말만 또렷하면 그것으로 — 실제 조건과 같게.
            numbers = digits_mod.numbers_from(reading.glyphs, reading.text)
            hit, detail = digits_mod.judge_numbers(watch, numbers)
            if hit is not None:
                mark = "✔ 조건 성립" if hit else "· 조건 불성립"
                found = " · ".join(n.text for n in numbers) or "없음"
                self.result_var.set(f"읽음: '{reading.text}' → 숫자 낱말: {found}\n"
                                    f"{mark} — {detail}")
                return
            blurred = detail
        if not reading.ok:
            # '앞 값이 뒤 값에 닿으면'은 글꼴 없이 모양으로도 판단한다 — 실제 조건과 같게.
            if watch.target == NUM_AT_MAX and reading.frame is not None:
                hit, detail = digits_mod.full_by_shape(reading.frame, watch, reading.glyphs)
                if hit is not None:
                    mark = "✔ 조건 성립 (가득)" if hit else "· 조건 불성립 (안 참)"
                    self.result_var.set(
                        f"글꼴로는 못 읽음 — {reading.describe()}\n"
                        f"{mark} — 모양 비교: {detail}")
                    return
                self.result_var.set(f"✘ {reading.describe()}\n모양 비교도 못 함: {detail}")
                return
            self.result_var.set(f"✘ {reading.describe()}"
                                + (f"\n{blurred}" if blurred else "")
                                + f"\n{self._rescue(watch)}")
            return
        current, maximum = reading.values[-2], reading.values[-1]
        hit, detail = watch.judge(current, maximum)
        mark = "✔ 조건 성립" if hit else "· 조건 불성립"
        self.result_var.set(
            f"읽음: '{reading.text}'  →  앞 {current} / 뒤 {maximum}   "
            f"[{reading.elapsed_ms:.0f}ms]{self._how(reading)}\n{mark} — {detail}"
        )

    def _rescue(self, watch) -> str:
        """못 읽었을 때 한 번 더 애써 본다.

        흔한 윈도 글꼴을 그려 보며 이 게임 글씨를 알아내고, 맞으면 그 모양을
        익혀 둔다(다음부터는 바로 읽는다). 그래도 못 알아보면 **무엇을 보고
        있었는지 그림으로 남겨** 어디가 문제인지 눈으로 볼 수 있게 한다.
        """
        self.result_var.set(self.result_var.get() + "\n글씨를 알아보는 중…")
        self.update_idletasks()
        try:
            name, detail = digits_mod.learn_line(
                watch, self.engine.library_root, self._window()
            )
        except Exception as exc:  # 글꼴을 못 그리는 환경
            name, detail = None, str(exc)
        if name:
            self._watch.font = name
            self.font_var.set(name)
            self._refresh_fonts()
            self._sync_known()
            self._changed()
            self.engine.log(f"숫자 글씨를 알아내 '{name}'(으)로 익혔습니다: {detail}")
            return (f"✔ 이 게임 글씨를 알아내 '{name}'(으)로 익혔습니다 → '{detail}'"
                    f"   [지금 읽어 보기]를 다시 눌러 보세요")
        shot = None
        try:
            shot = numprobe.save(
                digits_mod.grab(watch, self.engine.library_root, self._window()),
                "읽기실패",
            )
        except Exception:
            pass
        if shot is None:
            return "글씨를 못 알아봤습니다 — 영역을 숫자 줄에만 맞게 다시 잡아 보세요."
        return (f"글씨를 못 알아봤습니다. 무엇을 보고 있었는지 그림으로 남겼습니다:\n"
                f"{shot}")

    @staticmethod
    def _how(reading) -> str:
        """무엇으로 읽었는지 한 마디. 스스로 맞춘 것이 있으면 그것도."""
        bits = []
        if reading.reader:
            bits.append(f"{reading.reader} 모양")
        if reading.tuned:
            bits.append(f"스스로 맞춤: {reading.tuned}")
        return f"   ({' · '.join(bits)})" if bits else ""
