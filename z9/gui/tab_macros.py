"""탭 — 키/마우스 녹화 · 재생, 그리고 이벤트 편집."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from .. import editing
from ..keys import KEY_CHOICES, name_of, vk_of
from ..model import Macro
from ..recorder import balance_keys
from . import theme
from .base import ListEditorTab
from .widgets import (
    HotkeyField,
    ScrollFrame,
    capture_click_point,
    get_float,
    get_int,
    int_entry,
)

KIND_LABELS = {
    "key": "키",
    "button": "마우스 버튼",
    "move": "커서 이동",
    "wheel": "휠",
    "wait": "대기",
}
KIND_BY_LABEL = {v: k for k, v in KIND_LABELS.items()}

ACTION_LABELS = {True: "누름", False: "뗌"}
ACTION_BY_LABEL = {v: k for k, v in ACTION_LABELS.items()}

# 붙여넣을 때 앞뒤 이벤트와 벌려 둘 최소 간격(초).
GAP = 0.05

# 시각 스핀 버튼 한 번에 움직이는 폭(초).
TIME_STEP = 0.1

# 이벤트 목록에 최소한 남겨 둘 줄 수. 창을 줄여도 이만큼은 보이게 한다.
ROW_FLOOR = 7

# 되돌리기로 거슬러 올라갈 수 있는 걸음 수.
#
# 한 걸음이 매크로 한 벌(이벤트 전부 + 설정)이라 넉넉히 잡아도 가볍다. 이벤트
# 천 개짜리 매크로라도 한 벌이 백 킬로바이트 남짓이다.
HISTORY = 50


class MacroTab(ListEditorTab):
    kind = "macro"
    noun = "매크로"

    # ------------------------------------------------------------------
    def items(self) -> list[Macro]:
        return self.engine.profile.macros

    def columns(self) -> list[tuple[str, str, int]]:
        return [("name", "이름", 150), ("count", "이벤트", 60), ("dur", "길이", 60)]

    # ------------------------------------------------------------------
    def _place_event_sash(self, _event: object = None) -> None:
        """이벤트 목록과 편집 도구 사이 분할선을 처음 한 번 놓는다."""
        if self._vsash_placed:
            return
        height = self.vsplit.winfo_height()
        if height <= 1:
            return
        self._vsash_placed = True
        # 기본은 목록에 절반 남짓, 최소 일곱 줄. 아래 편집 도구는 스크롤되므로
        # 좁아도 쓸 수 있어서, 자리가 모자라면 목록 쪽을 먼저 챙긴다.
        # 픽셀로 잰 최소치는 배율을 크게 올리면 칸 자체보다 커진다. 그때는
        # 비율 쪽을 따라가야 아래 칸이 0으로 눌리지 않는다.
        floor = min(theme.px(ROW_FLOOR * theme.ROW_HEIGHT + 30), int(height * 0.5))
        want = self.engine.settings.sash_events or max(floor, int(height * 0.6))
        low = min(theme.px(120), int(height * 0.25))
        # 아래쪽은 스크롤되므로 조금만 남겨 두면 된다.
        high = max(low, height - min(theme.px(90), int(height * 0.3)))
        try:
            self.vsplit.sashpos(0, int(max(low, min(want, high))))
        except tk.TclError:
            pass

    def event_sash_value(self) -> int:
        if not self._vsash_placed:
            return 0
        try:
            return int(self.vsplit.sashpos(0))
        except tk.TclError:
            return 0

    def reset_sash(self) -> None:
        super().reset_sash()
        self._vsash_placed = False
        self._place_event_sash()

    # ------------------------------------------------------------------
    def row_values(self, item: Macro) -> tuple:
        return (item.name, len(item.events), f"{item.duration:.1f}s")

    def new_item(self) -> Macro:
        return Macro(name="빈 매크로")

    def copy_item(self, item: Macro) -> Macro:
        return copy.deepcopy(item)

    # ------------------------------------------------------------------
    def build_form(self, parent: ttk.Frame) -> None:
        # 되돌리기 기록. 단추가 만들어지기 전에도 불릴 수 있으므로 여기서 먼저 둔다.
        self._history: list[dict] = []
        self._hpos = 0
        self._history_for: int | None = None
        self._restoring = False

        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        self._clipboard: list[dict] = []
        self._drag_from = ""
        self._drag_over = ""
        self._drag_active = False
        self._drag_origin_y = 0

        self.name_var = tk.StringVar()
        self.repeat_var = tk.StringVar(value="1")
        self.speed_var = tk.StringVar(value="1.0")
        self.interval_var = tk.StringVar(value="0")
        self.scale_var = tk.BooleanVar(value=True)
        self.moves_var = tk.BooleanVar(value=False)

        # -- 재생 설정 -------------------------------------------------
        head = ttk.Frame(parent)
        head.grid(row=0, column=0, sticky="ew")

        ttk.Label(head, text="이름").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(head, textvariable=self.name_var, width=22).grid(row=0, column=1, sticky="w")
        ttk.Label(head, text="반복 (0=무한)").grid(row=0, column=2, sticky="w", padx=(14, 6))
        int_entry(head, self.repeat_var, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(head, text="속도 배율").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(head, textvariable=self.speed_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(head, text="반복 간 대기(ms)").grid(row=1, column=2, sticky="w", padx=(14, 6))
        int_entry(head, self.interval_var, width=8).grid(row=1, column=3, sticky="w")

        ttk.Label(head, text="핫키").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=3)
        self.hotkey_field = HotkeyField(head, width=13)
        self.hotkey_field.grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(
            head, text="창 크기 변화 시 좌표 비례 보정", variable=self.scale_var
        ).grid(row=2, column=2, columnspan=2, sticky="w", padx=(14, 0))
        ttk.Checkbutton(
            head,
            text="대기 중 움직임 넣기",
            variable=self.moves_var,
            command=self._on_moves_toggle,
        ).grid(row=2, column=4, columnspan=2, sticky="w", padx=(14, 0))

        self.info_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.info_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 4)
        )

        # -- 이벤트 목록 / 편집기 --------------------------------------
        # 아래 [이벤트 편집]과 [일괄 편집]은 높이가 고정이라, 예전 배치에서는
        # 둘이 폼 높이를 다 먹고 정작 이벤트 목록이 0에 가깝게 눌렸다.
        # 분할선으로 바꿔서 목록 몫을 직접 정하게 하고, 아래쪽은 좁혀도
        # 잘리지 않도록 스크롤되는 칸에 담는다.
        self.vsplit = ttk.PanedWindow(parent, orient="vertical")
        self.vsplit.grid(row=2, column=0, sticky="nsew")
        self._vsash_placed = False
        self.vsplit.bind("<Configure>", self._place_event_sash, add="+")

        top = ttk.Frame(self.vsplit, padding=(0, 0, 0, 4))
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        wrap = ttk.Frame(top)
        wrap.grid(row=0, column=0, sticky="nsew")

        self.events_tree = ttk.Treeview(
            wrap,
            columns=("n", "t", "kind", "detail"),
            show="headings",
            selectmode="extended",
            height=9,
        )
        for cid, text, width, anchor in (
            ("n", "#", 40, "e"),
            ("t", "시각(초)", 70, "e"),
            ("kind", "종류", 80, "w"),
            ("detail", "내용", 220, "w"),
        ):
            self.events_tree.heading(cid, text=text)
            self.events_tree.column(
                cid, width=theme.px(width), anchor=anchor, stretch=(cid == "detail")
            )
        self.events_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.events_tree.yview)
        bar.pack(side="left", fill="y")
        self.events_tree.configure(yscrollcommand=bar.set)
        self.events_tree.bind("<<TreeviewSelect>>", self._on_event_select)
        self._bind_shortcuts()
        self._bind_drag()

        ttk.Label(
            top,
            style="Faint.TLabel",
            text="Del 삭제 · Ctrl+C 복사 · Ctrl+X 잘라내기 · Ctrl+V 붙여넣기 · "
            "Ctrl+A 전체 선택 · Ctrl+Z 이전 · Ctrl+Y 다음 · 끌어서 순서 변경",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        bottom = ScrollFrame(self.vsplit)
        bottom.inner.columnconfigure(0, weight=1)
        self.vsplit.add(top, weight=3)
        self.vsplit.add(bottom, weight=1)

        # -- 이벤트 편집기 ---------------------------------------------
        editor = ttk.LabelFrame(bottom.inner, text="이벤트 편집", padding=8)
        editor.grid(row=0, column=0, sticky="ew", pady=(6, 0))

        self.ev_t = tk.StringVar(value="0.000")
        self.ev_kind = tk.StringVar(value=KIND_LABELS["key"])
        self.ev_action = tk.StringVar(value=ACTION_LABELS[True])
        self.ev_key = tk.StringVar(value="Z")
        self.ev_button = tk.StringVar(value="left")
        self.ev_x = tk.StringVar(value="0")
        self.ev_y = tk.StringVar(value="0")
        self.ev_wheel = tk.StringVar(value="120")
        self.ev_wheel_count = tk.StringVar(value="1")
        self.ev_wait = tk.StringVar(value="500")

        ttk.Label(editor, text="시각(초)").grid(row=0, column=0, sticky="w", padx=(0, 5))
        # 손으로 숫자를 치는 대신 화살표로 0.1초씩 올리고 내린다.
        self.time_spin = ttk.Spinbox(
            editor,
            textvariable=self.ev_t,
            from_=0.0,
            to=86400.0,
            increment=TIME_STEP,
            format="%.3f",
            width=9,
            command=self._on_time_spin,
        )
        self.time_spin.grid(row=0, column=1, sticky="w")
        # 스핀박스 위에서 휠을 굴려도 같은 단위로 움직이게 한다.
        self.time_spin.bind("<MouseWheel>", self._on_time_wheel)

        ttk.Label(editor, text="종류").grid(row=0, column=2, sticky="w", padx=(12, 5))
        kind_box = ttk.Combobox(
            editor, textvariable=self.ev_kind, values=list(KIND_LABELS.values()),
            width=12, state="readonly",
        )
        kind_box.grid(row=0, column=3, sticky="w")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_editor())

        ttk.Label(editor, text="동작").grid(row=0, column=4, sticky="w", padx=(12, 5))
        self.action_box = ttk.Combobox(
            editor, textvariable=self.ev_action, values=list(ACTION_LABELS.values()),
            width=6, state="readonly",
        )
        self.action_box.grid(row=0, column=5, sticky="w")

        ttk.Label(editor, text="키").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=(8, 0))
        self.key_box = ttk.Combobox(
            editor, textvariable=self.ev_key, values=KEY_CHOICES, width=10, height=20
        )
        self.key_box.grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(editor, text="버튼").grid(row=1, column=2, sticky="w", padx=(12, 5), pady=(8, 0))
        self.button_box = ttk.Combobox(
            editor, textvariable=self.ev_button, values=["left", "right", "middle"],
            width=8, state="readonly",
        )
        self.button_box.grid(row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Label(editor, text="X").grid(row=1, column=4, sticky="w", padx=(12, 5), pady=(8, 0))
        self.x_entry = int_entry(editor, self.ev_x, width=7)
        self.x_entry.grid(row=1, column=5, sticky="w", pady=(8, 0))
        ttk.Label(editor, text="Y").grid(row=1, column=6, sticky="w", padx=(8, 5), pady=(8, 0))
        self.y_entry = int_entry(editor, self.ev_y, width=7)
        self.y_entry.grid(row=1, column=7, sticky="w", pady=(8, 0))

        ttk.Label(editor, text="휠").grid(row=1, column=8, sticky="w", padx=(12, 5), pady=(8, 0))
        self.wheel_entry = int_entry(editor, self.ev_wheel, width=7)
        self.wheel_entry.grid(row=1, column=9, sticky="w", pady=(8, 0))

        # 한 줄로 뭉친 휠이 몇 칸을 굴릴지. 이 숫자만 고치면 굴림량이 바뀐다.
        ttk.Label(editor, text="칸").grid(row=1, column=10, sticky="w", padx=(8, 5), pady=(8, 0))
        self.wheel_count_entry = int_entry(editor, self.ev_wheel_count, width=5)
        self.wheel_count_entry.grid(row=1, column=11, sticky="w", pady=(8, 0))

        self.pick_button = ttk.Button(
            editor, text="🎯 화면에서 찍기", command=self._pick_coord
        )
        self.pick_button.grid(row=0, column=6, sticky="w", padx=(16, 0))

        self.pair_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            editor, text="짝 이벤트도 함께", variable=self.pair_var
        ).grid(row=0, column=7, sticky="w", padx=(8, 0))

        ttk.Label(editor, text="대기(ms)").grid(row=0, column=8, sticky="w", padx=(16, 5))
        self.wait_entry = int_entry(editor, self.ev_wait, width=7)
        self.wait_entry.grid(row=0, column=9, sticky="w")

        # -- 제작 채널 이동 --------------------------------------------------
        #
        # 채널 접속 매크로는 **클릭 하나만** 채널마다 다르다. 그 클릭에 표시를
        # 해 두면, 제작이 게임을 다시 켤 때마다 1채널 → 2채널 … 로 자리를
        # 갈아 끼운다. 매크로를 열 개 만들 까닭이 없다.
        channel = ttk.Frame(editor)
        channel.grid(row=3, column=0, columnspan=12, sticky="w", pady=(8, 0))
        self.channel_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            channel, text="제작 채널 이동 클릭", variable=self.channel_var,
            command=self._mark_channel,
        ).pack(side="left")
        ttk.Button(channel, text="채널 자리 10개 정하기…", style="Small.TButton",
                   command=self._channel_spots).pack(side="left", padx=6)
        self.channel_note = ttk.Label(channel, text="", style="Faint.TLabel")
        self.channel_note.pack(side="left", padx=(6, 0))

        buttons = ttk.Frame(editor)
        buttons.grid(row=2, column=0, columnspan=12, sticky="w", pady=(10, 0))
        ttk.Button(
            buttons, text="선택에 적용", style="Accent.TButton", command=self._apply_event
        ).pack(side="left")
        ttk.Button(buttons, text="＋ 추가", command=self._add_event).pack(side="left", padx=5)
        ttk.Button(buttons, text="＋ 대기", command=self._add_wait).pack(side="left")
        ttk.Button(buttons, text="복제", command=self._duplicate_event).pack(side="left")
        ttk.Button(
            buttons, text="삭제", style="SmallDanger.TButton", command=self._delete_event
        ).pack(side="left", padx=5)

        # -- 되돌리기 ----------------------------------------------------
        #
        # 편집 도구가 많고 **되돌릴 길이 없었다.** [간격 보정]이나 [이동 전부
        # 제거]처럼 한 번에 수십 개를 바꾸는 것들은 잘못 누르면 녹화를 다시
        # 해야 했다. 매크로 한 벌을 통째로 기억해 두면 그냥 되짚어 갈 수 있다.
        self.redo_button = ttk.Button(
            buttons, text="다음 ▶", width=8, command=self._redo
        )
        self.redo_button.pack(side="right")
        self.undo_button = ttk.Button(
            buttons, text="◀ 이전", width=8, command=self._undo
        )
        self.undo_button.pack(side="right", padx=(0, 4))
        self.history_var = tk.StringVar(value="")
        ttk.Label(
            buttons, textvariable=self.history_var, style="Faint.TLabel"
        ).pack(side="right", padx=(0, 8))

        # -- 일괄 편집 ---------------------------------------------------
        bulk = ttk.LabelFrame(bottom.inner, text="일괄 편집", padding=8)
        bulk.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.shift_var = tk.StringVar(value="100")
        self.slide_var = tk.StringVar(value="0.1")
        self.from_key = tk.StringVar(value="Z")
        self.to_key = tk.StringVar(value="X")

        # 고른 이벤트 **자기 자신부터** 뒤쪽 전부를 통째로 옮긴다.
        # 중간에 길게 남은 틈을 줄이거나, 반대로 여유를 만들 때 쓴다.
        ttk.Label(bulk, text="시각 당기기 / 풀기").grid(row=0, column=0, sticky="w")
        slide = ttk.Frame(bulk)
        slide.grid(row=0, column=1, columnspan=4, sticky="w", padx=5)
        ttk.Button(
            slide, text="◀ 당기기", width=9, command=lambda: self._slide(-1)
        ).pack(side="left")
        ttk.Spinbox(
            slide, textvariable=self.slide_var, from_=0.1, to=1.0, increment=0.1,
            format="%.1f", width=5,
        ).pack(side="left", padx=4)
        ttk.Label(slide, text="초").pack(side="left")
        ttk.Button(
            slide, text="풀기 ▶", width=9, command=lambda: self._slide(1)
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            slide, style="Faint.TLabel",
            text="  고른 이벤트를 포함해 그 뒤 전부를 옮깁니다.",
        ).pack(side="left")

        ttk.Label(bulk, text="선택 이후 시각 이동(ms)").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        int_entry(bulk, self.shift_var, width=7).grid(
            row=1, column=1, sticky="w", padx=5, pady=(8, 0)
        )
        ttk.Button(bulk, text="적용", width=6, command=self._shift_after).grid(
            row=1, column=2, sticky="w", pady=(8, 0)
        )

        ttk.Label(bulk, text="키 일괄 변경").grid(row=2, column=0, sticky="w", pady=(8, 0))
        swap = ttk.Frame(bulk)
        swap.grid(row=2, column=1, columnspan=3, sticky="w", pady=(8, 0), padx=5)
        ttk.Combobox(swap, textvariable=self.from_key, values=KEY_CHOICES, width=8,
                     height=20).pack(side="left")
        ttk.Label(swap, text=" → ").pack(side="left")
        ttk.Combobox(swap, textvariable=self.to_key, values=KEY_CHOICES, width=8,
                     height=20).pack(side="left")
        ttk.Button(swap, text="변경", width=6, command=self._swap_keys).pack(
            side="left", padx=5
        )

        # -- 자동 보정 -------------------------------------------------
        self.hold_min = tk.StringVar(value=str(editing.DEFAULT_HOLD_MIN_MS))
        self.hold_max = tk.StringVar(value=str(editing.DEFAULT_HOLD_MAX_MS))
        self.gap_min = tk.StringVar(value=str(editing.DEFAULT_GAP_MIN_MS))
        self.gap_max = tk.StringVar(value=str(editing.DEFAULT_GAP_MAX_MS))

        hold_row = ttk.Frame(bulk)
        hold_row.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(
            hold_row, text="누름·뗌 보정", width=14, command=self._normalize_holds
        ).pack(side="left")
        ttk.Label(hold_row, text="  범위(ms)").pack(side="left")
        int_entry(hold_row, self.hold_min, width=5).pack(side="left", padx=(4, 2))
        ttk.Label(hold_row, text="~").pack(side="left")
        int_entry(hold_row, self.hold_max, width=5).pack(side="left", padx=(2, 0))

        gap_row = ttk.Frame(bulk)
        gap_row.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(
            gap_row, text="시각 정리 보정", width=14, command=self._normalize_gaps
        ).pack(side="left")
        ttk.Label(gap_row, text="  간격(ms)").pack(side="left")
        int_entry(gap_row, self.gap_min, width=5).pack(side="left", padx=(4, 2))
        ttk.Label(gap_row, text="~").pack(side="left")
        int_entry(gap_row, self.gap_max, width=5).pack(side="left", padx=(2, 0))

        wheel_row = ttk.Frame(bulk)
        wheel_row.grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(
            wheel_row, text="휠 뭉치기", width=14, command=self._merge_wheels
        ).pack(side="left")
        ttk.Label(wheel_row, text="  모든 휠을").pack(side="left")
        self.wheel_bulk = tk.StringVar(value="3")
        int_entry(wheel_row, self.wheel_bulk, width=5).pack(side="left", padx=(4, 2))
        ttk.Label(wheel_row, text="칸으로").pack(side="left")
        ttk.Button(
            wheel_row, text="적용", width=6, command=self._apply_wheel_count
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            bulk,
            style="Faint.TLabel",
            justify="left",
            text="누름·뗌 보정은 키를 누르고 있는 시간을, 시각 정리 보정은 동작 사이\n"
            "간격을 맞춥니다. 목록에서 Ctrl로 2개 이상 고르면 그 부분만 보정합니다.\n"
            "휠 뭉치기는 줄줄이 이어진 휠 이벤트를 한 줄로 묶어 칸 수로 바꿉니다.",
        ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))

        tools = ttk.Frame(bulk)
        tools.grid(row=7, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(tools, text="마우스 이동 전부 제거", command=self._strip_moves).pack(
            side="left"
        )
        ttk.Button(tools, text="안 뗀 키 보정", command=self._balance).pack(
            side="left", padx=6
        )
        ttk.Button(tools, text="시작 시각 0으로", command=self._rebase).pack(side="left")

        self.convert_button = ttk.Button(
            bulk, text="창 기준 좌표로 변환", command=self._to_client_coords
        )
        self.convert_button.grid(row=8, column=0, columnspan=4, sticky="w", pady=(8, 0))

        self._sync_editor()

    def build_actions(self, parent: ttk.Frame) -> None:
        self.record_button = ttk.Button(
            parent, text="● 녹화 시작", command=self.toggle_record
        )
        self.record_button.pack(side="left", padx=(16, 0))

    # ------------------------------------------------------------------
    def load_form(self, item: Macro) -> None:
        if (not getattr(self, "_restoring", False)
                and getattr(self, "_history_for", None) != id(item)):
            # 매크로를 갈아탔다. 되돌리기는 매크로마다 따로 센다 — 남의 기록으로
            # 되돌리면 엉뚱한 매크로가 덮어씌워진다.
            self._history_reset(item)
        self.name_var.set(item.name)
        self.repeat_var.set(str(item.repeat))
        self.speed_var.set(str(item.speed))
        self.interval_var.set(str(item.interval_ms))
        self.scale_var.set(item.scale_to_window)
        self.moves_var.set(bool(item.use_moves))
        self.hotkey_field.set(item.hotkey)
        self._fill_events(item)

    def save_form(self, item: Macro) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.repeat = max(get_int(self.repeat_var, 1), 0)
        item.speed = max(get_float(self.speed_var, 1.0), 0.05)
        item.interval_ms = max(get_int(self.interval_var, 0), 0)
        item.scale_to_window = bool(self.scale_var.get())
        item.use_moves = bool(self.moves_var.get())
        if item.hotkey != self.hotkey_field.get():
            item.hotkey = self.hotkey_field.get()
            self.engine.rebind_hotkeys()
        if renamed:
            self.refresh(select_name=item.name)
        # 이벤트만이 아니라 반복·속도·단축키 같은 설정을 고친 것도 되돌릴 수 있게
        # 한 걸음으로 남긴다. 달라진 것이 없으면 _remember가 알아서 넘어간다.
        self._remember(item)

    # ------------------------------------------------------------------
    def _fill_events(self, item: Macro, select: int | None = None) -> None:
        item.events.sort(key=lambda e: e["t"])
        self.events_tree.delete(*self.events_tree.get_children())
        for index, event in enumerate(item.events):
            self.events_tree.insert(
                "", "end", iid=str(index),
                values=(index + 1, f"{event['t']:.3f}",
                        KIND_LABELS.get(event["kind"], event["kind"]),
                        _detail(event)),
                tags=(theme.row_tag(index),),
            )
        if item.absolute:
            basis = "⚠ 화면 절대좌표 — 창을 옮기면 어긋납니다"
        elif item.client_w:
            basis = f"창 기준 좌표 (녹화 시 {item.client_w}x{item.client_h})"
        else:
            basis = "창 기준 좌표"
        self.info_var.set(
            f"이벤트 {len(item.events)}개 · 길이 {item.duration:.2f}초 · {basis}"
        )
        self.convert_button.configure(
            state="normal" if item.absolute else "disabled"
        )
        if select is not None and 0 <= select < len(item.events):
            iid = str(select)
            self.events_tree.selection_set(iid)
            self.events_tree.see(iid)

    # ------------------------------------------------------------------
    # 단축키
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        tree = self.events_tree
        # 트리에 포커스가 있을 때만 동작하게 위젯에 직접 건다.
        tree.bind("<Delete>", self._on_delete_key)
        tree.bind("<Control-c>", self._on_copy_key)
        tree.bind("<Control-C>", self._on_copy_key)
        tree.bind("<Control-x>", self._on_cut_key)
        tree.bind("<Control-X>", self._on_cut_key)
        tree.bind("<Control-v>", self._on_paste_key)
        tree.bind("<Control-V>", self._on_paste_key)
        tree.bind("<Control-a>", self._on_select_all)
        tree.bind("<Control-A>", self._on_select_all)
        tree.bind("<Control-z>", self._on_undo_key)
        tree.bind("<Control-Z>", self._on_undo_key)
        tree.bind("<Control-y>", self._on_redo_key)
        tree.bind("<Control-Y>", self._on_redo_key)
        # 윈도우에서 흔히 쓰는 또 하나의 다시하기.
        tree.bind("<Control-Shift-Z>", self._on_redo_key)

    # "break"를 돌려줘야 Treeview 기본 처리가 뒤이어 끼어들지 않는다.
    def _on_delete_key(self, _e: object) -> str:
        self._delete_event()
        return "break"

    def _on_copy_key(self, _e: object) -> str:
        self._copy_events()
        return "break"

    def _on_cut_key(self, _e: object) -> str:
        if self._copy_events():
            self._delete_event()
        return "break"

    def _on_paste_key(self, _e: object) -> str:
        self._paste_events()
        return "break"

    def _on_select_all(self, _e: object) -> str:
        children = self.events_tree.get_children()
        if children:
            self.events_tree.selection_set(children)
        return "break"

    def _copy_events(self) -> bool:
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            return False
        self._clipboard = [
            copy.deepcopy(item.events[i]) for i in picks if 0 <= i < len(item.events)
        ]
        self.engine.log(f"이벤트 {len(self._clipboard)}개 복사")
        return bool(self._clipboard)

    def _paste_events(self) -> None:
        """복사한 이벤트를 선택 지점 뒤에 끼워 넣는다.

        붙여넣은 만큼 뒤쪽 이벤트를 밀어서 시각이 겹치지 않게 한다. 겹친 채로 두면
        같은 순간에 두 입력이 나가 게임이 하나를 흘린다.
        """
        item = self.selected()
        if item is None or not self._clipboard:
            return

        block = sorted((copy.deepcopy(e) for e in self._clipboard), key=lambda e: e["t"])
        base = block[0]["t"]
        span = block[-1]["t"] - base

        picks = self._selected_indices()
        if picks and picks[-1] < len(item.events):
            anchor = item.events[picks[-1]]["t"]
        elif item.events:
            anchor = item.events[-1]["t"]
        else:
            anchor = -GAP

        start = round(anchor + GAP, 4)
        shift = round(span + GAP, 4)
        for event in item.events:
            if event["t"] > anchor:
                event["t"] = round(event["t"] + shift, 4)
        for event in block:
            event["t"] = round(start + (event["t"] - base), 4)

        item.events.extend(block)
        self.engine.log(
            f"'{item.name}': 이벤트 {len(block)}개 붙여넣기 "
            f"({start:.3f}초 지점, 이후 {shift * 1000:.0f}ms 밀림)"
        )
        self._resync(item, start)

    # ------------------------------------------------------------------
    # 끌어서 순서 변경
    # ------------------------------------------------------------------
    def _bind_drag(self) -> None:
        tree = self.events_tree
        theme.stripe(tree)
        tree.tag_configure("drop", background=theme.PALETTE["accent_soft"])
        tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        tree.bind("<B1-Motion>", self._drag_motion, add="+")
        tree.bind("<ButtonRelease-1>", self._drag_drop, add="+")

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_from = self.events_tree.identify_row(event.y)
        self._drag_active = False
        self._drag_origin_y = event.y

    def _drag_motion(self, event: tk.Event) -> str | None:
        if not self._drag_from:
            return None
        # 몇 픽셀 이상 움직여야 끌기로 본다. 안 그러면 평범한 클릭도 끌기가 된다.
        if not self._drag_active and abs(event.y - self._drag_origin_y) < 5:
            return None
        self._drag_active = True

        target = self.events_tree.identify_row(event.y)
        if target != self._drag_over:
            self._clear_drop_mark()
            if target and target != self._drag_from:
                # 줄무늬 태그를 지우지 않도록 drop을 덧붙인다.
                stripe_tag = theme.row_tag(int(target))
                self.events_tree.item(target, tags=(stripe_tag, "drop"))
                self._drag_over = target
        # Treeview 기본 동작은 끌면 선택 영역을 넓힌다. 순서 변경과 충돌하므로
        # 끌기가 시작된 뒤에는 기본 처리를 막는다.
        return "break"

    def _drag_drop(self, event: tk.Event) -> None:
        source, active = self._drag_from, self._drag_active
        self._clear_drop_mark()
        self._drag_from = ""
        self._drag_active = False
        if not active or not source:
            return

        target = self.events_tree.identify_row(event.y)
        if not target or target == source:
            return
        self._reorder(int(source), int(target))

    def _clear_drop_mark(self) -> None:
        if self._drag_over:
            try:
                self.events_tree.item(
                    self._drag_over, tags=(theme.row_tag(int(self._drag_over)),)
                )
            except (tk.TclError, ValueError):
                pass
            self._drag_over = ""

    def _reorder(self, src: int, dst: int) -> None:
        """이벤트를 다른 자리로 옮긴다.

        시각 자체가 순서를 정하므로, 자리만 바꾸면 정렬 때 원위치로 돌아간다.
        그래서 **시각 슬롯은 그대로 두고 동작만 재배치**한다. 전체 리듬과 총 길이가
        유지되고, "무엇을 언제 하는가"만 바뀐다.
        """
        item = self.selected()
        if item is None:
            return
        events = item.events
        if not (0 <= src < len(events)) or not (0 <= dst < len(events)):
            return

        slots = [e["t"] for e in events]
        moved = events.pop(src)
        events.insert(dst, moved)
        for event, slot in zip(events, slots):
            event["t"] = slot

        self.engine.log(f"'{item.name}': {src + 1}번 → {dst + 1}번 자리로 이동")
        self._after_change(item, select=dst)

    def _selected_indices(self) -> list[int]:
        return sorted(int(i) for i in self.events_tree.selection())

    def _on_event_select(self, _e: object = None) -> None:
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks or picks[0] >= len(item.events):
            return
        event = item.events[picks[0]]
        self.ev_t.set(f"{event['t']:.3f}")
        self.ev_kind.set(KIND_LABELS.get(event["kind"], KIND_LABELS["key"]))
        self.ev_action.set(ACTION_LABELS[bool(event.get("down", True))])
        if event["kind"] == "key":
            self.ev_key.set(name_of(event["vk"]))
        if event["kind"] == "button":
            self.ev_button.set(event.get("button", "left"))
        if "cx" in event:
            self.ev_x.set(str(event.get("cx", 0)))
            self.ev_y.set(str(event.get("cy", 0)))
        if event["kind"] == "wait":
            self.ev_wait.set(str(event.get("duration_ms", 0)))
        if event["kind"] == "wheel":
            self.ev_wheel.set(str(event.get("wheel", 120)))
            self.ev_wheel_count.set(str(editing.wheel_count(event)))
        self._sync_channel(event)
        self._sync_editor()

    def _sync_editor(self) -> None:
        kind = KIND_BY_LABEL.get(self.ev_kind.get(), "key")
        self.wait_entry.configure(state="normal" if kind == "wait" else "disabled")
        self.key_box.configure(state="normal" if kind == "key" else "disabled")
        self.button_box.configure(state="readonly" if kind == "button" else "disabled")
        self.action_box.configure(
            state="readonly" if kind in ("key", "button") else "disabled"
        )
        coords = "normal" if kind in ("button", "move", "wheel") else "disabled"
        self.x_entry.configure(state=coords)
        self.y_entry.configure(state=coords)
        self.pick_button.configure(state=coords)
        wheel_state = "normal" if kind == "wheel" else "disabled"
        self.wheel_entry.configure(state=wheel_state)
        self.wheel_count_entry.configure(state=wheel_state)

    def _event_from_editor(self) -> dict | None:
        kind = KIND_BY_LABEL.get(self.ev_kind.get(), "key")
        try:
            t = max(0.0, float(self.ev_t.get()))
        except ValueError:
            t = 0.0
        down = ACTION_BY_LABEL.get(self.ev_action.get(), True)

        if kind == "wait":
            return {
                "t": t,
                "kind": "wait",
                "duration_ms": max(get_int(self.ev_wait, 0), 0),
            }

        if kind == "key":
            vk = vk_of(self.ev_key.get().strip())
            if vk is None:
                self.engine.log(f"알 수 없는 키: {self.ev_key.get()}")
                return None
            return {"t": t, "kind": "key", "vk": vk, "down": down}

        cx, cy = get_int(self.ev_x, 0), get_int(self.ev_y, 0)
        if kind == "button":
            return {"t": t, "kind": "button", "button": self.ev_button.get() or "left",
                    "down": down, "cx": cx, "cy": cy}
        if kind == "move":
            return {"t": t, "kind": "move", "cx": cx, "cy": cy}
        return {
            "t": t,
            "kind": "wheel",
            "wheel": get_int(self.ev_wheel, 120),
            "count": max(get_int(self.ev_wheel_count, 1), 1),
            "cx": cx,
            "cy": cy,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _wait_seconds(event: dict | None) -> float:
        if not event or event.get("kind") != "wait":
            return 0.0
        return max(int(event.get("duration_ms", 0)), 0) / 1000.0

    def _shift_events_after(self, item: Macro, after_t: float, delta: float) -> None:
        """after_t보다 뒤에 있는 이벤트를 통째로 민다.

        시각이 절대값이라, 대기를 넣거나 늘리면 뒤쪽도 같이 옮겨야 실제로 그만큼
        더 쉬게 된다. 안 그러면 대기 줄만 생기고 전체 길이는 그대로다.
        """
        if not delta:
            return
        for event in item.events:
            if event["t"] > after_t + 1e-9:
                event["t"] = round(max(0.0, event["t"] + delta), 4)

    # -- 제작 채널 이동 ---------------------------------------------------
    def _sync_channel(self, event: dict) -> None:
        """고른 이벤트가 '제작 채널 이동' 표시를 달고 있는지 보여 준다."""
        from ..craft import CHANNEL_MARK

        self.channel_var.set(bool(event.get(CHANNEL_MARK)))
        setup = self.engine.profile.craft
        done = sum(1 for spot in setup.channel_spots if spot.ready)
        nxt, _spot = setup.channel_spot()
        self.channel_note.configure(
            text=(f"채널 자리 {done}/10개 정함 · 다음은 {nxt}채널"
                  if done else "채널 자리를 아직 안 정했습니다"))

    def _mark_channel(self) -> None:
        """고른 클릭에 표시를 달거나 뗀다. 짝(누름·뗌)도 같이."""
        from ..craft import CHANNEL_MARK

        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            self.channel_var.set(False)
            return
        want = bool(self.channel_var.get())
        targets = set(picks)
        if self.pair_var.get():
            pairs, _unmatched = editing.find_pairs(item.events)
            for down, up in pairs:
                if down in targets or up in targets:
                    targets |= {down, up}
        touched = 0
        for index in sorted(targets):
            event = item.events[index]
            if "cx" not in event:
                continue   # 좌표가 없는 이벤트는 채널과 상관없다
            if want:
                event[CHANNEL_MARK] = True
            else:
                event.pop(CHANNEL_MARK, None)
            touched += 1
        if not touched:
            self.channel_var.set(False)
            messagebox.showinfo(
                "제작 채널 이동",
                "마우스 클릭 이벤트에만 표시할 수 있습니다.", parent=self)
            return
        self.engine.save()
        self.engine.log(
            f"'{item.name}': 클릭 {touched}개를 제작 채널 이동으로 "
            + ("표시했습니다." if want else "표시 해제했습니다."))
        self._after_change(item, select=picks[0])

    def _channel_spots(self) -> None:
        """채널 1~10의 클릭 자리를 정하는 작은 창."""
        setup = self.engine.profile.craft
        top = tk.Toplevel(self)
        top.title("제작 채널 자리")
        top.transient(self.winfo_toplevel())
        frame = ttk.Frame(top, padding=theme.pad(10))
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, style="Faint.TLabel", justify="left",
            wraplength=theme.px(460),
            text=("채널 단추 10개의 자리를 하나씩 찍어 주세요. 게임 창에서 "
                  "그 채널 단추를 누르면 됩니다 (클릭은 게임에 안 들어갑니다).\n"
                  "제작이 게임을 다시 켤 때마다 다음 채널로 넘어갑니다. 자리를 "
                  "안 찍은 채널은 건너뜁니다."),
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        labels = []
        def redraw() -> None:
            for i, var in enumerate(labels):
                var.set(setup.channel_spots[i].describe())
            nxt, _spot = setup.channel_spot()
            done = sum(1 for spot in setup.channel_spots if spot.ready)
            head.configure(text=f"{done}/10개 정함 · 다음에 쓸 채널: {nxt}채널")
            # 편집기 쪽 안내도 같이 고친다. 자리를 찍었는데 "아직 안 정했습니다"가
            # 남아 있으면 정말 안 된 줄 안다.
            self._sync_channel_note()

        def pick(index: int) -> None:
            window = self.engine.window()
            got = capture_click_point(top, window)
            if got is None:
                return
            cx, cy, _color = got
            spot = setup.channel_spots[index]
            spot.where, spot.x, spot.y = "", int(cx), int(cy)
            if window is not None:
                # 지금 게임 창 크기를 함께 적어 둔다. 나중에 창 크기가 달라지면
                # 자리가 다 어긋나는데, 적어 두면 그것을 알아챌 수 있다.
                setup.client_w, setup.client_h = window.client_size()
            self.engine.save()
            redraw()
            self.engine.log(f"제작: {index + 1}채널 자리를 ({cx}, {cy})로 "
                            "정했습니다.")

        def clear(index: int) -> None:
            spot = setup.channel_spots[index]
            spot.where, spot.x, spot.y = "", -1, -1
            self.engine.save()
            redraw()

        def use_next(index: int) -> None:
            setup.channel_next = index
            self.engine.save()
            redraw()

        for i in range(len(setup.channel_spots)):
            ttk.Label(frame, text=f"{i + 1}채널").grid(
                row=i + 1, column=0, sticky="w", pady=1)
            var = tk.StringVar()
            labels.append(var)
            ttk.Label(frame, textvariable=var, width=26).grid(
                row=i + 1, column=1, sticky="w", padx=(8, 8))
            ttk.Button(frame, text="🎯 찍기", style="Small.TButton",
                       command=lambda i=i: pick(i)).grid(row=i + 1, column=2)
            ttk.Button(frame, text="지우기", style="Small.TButton",
                       command=lambda i=i: clear(i)).grid(row=i + 1, column=3,
                                                          padx=(4, 0))
            ttk.Button(frame, text="다음은 여기", style="Small.TButton",
                       command=lambda i=i: use_next(i)).grid(row=i + 1, column=4,
                                                             padx=(4, 0))
        head = ttk.Label(frame, text="")
        head.grid(row=len(setup.channel_spots) + 1, column=0, columnspan=3,
                  sticky="w", pady=(8, 0))
        ttk.Button(frame, text="닫기",
                   command=lambda: (self._sync_channel_note(), top.destroy())
                   ).grid(row=len(setup.channel_spots) + 1, column=4,
                          sticky="e", pady=(8, 0))
        redraw()

    def _sync_channel_note(self) -> None:
        item = self.selected()
        picks = self._selected_indices()
        event = (item.events[picks[0]]
                 if item and picks and picks[0] < len(item.events) else {})
        self._sync_channel(event)

    def _apply_event(self) -> None:
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            return
        event = self._event_from_editor()
        if event is None:
            return
        old = item.events[picks[0]]
        delta = self._wait_seconds(event) - self._wait_seconds(old)
        item.events[picks[0]] = event
        self._shift_events_after(item, event["t"], delta)
        self._resync(item, event["t"])

    def _add_event(self) -> None:
        item = self.selected()
        if item is None:
            return
        event = self._event_from_editor()
        if event is None:
            return
        self._shift_events_after(item, event["t"], self._wait_seconds(event))
        item.events.append(event)
        self._resync(item, event["t"])

    def _add_wait(self) -> None:
        """선택한 이벤트 바로 뒤에 아무 입력도 없는 대기를 끼워 넣는다."""
        item = self.selected()
        if item is None:
            return
        duration = max(get_int(self.ev_wait, 0), 0)
        picks = self._selected_indices()
        if picks and picks[-1] < len(item.events):
            at = round(item.events[picks[-1]]["t"] + GAP, 4)
        elif item.events:
            at = round(item.events[-1]["t"] + GAP, 4)
        else:
            at = 0.0

        event = {"t": at, "kind": "wait", "duration_ms": duration}
        self._shift_events_after(item, at, duration / 1000.0)
        item.events.append(event)
        self.engine.log(f"'{item.name}': {at:.3f}초 지점에 {duration}ms 대기를 넣었습니다.")
        self._resync(item, at)

    def _duplicate_event(self) -> None:
        """고른 이벤트를 바로 뒤에 하나 더 놓는다.

        **뒤쪽을 GAP만큼 밀고 그 자리에 넣는다.** 그냥 0.05초 뒤에 놓기만 했더니
        하필 그 자리에 이벤트가 있으면 **시각이 겹쳤다** — 복제 한 번에
        [0.0, 0.05, 0.05]가 나왔다. 같은 순간에 두 입력이 나가면 게임이 하나를
        흘리므로, 붙여넣기와 같은 규칙으로 자리를 만들어 준다.
        """
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            return
        source = item.events[picks[0]]
        anchor = source["t"]
        clone = copy.deepcopy(source)
        at = round(anchor + GAP, 4)
        for event in item.events:
            if event["t"] > anchor + 1e-9:
                event["t"] = round(event["t"] + GAP, 4)
        clone["t"] = at
        item.events.append(clone)
        self._resync(item, at)

    def _delete_event(self) -> None:
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            return
        for index in reversed(picks):
            if 0 <= index < len(item.events):
                removed = item.events[index]
                del item.events[index]
                # 대기를 지우면 그만큼 뒤쪽을 당겨 빈 시간을 없앤다.
                self._shift_events_after(item, removed["t"], -self._wait_seconds(removed))
        self._after_change(item, select=min(picks[0], len(item.events) - 1))

    def _on_moves_toggle(self) -> None:
        """켰는데 쓸 움직임이 없거나 끼울 자리가 없으면 미리 알려 준다.

        조용히 아무 일도 안 일어나면 왜 안 되는지 알 길이 없다.
        """
        item = self.selected()
        if item is not None:
            item.use_moves = bool(self.moves_var.get())
        if not self.moves_var.get():
            return

        from ..moves import plan, usable

        ready = usable(self.engine.ensure_moves())
        if not ready:
            self.engine.log(
                "⚠ 녹화해 둔 움직임이 없습니다. [설정 열기 → 움직임]에서 먼저 "
                "녹화하세요."
            )
            return
        if item is None:
            return
        settings = self.engine.settings
        gaps = _gaps(item)
        room = [g for g in gaps if g >= settings.move_min_gap_s]
        if not room:
            longest = max(gaps, default=0.0)
            self.engine.log(
                f"⚠ '{item.name}'에는 {settings.move_min_gap_s:.1f}초 이상 되는 "
                f"대기가 없습니다 (가장 긴 틈 {longest:.1f}초). 이대로면 움직임이 "
                "들어가지 않습니다."
            )
            return
        self.engine.log(
            f"'{item.name}': {settings.move_min_gap_s:.1f}초 이상인 틈이 "
            f"{len(room)}군데 있습니다 (확률 {settings.move_chance}%)."
        )

    # ------------------------------------------------------------------
    # 되돌리기 — 매크로 한 벌을 통째로 기억해 두고 되짚어 간다
    # ------------------------------------------------------------------
    #
    # 걸음마다 무엇이 바뀌었는지 따로 적지 않는다. 편집 도구가 스무 가지가 넘고
    # 저마다 건드리는 데가 다른데, 그때그때 "무엇을 되돌릴지"를 손으로 적어 두면
    # 도구를 하나 더할 때마다 되돌리기도 같이 손봐야 하고 **한 군데만 빠뜨려도
    # 조용히 어긋난다.** 통째로 찍어 두면 도구가 몇 개든 상관없다.
    def _history_reset(self, item: Macro | None) -> None:
        """다른 매크로로 옮겼다. 그 매크로의 지금 모습에서 새로 시작한다."""
        self._history = [] if item is None else [self._snapshot(item)]
        self._hpos = 0
        self._history_for = None if item is None else id(item)
        self._sync_history()

    @staticmethod
    def _snapshot(item: Macro) -> dict:
        return copy.deepcopy(item.to_dict())

    def _remember(self, item: Macro) -> None:
        """방금 바뀐 모습을 한 걸음으로 남긴다."""
        if getattr(self, "_restoring", False) or item is None:
            return
        if getattr(self, "_history_for", None) != id(item):
            self._history_reset(item)
            return
        shot = self._snapshot(item)
        if self._history and shot == self._history[self._hpos]:
            return  # 아무것도 안 바뀌었다
        # 되돌린 뒤에 새로 고치면, 앞서 있던 '다음'들은 갈 곳이 없어진다.
        del self._history[self._hpos + 1:]
        self._history.append(shot)
        if len(self._history) > HISTORY:
            del self._history[0]
        self._hpos = len(self._history) - 1
        self._sync_history()

    def _restore(self, item: Macro, shot: dict) -> None:
        """찍어 둔 모습으로 되돌린다. **같은 객체를 고친다** — 프로필 목록도,
        시나리오가 이름으로 걸어 둔 것도 그대로 살아 있어야 하기 때문이다.
        """
        old_hotkey = item.hotkey
        vars(item).update(copy.deepcopy(shot))
        if item.hotkey != old_hotkey:
            self.engine.rebind_hotkeys()

    def _step_history(self, delta: int) -> None:
        item = self.selected()
        if item is None or not self._history:
            return
        target = self._hpos + delta
        if not (0 <= target < len(self._history)):
            return
        # 되돌리는 동안에는 새 걸음을 남기지 않는다. 안 그러면 되돌린 것 자체가
        # 한 걸음이 되어 [다음 ▶]으로 갈 자리가 사라진다.
        self._restoring = True
        try:
            self._hpos = target
            self._restore(item, self._history[target])
            self.refresh(select_name=item.name)
            self.load_form(item)
        finally:
            self._restoring = False
        self._sync_history()
        where = "이전" if delta < 0 else "다음"
        self.engine.log(
            f"'{item.name}': {where}으로 되돌림 "
            f"({self._hpos + 1}/{len(self._history)}단계)"
        )

    def _undo(self) -> None:
        if self._hpos <= 0:
            self.engine.log("더 되돌릴 것이 없습니다.")
            return
        self._step_history(-1)

    def _redo(self) -> None:
        if self._hpos >= len(self._history) - 1:
            self.engine.log("되돌린 것이 없어 다음으로 갈 수 없습니다.")
            return
        self._step_history(1)

    def _sync_history(self) -> None:
        """[◀ 이전]을 눌러야 [다음 ▶]이 눌린다 — 그 상태를 단추에 비춘다."""
        if not hasattr(self, "undo_button"):
            return
        steps = len(self._history)
        self.undo_button.state(
            ["!disabled"] if self._hpos > 0 else ["disabled"])
        self.redo_button.state(
            ["!disabled"] if self._hpos < steps - 1 else ["disabled"])
        self.history_var.set(
            f"{self._hpos + 1}/{steps}단계" if steps > 1 else "")

    def _on_undo_key(self, _e: object) -> str:
        self._undo()
        return "break"

    def _on_redo_key(self, _e: object) -> str:
        self._redo()
        return "break"

    # ------------------------------------------------------------------
    def _after_change(self, item: Macro, select: int | None = None) -> None:
        """이벤트를 고친 뒤 화면을 맞춘다.

        바깥 매크로 목록을 **먼저** 새로 그린다. 그쪽 선택이 바뀌면
        <<TreeviewSelect>> → load_form 이 돌면서 이벤트 목록을 다시 채우는데,
        순서를 반대로 하면 방금 잡아 둔 이벤트 선택이 그때 풀려 버린다.
        (스핀 화살표를 두 번째 눌렀을 때 아무 반응이 없던 원인)
        """
        self.refresh(select_name=item.name)
        self._fill_events(item, select=select)
        self._remember(item)

    def _resync(self, item: Macro, at_time: float) -> None:
        """정렬 후, 방금 다룬 시각의 이벤트를 다시 선택해 준다."""
        item.events.sort(key=lambda e: e["t"])
        target = next(
            (i for i, e in enumerate(item.events) if abs(e["t"] - at_time) < 1e-6), None
        )
        self._after_change(item, select=target)

    # ------------------------------------------------------------------
    def _slide_from(self, item: Macro, index: int, delta: float) -> tuple[int, float]:
        """index번 이벤트부터 끝까지 통째로 민다. (옮긴 개수, 실제 이동량).

        당길 때는 **앞 이벤트를 넘어설 수 없다.** 그냥 밀고 0에서 자르면 여러
        이벤트가 0초에 뭉쳐 순서가 무너지고, 그러면 매크로가 통째로 못 쓰게 된다.
        딱 붙는 것도 피한다 — 시각이 같으면 두 입력이 한 순간에 나가서, 같은
        키의 뗌과 누름이 겹치면 게임이 하나로 삼켜 버린다. 그래서 붙여넣기와
        같은 최소 간격(GAP)을 남긴다.
        """
        events = item.events
        if not (0 <= index < len(events)):
            return (0, 0.0)

        if delta < 0:
            room = (
                events[index]["t"] if index == 0
                else events[index]["t"] - events[index - 1]["t"] - GAP
            )
            delta = -min(-delta, max(room, 0.0))
        if abs(delta) < 1e-9:
            return (0, 0.0)

        for event in events[index:]:
            event["t"] = round(max(0.0, event["t"] + delta), 4)
        return (len(events) - index, delta)

    def _shift_after(self) -> None:
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            return
        index = picks[0]
        moved, delta = self._slide_from(item, index, get_int(self.shift_var, 0) / 1000.0)
        if not moved:
            self.engine.log("앞 이벤트에 붙어 있어 더 당길 수 없습니다.")
            return
        self.engine.log(f"'{item.name}': {moved}개 이벤트를 {delta * 1000:+.0f}ms 이동")
        self._resync(item, item.events[index]["t"])

    def _slide(self, direction: int) -> None:
        """[당기기] / [풀기] — 고른 이벤트부터 끝까지 앞뒤로 옮긴다."""
        item = self.selected()
        picks = self._selected_indices()
        if item is None or not picks:
            self.engine.log("옮길 기준이 될 이벤트를 먼저 고르세요.")
            return
        index = picks[0]
        want = max(get_float(self.slide_var, 0.1), 0.0) * direction
        moved, delta = self._slide_from(item, index, want)

        if not moved:
            gap = item.events[index]["t"] if index == 0 else (
                item.events[index]["t"] - item.events[index - 1]["t"]
            )
            self.engine.log(
                f"더 당길 수 없습니다 — {index + 1}번과 앞 이벤트 사이가 "
                f"{gap:.3f}초뿐입니다 (최소 {GAP:.2f}초는 띄웁니다)."
            )
            return

        word = "당김" if delta < 0 else "풂"
        note = ""
        if abs(abs(delta) - abs(want)) > 1e-6:
            note = f" (요청 {abs(want):.1f}초 중 앞 여유만큼만)"
        self.engine.log(
            f"'{item.name}': {index + 1}번부터 {moved}개를 {abs(delta):.3f}초 "
            f"{word}{note}"
        )
        self._resync(item, item.events[index]["t"])

    def _swap_keys(self) -> None:
        item = self.selected()
        if item is None:
            return
        src, dst = vk_of(self.from_key.get()), vk_of(self.to_key.get())
        if src is None or dst is None:
            self.engine.log("키 이름을 해석하지 못했습니다.")
            return
        changed = 0
        for event in item.events:
            if event["kind"] == "key" and event["vk"] == src:
                event["vk"] = dst
                changed += 1
        self.engine.log(
            f"'{item.name}': [{name_of(src)}] → [{name_of(dst)}] {changed}개 변경"
        )
        # **_fill_events가 아니라 _after_change로 간다.** 목록만 다시 그리면
        # 되돌리기에 한 걸음도 안 남아서, 키를 잘못 바꿔도 되돌릴 수가 없었다.
        self._after_change(item)

    def _strip_moves(self) -> None:
        item = self.selected()
        if item is None:
            return
        before = len(item.events)
        item.events = [e for e in item.events if e["kind"] != "move"]
        self.engine.log(f"'{item.name}': 이동 이벤트 {before - len(item.events)}개 제거")
        self._after_change(item)

    def _balance(self) -> None:
        item = self.selected()
        if item is None:
            return
        before = len(item.events)
        item.events = balance_keys(item.events)
        added = len(item.events) - before
        self.engine.log(
            f"'{item.name}': 안 떼진 키/버튼 {added}개에 뗌 이벤트를 추가했습니다."
            if added
            else f"'{item.name}': 모든 키가 정상적으로 떼어져 있습니다."
        )
        self._after_change(item)

    def _to_client_coords(self) -> None:
        """화면 절대좌표로 저장된 매크로를 창 기준 좌표로 바꾼다.

        게임 창이 **녹화할 때와 같은 자리에 있는 동안** 눌러야 한다. 지금 창 위치를
        기준으로 빼기 때문이다. 한 번 변환해 두면 그 뒤로는 창을 어디로 옮겨도
        같은 지점을 누른다.
        """
        item = self.selected()
        if item is None or not item.absolute:
            return
        window = self.engine.window()
        if window is None:
            self.engine.log("게임 창을 찾지 못해 변환할 수 없습니다.")
            return
        if not messagebox.askyesno(
            "창 기준 좌표로 변환",
            "게임 창이 녹화할 때와 같은 위치에 있어야 정확합니다.\n"
            f"현재 창: {window.title}\n\n계속할까요?",
            parent=self,
        ):
            return

        converted = 0
        for event in item.events:
            if "cx" in event:
                event["cx"], event["cy"] = window.screen_to_client(
                    event["cx"], event["cy"]
                )
                converted += 1
        item.absolute = False
        item.client_w, item.client_h = window.client_size()
        self.engine.log(
            f"'{item.name}': 마우스 좌표 {converted}개를 창 기준으로 변환했습니다 "
            f"(기준 크기 {item.client_w}x{item.client_h})."
        )
        self._after_change(item)

    # ------------------------------------------------------------------
    # 자동 보정
    # ------------------------------------------------------------------
    def _on_time_spin(self) -> None:
        """스핀 화살표를 누를 때마다 선택 이벤트에 바로 반영한다."""
        if self._selected_indices():
            self._apply_event()

    def _on_time_wheel(self, event: tk.Event) -> str:
        step = TIME_STEP if event.delta > 0 else -TIME_STEP
        try:
            current = float(self.ev_t.get())
        except ValueError:
            current = 0.0
        self.ev_t.set(f"{max(0.0, current + step):.3f}")
        self._on_time_spin()
        return "break"

    def _pick_coord(self) -> None:
        """게임 화면을 직접 클릭해서 좌표를 정한다.

        숫자를 눈으로 읽어 옮겨 적는 것보다 훨씬 정확하다. 클릭은 게임에 전달되지
        않으므로 찍는 동안 캐릭터가 움직이거나 하지 않는다.
        """
        item = self.selected()
        if item is None:
            return
        window = self.engine.window()
        if window is None and not item.absolute:
            self.engine.log(
                "게임 창을 찾지 못했습니다. [설정] 탭에서 대상 창을 먼저 지정하세요."
            )
            return

        result = capture_click_point(self.winfo_toplevel(), window)
        if result is None:
            return
        cx, cy, _color = result

        # 이 매크로가 화면 절대좌표로 저장돼 있으면 같은 기준으로 되돌려 넣는다.
        if item.absolute and window is not None:
            cx, cy = window.client_to_screen(cx, cy)

        self.ev_x.set(str(cx))
        self.ev_y.set(str(cy))

        targets = [
            i
            for i in self._selected_indices()
            if 0 <= i < len(item.events) and "cx" in item.events[i]
        ]
        # 누름/뗌은 보통 같은 자리를 가리킨다. 한쪽만 고쳐 두면 재생할 때
        # 눌렀다 떼는 지점이 어긋나므로 짝도 같이 옮긴다.
        if self.pair_var.get():
            pairs, _unmatched = editing.find_pairs(item.events)
            partner = {}
            for down_index, up_index in pairs:
                partner[down_index] = up_index
                partner[up_index] = down_index
            for index in list(targets):
                mate = partner.get(index)
                if mate is not None and mate not in targets and "cx" in item.events[mate]:
                    targets.append(mate)

        if not targets:
            self.engine.log(
                f"좌표 ({cx}, {cy})를 편집칸에 넣었습니다. "
                "[선택에 적용] 또는 [＋ 추가]로 반영하세요."
            )
            return

        for index in targets:
            item.events[index]["cx"] = cx
            item.events[index]["cy"] = cy
        self.engine.log(
            f"'{item.name}': 이벤트 {len(targets)}개의 좌표를 ({cx}, {cy})로 바꿨습니다."
        )
        self._after_change(item, select=min(targets))

    def _scope(self) -> tuple[set[int] | None, str]:
        """보정을 어디에 적용할지. 2개 이상 골랐으면 그 부분만."""
        picked = self._selected_indices()
        if len(picked) >= 2:
            return (set(picked), f"선택 {len(picked)}개 (#{picked[0] + 1}~#{picked[-1] + 1})")
        return (None, "전체")

    def _normalize_holds(self) -> None:
        item = self.selected()
        if item is None or not item.events:
            return
        indices, scope = self._scope()
        changed, unmatched = editing.normalize_holds(
            item.events,
            min_ms=max(get_int(self.hold_min, editing.DEFAULT_HOLD_MIN_MS), 1),
            max_ms=max(get_int(self.hold_max, editing.DEFAULT_HOLD_MAX_MS), 1),
            indices=indices,
        )
        message = (
            f"'{item.name}' [{scope}]: 누름·뗌 간격 {changed}개 보정"
            if changed
            else f"'{item.name}' [{scope}]: 이미 모두 범위 안입니다."
        )
        if unmatched and indices is None:
            message += f" (짝이 없는 누름 {unmatched}개는 건너뜀 — [안 뗀 키 보정]을 먼저 쓰세요)"
        self.engine.log(message)
        self._after_change(item)

    def _normalize_gaps(self) -> None:
        item = self.selected()
        if item is None or not item.events:
            return
        indices, scope = self._scope()
        changed, before, after = editing.normalize_gaps(
            item.events,
            min_ms=max(get_int(self.gap_min, editing.DEFAULT_GAP_MIN_MS), 1),
            max_ms=max(get_int(self.gap_max, editing.DEFAULT_GAP_MAX_MS), 1),
            indices=indices,
        )
        self.engine.log(
            f"'{item.name}' [{scope}]: 간격 {changed}개 보정, "
            f"길이 {before:.2f}초 → {after:.2f}초"
        )
        if after > before:
            self.engine.log(
                "  ※ 길이가 늘었습니다. 원래 간격이 최소값보다 촘촘했다는 뜻이니 "
                "최소 간격을 낮춰 보세요."
            )
        self._after_change(item)

    def _merge_wheels(self) -> None:
        """줄줄이 이어진 휠 이벤트를 한 줄로 묶고 칸 수로 바꾼다."""
        item = self.selected()
        if item is None or not item.events:
            return
        removed, groups = editing.merge_wheel_runs(item.events)
        if removed:
            self.engine.log(
                f"'{item.name}': 휠 이벤트 {removed}개를 {groups}묶음으로 합쳤습니다. "
                "이제 칸 수만 고치면 됩니다."
            )
        else:
            self.engine.log(f"'{item.name}': 합칠 휠 이벤트가 없습니다.")
        self._after_change(item)

    def _apply_wheel_count(self) -> None:
        """매크로 안의 모든 휠 이벤트를 같은 칸 수로 맞춘다."""
        item = self.selected()
        if item is None or not item.events:
            return
        count = max(get_int(self.wheel_bulk, 1), 1)
        changed = editing.set_wheel_count(item.events, count)
        self.engine.log(
            f"'{item.name}': 휠 이벤트 {changed}개를 {count}칸으로 바꿨습니다."
            if changed
            else f"'{item.name}': 바꿀 휠 이벤트가 없습니다."
        )
        self._after_change(item)

    def _rebase(self) -> None:
        item = self.selected()
        if item is None or not item.events:
            return
        offset = min(e["t"] for e in item.events)
        for event in item.events:
            event["t"] = round(event["t"] - offset, 4)
        self.engine.log(f"'{item.name}': 시작 시각을 0으로 맞췄습니다 (-{offset:.3f}초)")
        self._after_change(item)

    # ------------------------------------------------------------------
    # 녹화
    # ------------------------------------------------------------------
    def toggle_record(self) -> None:
        if self.engine.recorder.recording:
            base = self.name_var.get().strip() or "녹화 매크로"
            macro = self.engine.stop_recording(base)
            self.record_button.configure(text="● 녹화 시작")
            self.refresh(select_name=macro.name if macro else None)
        else:
            if self.engine.start_recording():
                self.record_button.configure(text="■ 녹화 정지")

    def request_record_toggle(self) -> None:
        """훅 스레드에서 호출된다 — GUI 스레드로 넘긴다."""
        self.after(0, self.toggle_record)


def _gaps(macro: Macro) -> list[float]:
    """이벤트 사이의 빈 시간들. 맨 끝 대기도 포함한다."""
    times = [e.get("t", 0.0) for e in macro.events]
    out = [b - a for a, b in zip(times, times[1:])]
    if times:
        out.append(macro.duration - times[-1])
    return out


def _detail(event: dict) -> str:
    kind = event["kind"]
    if kind == "key":
        return f"[{name_of(event['vk'])}] {ACTION_LABELS[bool(event['down'])]}"
    if kind == "button":
        return (
            f"{event['button']} {ACTION_LABELS[bool(event['down'])]} "
            f"({event.get('cx', 0)}, {event.get('cy', 0)})"
        )
    if kind == "move":
        return f"({event.get('cx', 0)}, {event.get('cy', 0)})"
    if kind == "wait":
        return f"{event.get('duration_ms', 0)}ms 쉬기"
    if kind == "wheel":
        count = max(int(event.get("count", 1)), 1)
        delta = event.get("wheel", 0)
        arrow = "내림" if delta < 0 else "올림"
        return f"{delta:+d} × {count}칸 {arrow}"
    return ""
