"""낚시 탭 — 미니게임을 자동으로 푼다.

낚시는 다른 기능과 성질이 다르다. 매크로는 정해진 것을 정해진 때에 보내면 되지만,
미니게임은 **움직이는 두 물체가 겹치는 순간**을 맞혀야 한다. 그 순간은 몇 ms뿐이고,
빗나가면 경험치가 줄고 물고기 체력이 회복된다. 그래서 여러 번 눌러 확률을 올리는
방법을 쓸 수 없다.

푸는 쪽은 [fishing.py]와 [fishtask.py]에, 고르는 창은 [fishpick.py]에, 눈으로
확인하는 창은 [fishcheck.py]에 있다. 이 파일은 그것들을 한 화면에 늘어놓는다.

화면은 **하는 순서대로** 놓았다.

    1. 판 잡기      미니게임이 창 안 어디에 뜨는가
    2. 클릭 범위    미니게임 도중 어디를 눌러도 되는가
    3. 낚시 흐름    던지기 · 머리 위 연타
    4. 성공 알림    "○○ 떡밥 1개가 차감됐어요" (빨간 글씨)
    5. 낚은 자세    낚싯대에 매달린 물고기가 흔들리는 자리
    6. 성공 효과음  낚시에 성공할 때 울리는 소리
    7. 배운 것

    4·5·6번은 **모두 낚음을 알아보는 근거**다. 하나만 있어도 돌지만, 함께 두면
    훨씬 덜 놓친다 — 서로 다른 이유로 놓치기 때문이다. 그중 **6번이 가장
    든든하다.** 앞의 둘은 결국 화면을 보는 것이라 창이 가리거나 자리가 밀리면
    그대로 못 보는데, 소리는 그런 것에 안 걸린다.

순서를 지키지 않으면 뒤엣것이 앞엣것 없이는 뜻이 없다 — 판을 안 잡고 색을 고를 수
없고, 색을 안 고르고 검사해 봐야 아무것도 안 나온다. 그래서 각 칸의 단추는
앞 단계가 없으면 이유를 말하고 멈춘다.
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from .. import fishing, pixel, sound
from ..fishtask import MotionWatch, spot_count
from ..model import FishingSetup
from . import fishcheck, fishpick, region_picker, theme
from .widgets import ColorSwatch, ScrollFrame, get_float, get_int, int_entry


def get_bool(var) -> bool:
    try:
        return bool(var.get())
    except Exception:  # noqa: BLE001 — 아직 안 만들어진 칸
        return False

TASK = ("fishing", "낚시")

BUTTON_LABELS = {"left": "왼쪽", "right": "오른쪽"}
BUTTON_BY_LABEL = {v: k for k, v in BUTTON_LABELS.items()}


class NoticeRow(ttk.LabelFrame):
    """낚시 성공 알림 — 게임 창 왼쪽 위에 뜨는 빨간 글씨.

    "○○ 떡밥 1개가 차감됐어요." 떡밥 종류가 많아 **글자는 매번 다르지만 색은 늘
    같다.** 그래서 글자를 읽지 않고 그 색이 몇 칸 보이는지만 센다. 글자를 읽으려
    들면 떡밥 이름을 전부 가르쳐야 하고, 하나라도 빠지면 그때부터 못 센다.
    """

    def __init__(self, parent, engine, get_setup, on_change) -> None:
        super().__init__(parent, text="4. 낚시 성공 알림 (빨간 글씨)",
                         padding=theme.pad(8))
        self.engine = engine
        self._get = get_setup
        self._on_change = on_change
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("낚시에 성공하면 게임 창 왼쪽 위에 "
                  "「○○ 떡밥 1개가 차감됐어요」가 빨간 글씨로 뜹니다. 이 글씨가 "
                  "보이면 = 경험치를 얻었고 = 한 마리 낚았고 = 다시 던질 때입니다.\n"
                  "그 글씨가 떠 있을 때 [영역 지정] → [색 고르기]로 빨간 글자를 "
                  "찍어 주세요."),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info_var).grid(
            row=1, column=0, columnspan=2, sticky="w")
        self.swatch = ColorSwatch(self, size=theme.px(16))
        self.swatch.grid(row=1, column=2, sticky="e")

        line = ttk.Frame(self)
        line.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(line, text="영역 지정", style="Small.TButton",
                   command=self._pick_area).pack(side="left")
        ttk.Button(line, text="색 고르기", style="Small.TButton",
                   command=self._pick_color).pack(side="left", padx=4)
        ttk.Button(line, text="지금 보이나", style="Small.TButton",
                   command=self._probe).pack(side="left")
        ttk.Button(line, text="지우기", style="Small.TButton",
                   command=self._clear).pack(side="left", padx=4)

        nums = ttk.Frame(self)
        nums.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(nums, text="다시 안 셀 시간").pack(side="left", padx=(0, 3))
        self.cool_var = tk.StringVar(value="3")
        int_entry(nums, self.cool_var, width=5).pack(side="left")
        ttk.Label(nums, text="초").pack(side="left", padx=(2, 12))
        ttk.Label(nums, text="돌아가는 키").pack(side="left", padx=(0, 3))
        self.key_var = tk.StringVar(value="")
        ttk.Entry(nums, textvariable=self.key_var, width=8).pack(side="left")
        ttk.Label(nums, text="(비우면 던지는 키)", style="Faint.TLabel").pack(
            side="left", padx=(4, 0))
        for var in (self.cool_var, self.key_var):
            var.trace_add("write", lambda *_a: self._commit())

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("글씨는 몇 초 떠 있습니다. 떠 있는 내내 세면 한 마리를 여러 번 "
                  "센 것이 되므로, **없다가 생긴 순간**만 세고 그 뒤 잠깐은 "
                  "다시 세지 않습니다.").replace("**", ""),
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.refresh()

    @property
    def spot(self):
        return self._get().notice

    def refresh(self) -> None:
        spot = self.spot
        setup = self._get()
        if spot.w <= 0 or spot.h <= 0:
            self.info_var.set("아직 정하지 않음")
        else:
            self.info_var.set(
                f"창 기준 ({spot.x}, {spot.y}) · {spot.w}×{spot.h} · "
                f"{spot.color or '색 안 고름'} · 허용차 {spot.tol} · "
                f"{spot.min_px}칸 이상이면 떴다고 봄")
        self.swatch.set_color(pixel.from_hex(spot.color) or (40, 40, 40))
        if get_float(self.cool_var, -1) != setup.notice_cooldown_s:
            self.cool_var.set(f"{setup.notice_cooldown_s:g}")
        if self.key_var.get() != setup.resume_key:
            self.key_var.set(setup.resume_key)

    def _commit(self) -> None:
        setup = self._get()
        setup.notice_cooldown_s = max(0.5, min(30.0,
                                               get_float(self.cool_var, 3.0)))
        setup.resume_key = self.key_var.get().strip()
        self._on_change()

    def _pick_area(self) -> None:
        spot = self.spot
        initial = (spot.x, spot.y, spot.w, spot.h) if spot.w > 0 else None
        rect, _t = region_picker.pick(
            self, self.engine, initial=initial, show_digits=False,
            title="성공 알림이 뜨는 자리 (창 왼쪽 위)")
        if rect is None:
            return
        spot.x, spot.y, spot.w, spot.h = rect
        self.refresh()
        self._on_change()

    def _pick_color(self) -> None:
        spot = self.spot
        if spot.w <= 0 or spot.h <= 0:
            messagebox.showinfo("먼저 영역을 정하세요",
                                "[영역 지정]으로 자리를 먼저 정해 주세요.",
                                parent=self)
            return
        picker = fishpick.SpotPicker(self, self.engine, spot, "성공 알림")
        self.wait_window(picker)
        self.refresh()
        self._on_change()

    def _probe(self) -> None:
        spot = self.spot
        if not spot.ready:
            self.engine.log("성공 알림: 영역과 색을 먼저 정하세요.")
            return
        count = spot_count(spot, self.engine.window())
        verdict = "떴습니다" if count >= spot.min_px else "안 떴습니다"
        self.engine.log(
            f"성공 알림: {count}칸 (문턱 {spot.min_px}) → {verdict}")

    def _clear(self) -> None:
        spot = self.spot
        spot.x = spot.y = spot.w = spot.h = 0
        spot.color = ""
        self.refresh()
        self._on_change()


class PopupRow(ttk.LabelFrame):
    """버프 중첩 알림 — 켜져 있는 버프를 또 쓰면 뜨는 확인 창.

    "지금 적용 중인 낚시꾼의 왕관 효과를 낚시꾼의 왕관로 바꿀게요. 사용하시겠어요?"
    이 창이 떠 있으면 **뒤따르는 키가 전부 막혀** 낚시가 멈춘다. 뜨면 [Esc]를 한 번
    눌러 닫는다.

    무조건 누르지 않고 **보일 때만** 누른다. 아무 창도 없을 때 [Esc]를 누르면 게임
    메뉴가 열려 오히려 입력이 막힐 수 있다. 그래서 성공 알림처럼 색으로 알아본다 —
    창 안의 노란 글씨가 몇 칸 보이는지만 센다.
    """

    def __init__(self, parent, engine, get_setup, on_change) -> None:
        super().__init__(parent, text="4-1. 버프 중첩 알림 (뜨면 Esc 한 번)",
                         padding=theme.pad(8))
        self.engine = engine
        self._get = get_setup
        self._on_change = on_change
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("이미 켜져 있는 버프(왕관 등)를 또 쓰면 「지금 적용 중인 … 효과를 "
                  "…로 바꿀게요. 사용하시겠어요?」 창이 뜨고, 그동안 다른 키가 "
                  "막힙니다. 이 창이 보이면 [Esc]를 한 번 눌러 닫습니다.\n"
                  "그 창을 띄워 둔 채로 [영역 지정]으로 창을 감싸고, [색 고르기]로 "
                  "노란 글씨를 찍어 주세요. 창이 없을 때 [지금 보이나]가 "
                  "'안 떴습니다'여야 합니다."),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info_var).grid(
            row=1, column=0, columnspan=2, sticky="w")
        self.swatch = ColorSwatch(self, size=theme.px(16))
        self.swatch.grid(row=1, column=2, sticky="e")

        line = ttk.Frame(self)
        line.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(line, text="영역 지정", style="Small.TButton",
                   command=self._pick_area).pack(side="left")
        ttk.Button(line, text="색 고르기", style="Small.TButton",
                   command=self._pick_color).pack(side="left", padx=4)
        ttk.Button(line, text="지금 보이나", style="Small.TButton",
                   command=self._probe).pack(side="left")
        ttk.Button(line, text="지우기", style="Small.TButton",
                   command=self._clear).pack(side="left", padx=4)

        nums = ttk.Frame(self)
        nums.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(nums, text="닫는 키").pack(side="left", padx=(0, 3))
        self.key_var = tk.StringVar(value="Esc")
        ttk.Entry(nums, textvariable=self.key_var, width=8).pack(side="left")
        ttk.Label(nums, text="버프 키 뒤 지켜볼 시간").pack(side="left",
                                                     padx=(12, 3))
        self.wait_var = tk.StringVar(value="0.5")
        ttk.Entry(nums, textvariable=self.wait_var, width=5).pack(side="left")
        ttk.Label(nums, text="초").pack(side="left", padx=(2, 0))
        for var in (self.key_var, self.wait_var):
            var.trace_add("write", lambda *_a: self._commit())
        self.refresh()

    @property
    def spot(self):
        return self._get().stack_popup

    def refresh(self) -> None:
        spot = self.spot
        setup = self._get()
        if spot.w <= 0 or spot.h <= 0:
            self.info_var.set("아직 정하지 않음 — 알림이 떠도 못 닫습니다")
        else:
            self.info_var.set(
                f"창 기준 ({spot.x}, {spot.y}) · {spot.w}×{spot.h} · "
                f"{spot.color or '색 안 고름'} · 허용차 {spot.tol} · "
                f"{spot.min_px}칸 이상이면 떴다고 봄")
        self.swatch.set_color(pixel.from_hex(spot.color) or (40, 40, 40))
        if self.key_var.get() != setup.stack_close_key:
            self.key_var.set(setup.stack_close_key)
        if get_float(self.wait_var, -1) != setup.stack_wait_s:
            self.wait_var.set(f"{setup.stack_wait_s:g}")

    def _commit(self) -> None:
        setup = self._get()
        setup.stack_close_key = self.key_var.get().strip() or "Esc"
        setup.stack_wait_s = max(0.1, min(3.0, get_float(self.wait_var, 0.5)))
        self._on_change()

    def _pick_area(self) -> None:
        spot = self.spot
        initial = (spot.x, spot.y, spot.w, spot.h) if spot.w > 0 else None
        rect, _t = region_picker.pick(
            self, self.engine, initial=initial, show_digits=False,
            title="버프 중첩 알림 창이 뜨는 자리")
        if rect is None:
            return
        spot.x, spot.y, spot.w, spot.h = rect
        self.refresh()
        self._on_change()

    def _pick_color(self) -> None:
        spot = self.spot
        if spot.w <= 0 or spot.h <= 0:
            messagebox.showinfo("먼저 영역을 정하세요",
                                "[영역 지정]으로 자리를 먼저 정해 주세요.",
                                parent=self)
            return
        picker = fishpick.SpotPicker(self, self.engine, spot, "버프 중첩 알림")
        self.wait_window(picker)
        self.refresh()
        self._on_change()

    def _probe(self) -> None:
        spot = self.spot
        if not spot.ready:
            self.engine.log("버프 중첩 알림: 영역과 색을 먼저 정하세요.")
            return
        count = spot_count(spot, self.engine.window())
        verdict = "떴습니다" if count >= spot.min_px else "안 떴습니다"
        self.engine.log(
            f"버프 중첩 알림: {count}칸 (문턱 {spot.min_px}) → {verdict}")

    def _clear(self) -> None:
        spot = self.spot
        spot.x = spot.y = spot.w = spot.h = 0
        spot.color = ""
        self.refresh()
        self._on_change()


class MotionRow(ttk.LabelFrame):
    """낚은 자세 — 낚싯대 끝에 매달린 물고기의 **흔들림**.

    색으로 자세를 가리려던 적이 있는데 안 됐다. 낚는 자세와 낚시중 자세는 색이
    거의 같아서다. 하지만 **낚았을 때는 물고기가 매달려 쉬지 않고 까딱거린다.**
    색이 아니라 바뀌는 것을 보면 둘이 갈린다. 물고기 종류가 여러 가지라 색도
    모양도 매번 다른데, 흔들림은 종류를 안 가린다.

    **문턱은 스스로 잡는다.** 한때 절대 문턱을 사람이 재서 넣게 했는데, 자리마다
    물고기마다 배경마다 값이 딴판이라 한 번 잘 맞춘 값도 다음 판에는 안 맞았다.
    지금은 그 자리를 늘 보고 있으므로 조용할 때가 어느 만큼인지가 저절로 쌓이고,
    그 바탕의 몇 배로 튀면 움직임으로 본다.
    """

    SAMPLES = 24  # 재볼 때 찍는 장 수

    def __init__(self, parent, engine, get_setup, on_change) -> None:
        super().__init__(parent, text="5. 낚은 자세 (낚싯대 흔들림)",
                         padding=theme.pad(8))
        self.engine = engine
        self._get = get_setup
        self._on_change = on_change
        self._job = None  # 재보는 중인 타이머 (겹치면 사슬이 늘어난다)
        self._seen: list[int] = []
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("낚시에 성공하면 캐릭터가 낚싯대를 들고, 그 끝에 물고기가 매달려 "
                  "대롱대롱 흔들립니다. 자세만 봐서는 낚시중과 색이 거의 같아 "
                  "못 가리지만, **흔들리는지**를 보면 확실히 갈립니다.\n"
                  "[영역 지정]으로 낚싯대 끝 물고기가 있는 자리를 잡아 주세요 — "
                  "캐릭터 전체가 아니라 물고기만 좁게 잡을수록 잘 걸립니다."
                  ).replace("**", ""),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info_var).grid(
            row=1, column=0, columnspan=3, sticky="w")

        line = ttk.Frame(self)
        line.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(line, text="영역 지정", style="Small.TButton",
                   command=self._pick_area).pack(side="left")
        self.probe_btn = ttk.Button(line, text="지금 재보기",
                                    style="Small.TButton", command=self._probe)
        self.probe_btn.pack(side="left", padx=4)
        ttk.Button(line, text="지우기", style="Small.TButton",
                   command=self._clear).pack(side="left")

        nums = ttk.Frame(self)
        nums.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(nums, text="문턱 스스로 잡기",
                        variable=self.auto_var).pack(side="left", padx=(0, 10))
        ttk.Label(nums, text="바탕의").pack(side="left", padx=(0, 3))
        self.rise_var = tk.StringVar(value="3")
        ttk.Spinbox(nums, textvariable=self.rise_var, width=5, from_=1.2,
                    to=20.0, increment=0.5, format="%.1f").pack(side="left")
        ttk.Label(nums, text="배로 튀면 움직임").pack(side="left", padx=(2, 12))
        ttk.Label(nums, text="(직접 정하면").pack(side="left", padx=(0, 3))
        self.min_var = tk.StringVar(value="25")
        int_entry(nums, self.min_var, width=6).pack(side="left")
        ttk.Label(nums, text="칸)", style="Faint.TLabel").pack(
            side="left", padx=(2, 0))

        nums3 = ttk.Frame(self)
        nums3.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.span_var = tk.StringVar(value="1.2")
        ttk.Spinbox(nums3, textvariable=self.span_var, width=6, from_=0.2,
                    to=10.0, increment=0.1, format="%.1f").pack(side="left")
        ttk.Label(nums3, text="초 안에 움직인 장이").pack(side="left", padx=(3, 3))
        self.repeats_var = tk.StringVar(value="4")
        int_entry(nums3, self.repeats_var, width=4).pack(side="left")
        ttk.Label(nums3, text="개면 흔들리는 중 (되풀이)").pack(
            side="left", padx=(2, 0))

        nums2 = ttk.Frame(self)
        nums2.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(nums2, text="허용차").pack(side="left", padx=(0, 3))
        self.tol_var = tk.StringVar(value="16")
        int_entry(nums2, self.tol_var, width=5).pack(side="left")
        ttk.Label(nums2, text="(밝기가 이만큼 안쪽이면 같은 것)",
                  style="Faint.TLabel").pack(side="left", padx=(3, 12))
        ttk.Label(nums2, text="찍는 간격").pack(side="left", padx=(0, 3))
        self.gap_var = tk.StringVar(value="0.1")
        ttk.Entry(nums2, textvariable=self.gap_var, width=6).pack(side="left")
        ttk.Label(nums2, text="초").pack(side="left", padx=(2, 12))
        ttk.Label(nums2, text="다시 안 셀 시간").pack(side="left", padx=(0, 3))
        self.cool_var = tk.StringVar(value="4")
        ttk.Entry(nums2, textvariable=self.cool_var, width=5).pack(side="left")
        ttk.Label(nums2, text="초").pack(side="left", padx=(2, 0))

        for var in (self.min_var, self.rise_var, self.repeats_var,
                    self.span_var, self.tol_var, self.gap_var, self.cool_var):
            var.trace_add("write", lambda *_a: self._commit())
        self.auto_var.trace_add("write", lambda *_a: self._commit())

        self.result_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.result_var, justify="left",
                  wraplength=theme.px(720)).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("문턱을 손으로 맞힐 필요가 없습니다. 그 자리를 늘 지켜보면서 "
                  "조용할 때가 어느 만큼인지(바탕)를 스스로 재고, 그 몇 배로 "
                  "튀면 움직임으로 봅니다.\n"
                  "대롱대롱은 한 번이 아니라 되풀이입니다. 그래서 정한 시간 안에 "
                  "움직인 장이 몇 개는 나와야 흔들린다고 봅니다 — 창이 하나 뜨는 "
                  "것 같은 한 번뿐인 변화에 안 속으려는 것입니다.\n"
                  "[지금 재보기]로 바탕과 문턱이 어떻게 잡혔는지 볼 수 있습니다. "
                  "낚시중일 때와 낚았을 때 각각 눌러 보세요."),
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.refresh()

    @property
    def spot(self):
        return self._get().catch_motion

    def refresh(self) -> None:
        spot = self.spot
        if spot.w <= 0 or spot.h <= 0:
            self.info_var.set("아직 정하지 않음 — 빨간 글씨만으로 낚음을 셉니다")
        else:
            self.info_var.set(
                f"창 기준 ({spot.x}, {spot.y}) · {spot.w}×{spot.h} "
                f"({spot.area}칸) · {spot.gap_s * spot.need_frames:.1f}초쯤 "
                f"보면 흔들리는지 알 수 있음")
        for var, val in ((self.min_var, spot.min_px),
                         (self.repeats_var, spot.repeats),
                         (self.tol_var, spot.tol)):
            if get_int(var, -1) != val:
                var.set(str(val))
        if bool(self.auto_var.get()) != bool(spot.auto):
            self.auto_var.set(bool(spot.auto))
        if get_float(self.rise_var, -1) != spot.rise:
            self.rise_var.set(f"{spot.rise:g}")
        if get_float(self.span_var, -1) != spot.span_s:
            self.span_var.set(f"{spot.span_s:g}")
        if get_float(self.gap_var, -1) != spot.gap_s:
            self.gap_var.set(f"{spot.gap_s:g}")
        if get_float(self.cool_var, -1) != spot.cooldown_s:
            self.cool_var.set(f"{spot.cooldown_s:g}")

    def _commit(self) -> None:
        spot = self.spot
        spot.auto = bool(self.auto_var.get())
        spot.min_px = max(1, get_int(self.min_var, 25))
        spot.rise = max(1.2, min(20.0, get_float(self.rise_var, 3.0)))
        spot.repeats = max(2, min(30, get_int(self.repeats_var, 4)))
        spot.span_s = max(0.2, min(10.0, get_float(self.span_var, 1.2)))
        spot.tol = max(1, min(150, get_int(self.tol_var, 16)))
        spot.gap_s = max(0.02, min(1.0, get_float(self.gap_var, 0.1)))
        spot.cooldown_s = max(0.5, min(30.0, get_float(self.cool_var, 4.0)))
        self._on_change()

    def _pick_area(self) -> None:
        spot = self.spot
        initial = (spot.x, spot.y, spot.w, spot.h) if spot.w > 0 else None
        rect, _t = region_picker.pick(
            self, self.engine, initial=initial, show_digits=False,
            title="낚싯대 끝에 물고기가 매달리는 자리")
        if rect is None:
            return
        spot.x, spot.y, spot.w, spot.h = rect
        self.refresh()
        self._on_change()
        self.engine.log(
            f"낚은 자세(흔들림) 자리: ({rect[0]}, {rect[1]}) "
            f"{rect[2]}×{rect[3]} — [재보기]로 문턱을 재 주세요.")

    def _clear(self) -> None:
        self._stop()
        spot = self.spot
        spot.x = spot.y = spot.w = spot.h = 0
        self.result_var.set("")
        self.refresh()
        self._on_change()

    # -- 재보기 ------------------------------------------------------------
    def _stop(self) -> None:
        """돌던 타이머를 반드시 끊는다.

        인식 검사 창에서 이걸 안 해 사슬이 늘어난 적이 있다. 밖에서 한 번 더
        누를 때마다 타이머가 하나씩 더 붙어 초당 다섯 번이 545번이 됐다.
        """
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _probe(self) -> None:
        spot = self.spot
        if spot.w <= 0 or spot.h <= 0:
            messagebox.showinfo("먼저 영역을 정하세요",
                                "[영역 지정]으로 낚싯대 끝 자리를 먼저 "
                                "잡아 주세요.", parent=self)
            return
        if self.engine.window() is None:
            messagebox.showinfo("게임 창을 못 찾음",
                                "게임 창을 먼저 잡아 주세요.", parent=self)
            return
        self._stop()
        self._seen = []
        self._watch = MotionWatch(spot, self.engine.window())
        self.probe_btn.state(["disabled"])
        self.result_var.set("재는 중…")
        self._tick()

    def _tick(self) -> None:
        self._job = None
        spot = self.spot
        got = self._watch.sample()
        if got is not None:
            self._seen.append(got)
        if len(self._seen) < self.SAMPLES:
            self._job = self.after(max(20, int(spot.gap_s * 1000)), self._tick)
            return
        self.probe_btn.state(["!disabled"])
        seen = sorted(self._seen)
        lo, mid, hi = seen[0], seen[len(seen) // 2], seen[-1]
        base = self._watch.baseline()
        mark = self._watch.threshold()
        over = sum(1 for v in seen if v >= mark)
        room = max(1, spot.area)
        how = "스스로 잡음" if spot.auto else "직접 정함"
        self.result_var.set(
            f"{len(seen)}장 재봄 — 바뀐 칸 최소 {lo} · 가운데 {mid} · 최대 {hi} "
            f"(영역 {room}칸)\n"
            f"바탕 {base:.0f}칸 → 문턱 {mark:.0f}칸 ({how}) · {len(seen)}장 중 "
            f"{over}장이 문턱을 넘음\n"
            + ("→ 이대로면 흔들린다고 봅니다"
               if over >= spot.repeats else
               f"→ 이대로면 안 흔들린다고 봅니다 ({spot.repeats}장 필요)"))
        self.engine.log(
            f"낚은 자세 재보기: 최소 {lo} · 가운데 {mid} · 최대 {hi}칸 · "
            f"바탕 {base:.0f} → 문턱 {mark:.0f} · {over}/{len(seen)}장 움직임")

    def destroy(self):
        self._stop()
        super().destroy()


class SoundRow(ttk.LabelFrame):
    """낚시 성공 효과음.

    화면으로 낚음을 가리는 것이 번번이 어긋나서 마지막으로 기대는 곳이다. 소리는
    가려지지도, 밀리지도, 미세하지도 않다.

    **소리 크기가 아니라 결로 가린다.** 크기만 보면 배경 음악에 그대로 속는다.
    어느 높이가 얼마나 섞였는지를 재서 배워 둔 것과 견주므로, 볼륨을 바꿔도
    그대로 알아본다.
    """

    LEARN_S = 3.0  # 배울 때 귀 기울이는 시간
    WATCH_MS = 120  # 들어보는 중에 화면을 새로 그리는 간격

    INTRO = ("낚시에 성공하면 효과음이 울립니다. 그 소리를 한 번 배워 두면, "
             "들릴 때마다 낚은 것으로 보고 바로 다시 던집니다.\n"
             "화면을 안 보므로 게임 창이 가려도, 다른 창이 위에 있어도 "
             "똑같이 들립니다. 스피커로 나가는 소리를 되받아 듣기 때문에 "
             "볼륨을 줄여 두어도 됩니다.")
    HOW = ("[효과음 배우기]를 누르면 3초 동안 귀를 기울입니다. 그 사이에 "
           "낚시에 성공해서 효과음이 울리게 하세요 — 게임에서 한 마리 "
           "낚으면 됩니다.\n"
           "그 3초 동안 다른 소리(음악·채팅 알림)는 꺼 두는 편이 좋습니다. "
           "섞여 들어가면 배운 결이 흐려집니다.")

    def __init__(self, parent, engine, get_setup, on_change,
                 attr: str = "catch_sound", title: str = "6. 낚시 성공 효과음",
                 intro: str = "", how: str = "",
                 prompt: str = "지금 낚시에 성공해 주세요",
                 cooldown: bool = True) -> None:
        # 성공 효과음과 클릭 소리(맞음·빗나감)가 **같은 틀**을 쓴다. 배우고 들어
        # 보는 일은 똑같고, 무엇을 배우는지와 안내 문구만 다르다.
        super().__init__(parent, text=title, padding=theme.pad(8))
        self.engine = engine
        self._get = get_setup
        self._on_change = on_change
        self._attr = attr
        self._prompt = prompt
        self._ear = None
        self._job = None
        self._mode = ""  # "learn" 또는 "watch"
        self._until = 0.0
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=intro or self.INTRO,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info_var, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w")

        line = ttk.Frame(self)
        line.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.learn_btn = ttk.Button(line, text="효과음 배우기",
                                    style="Small.TButton", command=self._learn)
        self.learn_btn.pack(side="left")
        self.watch_btn = ttk.Button(line, text="지금 들어보기",
                                    style="Small.TButton", command=self._watch)
        self.watch_btn.pack(side="left", padx=4)
        ttk.Button(line, text="지우기", style="Small.TButton",
                   command=self._clear).pack(side="left")

        nums = ttk.Frame(self)
        nums.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(nums, text="닮은 정도").pack(side="left", padx=(0, 3))
        self.near_var = tk.StringVar(value="0.88")
        ttk.Entry(nums, textvariable=self.near_var, width=6).pack(side="left")
        ttk.Label(nums, text="이상인 조각").pack(side="left", padx=(2, 3))
        self.hits_var = tk.StringVar(value="2")
        int_entry(nums, self.hits_var, width=4).pack(side="left")
        ttk.Label(nums, text="개면 그 소리 · 이보다 작은 소리는 무시").pack(
            side="left", padx=(2, 3))
        self.floor_var = tk.StringVar(value="0.03")
        ttk.Entry(nums, textvariable=self.floor_var, width=6).pack(side="left")

        nums2 = ttk.Frame(self)
        if cooldown:
            # 클릭 소리는 한 판에 수십 번 나므로 "다시 안 셀 시간"이 뜻이 없다.
            nums2.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Label(nums2, text="다시 안 셀 시간").pack(side="left", padx=(0, 3))
        self.cool_var = tk.StringVar(value="4")
        ttk.Entry(nums2, textvariable=self.cool_var, width=5).pack(side="left")
        ttk.Label(nums2, text="초").pack(side="left", padx=(2, 0))

        for var in (self.near_var, self.hits_var, self.floor_var,
                    self.cool_var):
            var.trace_add("write", lambda *_a: self._commit())

        self.result_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.result_var, justify="left",
                  wraplength=theme.px(720)).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Label(
            self, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=how or self.HOW,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.refresh()

    @property
    def cue(self):
        return getattr(self._get(), self._attr)

    def refresh(self) -> None:
        cue = self.cue
        if not cue.ready:
            self.info_var.set("아직 안 배움 — [효과음 배우기]를 눌러 주세요")
        else:
            self.info_var.set(f"배워 둠 · {cue.describe()} · "
                              f"배울 때 크기 {cue.learned_level:.3f}")
        if get_float(self.near_var, -1) != cue.near:
            self.near_var.set(f"{cue.near:g}")
        if get_int(self.hits_var, -1) != cue.hits:
            self.hits_var.set(str(cue.hits))
        if get_float(self.floor_var, -1) != cue.floor:
            self.floor_var.set(f"{cue.floor:g}")
        if get_float(self.cool_var, -1) != cue.cooldown_s:
            self.cool_var.set(f"{cue.cooldown_s:g}")

    def _commit(self) -> None:
        cue = self.cue
        cue.near = max(0.3, min(0.999, get_float(self.near_var, 0.88)))
        cue.hits = max(1, min(30, get_int(self.hits_var, 2)))
        cue.floor = max(0.0, min(0.9, get_float(self.floor_var, 0.03)))
        cue.cooldown_s = max(0.5, min(30.0, get_float(self.cool_var, 4.0)))
        self._on_change()

    def _clear(self) -> None:
        self._stop()
        cue = self.cue
        cue.shape = []
        cue.learned_level = 0.0
        self.result_var.set("")
        self.refresh()
        self._on_change()

    # -- 귀 ---------------------------------------------------------------
    def _stop(self) -> None:
        """타이머와 귀를 반드시 함께 거둔다."""
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        if self._ear is not None:
            self._ear.close()
            self._ear = None
        self._mode = ""
        self.learn_btn.state(["!disabled"])
        self.watch_btn.configure(text="지금 들어보기")

    def _open(self) -> bool:
        self._stop()
        # 게임 창이 떠 있으면 **게임 소리만** 듣는다 — 스피커 음량을 0으로 둬도 된다.
        ear = sound.Ear(sound.game_pid(self.engine.window()))
        try:
            ear.open()
        except sound.SoundError as exc:
            messagebox.showwarning("소리를 못 듣습니다", str(exc), parent=self)
            self.engine.log(f"효과음: {exc}")
            return False
        self._ear = ear
        self.engine.log(f"효과음: 듣기 시작 — {ear.source} ({ear.fmt.describe()})")
        return True

    def _learn(self) -> None:
        if not self._open():
            return
        self._mode = "learn"
        self._until = time.perf_counter() + self.LEARN_S
        self.learn_btn.state(["disabled"])
        self._ear.clear()
        self.result_var.set(f"{self.LEARN_S:g}초 동안 듣는 중… {self._prompt}")
        self._tick()

    def _watch(self) -> None:
        if self._mode == "watch":
            self._stop()
            self.result_var.set("그만 들음")
            return
        if not self._open():
            return
        self._mode = "watch"
        self._until = 0.0
        self.watch_btn.configure(text="그만 듣기")
        self._tick()

    def _tick(self) -> None:
        self._job = None
        if self._ear is None:
            return
        now = time.perf_counter()
        if self._mode == "learn":
            if now < self._until:
                left = self._until - now
                self.result_var.set(f"{left:.1f}초 남음 — {self._prompt}")
                self._job = self.after(self.WATCH_MS, self._tick)
                return
            self._finish_learn()
            return

        # 들어보는 중 — 지금 무엇이 들리는지 그대로 보여 준다.
        cue = self.cue
        frames = self._ear.recent(now - 1.0)
        level = max((f[1] for f in frames), default=0.0)
        best = 0.0
        if cue.ready:
            _hit, best = sound.match(frames, sound.SoundPrint(cue.shape),
                                     cue.near, cue.floor, cue.hits)
        bar = "█" * min(30, int(level * 100))
        line = f"소리 크기 {level:.3f} {bar}"
        if cue.ready:
            verdict = "← 그 소리!" if best >= cue.near else ""
            line += (f"\n배운 소리와 닮은 정도 {best:.2f} "
                     f"(문턱 {cue.near:.2f}) {verdict}")
        else:
            line += "\n아직 안 배웠습니다 — [효과음 배우기]를 먼저 눌러 주세요"
        self.result_var.set(line)
        self._job = self.after(self.WATCH_MS, self._tick)

    def _finish_learn(self) -> None:
        frames = self._ear.recent(0)
        got = sound.learn(frames)
        self._stop()
        if got is None:
            self.result_var.set(
                "아무 소리도 못 들었습니다. 게임 소리가 나오는지, 윈도우 소리 "
                "설정에서 기본 재생 장치가 맞는지 보고 다시 해 주세요.")
            self.engine.log("효과음: 배우기 실패 — 들린 소리가 없습니다")
            return
        shape, level = got
        cue = self.cue
        cue.shape = [round(v, 5) for v in shape]
        cue.learned_level = round(level, 5)
        self.refresh()
        self._on_change()
        self.result_var.set(
            f"배웠습니다 — {cue.describe()} · 그때 크기 {level:.3f}\n"
            "[지금 들어보기]로 그 소리를 다시 내 보며 닮은 정도가 문턱을 "
            "넘는지 확인해 보세요.")
        self.engine.log(
            f"효과음 배움: {cue.describe()} · 크기 {level:.3f} · "
            f"조각 {len(frames)}개에서")

    def destroy(self):
        self._stop()
        super().destroy()


class FishingTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine) -> None:
        super().__init__(parent, padding=theme.pad(10))
        self.engine = engine
        self._commit_job = None
        self._check = None
        # 아래 칸들을 만드는 도중에 값이 바뀌면 새로고침이 불린다. 그때는 아직
        # 없는 칸을 읽게 되므로, 다 만들 때까지 새로고침을 막아 둔다.
        self._ready = False

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        head.columnconfigure(0, weight=1)
        self.summary_var = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.summary_var,
                  style="Heading.TLabel").grid(row=0, column=0, sticky="w")
        buttons = ttk.Frame(head)
        buttons.grid(row=0, column=1, sticky="e")
        ttk.Button(buttons, text="인식 검사", command=self._open_check).pack(
            side="left")
        self.run_btn = ttk.Button(buttons, text="▶ 낚시 시작",
                                  style="Accent.TButton", command=self._toggle)
        self.run_btn.pack(side="left", padx=(6, 0))

        body = ScrollFrame(self)
        body.grid(row=1, column=0, sticky="nsew")
        inner = body.inner
        inner.columnconfigure(0, weight=1)

        self._build_board(inner, 0)
        self._build_click(inner, 1)
        self._build_flow(inner, 2)
        self._build_spots(inner, 3)
        self._build_learned(inner, 9)

        self._ready = True
        self.refresh()

    # -- 1. 판과 무엇을 볼지 ------------------------------------------------
    def _build_board(self, parent, row: int) -> None:
        box = ttk.LabelFrame(parent, text="1. 미니게임 판과 볼 것들",
                             padding=theme.pad(8))
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("미니게임 창은 늘 같은 자리에 뜹니다. 그 자리를 한 번 정해 두면 "
                  "매 판 화면을 뒤질 필요가 없습니다 — 뒤지는 시간이 그대로 "
                  "빗나감이 됩니다. 판을 되도록 좁게 잡으세요.\n"
                  "미니게임을 띄워 둔 채로 [영역 지정] → [판 살펴보기] 순서로 "
                  "하시면 됩니다."),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.board_var = tk.StringVar(value="")
        ttk.Label(box, text="판 영역").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(box, textvariable=self.board_var).grid(row=1, column=1, sticky="w")
        actions = ttk.Frame(box)
        actions.grid(row=1, column=2, sticky="e")
        ttk.Button(actions, text="영역 지정", style="Small.TButton",
                   command=self._pick_board).pack(side="left")
        ttk.Button(actions, text="판 살펴보기", style="Accent.TButton",
                   command=self._open_picker).pack(side="left", padx=4)

        table = ttk.Frame(box)
        table.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        table.columnconfigure(2, weight=1)
        self.role_vars = {}
        self.role_swatches = {}
        for index, role in enumerate(fishpick.ROLES):
            ttk.Label(table, text=fishpick.NAMES[role]).grid(
                row=index, column=0, sticky="w", padx=(0, 8), pady=1)
            if fishpick.HAS_COLOR[role]:
                swatch = ColorSwatch(table, size=theme.px(14))
                swatch.grid(row=index, column=1, sticky="w", padx=(0, 6))
                self.role_swatches[role] = swatch
            var = tk.StringVar(value="")
            self.role_vars[role] = var
            ttk.Label(table, textvariable=var).grid(row=index, column=2,
                                                    sticky="w")

        nums = ttk.Frame(box)
        nums.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.limit_var = tk.StringVar()
        self.clear_var = tk.StringVar()
        self.minpx_var = tk.StringVar()
        for col, (label, var, tail) in enumerate((
            ("한 판 제한", self.limit_var, "초"),
            ("깼다고 볼 체력", self.clear_var, "%"),
            ("찾았다고 볼 칸 수", self.minpx_var, "칸"),
        )):
            ttk.Label(nums, text=label).grid(row=0, column=col * 3, sticky="w",
                                             padx=(0 if col == 0 else 14, 4))
            int_entry(nums, var, width=6).grid(row=0, column=col * 3 + 1,
                                               sticky="w")
            ttk.Label(nums, text=tail).grid(row=0, column=col * 3 + 2, sticky="w",
                                            padx=(2, 0))

        hit = ttk.Frame(box)
        hit.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.auto_hit_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(hit, text="겹침 거리를 판마다 재서 정하기",
                        variable=self.auto_hit_var,
                        command=self._touch).pack(side="left")
        ttk.Label(hit, text="비율").pack(side="left", padx=(12, 3))
        self.ratio_var = tk.StringVar()
        int_entry(hit, self.ratio_var, width=5).pack(side="left")
        ttk.Label(hit, text="· 직접 정할 때").pack(side="left", padx=(14, 3))
        self.hit_var = tk.StringVar()
        self.hit_entry = int_entry(hit, self.hit_var, width=6)
        self.hit_entry.pack(side="left")
        ttk.Label(hit, text="px").pack(side="left", padx=(2, 12))
        ttk.Label(hit, text="한 번 누르는 시간").pack(side="left", padx=(0, 3))
        self.hold_var = tk.StringVar()
        int_entry(hit, self.hold_var, width=5).pack(side="left")
        ttk.Label(hit, text="ms").pack(side="left", padx=(2, 12))
        ttk.Label(hit, text="겹쳤을 때 클릭 속도 ×").pack(side="left", padx=(0, 3))
        self.speed_var = tk.StringVar()
        ttk.Spinbox(hit, textvariable=self.speed_var, width=5, from_=0.5, to=3.0,
                    increment=0.1, format="%.1f").pack(side="left")

        # **row=4는 위 [hit] 칸이 이미 쓰고 있다.** grid는 같은 자리에 둘을
        # 놓아도 아무 말 없이 겹쳐 그려서, 뒤엣것이 앞엣것을 덮고 입력칸이
        # 잘려 보였다.
        for var in (self.hit_var, self.limit_var, self.clear_var,
                    self.minpx_var, self.ratio_var, self.hold_var, self.speed_var,
                    ):
            var.trace_add("write", lambda *_a: self._touch())

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("**물고기 크기는 미니게임마다 다릅니다.** 그래서 겹쳤다고 볼 거리를 "
                  "고정값으로 두면 어떤 판에서는 너무 좁고 어떤 판에서는 너무 "
                  "넓습니다. 기본은 화면에서 잰 막대와 물고기의 폭에서 뽑아 "
                  "씁니다 — 두 반폭을 더한 값(가장자리가 맞닿는 거리)에 비율을 "
                  "곱합니다.\n"
                  "비율 1.0 = 닿기만 하면 겹친 것으로 봅니다. 게임도 그렇게 "
                  "판정합니다 — 눈으로 본 겹침만 누르므로 여기 바짝 붙여도 "
                  "빗나감이 늘지 않습니다. 1.1로 넘기면 그때부터 늘어납니다.\n"
                  "한 번 누르는 시간이 길면 그만큼 덜 누르게 됩니다. 짧게 하면 "
                  "게임이 클릭을 놓칠 수 있으니, 명중률을 보며 줄여 보세요.\n"
                  "**몰아치기**는 겹친 것을 본 자리에서 화면을 다시 보지 않고 몇 "
                  "번 더 누르는 것입니다. 화면 한 장 읽는 데 6.9ms가 드는데 그동안은 "
                  "못 누르므로 그만큼을 아낍니다. 대신 그 사이는 눈을 감고 있는 "
                  "셈이라, 물체가 빠르거나 간격이 길면 뒤쪽 클릭이 빗나가 체력을 "
                  "도로 채웁니다.\n"
                  "체력은 게이지 전체 길이에 대한 남은 길이의 비율로 잽니다.")
            .replace("**", ""),
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))

    # -- 2. 클릭 범위 -------------------------------------------------------
    def _build_click(self, parent, row: int) -> None:
        box = ttk.LabelFrame(parent, text="2. 클릭 범위", padding=theme.pad(8))
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(1, weight=1)

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("화면 아무 데나 눌러도 되므로 사각형으로 받습니다. 그 안에서 "
                  "매번 무작위로 한 점을 고릅니다 — 늘 같은 자리를 누르면 사람이 "
                  "아닌 티가 나고, 하필 그 자리에 다른 것이 겹치면 통째로 "
                  "망가집니다."),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.click_var = tk.StringVar(value="")
        ttk.Label(box, text="누를 범위").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(box, textvariable=self.click_var).grid(row=1, column=1, sticky="w")
        ttk.Button(box, text="범위 지정", style="Small.TButton",
                   command=self._pick_click).grid(row=1, column=2, sticky="e")

        line = ttk.Frame(box)
        line.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(line, text="버튼").pack(side="left", padx=(0, 6))
        self.button_var = tk.StringVar()
        combo = ttk.Combobox(line, textvariable=self.button_var, state="readonly",
                             width=8, values=list(BUTTON_LABELS.values()))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._touch())

    # -- 3. 낚시 흐름 -------------------------------------------------------
    def _build_flow(self, parent, row: int) -> None:
        box = ttk.LabelFrame(parent, text="3. 낚시 흐름", padding=theme.pad(8))
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("낚시중에는 캐릭터 머리 위를 계속 두드립니다. 미니게임이 뜨면 "
                  "두드리기를 멈추고 겹칠 때만 누르고, 성공 알림이 뜨면 다시 "
                  "던집니다.\n"
                  "찌가 보이는지 따지지 않습니다 — 찌는 작고 잠깐 떠서 놓치기 "
                  "일쑤인데, 헛클릭은 아무 해가 없기 때문입니다."),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        self.cast_var = tk.StringVar()
        self.bite_var = tk.StringVar()
        self.rest_var = tk.StringVar()
        line = ttk.Frame(box)
        line.grid(row=1, column=0, columnspan=6, sticky="w")
        ttk.Label(line, text="던지는 키").pack(side="left", padx=(0, 4))
        ttk.Entry(line, textvariable=self.cast_var, width=8).pack(side="left")
        ttk.Label(line, text="조용하면 다시 던지기").pack(side="left", padx=(14, 4))
        int_entry(line, self.bite_var, width=6).pack(side="left")
        ttk.Label(line, text="초").pack(side="left", padx=(2, 0))
        ttk.Label(line, text="던진 뒤 쉼").pack(side="left", padx=(14, 4))
        int_entry(line, self.rest_var, width=6).pack(side="left")
        ttk.Label(line, text="초").pack(side="left", padx=(2, 0))

        tap = ttk.Frame(box)
        tap.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        tap.columnconfigure(1, weight=1)
        ttk.Label(tap, text="연타할 자리").grid(row=0, column=0, sticky="w",
                                            padx=(0, 8))
        self.tap_var = tk.StringVar(value="")
        ttk.Label(tap, textvariable=self.tap_var).grid(row=0, column=1, sticky="w")
        ttk.Button(tap, text="영역 지정", style="Small.TButton",
                   command=self._pick_tap).grid(row=0, column=2, sticky="e")

        gap = ttk.Frame(box)
        gap.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(gap, text="누르는 간격").pack(side="left", padx=(0, 4))
        self.tap_min_var = tk.StringVar()
        int_entry(gap, self.tap_min_var, width=5).pack(side="left")
        ttk.Label(gap, text="~").pack(side="left", padx=3)
        self.tap_max_var = tk.StringVar()
        int_entry(gap, self.tap_max_var, width=5).pack(side="left")
        ttk.Label(gap, text="초 사이에서 무작위").pack(side="left", padx=(4, 0))

        # -- 두드리기만 오래 이어지면 끊는다 -------------------------------
        stuck = ttk.Frame(box)
        stuck.grid(row=4, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(stuck, text="두드리기만").pack(side="left", padx=(0, 4))
        self.tap_limit_var = tk.StringVar()
        ttk.Spinbox(stuck, textvariable=self.tap_limit_var, width=7,
                    from_=0.0, to=600.0, increment=0.1,
                    format="%.1f").pack(side="left")
        ttk.Label(stuck, text="초 이어지면 다시 던지기 (0이면 안 끊음)").pack(
            side="left", padx=(4, 0))
        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("낚음을 알아보는 세 근거가 다 어긋나면 이미 낚아 놓고도 계속 "
                  "두드리게 됩니다. 그 상태는 아무 일도 안 일어나므로 스스로 "
                  "빠져나올 수가 없어서, 예전에는 위의 [조용하면 다시 던지기]가 "
                  "다 지나야 풀렸습니다. 미니게임을 푸는 동안은 이 시간을 "
                  "세지 않습니다."),
        ).grid(row=5, column=0, columnspan=6, sticky="w", pady=(2, 0))

        # -- 한참 못 낚으면 되살리기 ---------------------------------------
        dry = ttk.Frame(box)
        dry.grid(row=6, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self.dry_var = tk.StringVar()
        ttk.Spinbox(dry, textvariable=self.dry_var, width=7,
                    from_=0.0, to=600.0, increment=1.0,
                    format="%.0f").pack(side="left")
        ttk.Label(dry, text="초 동안 한 마리도 못 낚으면  [Esc]×").pack(
            side="left", padx=(4, 2))
        self.dry_esc_var = tk.StringVar()
        int_entry(dry, self.dry_esc_var, width=3).pack(side="left")
        ttk.Label(dry, text="→ 낚싯대 키").pack(side="left", padx=(6, 3))
        self.dry_rod_var = tk.StringVar()
        ttk.Entry(dry, textvariable=self.dry_rod_var, width=5).pack(side="left")
        ttk.Label(dry, text="→ 다시 던지기 (0이면 안 함)").pack(side="left", padx=(4, 0))
        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("손에 낚싯대가 아닌 것을 들었거나, 초대·거래 같은 신청 창이 떠서 "
                  "키가 통째로 안 먹을 때가 있습니다. 둘 다 화면으로 가려내기는 "
                  "어렵지만 되살리는 방법은 같습니다 — 창을 닫고, 낚싯대를 들고, "
                  "다시 던집니다.\n"
                  "미니게임을 푸는 중에는 절대 끼어들지 않습니다(판이 뜨면 시계를 "
                  "되돌립니다). 낚은 때에도 되돌아갑니다."),
        ).grid(row=7, column=0, columnspan=6, sticky="w", pady=(2, 0))

        # -- 버프 ----------------------------------------------------------
        buff = ttk.LabelFrame(box, text="버프", padding=theme.pad(6))
        buff.grid(row=6, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Label(
            buff, style="Faint.TLabel", justify="left",
            wraplength=theme.px(720),
            text=("낚시를 시작할 때 버프를 걸고, 유지 시간이 다 되면 다시 겁니다.\n"
                  "**만료되자마자 걸지 않습니다** — 낚시 도중에 끼어들면 그 판이 "
                  "날아가므로, 다음에 한 마리 낚을 때까지 기다렸다가 그 틈에 "
                  "겁니다.").replace("**", ""),
        ).grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 6))

        brow = ttk.Frame(buff)
        brow.grid(row=1, column=0, columnspan=8, sticky="w")
        self.buff_on_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(brow, text="버프 쓰기",
                        variable=self.buff_on_var).pack(side="left",
                                                        padx=(0, 8))
        self.buff_center_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(brow, text="먼저 창 한복판 클릭",
                        variable=self.buff_center_var).pack(side="left",
                                                            padx=(0, 14))
        ttk.Label(brow, text="먼저 누를 키").pack(side="left", padx=(0, 3))
        self.buff_pre_var = tk.StringVar()
        ttk.Entry(brow, textvariable=self.buff_pre_var, width=5).pack(
            side="left")
        ttk.Label(brow, text="· 물건 키").pack(side="left", padx=(8, 3))
        self.buff_zero_var = tk.StringVar()
        ttk.Entry(brow, textvariable=self.buff_zero_var, width=5).pack(
            side="left")
        ttk.Label(brow, text="· 낚싯대 키").pack(side="left", padx=(8, 3))
        self.buff_rod_var = tk.StringVar()
        ttk.Entry(brow, textvariable=self.buff_rod_var, width=5).pack(
            side="left")
        ttk.Label(brow, text="· 처음에 물건 키").pack(side="left", padx=(8, 3))
        self.buff_open_var = tk.StringVar()
        int_entry(brow, self.buff_open_var, width=5).pack(side="left")
        ttk.Label(brow, text="번").pack(side="left", padx=(2, 0))
        ttk.Label(brow, text="· 버프 사이 쉬기").pack(side="left", padx=(8, 3))
        self.buff_gap_var = tk.StringVar()
        ttk.Spinbox(brow, textvariable=self.buff_gap_var, width=5, from_=0.0, to=10.0,
                    increment=0.1, format="%.1f").pack(side="left")
        ttk.Label(brow, text="초").pack(side="left", padx=(2, 0))

        for i, (label, kv, mv, zv) in enumerate((
            ("버프 ①", "buff_a_var", "buff_a_sec_var", "buff_a_zeros_var"),
            ("버프 ②", "buff_b_var", "buff_b_sec_var", "buff_b_zeros_var"),
            ("버프 ③", "buff_c_var", "buff_c_sec_var", "buff_c_zeros_var"),
        )):
            line = ttk.Frame(buff)
            line.grid(row=2 + i, column=0, columnspan=8, sticky="w",
                      pady=(6, 0))
            ttk.Label(line, text=label).pack(side="left", padx=(0, 4))
            setattr(self, kv, tk.StringVar())
            ttk.Entry(line, textvariable=getattr(self, kv), width=5).pack(
                side="left")
            ttk.Label(line, text="키 ·").pack(side="left", padx=(3, 4))
            setattr(self, mv, tk.StringVar())
            # **초 단위다.** 분으로만 두면 "15분 기준으로 초 단위 조절"을 못 한다.
            ttk.Spinbox(line, textvariable=getattr(self, mv), width=8,
                        from_=1.0, to=36000.0, increment=1.0,
                        format="%.0f").pack(side="left")
            ttk.Label(line, text="초 유지 · 걸고 나서 물건 키").pack(
                side="left", padx=(3, 4))
            setattr(self, zv, tk.StringVar())
            int_entry(line, getattr(self, zv), width=5).pack(side="left")
            ttk.Label(line, text="번").pack(side="left", padx=(2, 0))

        self.buff_hint_var = tk.StringVar(value="")
        ttk.Label(buff, textvariable=self.buff_hint_var, justify="left",
                  wraplength=theme.px(720)).grid(
            row=5, column=0, columnspan=8, sticky="w", pady=(6, 0))

        # -- 얼음낚시 ------------------------------------------------------
        ice = ttk.LabelFrame(box, text="얼음낚시 (땅 파기)",
                             padding=theme.pad(6))
        ice.grid(row=7, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Label(
            ice, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("얼음낚시터는 땅이 다시 얼어붙습니다. 얼면 낚시가 안 되므로 "
                  "때맞춰 다시 파야 하는데, 파는 동안은 낚시가 끊기므로 파고 나서 "
                  "다시 던져야 합니다. 아래 키들을 차례로 누릅니다 — 마지막 "
                  "[ctrl]이 낚시를 다시 시작하는 몫입니다.\n"
                  "일반 낚시터라면 이 칸은 꺼 두세요. 꺼 두면 아무것도 "
                  "달라지지 않습니다."),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        row1 = ttk.Frame(ice)
        row1.grid(row=1, column=0, columnspan=6, sticky="w")
        self.ice_on_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="얼음낚시로 돌리기",
                        variable=self.ice_on_var).pack(side="left",
                                                       padx=(0, 14))
        ttk.Label(row1, text="땅 파는 주기").pack(side="left", padx=(0, 4))
        self.ice_every_var = tk.StringVar()
        ttk.Spinbox(row1, textvariable=self.ice_every_var, width=8,
                    from_=0, to=36000, increment=1,
                    format="%.0f").pack(side="left")
        ttk.Label(row1, text="초").pack(side="left", padx=(2, 0))
        self.ice_hint_var = tk.StringVar(value="")
        ttk.Label(row1, textvariable=self.ice_hint_var,
                  style="Faint.TLabel").pack(side="left", padx=(6, 0))

        row2 = ttk.Frame(ice)
        row2.grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(row2, text="삽").pack(side="left", padx=(0, 3))
        self.ice_dig_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.ice_dig_var, width=6).pack(
            side="left")
        ttk.Label(row2, text="→ 내리치기").pack(side="left", padx=(6, 3))
        self.ice_hit_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.ice_hit_var, width=6).pack(
            side="left")
        ttk.Label(row2, text="×").pack(side="left", padx=(4, 3))
        self.ice_hits_var = tk.StringVar()
        int_entry(row2, self.ice_hits_var, width=4).pack(side="left")
        ttk.Label(row2, text="번 (처음 뚫는 자리는").pack(side="left", padx=(3, 3))
        self.ice_first_var = tk.StringVar()
        int_entry(row2, self.ice_first_var, width=4).pack(side="left")
        ttk.Label(row2, text="번)").pack(side="left", padx=(2, 6))
        ttk.Label(row2, text="→ 낚싯대").pack(side="left", padx=(4, 3))
        self.ice_back_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.ice_back_var, width=6).pack(
            side="left")

        row3 = ttk.Frame(ice)
        row3.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(row3, text="한 번 내리칠 때 붙잡기").pack(side="left", padx=(0, 4))
        self.ice_hold_min_var = tk.StringVar()
        ttk.Spinbox(row3, textvariable=self.ice_hold_min_var, width=6,
                    from_=0.02, to=10.0, increment=0.1,
                    format="%.2f").pack(side="left")
        ttk.Label(row3, text="~").pack(side="left", padx=3)
        self.ice_hold_max_var = tk.StringVar()
        ttk.Spinbox(row3, textvariable=self.ice_hold_max_var, width=6,
                    from_=0.02, to=10.0, increment=0.1,
                    format="%.2f").pack(side="left")
        ttk.Label(row3, text="초 · 내리침 사이").pack(side="left", padx=(4, 4))
        self.ice_press_min_var = tk.StringVar()
        ttk.Spinbox(row3, textvariable=self.ice_press_min_var, width=6,
                    from_=0.02, to=10.0, increment=0.1,
                    format="%.2f").pack(side="left")
        ttk.Label(row3, text="~").pack(side="left", padx=3)
        self.ice_press_max_var = tk.StringVar()
        ttk.Spinbox(row3, textvariable=self.ice_press_max_var, width=6,
                    from_=0.02, to=10.0, increment=0.1,
                    format="%.2f").pack(side="left")
        ttk.Label(row3, text="초 · 도구 바꾼 뒤").pack(side="left", padx=(4, 4))
        self.ice_gap_var = tk.StringVar()
        ttk.Spinbox(row3, textvariable=self.ice_gap_var, width=6,
                    from_=0.05, to=3.0, increment=0.05,
                    format="%.2f").pack(side="left")
        ttk.Label(row3, text="초").pack(side="left", padx=(2, 0))

        # -- 피로도 확인 ----------------------------------------------------
        tired = ttk.LabelFrame(box, text="피로도 확인 (낚음 N마리마다)",
                               padding=theme.pad(6))
        tired.grid(row=8, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Label(
            tired, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("낚음 N마리마다 피로도 조건을 확인하고, 가득 찼으면 정한 매크로를 "
                  "한 번 돌린 뒤 다시 던집니다.\n"
                  "조건은 [조건] 탭에서 만든 것을 고릅니다 — 숫자 읽기에서 "
                  "'앞 값이 뒤 값에 닿으면'으로 만들고 거기서 시험해 두세요. 조건에 "
                  "점·그림이 함께 들어 있으면 그것까지 모두 맞아야 가득으로 봅니다.\n"
                  "아래 기준값을 넣으면 가득 차기를 기다리지 않고 앞 값이 그 수 "
                  "이상일 때 돕니다 — 피로도: 31057 / 542000 에서 31057 쪽. "
                  "조건에 적어 둔 읽을 자리·글꼴·밝기는 그대로 씁니다."),
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        trow = ttk.Frame(tired)
        trow.grid(row=1, column=0, columnspan=6, sticky="w")
        self.fatigue_on_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(trow, text="피로도 확인하기",
                        variable=self.fatigue_on_var).pack(side="left",
                                                           padx=(0, 14))
        ttk.Label(trow, text="낚음").pack(side="left", padx=(0, 4))
        self.fatigue_every_var = tk.StringVar()
        int_entry(trow, self.fatigue_every_var, width=5).pack(side="left")
        ttk.Label(trow, text="마리마다").pack(side="left", padx=(3, 0))
        trow2 = ttk.Frame(tired)
        trow2.grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(trow2, text="피로도 조건").pack(side="left", padx=(0, 4))
        self.fatigue_rule_var = tk.StringVar()
        rule_box = ttk.Combobox(trow2, textvariable=self.fatigue_rule_var,
                                width=22, state="readonly",
                                postcommand=lambda: rule_box.configure(
                                    values=[r.name for r in
                                            self.engine.profile.rules]))
        rule_box.pack(side="left")
        rule_box.bind("<<ComboboxSelected>>", lambda _e: self._touch())
        ttk.Label(trow2, text="→ 가득이면 매크로").pack(side="left", padx=(8, 4))
        self.fatigue_macro_var = tk.StringVar()
        macro_box = ttk.Combobox(trow2, textvariable=self.fatigue_macro_var,
                                 width=22, state="readonly",
                                 postcommand=lambda: macro_box.configure(
                                     values=[m.name for m in
                                             self.engine.profile.macros]))
        macro_box.pack(side="left")
        macro_box.bind("<<ComboboxSelected>>", lambda _e: self._touch())
        ttk.Label(trow2, text="한 번 → 다시 던짐").pack(side="left", padx=(4, 0))
        trow3 = ttk.Frame(tired)
        trow3.grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(trow3, text="기준값 (앞 값이 이 수 이상이면)").pack(
            side="left", padx=(0, 4))
        self.fatigue_over_var = tk.StringVar()
        int_entry(trow3, self.fatigue_over_var, width=10).pack(side="left")
        ttk.Label(trow3, style="Faint.TLabel",
                  text="   0 = 가득 찰 때까지 기다림").pack(side="left")
        self.fatigue_hint_var = tk.StringVar(value="")
        ttk.Label(tired, textvariable=self.fatigue_hint_var, justify="left",
                  wraplength=theme.px(720)).grid(
            row=4, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self.fatigue_on_var.trace_add("write", lambda *_a: self._touch())
        self.fatigue_every_var.trace_add("write", lambda *_a: self._touch())
        self.fatigue_over_var.trace_add("write", lambda *_a: self._touch())

        for var in (self.cast_var, self.bite_var, self.rest_var,
                    self.tap_min_var, self.tap_max_var, self.tap_limit_var,
                    self.dry_var, self.dry_esc_var, self.dry_rod_var,
                    self.ice_every_var, self.ice_gap_var, self.ice_dig_var,
                    self.ice_hit_var, self.ice_hits_var, self.ice_first_var,
                    self.ice_back_var, self.ice_hold_min_var,
                    self.ice_hold_max_var, self.ice_press_min_var,
                    self.ice_press_max_var, self.buff_pre_var,
                    self.buff_zero_var, self.buff_rod_var, self.buff_open_var,
                    self.buff_gap_var,
                    self.buff_a_var, self.buff_a_sec_var,
                    self.buff_a_zeros_var, self.buff_b_var,
                    self.buff_b_sec_var, self.buff_b_zeros_var,
                    self.buff_c_var, self.buff_c_sec_var,
                    self.buff_c_zeros_var):
            var.trace_add("write", lambda *_a: self._touch())
        self.ice_on_var.trace_add("write", lambda *_a: self._touch())
        self.buff_on_var.trace_add("write", lambda *_a: self._touch())
        self.buff_center_var.trace_add("write", lambda *_a: self._touch())

    # -- 4. 성공 알림 -------------------------------------------------------
    def _build_spots(self, parent, row: int) -> None:
        self.notice_row = NoticeRow(parent, self.engine, lambda: self.setup,
                                    self._after_spot)
        self.notice_row.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        self.popup_row = PopupRow(parent, self.engine, lambda: self.setup,
                                  self._after_spot)
        self.popup_row.grid(row=row + 1, column=0, sticky="ew", pady=(0, 8))
        self.motion_row = MotionRow(parent, self.engine, lambda: self.setup,
                                    self._after_spot)
        self.motion_row.grid(row=row + 2, column=0, sticky="ew", pady=(0, 8))
        self.sound_row = SoundRow(parent, self.engine, lambda: self.setup,
                                  self._after_spot)
        self.sound_row.grid(row=row + 3, column=0, sticky="ew", pady=(0, 8))
        self.hit_row = SoundRow(
            parent, self.engine, lambda: self.setup, self._after_spot,
            attr="hit_sound", title="6-1. 클릭 소리 — 겹쳤을 때 (맞음)",
            intro=("미니게임에서 막대와 물고기가 **겹쳤을 때** 누르면 나는 소리입니다. "
                   "배워 두면 판마다 몇 번 들렸는지 로그에 남기고, [인식 검사]의 "
                   "[겹침 진단]에서 그 순간 우리 판정과 맞춰 봅니다.\n"
                   "클릭을 보냈는데 맞음·빗나감 소리가 둘 다 안 나면 게임이 클릭을 "
                   "못 받은 것입니다.").replace("**", ""),
            how=("[효과음 배우기]를 누르고 3초 안에 미니게임에서 겹쳤을 때 "
                 "한 번 눌러 주세요. 겹치지 않을 때 누르면 빗나감 소리가 섞입니다."),
            prompt="겹쳤을 때 한 번 눌러 주세요", cooldown=False)
        self.hit_row.grid(row=row + 4, column=0, sticky="ew", pady=(0, 8))
        self.miss_row = SoundRow(
            parent, self.engine, lambda: self.setup, self._after_spot,
            attr="miss_sound", title="6-2. 클릭 소리 — 안 겹쳤을 때 (빗나감)",
            intro=("미니게임에서 **안 겹쳤을 때** 누르면 나는 소리입니다. 맞음 "
                   "소리와 함께 배워 두면 둘 중 더 닮은 쪽으로 가려 셉니다.")
            .replace("**", ""),
            how=("[효과음 배우기]를 누르고 3초 안에 미니게임에서 막대와 물고기가 "
                 "떨어져 있을 때 한 번 눌러 주세요."),
            prompt="떨어져 있을 때 한 번 눌러 주세요", cooldown=False)
        self.miss_row.grid(row=row + 5, column=0, sticky="ew", pady=(0, 8))

    # -- 7. 배운 것 ---------------------------------------------------------
    def _build_learned(self, parent, row: int) -> None:
        box = ttk.LabelFrame(parent, text="7. 스스로 배운 것", padding=theme.pad(8))
        box.grid(row=row, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("두 가지를 스스로 배웁니다. **lead** 는 겹치기 몇 ms 전에 "
                  "눌러야 맞는지이고, **겹침 배수** 는 잰 그림 폭의 몇 배까지를 "
                  "겹친 것으로 볼지입니다.\n"
                  "배수가 중요합니다 — 그림 폭대로(1.0) 잡으면 게임이 맞다고 "
                  "치는 자리보다 훨씬 넓을 수 있고, 넓은 만큼이 고스란히 "
                  "헛클릭이 되어 깎아 둔 체력을 도로 채워 줍니다. 빗나감은 "
                  "보통 맞힘보다 손해가 큽니다.\n"
                  "**명중률이 아니라 초당 깎은 체력으로 고릅니다.** 명중률로 "
                  "고르면 아주 좁게 잡아 백발백중이 되지만 클릭이 줄어 판을 못 "
                  "끝냅니다 (시늉으로 재 보니 클리어율 100% → 28%).").replace(
                      "**", ""),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.learn_hit_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="겹침 배수도 스스로 배우기",
                        variable=self.learn_hit_var).grid(
            row=3, column=0, sticky="w", pady=(6, 0))
        self.learn_hit_var.trace_add("write", lambda *_a: self._touch())

        self.learned_var = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.learned_var, justify="left").grid(
            row=1, column=0, sticky="w")
        self.table_var = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.table_var, style="Faint.TLabel",
                  justify="left").grid(row=2, column=0, sticky="w", pady=(2, 0))
        ttk.Button(box, text="기록 보기", style="Small.TButton",
                   command=self._show_log).grid(row=4, column=0, sticky="w",
                                                pady=(6, 0))
        ttk.Button(box, text="보정 초기화", style="Small.TButton",
                   command=self._reset_lead).grid(row=1, column=1, rowspan=2,
                                                  sticky="e", padx=(12, 0))

    # ------------------------------------------------------------------
    # 값 옮기기
    # ------------------------------------------------------------------
    @property
    def setup(self) -> FishingSetup:
        return self.engine.profile.fishing

    def refresh(self, reload_form: bool = True) -> None:
        if not self._ready:
            return
        s = self.setup
        if reload_form:
            self.hit_var.set(f"{s.hit_px:g}")
            self.ratio_var.set(f"{s.hit_ratio:g}")
            self.hold_var.set(f"{s.click_hold_ms:g}")
            self.speed_var.set(f"{s.overlap_speed:.1f}")
            self.auto_hit_var.set(s.hit_mode == "auto")
            self.limit_var.set(f"{s.limit_s:g}")
            self.clear_var.set(str(int(round(s.clear_ratio * 100))))
            self.minpx_var.set(str(s.track_min_px))
            self.button_var.set(BUTTON_LABELS.get(s.click_button, "왼쪽"))
            self.cast_var.set(s.cast_key)
            self.bite_var.set(f"{s.bite_wait_s:g}")
            self.rest_var.set(f"{s.rest_s:g}")
            self.tap_min_var.set(f"{s.tap_min_s:g}")
            self.tap_max_var.set(f"{s.tap_max_s:g}")
            self.tap_limit_var.set(f"{s.tap_limit_s:.1f}")
            self.dry_var.set(f"{s.dry_s:.0f}")
            self.dry_esc_var.set(str(s.dry_esc_times))
            self.dry_rod_var.set(s.dry_rod_key)
            self.ice_on_var.set(bool(s.ice_mode))
            self.ice_every_var.set(f"{s.ice_every_s:.0f}")
            self.ice_gap_var.set(f"{s.ice_gap_s:.2f}")
            self.fatigue_on_var.set(bool(s.fatigue_mode))
            self.fatigue_every_var.set(str(s.fatigue_every))
            self.fatigue_rule_var.set(s.fatigue_rule)
            self.fatigue_macro_var.set(s.fatigue_macro)
            self.fatigue_over_var.set(
                f"{s.fatigue_over:g}" if s.fatigue_over > 0 else "0")
            self.buff_on_var.set(bool(s.buff_mode))
            self.buff_center_var.set(bool(s.buff_center_click))
            self.buff_pre_var.set(s.buff_pre_key)
            self.buff_zero_var.set(s.buff_zero_key)
            self.buff_rod_var.set(s.buff_rod_key)
            self.buff_open_var.set(str(s.buff_open_zeros))
            self.buff_gap_var.set(f"{s.buff_open_gap_s:.1f}")
            self.buff_a_var.set(s.buff_a_key)
            self.buff_a_sec_var.set(f"{s.buff_a_sec:g}")
            self.buff_a_zeros_var.set(str(s.buff_a_zeros))
            self.buff_b_var.set(s.buff_b_key)
            self.buff_b_sec_var.set(f"{s.buff_b_sec:g}")
            self.buff_b_zeros_var.set(str(s.buff_b_zeros))
            self.buff_c_var.set(s.buff_c_key)
            self.buff_c_sec_var.set(f"{s.buff_c_sec:g}")
            self.buff_c_zeros_var.set(str(s.buff_c_zeros))
            self.ice_dig_var.set(s.ice_dig_key)
            self.ice_hit_var.set(s.ice_hit_key)
            self.ice_hits_var.set(str(s.ice_hits))
            self.ice_first_var.set(str(s.ice_first_hits))
            self.ice_back_var.set(s.ice_back_key)
            self.ice_hold_min_var.set(f"{s.ice_hold_min_s:.2f}")
            self.ice_hold_max_var.set(f"{s.ice_hold_max_s:.2f}")
            self.ice_press_min_var.set(f"{s.ice_press_min_s:.2f}")
            self.ice_press_max_var.set(f"{s.ice_press_max_s:.2f}")
        self.notice_row.refresh()
        self.popup_row.refresh()
        self.motion_row.refresh()
        self.sound_row.refresh()
        self.hit_row.refresh()
        self.miss_row.refresh()
        self._sync_labels()

    def _sync_labels(self) -> None:
        if not self._ready:
            return
        s = self.setup
        if hasattr(self, "buff_hint_var"):
            if not s.buff_mode:
                self.buff_hint_var.set("(꺼짐 — 버프를 안 씁니다)")
            elif not s.buff_ready:
                self.buff_hint_var.set("⚠ 버프 키가 비어 있습니다")
            else:
                self.buff_hint_var.set(
                    ("창 한복판 클릭 → " if s.buff_center_click else "")
                    + s.buff_story())
        if hasattr(self, "ice_hint_var"):
            if not s.ice_mode:
                self.ice_hint_var.set("(꺼짐 — 일반 낚시터)")
            elif not s.ice_ready:
                self.ice_hint_var.set("⚠ 주기나 키가 비어 있습니다")
            else:
                mins = s.ice_every_s / 60.0
                self.ice_hint_var.set(
                    f"= {mins:.1f}분마다 " + s.ice_story(first=False))
        if hasattr(self, "fatigue_hint_var"):
            if not s.fatigue_mode:
                self.fatigue_hint_var.set("(꺼짐 — 피로도를 안 봅니다)")
            elif not s.fatigue_rule or self.engine.find_rule(s.fatigue_rule) is None:
                self.fatigue_hint_var.set("⚠ 피로도 조건을 골라 주세요 ([조건] 탭에서 "
                                          "만든 것)")
            elif not s.fatigue_macro or self.engine.find_macro(s.fatigue_macro) is None:
                self.fatigue_hint_var.set("⚠ 다 찼을 때 돌릴 매크로를 골라 주세요")
            else:
                goal = (f"앞 값이 {s.fatigue_over:g} 이상"
                        if s.fatigue_over > 0 else "가득")
                self.fatigue_hint_var.set(
                    f"= 낚음 {s.fatigue_every}마리마다 '{s.fatigue_rule}' 확인 → "
                    f"{goal}이면 '{s.fatigue_macro}' 한 번 → [{s.back_key}]로 "
                    f"다시 던짐")
        self.board_var.set(
            f"창 기준 ({s.board_x}, {s.board_y}) · {s.board_w}×{s.board_h}"
            if s.board_w > 0 else "아직 정하지 않음")

        for role in fishpick.ROLES:
            self.role_vars[role].set(self._role_text(role))
            if role in self.role_swatches:
                hexed = getattr(s, fishpick.COLOR_FIELD[role])
                self.role_swatches[role].set_color(
                    pixel.from_hex(hexed) or (40, 40, 40))

        self.click_var.set(
            f"창 기준 ({s.click_x}, {s.click_y}) · {s.click_w}×{s.click_h} "
            f"— 이 안에서 무작위"
            if s.click_w > 0 else "아직 정하지 않음")
        self.tap_var.set(
            f"창 기준 ({s.tap_x}, {s.tap_y}) · {s.tap_w}×{s.tap_h} "
            f"— 이 안에서 무작위"
            if s.tap_w > 0 else "⚠ 아직 정하지 않음 (두드리지 않습니다)")

        lead = fishing.Lead().load(s.lead_stats, s.lead_ms)
        ratio = fishing.Ratio().load(s.ratio_stats)
        learned = (
            f"보정된 lead {lead.best:+.0f}ms · 명중률 {lead.rate * 100:.0f}%"
            if lead.shots else "아직 배운 것 없음 — 몇십 판 돌리면 자리를 잡습니다"
        )
        if ratio.shots:
            learned += f" · 겹침 배수 {ratio.best:.1f}"
        tail = f" · 낚음 {s.caught}마리" if s.can_tell_caught else ""
        self.learned_var.set(
            f"누적 {s.rounds}판 · 클리어 {s.clears}판 "
            f"({s.clear_rate * 100:.0f}%){tail}   " + learned)
        table = "lead  " + (lead.table() or "아직 없음")
        if ratio.shots:
            table += "\n배수  " + ratio.table()
        self.table_var.set(table)
        if get_bool(self.learn_hit_var) != s.learn_hit:
            self.learn_hit_var.set(bool(s.learn_hit))

        problems = s.problems()
        if problems:
            self.summary_var.set("낚시 — 아직 못 정한 것: " + ", ".join(problems))
        else:
            extras = s.extras()
            how = (f"판마다 폭을 재서 (비율 {s.hit_ratio:g})"
                   if s.hit_mode == "auto" else f"{s.hit_px:g}px 고정")
            text = (f"낚시 — 준비됐습니다. 한 판 {s.limit_s:g}초 · 겹침 {how} · "
                    f"클릭 범위 {s.click_w}×{s.click_h}")
            if extras:
                text += "   (안 정한 것: " + ", ".join(extras) + " — 없어도 됩니다)"
            self.summary_var.set(text)
        running = self.engine.is_running(*TASK)
        self.run_btn.configure(text="■ 정지" if running else "▶ 낚시 시작")

    def _role_text(self, role: str) -> str:
        """항목 한 줄. 막대·물고기는 가로를 [움직이는 범위]에서 빌려 온다."""
        s = self.setup
        if role == "track":
            x0, x1, y0, y1 = s.track_box()
            return (f"x {x0}~{x1} · y {y0}~{y1}  (막대·물고기가 오가는 사각형)"
                    if x1 > x0 and y1 > y0 else "⚠ 안 정함")

        hexed = getattr(s, fishpick.COLOR_FIELD[role])
        if not hexed:
            return "안 정함" + ("  (없어도 됩니다)" if role == "time" else "")
        tol = f"허용차 {getattr(s, role + '_tol')}"
        if fishpick.MOVING[role]:
            y0, y1 = getattr(s, role + "_y0"), getattr(s, role + "_y1")
            where = (f"세로 {y0}~{y1}" if y1 > y0
                     else "세로 안 정함 (움직이는 범위 전체)")
            return f"{hexed} · {where} · {tol}"
        x0, x1, y0, y1 = (s.health_box() if role == "health" else s.time_box())
        if x1 <= x0 or y1 <= y0:
            return f"{hexed} · ⚠ 영역 안 정함"
        return f"{hexed} · x {x0}~{x1} · y {y0}~{y1} · {tol}"

    def _after_spot(self) -> None:
        if not self._ready:
            return
        self.engine.save()
        self._sync_labels()

    def _touch(self) -> None:
        """값이 바뀌었다. 잠깐 모았다가 한 번에 저장한다."""
        if not self._ready:
            return
        if self._commit_job is not None:
            self.after_cancel(self._commit_job)
        self._commit_job = self.after(400, self._commit)

    def _commit(self) -> None:
        self._commit_job = None
        s = self.setup
        s.hit_mode = "auto" if self.auto_hit_var.get() else "manual"
        s.hit_ratio = max(0.1, min(2.0, get_float(self.ratio_var, 0.8)))
        s.hit_px = max(1.0, min(200.0, get_float(self.hit_var, s.hit_px)))
        s.click_hold_ms = max(0.0, min(60.0,
                                       get_float(self.hold_var, 4.0)))
        s.overlap_speed = max(0.5, min(3.0, get_float(self.speed_var, 1.0)))
        self.hit_entry.configure(
            state="disabled" if s.hit_mode == "auto" else "normal")
        s.limit_s = max(3.0, min(180.0, get_float(self.limit_var, s.limit_s)))
        s.clear_ratio = max(0.0, min(0.5, get_float(self.clear_var, 15) / 100.0))
        s.track_min_px = max(1, get_int(self.minpx_var, s.track_min_px))
        s.click_button = BUTTON_BY_LABEL.get(self.button_var.get(), "left")
        s.cast_key = self.cast_var.get().strip() or "ctrl"
        s.bite_wait_s = max(1.0, get_float(self.bite_var, s.bite_wait_s))
        s.rest_s = max(0.0, get_float(self.rest_var, s.rest_s))
        s.tap_min_s = max(0.02, min(5.0, get_float(self.tap_min_var, 0.1)))
        s.tap_max_s = max(s.tap_min_s, min(5.0,
                                           get_float(self.tap_max_var, 0.3)))
        # 0.1초 눈금. 0은 "안 끊음"이라는 뜻이라 그대로 둔다.
        s.tap_limit_s = round(
            max(0.0, min(600.0, get_float(self.tap_limit_var, 5.0))), 1)
        s.dry_s = round(max(0.0, min(600.0, get_float(self.dry_var, 30.0))), 0)
        s.dry_esc_times = max(0, min(20, get_int(self.dry_esc_var, 5)))
        s.dry_rod_key = self.dry_rod_var.get().strip()
        s.fatigue_mode = bool(self.fatigue_on_var.get())
        s.fatigue_every = max(1, min(1000, get_int(self.fatigue_every_var, 10)))
        s.fatigue_rule = self.fatigue_rule_var.get().strip()
        s.fatigue_macro = self.fatigue_macro_var.get().strip()
        s.fatigue_over = float(max(0, get_int(self.fatigue_over_var, 0)))
        s.ice_mode = bool(self.ice_on_var.get())
        s.ice_every_s = float(round(
            max(0.0, min(36000.0, get_float(self.ice_every_var, 300.0)))))
        s.learn_hit = bool(self.learn_hit_var.get())
        s.buff_mode = bool(self.buff_on_var.get())
        s.buff_center_click = bool(self.buff_center_var.get())
        for var, field in ((self.buff_pre_var, "buff_pre_key"),
                           (self.buff_zero_var, "buff_zero_key")):
            text = var.get().strip()
            if text:
                setattr(s, field, text)
        # 낚싯대 키와 버프 키는 비워 둘 수 있다 (그러면 안 누른다).
        s.buff_rod_key = self.buff_rod_var.get().strip()
        s.buff_a_key = self.buff_a_var.get().strip()
        s.buff_b_key = self.buff_b_var.get().strip()
        s.buff_c_key = self.buff_c_var.get().strip()
        s.buff_open_zeros = max(0, min(200, get_int(self.buff_open_var, 23)))
        s.buff_open_gap_s = max(0.05, min(10.0, get_float(self.buff_gap_var, 1.0)))
        s.buff_a_zeros = max(0, min(200, get_int(self.buff_a_zeros_var, 4)))
        s.buff_b_zeros = max(0, min(200, get_int(self.buff_b_zeros_var, 19)))
        s.buff_c_zeros = max(0, min(200, get_int(self.buff_c_zeros_var, 0)))
        for slot, fallback in (("a", 180.0), ("b", 600.0), ("c", 900.0)):
            var = getattr(self, f"buff_{slot}_sec_var")
            setattr(s, f"buff_{slot}_sec",
                    float(round(max(1.0, min(36000.0,
                                             get_float(var, fallback))))))
        s.ice_gap_s = max(0.05, min(3.0, get_float(self.ice_gap_var, 0.35)))
        for var, field in ((self.ice_dig_var, "ice_dig_key"),
                           (self.ice_hit_var, "ice_hit_key"),
                           (self.ice_back_var, "ice_back_key")):
            text = var.get().strip()
            if text:
                setattr(s, field, text)
        s.ice_hits = max(1, min(20, get_int(self.ice_hits_var, 2)))
        s.ice_first_hits = max(1, min(20, get_int(self.ice_first_var, 3)))
        s.ice_hold_min_s = max(0.02, min(10.0,
                                         get_float(self.ice_hold_min_var, 0.1)))
        s.ice_hold_max_s = max(s.ice_hold_min_s,
                               min(10.0,
                                   get_float(self.ice_hold_max_var, 3.0)))
        s.ice_press_min_s = max(
            0.02, min(10.0, get_float(self.ice_press_min_var, 1.0)))
        s.ice_press_max_s = max(
            s.ice_press_min_s,
            min(10.0, get_float(self.ice_press_max_var, 2.0)))
        self.engine.save()
        self._sync_labels()

    # ------------------------------------------------------------------
    # 단추
    # ------------------------------------------------------------------
    def _pick_board(self) -> None:
        s = self.setup
        initial = ((s.board_x, s.board_y, s.board_w, s.board_h)
                   if s.board_w > 0 else None)
        rect, _tuned = region_picker.pick(
            self, self.engine, initial=initial, show_digits=False,
            title="미니게임 판 영역 고르기")
        if rect is None:
            return
        changed = rect != (s.board_x, s.board_y, s.board_w, s.board_h)
        had = s.track_x1 > s.track_x0
        s.board_x, s.board_y, s.board_w, s.board_h = rect
        if changed and had:
            # 판이 옮겨지거나 크기가 바뀌면 안쪽 좌표는 뜻을 잃는다. 남겨 두면
            # 엉뚱한 자리를 보면서 "왜 안 잡히지"를 하게 된다.
            s.track_x0 = s.track_x1 = s.track_y0 = s.track_y1 = 0
            s.health_x0 = s.health_x1 = s.health_y0 = s.health_y1 = 0
            s.time_x0 = s.time_x1 = s.time_y0 = s.time_y1 = 0
            self.engine.log("판이 바뀌어 안쪽 영역을 비웠습니다. "
                            "[판 살펴보기]에서 다시 골라 주세요.")
        self.engine.save()
        self._sync_labels()
        self.engine.log(f"낚시 판 영역: ({rect[0]}, {rect[1]}) {rect[2]}×{rect[3]}")

    def _pick_click(self) -> None:
        s = self.setup
        initial = ((s.click_x, s.click_y, s.click_w, s.click_h)
                   if s.click_w > 0 else None)
        rect, _tuned = region_picker.pick(
            self, self.engine, initial=initial, show_digits=False,
            title="클릭 범위 고르기 — 이 안에서 무작위로 누릅니다")
        if rect is None:
            return
        s.click_x, s.click_y, s.click_w, s.click_h = rect
        self.engine.save()
        self._sync_labels()
        self.engine.log(
            f"낚시 클릭 범위: ({rect[0]}, {rect[1]}) {rect[2]}×{rect[3]}")

    def _pick_tap(self) -> None:
        s = self.setup
        initial = ((s.tap_x, s.tap_y, s.tap_w, s.tap_h)
                   if s.tap_w > 0 else None)
        rect, _tuned = region_picker.pick(
            self, self.engine, initial=initial, show_digits=False,
            title="낚시중에 두드릴 자리 (캐릭터 머리 위)")
        if rect is None:
            return
        s.tap_x, s.tap_y, s.tap_w, s.tap_h = rect
        self.engine.save()
        self._sync_labels()
        self.engine.log(
            f"연타할 자리: ({rect[0]}, {rect[1]}) {rect[2]}×{rect[3]}")

    def _open_picker(self) -> None:
        if self.setup.board_w <= 0:
            messagebox.showinfo(
                "먼저 판 영역을 정하세요",
                "[영역 지정]으로 미니게임 판의 자리를 먼저 정해 주세요.",
                parent=self)
            return
        picker = fishpick.BoardPicker(self, self.engine, self.setup)
        self.wait_window(picker)
        self.engine.save()
        self._sync_labels()

    def _open_check(self) -> None:
        if self.setup.board_w <= 0:
            messagebox.showinfo(
                "먼저 판 영역을 정하세요",
                "볼 자리를 모르면 검사할 것이 없습니다.", parent=self)
            return
        if self._check is not None and self._check.winfo_exists():
            self._check.lift()
            return
        self._check = fishcheck.FishCheck(self, self.engine, self.setup)

    def _show_log(self) -> None:
        """돌린 기록들을 간추려 로그에 낸다.

        **낚음 주기가 짧은 쪽이 좋은 것이다.** 클리어율도 명중률도 결국 여기로
        모이므로, 설정을 바꿔 가며 돌려 보고 이 표를 보면 된다.
        """
        from .. import fishlog, storage

        folder = storage.DATA_DIR / "fishlog"
        self.engine.log("─" * 8 + " 낚시 기록 " + "─" * 8)
        for line in fishlog.report(folder).splitlines():
            self.engine.log(line)
        self.engine.log(f"(파일: {folder})")

    def _reset_lead(self) -> None:  # lead와 배수 성적을 함께 지운다
        if not messagebox.askyesno(
            "보정 초기화",
            "지금까지 배운 성적을 지웁니다. 다시 몇십 판을 돌려야 자리를 잡습니다.\n"
            "계속할까요?", parent=self):
            return
        s = self.setup
        s.lead_stats = {}
        s.lead_ms = 0.0
        s.ratio_stats = {}
        s.rounds = s.clears = s.caught = 0
        self.engine.save()
        self._sync_labels()
        self.engine.log("낚시 보정을 초기화했습니다.")

    def _toggle(self) -> None:
        if self.engine.is_running(*TASK):
            self.engine.stop(*TASK)
            self._sync_labels()
            return
        problems = self.setup.problems()
        if problems:
            messagebox.showwarning(
                "아직 못 정한 것이 있습니다",
                "\n".join("· " + p for p in problems)
                + "\n\n[판 살펴보기]에서 정할 수 있습니다.", parent=self)
            return
        if self.setup.tap_w <= 0 and not messagebox.askyesno(
            "연타할 자리를 안 정했습니다",
            "낚시중에 머리 위를 두드리지 않으면 미니게임이 열리지 않을 수 "
            "있습니다.\n\n이대로 시작할까요?", parent=self,
        ):
            return
        self.engine.run(*TASK)
        self._sync_labels()
