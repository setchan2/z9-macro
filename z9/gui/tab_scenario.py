"""탭 — 시나리오 편집기.

`녹화 · 재생`이 매크로 한 덩어리를 만드는 곳이라면, 여기는 만들어 둔 매크로들을
**그룹으로 묶고 조건을 걸어** 하나의 흐름으로 만드는 곳이다.

화면은 흐름을 그대로 보여주는 트리 하나로 통일했다. 그룹 안에 단계가 들어가고,
그룹이 한 사이클 돌고 난 뒤 확인할 조건이 그 아래 붙는다. 실행 순서가 위에서
아래로 읽히도록 배치해서, 시나리오가 어떻게 진행되는지 눈으로 따라갈 수 있다.

    ▼ 파밍                        3회 반복
        1. 수확                   16개 · 1.7s
        2. 이동                    4개 · 0.9s
        조건 1  [HP 낮음] → 매크로 '물약' 실행
    ▼ 판매                        1회
        1. 상점이동                8개 · 1.2s
"""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk

from ..model import (
    LIMIT_COUNT,
    LIMIT_ITEM,
    LIMIT_TIME,
    GROUP_CONDITIONAL,
    GROUP_NORMAL,
    TRIGGER_CYCLE,
    TRIGGER_STEP,
    USE_GROUP_DELAY,
    USE_MACRO_WHEEL,
    GroupCondition,
    Scenario,
    ScenarioGroup,
    ScenarioStep,
)
from . import theme
from .base import ListEditorTab
from .widgets import HotkeyField, get_float, get_int, int_entry

ACTION_LABELS = {
    "click": "찾은 그림 누르기",
    "run": "매크로 실행",
    "group": "그룹 1회 실행 (돌아옴)",
    "goto": "그룹으로 이동 (안 돌아옴)",
    "stop": "시나리오 중지",
}
ACTION_BY_LABEL = {v: k for k, v in ACTION_LABELS.items()}

GROUP_KIND_LABELS = {
    GROUP_NORMAL: "일반 그룹 — 차례대로 실행",
    GROUP_CONDITIONAL: "조건부 그룹 — 조건이 걸릴 때만 끼어들기",
}
GROUP_KIND_BY_LABEL = {v: k for k, v in GROUP_KIND_LABELS.items()}

TRIGGER_WHEN_LABELS = {
    TRIGGER_CYCLE: "사이클마다",
    TRIGGER_STEP: "단계마다",
}
TRIGGER_WHEN_BY_LABEL = {v: k for k, v in TRIGGER_WHEN_LABELS.items()}

STEP_LABELS = {
    "macro": "매크로",
    "repeat": "연타",
    "path": "이동 경로",
    "wait": "대기",
    "schedule": "예약 확인",
    "fishing": "낚시",
}
STEP_KIND_BY_LABEL = {v: k for k, v in STEP_LABELS.items()}
STEP_ICONS = {
    "macro": "▶", "repeat": "⟳", "path": "↷", "wait": "…", "schedule": "⏰",
    "fishing": "낚",
}

# [＋ 대기] 로 만든 단계가 처음에 쉬는 시간. 곧바로 고칠 수 있으므로
# 눈에 띄되 거슬리지 않을 만한 값으로 둔다.
DEFAULT_WAIT_MS = 1000

LIMIT_LABELS = {
    LIMIT_ITEM: "항목 설정",
    LIMIT_COUNT: "횟수만큼",
    LIMIT_TIME: "시간 동안",
}
LIMIT_BY_LABEL = {v: k for k, v in LIMIT_LABELS.items()}


def _gid(group: int) -> str:
    return f"g{group}"


def _sid(group: int, step: int) -> str:
    return f"s{group}.{step}"


def _cid(group: int, condition: int) -> str:
    return f"c{group}.{condition}"


def parse_node(iid: str) -> tuple[str, tuple[int, ...]] | None:
    """트리 항목 id → (종류, 인덱스들). 'g0' / 's0.2' / 'c1.0'"""
    if not iid or iid[0] not in "gsc":
        return None
    try:
        numbers = tuple(int(part) for part in iid[1:].split("."))
    except ValueError:
        return None
    return (iid[0], numbers)


class ScenarioTab(ListEditorTab):
    kind = "scenario"
    noun = "시나리오"

    # ------------------------------------------------------------------
    def items(self) -> list[Scenario]:
        return self.engine.profile.scenarios

    def columns(self) -> list[tuple[str, str, int]]:
        return [("name", "이름", 150), ("groups", "그룹", 50), ("hotkey", "핫키", 100)]

    def row_values(self, item: Scenario) -> tuple:
        return (item.name, len(item.groups), item.hotkey or "-")

    def new_item(self) -> Scenario:
        return Scenario(name="새 시나리오", groups=[ScenarioGroup(name="그룹 1")])

    def copy_item(self, item: Scenario) -> Scenario:
        return copy.deepcopy(item)

    # ------------------------------------------------------------------
    def build_form(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)

        self._clipboard: list[ScenarioStep] = []
        self._drag_from = ""
        self._drag_over = ""
        self._drag_active = False
        self._drag_origin_y = 0
        self._loading_inspector = False
        # 흐름 표시가 무엇을 근거로 그려졌는지 적어 둔 값. 이게 달라졌다는 것은
        # 바깥에서 (녹화·재생 탭이나 설정 창에서) 무언가 바뀌었다는 뜻이다.
        self._flow_stamp: tuple | None = None
        self.palette: MacroPalette | None = None
        self._tools: dict[str, tuple[tk.Toplevel, tk.Misc]] = {}

        self.name_var = tk.StringVar()
        self.repeat_var = tk.StringVar(value="1")
        self.interval_var = tk.StringVar(value="300")

        # -- 시나리오 설정 ---------------------------------------------
        head = ttk.Frame(parent)
        head.grid(row=0, column=0, sticky="ew")

        ttk.Label(head, text="이름").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        ttk.Entry(head, textvariable=self.name_var, width=22).grid(row=0, column=1, sticky="w")
        ttk.Label(head, text="전체 반복 (0=무한)").grid(row=0, column=2, sticky="w", padx=(14, 6))
        int_entry(head, self.repeat_var, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(head, text="그룹 간 대기(ms)").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=3
        )
        int_entry(head, self.interval_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(head, text="핫키").grid(row=1, column=2, sticky="w", padx=(14, 6))
        self.hotkey_field = HotkeyField(head, width=13)
        self.hotkey_field.grid(row=1, column=3, sticky="w")

        self.info_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.info_var, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(8, 4)
        )

        # -- 도구 모음 ---------------------------------------------------
        tools = ttk.Frame(parent)
        tools.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(
            tools, text="＋ 매크로 담기", style="Accent.TButton", command=self.open_palette
        ).pack(side="left")
        ttk.Button(
            tools, text="＋ 그룹", style="Small.TButton", command=self._add_group
        ).pack(side="left", padx=(10, 4))
        ttk.Button(
            tools, text="＋ 대기", style="Small.TButton", command=self._add_wait
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            tools, text="＋ 낚시", style="Small.TButton", command=self._add_fishing
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            tools, text="＋ 조건", style="Small.TButton", command=self._add_condition
        ).pack(side="left")
        ttk.Button(
            tools, text="▲", width=3, style="Small.TButton",
            command=lambda: self._move(-1),
        ).pack(side="left", padx=(12, 2))
        ttk.Button(
            tools, text="▼", width=3, style="Small.TButton",
            command=lambda: self._move(1),
        ).pack(side="left")
        ttk.Button(
            tools, text="삭제", style="SmallDanger.TButton", command=self._delete_selected
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            tools, text="↻ 새로고침", style="Small.TButton", command=self.force_reload
        ).pack(side="left", padx=(12, 0))

        # 시나리오만 돌리게 되므로, 나머지 설정도 전부 여기서 열 수 있어야 한다.
        # 같은 줄 오른쪽 끝에 붙이되, 별도 grid 칸이 아니라 왼쪽 버튼들과 같은
        # 틀 안에 pack 으로 넣는다. 칸을 겹쳐 놓으면 창이 좁아질 때 서로 덮는다.
        setup = ttk.Frame(tools)
        setup.pack(side="right")
        ttk.Label(setup, text="설정 열기 ", style="Faint.TLabel").pack(side="left")
        for text, command in (
            ("매크로", self.open_macro_tool),
            ("연타", self.open_repeat_tool),
            ("경로", self.open_path_tool),
            ("조건", self.open_rule_tool),
            ("움직임", self.open_moves_tool),
            ("버프", self.open_buff_tool),
            ("예약", self.open_schedule_tool),
            ("관찰", self.open_observe_tool),
            ("프리셋", self.open_preset_tool),
        ):
            ttk.Button(setup, text=text, style="Small.TButton", command=command).pack(
                side="left", padx=2
            )

        self._build_inspector(parent)

        # -- 흐름 트리 ---------------------------------------------------
        wrap = ttk.Frame(parent)
        wrap.grid(row=4, column=0, sticky="nsew")

        self.flow = ttk.Treeview(
            wrap, columns=("info", "detail"), show="tree headings",
            selectmode="browse", height=12,
        )
        self.flow.heading("#0", text="흐름")
        self.flow.column("#0", width=250, minwidth=160, stretch=True)
        self.flow.heading("info", text="반복 / 대기 / 동작")
        self.flow.column("info", width=210, minwidth=150, anchor="w", stretch=False)
        self.flow.heading("detail", text="내용")
        # "20개 · 3.1s · 10.0초 동안" 까지 잘리지 않고 들어가야 한다.
        self.flow.column("detail", width=260, minwidth=140, anchor="w", stretch=False)
        self.flow.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.flow.yview)
        bar.pack(side="left", fill="y")
        self.flow.configure(yscrollcommand=bar.set)

        theme.stripe(self.flow)
        self._apply_flow_fonts()
        self.flow.tag_configure("cond", foreground=theme.PALETTE["accent"])
        self.flow.tag_configure("missing", foreground=theme.PALETTE["danger"])
        self.flow.tag_configure("drop", background=theme.PALETTE["accent_soft"])
        self.flow.bind("<<TreeviewSelect>>", self._on_node_select)
        self._bind_shortcuts()
        self._bind_drag()

        ttk.Label(
            parent,
            style="Faint.TLabel",
            text="단계를 클릭하면 위 [선택 항목 설정]에서 반복 횟수 · 시간 · 대기를 "
            "정할 수 있습니다 · Del 삭제 · Ctrl+C/X/V 복사·잘라내기·붙여넣기 · "
            "끌어서 순서 변경",
        ).grid(row=5, column=0, sticky="w", pady=(6, 0))

    # ------------------------------------------------------------------
    def _build_inspector(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="선택 항목 설정", padding=8)
        box.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(0, weight=1)
        self.inspector = box

        self.empty_hint = ttk.Label(
            box, style="Faint.TLabel",
            text="아래 흐름에서 그룹 · 단계 · 조건을 클릭하세요. "
            "단계를 고르면 몇 회 / 몇 초 반복할지 여기서 정합니다.",
        )
        self.empty_hint.grid(row=0, column=0, sticky="w")

        # -- 그룹 --------------------------------------------------------
        self.group_panel = ttk.Frame(box)
        self.group_panel.grid(row=1, column=0, sticky="ew")
        self.g_name = tk.StringVar()
        self.g_repeat = tk.StringVar(value="1")
        self.g_interval = tk.StringVar(value="300")

        ttk.Label(self.group_panel, text="그룹 이름").grid(row=0, column=0, sticky="w", padx=(0, 6))
        entry = ttk.Entry(self.group_panel, textvariable=self.g_name, width=20)
        entry.grid(row=0, column=1, sticky="w")
        entry.bind("<KeyRelease>", lambda _e: self._apply_inspector())
        ttk.Label(self.group_panel, text="반복 (0=무한)").grid(
            row=0, column=2, sticky="w", padx=(14, 6)
        )
        rep = int_entry(self.group_panel, self.g_repeat, width=6)
        rep.grid(row=0, column=3, sticky="w")
        rep.bind("<KeyRelease>", lambda _e: self._apply_inspector())
        ttk.Label(self.group_panel, text="단계 간 대기(ms)").grid(
            row=0, column=4, sticky="w", padx=(14, 6)
        )
        gap = int_entry(self.group_panel, self.g_interval, width=7)
        gap.grid(row=0, column=5, sticky="w")
        gap.bind("<KeyRelease>", lambda _e: self._apply_inspector())

        # 한 사이클이 끝날 때마다 챙길 버프들.
        ttk.Label(self.group_panel, text="사이클마다 챙길 버프").grid(
            row=1, column=0, sticky="nw", padx=(0, 6), pady=(10, 0)
        )
        self.buff_box = tk.Listbox(
            self.group_panel, selectmode="multiple", height=4, exportselection=False
        )
        theme.style_text(self.buff_box)
        self.buff_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        self.buff_box.bind("<<ListboxSelect>>", lambda _e: self._apply_inspector())

        ttk.Label(self.group_panel, text="만료 몇 초 전에").grid(
            row=1, column=4, sticky="nw", padx=(14, 6), pady=(10, 0)
        )
        self.g_margin = tk.StringVar(value="30")
        margin = int_entry(self.group_panel, self.g_margin, width=6)
        margin.grid(row=1, column=5, sticky="nw", pady=(10, 0))
        margin.bind("<KeyRelease>", lambda _e: self._apply_inspector())

        # -- 그룹 종류 ----------------------------------------------------
        # 조건부 그룹은 차례에서 빠지고, 조건이 걸릴 때만 끼어들어 한 번 돌고
        # 원래 자리로 돌아온다. "언제 필요할지 모르는 일"을 흐름에 억지로 끼워
        # 넣지 않아도 되게 하려는 것이다.
        ttk.Separator(self.group_panel, orient="horizontal").grid(
            row=2, column=0, columnspan=6, sticky="ew", pady=(12, 8)
        )

        self.g_kind = tk.StringVar(value=GROUP_KIND_LABELS[GROUP_NORMAL])
        ttk.Label(self.group_panel, text="그룹 종류").grid(
            row=3, column=0, sticky="w", padx=(0, 6)
        )
        kind_box = ttk.Combobox(
            self.group_panel, textvariable=self.g_kind,
            values=list(GROUP_KIND_LABELS.values()), width=34, state="readonly",
        )
        kind_box.grid(row=3, column=1, columnspan=3, sticky="w")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._on_group_kind_change())

        self.cond_group_panel = ttk.Frame(self.group_panel)
        self.cond_group_panel.grid(
            row=4, column=0, columnspan=6, sticky="ew", pady=(10, 0)
        )

        self.g_trigger = tk.StringVar()
        self.g_when = tk.StringVar(value=TRIGGER_WHEN_LABELS[TRIGGER_CYCLE])
        self.g_cooldown = tk.StringVar(value="0")

        ttk.Label(self.cond_group_panel, text="발동 조건").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.g_trigger_box = ttk.Combobox(
            self.cond_group_panel, textvariable=self.g_trigger, width=24,
            state="readonly",
        )
        self.g_trigger_box.grid(row=0, column=1, sticky="w")
        self.g_trigger_box.bind(
            "<<ComboboxSelected>>", lambda _e: self._apply_inspector()
        )

        ttk.Label(self.cond_group_panel, text="확인 시점").grid(
            row=0, column=2, sticky="w", padx=(14, 6)
        )
        when_box = ttk.Combobox(
            self.cond_group_panel, textvariable=self.g_when,
            values=list(TRIGGER_WHEN_LABELS.values()), width=12, state="readonly",
        )
        when_box.grid(row=0, column=3, sticky="w")
        when_box.bind("<<ComboboxSelected>>", lambda _e: self._on_trigger_when_change())

        ttk.Label(self.cond_group_panel, text="재발동 대기(초)").grid(
            row=0, column=4, sticky="w", padx=(14, 6)
        )
        cool = int_entry(self.cond_group_panel, self.g_cooldown, width=6)
        cool.grid(row=0, column=5, sticky="w")
        cool.bind("<KeyRelease>", lambda _e: self._apply_inspector())

        self.g_trigger_hint = ttk.Label(
            self.cond_group_panel, style="Faint.TLabel", justify="left", wraplength=620,
        )
        self.g_trigger_hint.grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(8, 0)
        )

        # -- 단계 --------------------------------------------------------
        self.step_panel = ttk.Frame(box)
        self.step_panel.grid(row=1, column=0, sticky="ew")
        self.s_macro = tk.StringVar()
        self.s_kind = tk.StringVar(value=STEP_LABELS["macro"])
        self.s_limit = tk.StringVar(value=LIMIT_LABELS[LIMIT_ITEM])
        self.s_repeat = tk.StringVar(value="1")
        self.s_seconds = tk.StringVar(value="10.0")
        self.s_wait = tk.StringVar(value="1000")
        self.s_custom_delay = tk.BooleanVar(value=False)
        self.s_delay = tk.StringVar(value="300")

        # 한 줄에 [설정 위젯들 …… | 안내문] 형태로 놓는다. 안내문은 전부
        # HINT_COL 한 칸에 모아서, 설정 위젯이 있는 칸(0~6)과 절대 겹치지 않게 한다.
        HINT_COL = 7
        self.step_panel.columnconfigure(HINT_COL, weight=1)

        ttk.Label(self.step_panel, text="종류").grid(row=0, column=0, sticky="w", padx=(0, 6))
        kind_box = ttk.Combobox(
            self.step_panel, textvariable=self.s_kind,
            values=list(STEP_LABELS.values()), width=10, state="readonly",
        )
        kind_box.grid(row=0, column=1, sticky="w")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._on_step_kind_change())

        self.s_target_label = ttk.Label(self.step_panel, text="대상")
        self.s_target_label.grid(row=0, column=2, sticky="w", padx=(14, 6))
        self.s_macro_box = ttk.Combobox(
            self.step_panel, textvariable=self.s_macro, width=26, state="readonly"
        )
        self.s_macro_box.grid(row=0, column=3, columnspan=2, sticky="w")
        self.s_macro_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_inspector())

        self.s_edit_button = ttk.Button(
            self.step_panel, text="이 항목 편집…", style="Small.TButton",
            command=self._edit_step_target,
        )
        self.s_edit_button.grid(row=0, column=5, sticky="w", padx=(8, 0))

        self.s_wait_label = ttk.Label(self.step_panel, text="쉴 시간(ms)")
        self.s_wait_label.grid(row=0, column=6, sticky="w", padx=(14, 6))
        self.s_wait_entry = int_entry(self.step_panel, self.s_wait, width=7)
        self.s_wait_entry.grid(row=0, column=HINT_COL, sticky="w")
        self.s_wait_entry.bind("<KeyRelease>", lambda _e: self._apply_inspector())

        # -- 1행: 언제까지 -------------------------------------------------
        self.s_custom_wheel = tk.BooleanVar(value=False)
        self.s_wheel = tk.StringVar(value="3")

        ttk.Label(self.step_panel, text="언제까지").grid(
            row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 6)
        )
        self.s_limit_box = ttk.Combobox(
            self.step_panel, textvariable=self.s_limit,
            values=list(LIMIT_LABELS.values()), width=10, state="readonly",
        )
        self.s_limit_box.grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.s_limit_box.bind("<<ComboboxSelected>>", lambda _e: self._on_limit_change())

        self.s_repeat_entry = int_entry(self.step_panel, self.s_repeat, width=6)
        self.s_repeat_entry.grid(row=1, column=2, sticky="w", pady=(8, 0), padx=(14, 0))
        self.s_repeat_entry.bind("<KeyRelease>", lambda _e: self._apply_inspector())
        self.s_repeat_unit = ttk.Label(self.step_panel, text="회")
        self.s_repeat_unit.grid(row=1, column=3, sticky="w", pady=(8, 0), padx=(4, 0))

        # 초는 0.1 단위로 올리고 내릴 수 있게 화살표를 붙인다.
        self.s_seconds_spin = ttk.Spinbox(
            self.step_panel, textvariable=self.s_seconds,
            from_=0.1, to=86400.0, increment=0.1, format="%.1f", width=8,
            command=self._apply_inspector,
        )
        self.s_seconds_spin.grid(row=1, column=4, sticky="w", pady=(8, 0), padx=(14, 0))
        self.s_seconds_spin.bind("<KeyRelease>", lambda _e: self._apply_inspector())
        self.s_seconds_unit = ttk.Label(self.step_panel, text="초")
        self.s_seconds_unit.grid(row=1, column=5, sticky="w", pady=(8, 0), padx=(4, 0))

        self.s_repeat_hint = ttk.Label(self.step_panel, style="Faint.TLabel", text="")
        self.s_repeat_hint.grid(
            row=1, column=HINT_COL, sticky="w", pady=(8, 0), padx=(16, 0)
        )

        # -- 2행: 이 단계 뒤 대기 -------------------------------------------
        self.s_delay_check = ttk.Checkbutton(
            self.step_panel,
            text="이 단계 뒤 대기를 따로 지정",
            variable=self.s_custom_delay,
            command=self._on_delay_toggle,
        )
        self.s_delay_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.s_delay_entry = int_entry(self.step_panel, self.s_delay, width=7)
        self.s_delay_entry.grid(row=2, column=2, sticky="w", pady=(8, 0), padx=(14, 0))
        self.s_delay_entry.bind("<KeyRelease>", lambda _e: self._apply_inspector())
        ttk.Label(self.step_panel, text="ms").grid(
            row=2, column=3, sticky="w", pady=(8, 0), padx=(4, 0)
        )

        self.s_delay_hint = ttk.Label(self.step_panel, style="Faint.TLabel", text="")
        self.s_delay_hint.grid(
            row=2, column=HINT_COL, sticky="w", pady=(8, 0), padx=(16, 0)
        )

        # -- 3행: 휠 칸 수 ---------------------------------------------------
        self.s_wheel_check = ttk.Checkbutton(
            self.step_panel,
            text="휠 칸 수를 따로 지정",
            variable=self.s_custom_wheel,
            command=self._on_wheel_toggle,
        )
        self.s_wheel_check.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.s_wheel_entry = int_entry(self.step_panel, self.s_wheel, width=7)
        self.s_wheel_entry.grid(row=3, column=2, sticky="w", pady=(8, 0), padx=(14, 0))
        self.s_wheel_entry.bind("<KeyRelease>", lambda _e: self._apply_inspector())
        ttk.Label(self.step_panel, text="칸").grid(
            row=3, column=3, sticky="w", pady=(8, 0), padx=(4, 0)
        )

        self.s_wheel_hint = ttk.Label(
            self.step_panel,
            style="Faint.TLabel",
            text="휠이 든 매크로를 굴림량만 바꿔 여러 곳에 쓸 때 씁니다. "
            "매크로 안의 휠 이벤트를 전부 이 칸 수로 바꿔 실행합니다.",
        )
        self.s_wheel_hint.grid(
            row=3, column=HINT_COL, sticky="w", pady=(8, 0), padx=(16, 0)
        )

        # -- 조건 --------------------------------------------------------
        self.cond_panel = ttk.Frame(box)
        self.cond_panel.grid(row=1, column=0, sticky="ew")
        self.c_rule = tk.StringVar()
        self.c_action = tk.StringVar(value=ACTION_LABELS["run"])
        self.c_target = tk.StringVar()
        self.c_enabled = tk.BooleanVar(value=True)

        ttk.Label(self.cond_panel, text="이 조건이 성립하면").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.c_rule_box = ttk.Combobox(
            self.cond_panel, textvariable=self.c_rule, width=24, state="readonly"
        )
        self.c_rule_box.grid(row=0, column=1, sticky="w")
        self.c_rule_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_inspector())

        ttk.Label(self.cond_panel, text="동작").grid(row=0, column=2, sticky="w", padx=(14, 6))
        self.c_action_box = ttk.Combobox(
            self.cond_panel, textvariable=self.c_action,
            values=list(ACTION_LABELS.values()), width=14, state="readonly",
        )
        self.c_action_box.grid(row=0, column=3, sticky="w")
        self.c_action_box.bind("<<ComboboxSelected>>", lambda _e: self._on_action_change())

        ttk.Label(self.cond_panel, text="대상").grid(row=0, column=4, sticky="w", padx=(14, 6))
        self.c_target_box = ttk.Combobox(
            self.cond_panel, textvariable=self.c_target, width=22, state="readonly"
        )
        self.c_target_box.grid(row=0, column=5, sticky="w")
        self.c_target_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_inspector())

        ttk.Checkbutton(
            self.cond_panel, text="사용", variable=self.c_enabled,
            command=self._apply_inspector,
        ).grid(row=0, column=6, sticky="w", padx=(14, 0))

        ttk.Label(
            self.cond_panel, style="Faint.TLabel",
            text="조건은 그룹이 한 사이클 돌고 난 뒤에 확인합니다. "
            "위에 있는 조건이 먼저이며, 먼저 걸리는 하나만 발동합니다.",
        ).grid(row=1, column=0, columnspan=7, sticky="w", pady=(8, 0))

        self._show_panel(None)

    def _show_panel(self, kind: str | None) -> None:
        for panel in (self.group_panel, self.step_panel, self.cond_panel):
            panel.grid_remove()
        self.empty_hint.grid_remove()
        if kind == "g":
            self.group_panel.grid()
        elif kind == "s":
            self.step_panel.grid()
        elif kind == "c":
            self.cond_panel.grid()
        else:
            self.empty_hint.grid()

    # ------------------------------------------------------------------
    def load_form(self, item: Scenario) -> None:
        self.name_var.set(item.name)
        self.repeat_var.set(str(item.repeat))
        self.interval_var.set(str(item.interval_ms))
        self.hotkey_field.set(item.hotkey)
        self.refresh_sources()
        self._fill_flow(item)

    def save_form(self, item: Scenario) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.repeat = max(get_int(self.repeat_var, 1), 0)
        item.interval_ms = max(get_int(self.interval_var, 300), 0)
        if item.hotkey != self.hotkey_field.get():
            item.hotkey = self.hotkey_field.get()
            self.engine.rebind_hotkeys()
        if renamed:
            self.refresh(select_name=item.name)

    # ------------------------------------------------------------------
    def _fill_flow(self, item: Scenario, select: str | None = None) -> None:
        opened = {
            iid for iid in self.flow.get_children() if self.flow.item(iid, "open")
        }
        self.flow.delete(*self.flow.get_children())

        total = 0.0
        missing = 0
        row = 0
        for gi, group in enumerate(item.groups):
            if group.conditional:
                cycles = group.interrupt_cycles()
                when = TRIGGER_WHEN_LABELS.get(group.trigger_when, "")
                repeat = (
                    f"조건 '{group.trigger}' → {cycles}회 끼어들기"
                    if group.trigger
                    else "⚠ 발동 조건 없음 — 영영 실행되지 않습니다"
                )
                if group.trigger:
                    repeat += f" · {when} 확인"
            else:
                repeat = f"{group.repeat}회 반복" if group.repeat > 0 else "무한 반복"
            if group.buffs:
                repeat += f" · 버프 {len(group.buffs)}개"
            gid = _gid(gi)
            group_seconds = 0.0
            # 맑은 고딕에 없는 글자를 쓰면 네모로 깨진다. KS 기호 범위에서 고른다.
            mark = "◆ " if group.conditional else ""
            self.flow.insert(
                "", "end", iid=gid,
                text=f"{mark}{group.name}",
                values=(repeat, f"단계 {len(group.steps)}개"),
                open=(gid in opened) or not opened,
                tags=(theme.row_tag(row), "group"),
            )
            row += 1

            for si, step in enumerate(group.steps):
                detail, seconds, ok = self._describe_step(step)
                if not ok:
                    missing += 1
                    tags = (theme.row_tag(row), "missing")
                else:
                    group_seconds += seconds
                    tags = (theme.row_tag(row),)

                delay = step.effective_delay(group.interval_ms)
                group_seconds += delay / 1000.0
                if delay <= 0:
                    info = "대기 없음"
                elif step.custom_delay:
                    info = f"뒤 {delay}ms 대기 (직접 지정)"
                else:
                    info = f"뒤 {delay}ms 대기"
                if step.custom_wheel:
                    info += f" · 휠 {step.wheel_count}칸"

                self.flow.insert(
                    gid, "end", iid=_sid(gi, si),
                    text=f"{si + 1}. {STEP_ICONS[step.kind]} {step.label}",
                    values=(info, detail),
                    tags=tags,
                )
                row += 1

            if not group.conditional:
                total += group_seconds * max(group.repeat, 1)

            for ci, condition in enumerate(group.conditions):
                tags = [theme.row_tag(row), "cond"]
                if not condition.enabled:
                    tags = [theme.row_tag(row), "missing"]
                self.flow.insert(
                    gid, "end", iid=_cid(gi, ci),
                    text=f"    조건 {ci + 1}. {condition.rule or '(고르지 않음)'}",
                    values=(_describe_action(condition), "사용" if condition.enabled else "꺼짐"),
                    tags=tuple(tags),
                )
                row += 1

        ordered = item.ordered_groups
        watched = [g for g in item.groups if g.conditional]
        total += max(len(ordered) - 1, 0) * item.interval_ms / 1000.0
        summary = (
            f"그룹 {len(ordered)}개 · 단계 {item.step_count}개 · "
            f"1회 예상 {total:.1f}초"
        )
        if watched:
            summary += f" · 조건부 그룹 {len(watched)}개 (예상 시간에는 안 들어감)"
        if missing:
            # 예전에는 "없는 매크로"라고만 적었는데, 낚시처럼 가리키는 항목이
            # 없는 단계도 여기에 걸린다. 그때는 이유가 매크로가 아니다.
            summary += f" · ⚠ 그대로는 못 도는 단계 {missing}개"
        self.info_var.set(summary)

        self._flow_stamp = self._flow_fingerprint(item)

        if select and self.flow.exists(select):
            self.flow.selection_set(select)
            self.flow.see(select)
        elif self.flow.exists(_sid(0, 0)):
            # 설정 패널이 빈 채로 있으면 어디서 반복 횟수를 정하는지 알 수 없다.
            # 첫 단계를 미리 골라 두어 무엇을 조절할 수 있는지 바로 보이게 한다.
            self.flow.selection_set(_sid(0, 0))
            self._on_node_select()
        else:
            self._show_panel(None)

    # ------------------------------------------------------------------
    # 바깥에서 바뀐 것 따라가기
    # ------------------------------------------------------------------
    def _source_stamp(self, step: ScenarioStep):
        """단계가 가리키는 항목의 '지금 모습'.

        흐름 표시에 실제로 드러나는 값만 모은다. 매크로를 녹화·재생 탭에서
        고치면 여기가 달라지고, 그때 흐름 트리를 다시 그리면 된다.
        """
        if step.kind == "macro":
            found = self.engine.find_macro(step.target)
            return found and (len(found.events), round(found.duration, 3), found.repeat)
        if step.kind == "repeat":
            found = self.engine.find_repeat(step.target)
            return found and (found.key, found.interval_ms, found.duration_s)
        if step.kind == "path":
            found = self.engine.find_path(step.target)
            return found and (
                len(found.steps), found.repeat,
                sum(max(s.duration_ms, 0) for s in found.steps),
            )
        if step.kind == "schedule":
            found = self.engine.find_schedule(step.target)
            return found and (
                found.mode, found.minute, found.every_minutes,
                found.action_kind, found.action_target,
            )
        return None

    def _flow_fingerprint(self, item: Scenario) -> tuple:
        parts: list = [item.interval_ms, item.repeat]
        for group in item.groups:
            parts.append(
                (group.name, group.repeat, group.interval_ms, tuple(group.buffs))
            )
            for step in group.steps:
                parts.append((
                    step.kind, step.target, step.delay_ms, step.wheel_count,
                    step.limit_mode, step.repeat_count, step.limit_seconds,
                    step.wait_ms, self._source_stamp(step),
                ))
            for cond in group.conditions:
                parts.append((cond.rule, cond.action, cond.target, cond.enabled))
        return tuple(parts)

    # 글자를 받아들이는 위젯들. 여기에 포커스가 있으면 폼을 건드리지 않는다.
    _TYPING_CLASSES = frozenset(
        {"Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox", "Text"}
    )

    def _typing(self) -> bool:
        try:
            focused = self.focus_get()
        except (KeyError, tk.TclError):
            return False
        if focused is None or not str(focused).startswith(str(self)):
            return False
        try:
            return focused.winfo_class() in self._TYPING_CLASSES
        except tk.TclError:
            return False

    def sync_flow(self) -> None:
        """바깥에서 항목이 바뀌었으면 흐름 표시를 조용히 맞춘다.

        고르고 있던 단계는 그대로 둔다. 사용자가 보고 있는 자리가 제멋대로
        튀면 편집이 불가능해진다. 또 이 탭의 입력칸에 글자를 치고 있는
        중이라면 미룬다 — 타이핑 도중 폼을 다시 채우면 글자가 날아간다.
        (트리나 버튼에 포커스가 있는 것은 상관없다. 그쪽까지 피하면 이 탭을
        보고 있는 동안에는 영영 갱신되지 않는다.)
        """
        item = self.selected()
        if item is None:
            self._flow_stamp = None
            return
        if self._flow_fingerprint(item) == self._flow_stamp:
            return
        if self._typing():
            return

        node = self.flow.selection()
        self.refresh_sources()
        self._fill_flow(item, select=node[0] if node else None)

    def _after_change(self, item: Scenario, select: str | None = None) -> None:
        # 바깥 목록을 먼저 그린다 (base._on_select가 폼을 다시 채우며
        # 트리 선택을 지우는 것을 피하기 위해).
        self.refresh(select_name=item.name)
        self._fill_flow(item, select=select)

    # ------------------------------------------------------------------
    def _selected_node(self) -> tuple[str, tuple[int, ...]] | None:
        selection = self.flow.selection()
        return parse_node(selection[0]) if selection else None

    def _target_group(self) -> int | None:
        """지금 선택으로 미루어 어느 그룹을 대상으로 할지."""
        node = self._selected_node()
        if node is None:
            item = self.selected()
            return len(item.groups) - 1 if item and item.groups else None
        return node[1][0]

    def _on_node_select(self, _e: object = None) -> None:
        node = self._selected_node()
        item = self.selected()
        if node is None or item is None:
            self._show_panel(None)
            return

        kind, idx = node
        self._loading_inspector = True
        try:
            if kind == "g" and idx[0] < len(item.groups):
                group = item.groups[idx[0]]
                self.g_name.set(group.name)
                self.g_repeat.set(str(group.repeat))
                self.g_interval.set(str(group.interval_ms))
                self.g_margin.set(str(group.buff_margin_s))
                self.g_kind.set(
                    GROUP_KIND_LABELS.get(group.kind, GROUP_KIND_LABELS[GROUP_NORMAL])
                )
                self.g_trigger_box.configure(
                    values=[r.name for r in self.engine.profile.rules]
                )
                self.g_trigger.set(group.trigger)
                self.g_when.set(
                    TRIGGER_WHEN_LABELS.get(
                        group.trigger_when, TRIGGER_WHEN_LABELS[TRIGGER_CYCLE]
                    )
                )
                self.g_cooldown.set(str(group.trigger_cooldown_s))
                self._fill_buffs(group)
                self._sync_group_kind(group)
                self._show_panel("g")
            elif kind == "s":
                group = item.groups[idx[0]]
                step = group.steps[idx[1]]
                self.s_kind.set(STEP_LABELS.get(step.kind, STEP_LABELS["macro"]))
                self._sync_step_kind()
                self.s_macro.set(step.target)
                self.s_wait.set(str(step.wait_ms))
                self.s_custom_delay.set(step.custom_delay)
                self.s_delay.set(
                    str(step.delay_ms if step.custom_delay else group.interval_ms)
                )
                self.s_limit.set(LIMIT_LABELS.get(step.limit_mode, LIMIT_LABELS[LIMIT_ITEM]))
                self.s_repeat.set(str(max(int(step.repeat_count), 1)))
                self.s_seconds.set(f"{max(float(step.limit_seconds), 0.1):.1f}")
                self.s_custom_wheel.set(step.custom_wheel)
                if step.custom_wheel:
                    self.s_wheel.set(str(step.wheel_count))
                self._sync_delay_state(group)
                self._sync_wheel_state()
                self._sync_repeat_state(step)
                self._show_panel("s")
            elif kind == "c":
                group = item.groups[idx[0]]
                condition = group.conditions[idx[1]]
                self.c_rule_box.configure(
                    values=[r.name for r in self.engine.profile.rules]
                )
                self.c_rule.set(condition.rule)
                self.c_action.set(ACTION_LABELS.get(condition.action, ACTION_LABELS["run"]))
                self._refresh_targets(item, condition.action)
                self.c_target.set(condition.target)
                self.c_enabled.set(condition.enabled)
                self._show_panel("c")
            else:
                self._show_panel(None)
        except IndexError:
            self._show_panel(None)
        finally:
            self._loading_inspector = False

    def _refresh_targets(self, item: Scenario, action: str) -> None:
        if action == "run":
            values = [m.name for m in self.engine.profile.macros]
            state = "readonly"
        elif action == "goto":
            # 옮겨 가는 것이므로 차례대로 도는 그룹만 대상이 된다.
            values = [g.name for g in item.ordered_groups]
            state = "readonly"
        elif action == "group":
            values = [g.name for g in item.groups]
            state = "readonly"
        elif action == "click":
            values = []
            state = "disabled"
        else:
            values = []
            state = "disabled"
        self.c_target_box.configure(values=values, state=state)

    def _sync_delay_state(self, group: ScenarioGroup) -> None:
        custom = bool(self.s_custom_delay.get())
        self.s_delay_entry.configure(state="normal" if custom else "disabled")
        self.s_delay_hint.configure(
            text=(
                f"이 단계 뒤에만 {self.s_delay.get()}ms 쉽니다."
                if custom
                else f"그룹 기본값({group.interval_ms}ms)을 따릅니다. "
                "특정 매크로 뒤에만 더 쉬어야 하면 왼쪽을 켜세요."
            )
        )

    def _on_delay_toggle(self) -> None:
        item = self.selected()
        node = self._selected_node()
        if item is None or node is None or node[0] != "s":
            return
        group = item.groups[node[1][0]]
        if self.s_custom_delay.get() and not self.s_delay.get().strip():
            self.s_delay.set(str(group.interval_ms))
        self._apply_inspector()

    def _fill_buffs(self, group: ScenarioGroup) -> None:
        """등록된 버프를 나열하고, 이 그룹에 붙은 것만 선택 상태로 만든다."""
        self.buff_box.delete(0, "end")
        for index, buff in enumerate(self.engine.profile.buffs):
            self.buff_box.insert(
                "end", f"{buff.name}  ({buff.duration_min}분)"
            )
            if buff.name in group.buffs:
                self.buff_box.selection_set(index)

    # ------------------------------------------------------------------
    # 단계 종류
    # ------------------------------------------------------------------
    def _step_sources(self, kind: str) -> list[str]:
        if kind == "repeat":
            return [r.name for r in self.engine.profile.repeats]
        if kind == "path":
            return [p.name for p in self.engine.profile.paths]
        if kind == "macro":
            return [m.name for m in self.engine.profile.macros]
        if kind == "schedule":
            return [s.name for s in self.engine.profile.schedules]
        return []

    def _describe_step(self, step: ScenarioStep) -> tuple[str, float, bool]:
        """(내용 설명, 예상 소요 초, 대상을 찾았는지)."""
        if step.kind == "wait":
            return (f"{step.wait_ms}ms", step.wait_ms / 1000.0, True)

        if step.kind == "fishing":
            setup = self.engine.profile.fishing
            missing = setup.problems()
            if missing:
                return ("낚시 설정이 덜 됨: " + ", ".join(missing), 0.0, False)
            if step.timed:
                seconds = step.effective_seconds()
                return (f"{seconds:.0f}초 동안", seconds, True)
            rounds = max(1, step.effective_repeat(1))
            # 한 판은 던지고 기다리는 시간까지 합쳐 대략 제한 시간의 절반쯤 더 든다.
            return (f"{rounds}판", rounds * (setup.limit_s * 0.6 + setup.rest_s), True)

        if step.kind == "schedule":
            task = self.engine.find_schedule(step.target)
            if task is None:
                return ("없는 예약", 0.0, False)
            from ..tasks import describe_schedule

            # 시각이 안 됐으면 그냥 지나가므로 예상 시간에는 넣지 않는다.
            return (
                f"{describe_schedule(task)} → {task.action_target or '(비어 있음)'}",
                0.0,
                True,
            )

        if step.kind == "repeat":
            task = self.engine.find_repeat(step.target)
            if task is None:
                return ("없는 연타", 0.0, False)
            seconds = step.effective_seconds(task.duration_s) or 10
            return (
                f"[{task.key}] {task.interval_ms}ms · {seconds:.1f}초", seconds, True
            )

        if step.kind == "path":
            path = self.engine.find_path(step.target)
            if path is None:
                return ("없는 경로", 0.0, False)
            times = step.effective_repeat(path.repeat)
            rough = sum(max(s.duration_ms, 0) for s in path.steps) / 1000.0
            seconds = step.limit_seconds if step.timed else rough * times
            return (
                f"단계 {len(path.steps)}개{_times(step, times)}",
                seconds,
                True,
            )

        macro = self.engine.find_macro(step.target)
        if macro is None:
            return ("없는 매크로", 0.0, False)
        times = step.effective_repeat(macro.repeat)
        seconds = step.limit_seconds if step.timed else macro.duration * times
        return (
            f"{len(macro.events)}개 · {macro.duration:.1f}s{_times(step, times)}",
            seconds,
            True,
        )

    def _sync_step_kind(self) -> None:
        kind = STEP_KIND_BY_LABEL.get(self.s_kind.get(), "macro")
        is_wait = kind == "wait"
        # 낚시도 고를 대상이 없다 — 설정이 [낚시] 탭에 한 벌뿐이다.
        no_target = is_wait or kind == "fishing"
        names = self._step_sources(kind)

        self.s_macro_box.configure(
            values=names, state="disabled" if no_target or not names else "readonly"
        )
        self.s_edit_button.configure(
            state="normal" if kind == "fishing" or not is_wait else "disabled")
        # 예약 확인과 낚시는 휠을 바꿔 끼울 대상이 없다.
        self.s_wheel_check.configure(
            state="disabled" if kind in ("wait", "schedule", "fishing") else "normal"
        )
        self.s_wait_entry.configure(state="normal" if is_wait else "disabled")
        self.s_wait_label.configure(style="TLabel" if is_wait else "Faint.TLabel")
        self.s_target_label.configure(
            style="Faint.TLabel" if no_target else "TLabel")

    def _on_step_kind_change(self) -> None:
        kind = STEP_KIND_BY_LABEL.get(self.s_kind.get(), "macro")
        names = self._step_sources(kind)
        if self.s_macro.get() not in names:
            self.s_macro.set(names[0] if names else "")
        self._sync_step_kind()
        self._apply_inspector()


    def _edit_step_target(self) -> None:
        """이 단계가 가리키는 항목의 편집 창을 연다."""
        kind = STEP_KIND_BY_LABEL.get(self.s_kind.get(), "macro")
        name = self.s_macro.get()
        if kind == "fishing":
            self.engine.log("낚시 설정은 위쪽 [낚시] 탭에 있습니다.")
            return
        window = {
            "macro": self.open_macro_tool,
            "repeat": self.open_repeat_tool,
            "path": self.open_path_tool,
            "schedule": self.open_schedule_tool,
        }.get(kind)
        if window is None:
            return
        tool = window()
        if tool is not None and name:
            tool.refresh(select_name=name)

    def _sync_repeat_state(self, step: ScenarioStep) -> None:
        """한계 방식에 맞춰 입력칸을 열고 닫고, 실제로 어떻게 될지 알려준다."""
        if step.kind in ("wait", "schedule"):
            self.s_limit_box.configure(state="disabled")
            self.s_repeat_entry.configure(state="disabled")
            self.s_seconds_spin.configure(state="disabled")
            self.s_repeat_hint.configure(
                text="대기는 위의 쉴 시간으로 정합니다."
                if step.kind == "wait"
                else "시각이 지났으면 한 번 실행하고, 아니면 그냥 지나갑니다."
            )
            return

        mode = LIMIT_BY_LABEL.get(self.s_limit.get(), LIMIT_ITEM)
        # 연타는 '몇 번'이 아니라 '몇 초'로 다루는 게 자연스럽다.
        allowed = [LIMIT_ITEM, LIMIT_TIME] if step.kind == "repeat" else list(LIMIT_LABELS)
        if step.kind == "fishing":
            # 낚시에는 '항목 설정'이랄 것이 없다. 몇 판인지 몇 초인지만 정한다.
            allowed = [LIMIT_COUNT, LIMIT_TIME]
        self.s_limit_box.configure(
            state="readonly", values=[LIMIT_LABELS[m] for m in allowed]
        )
        if mode not in allowed:
            mode = LIMIT_ITEM
            self.s_limit.set(LIMIT_LABELS[mode])

        self.s_repeat_entry.configure(state="normal" if mode == LIMIT_COUNT else "disabled")
        self.s_seconds_spin.configure(state="normal" if mode == LIMIT_TIME else "disabled")
        self.s_repeat_unit.configure(
            style="TLabel" if mode == LIMIT_COUNT else "Faint.TLabel"
        )
        self.s_seconds_unit.configure(
            style="TLabel" if mode == LIMIT_TIME else "Faint.TLabel"
        )

        if mode == LIMIT_COUNT:
            self.s_repeat_hint.configure(text="그만큼 돌리고 다음 단계로 넘어갑니다.")
            return
        if mode == LIMIT_TIME:
            self.s_repeat_hint.configure(
                text="시간이 찰 때까지 되풀이합니다. 시작한 한 바퀴는 끝까지 돕니다."
            )
            return

        self.s_repeat_hint.configure(text=self._item_default_hint(step))

    def _item_default_hint(self, step: ScenarioStep) -> str:
        if step.kind == "repeat":
            task = self.engine.find_repeat(step.target)
            if task is None:
                return "항목 자체 설정을 따릅니다."
            if task.duration_s > 0:
                return f"연타 설정({task.duration_s}초)을 따릅니다."
            return "연타에 시간 제한이 없어 10초만 돕니다."

        found = (
            self.engine.find_macro(step.target)
            if step.kind == "macro"
            else self.engine.find_path(step.target)
        )
        if found is None:
            return "항목 자체 설정을 따릅니다."
        if found.repeat == 0:
            return "항목이 무한 반복이라 시나리오 안에서는 1회만 돕니다."
        return f"항목 설정({found.repeat}회)을 따릅니다."

    def _on_limit_change(self) -> None:
        self._apply_inspector()

    def _sync_wheel_state(self) -> None:
        custom = bool(self.s_custom_wheel.get())
        self.s_wheel_entry.configure(state="normal" if custom else "disabled")

    def _on_wheel_toggle(self) -> None:
        self._apply_inspector()

    def _on_group_kind_change(self) -> None:
        self._apply_inspector()
        item = self.selected()
        node = self._selected_node()
        if item is None or node is None or node[0] != "g":
            return
        self._sync_group_kind(item.groups[node[1][0]])
        self._fill_flow(item, select=_gid(node[1][0]))

    def _on_trigger_when_change(self) -> None:
        # '단계마다'는 확인이 잦다. 대기가 0이면 조건이 걸린 채로 남아 있을 때
        # 단계마다 끼어들어 본작업이 밀리므로, 처음 고를 때 기본값을 넣어 준다.
        if (
            TRIGGER_WHEN_BY_LABEL.get(self.g_when.get()) == TRIGGER_STEP
            and get_int(self.g_cooldown, 0) <= 0
        ):
            self.g_cooldown.set("10")
        self._apply_inspector()
        item = self.selected()
        node = self._selected_node()
        if item is not None and node is not None and node[0] == "g":
            self._sync_group_kind(item.groups[node[1][0]])

    def _sync_group_kind(self, group: ScenarioGroup) -> None:
        """그룹 종류에 맞춰 조건부 칸을 보이거나 감춘다."""
        if group.conditional:
            self.cond_group_panel.grid()
        else:
            self.cond_group_panel.grid_remove()
            return

        when = TRIGGER_WHEN_BY_LABEL.get(self.g_when.get(), TRIGGER_CYCLE)
        cooldown = max(0, get_int(self.g_cooldown, 0))
        cycles = group.interrupt_cycles()
        where = (
            "사이클을 시작하기 전마다"
            if when == TRIGGER_CYCLE
            else "단계를 시작하기 전마다"
        )
        wait = (
            f"한 번 발동하면 {cooldown}초 동안은 다시 보지 않습니다."
            if cooldown > 0
            else "⚠ 재발동 대기가 0입니다 — 조건이 계속 걸려 있으면 쉴 새 없이 "
            "되풀이합니다."
        )
        self.g_trigger_hint.configure(
            text=(
                f"이 그룹은 차례에서 빠집니다. 시나리오가 도는 동안 {where} 조건을 "
                f"보고, 걸리면 하던 일을 멈추고 이 그룹을 {cycles}회 돌린 뒤 원래 "
                f"자리로 돌아옵니다.  {wait}"
            )
        )

    def _on_action_change(self) -> None:
        item = self.selected()
        if item is None:
            return
        action = ACTION_BY_LABEL.get(self.c_action.get(), "run")
        self._refresh_targets(item, action)
        self.c_target.set("")
        self._apply_inspector()

    def _apply_inspector(self) -> None:
        if self._loading_inspector:
            return
        node = self._selected_node()
        item = self.selected()
        if node is None or item is None:
            return
        kind, idx = node
        try:
            if kind == "g":
                group = item.groups[idx[0]]
                group.name = self.g_name.get().strip() or group.name
                group.repeat = max(get_int(self.g_repeat, 1), 0)
                group.interval_ms = max(get_int(self.g_interval, 300), 0)
                group.buff_margin_s = max(get_int(self.g_margin, 30), 0)
                names = [b.name for b in self.engine.profile.buffs]
                group.buffs = [
                    names[i] for i in self.buff_box.curselection() if i < len(names)
                ]
                group.kind = GROUP_KIND_BY_LABEL.get(self.g_kind.get(), GROUP_NORMAL)
                group.trigger = self.g_trigger.get().strip()
                group.trigger_when = TRIGGER_WHEN_BY_LABEL.get(
                    self.g_when.get(), TRIGGER_CYCLE
                )
                group.trigger_cooldown_s = max(0, get_int(self.g_cooldown, 0))
            elif kind == "s":
                group = item.groups[idx[0]]
                step = group.steps[idx[1]]
                step.kind = STEP_KIND_BY_LABEL.get(self.s_kind.get(), "macro")
                step.target = self.s_macro.get()
                step.wait_ms = max(get_int(self.s_wait, 1000), 0)
                if self.s_custom_delay.get():
                    step.delay_ms = max(get_int(self.s_delay, group.interval_ms), 0)
                else:
                    step.delay_ms = USE_GROUP_DELAY
                step.limit_mode = LIMIT_BY_LABEL.get(self.s_limit.get(), LIMIT_ITEM)
                step.repeat_count = max(get_int(self.s_repeat, 1), 1)
                step.limit_seconds = max(get_float(self.s_seconds, 10.0), 0.1)
                if self.s_custom_wheel.get():
                    step.wheel_count = max(get_int(self.s_wheel, 1), 1)
                else:
                    step.wheel_count = USE_MACRO_WHEEL
                self._sync_delay_state(group)
                self._sync_wheel_state()
                self._sync_repeat_state(step)
            elif kind == "c":
                condition = item.groups[idx[0]].conditions[idx[1]]
                condition.rule = self.c_rule.get()
                condition.action = ACTION_BY_LABEL.get(self.c_action.get(), "run")
                condition.target = self.c_target.get()
                condition.enabled = bool(self.c_enabled.get())
        except IndexError:
            return

        selected_iid = self.flow.selection()[0] if self.flow.selection() else None
        self._fill_flow(item, select=selected_iid)

    # ------------------------------------------------------------------
    # 추가 / 삭제 / 이동
    # ------------------------------------------------------------------
    def _add_group(self) -> None:
        item = self.selected()
        if item is None:
            return
        existing = {g.name for g in item.groups}
        number = len(item.groups) + 1
        while f"그룹 {number}" in existing:
            number += 1
        item.groups.append(ScenarioGroup(name=f"그룹 {number}"))
        self.engine.log(f"'{item.name}': 그룹 {number} 추가")
        self._after_change(item, select=_gid(len(item.groups) - 1))

    def _add_condition(self) -> None:
        item = self.selected()
        gi = self._target_group()
        if item is None or gi is None or gi >= len(item.groups):
            self.engine.log("조건을 붙일 그룹을 먼저 고르세요.")
            return
        group = item.groups[gi]
        rules = self.engine.profile.rules
        group.conditions.append(
            GroupCondition(rule=rules[0].name if rules else "", action="run")
        )
        if not rules:
            self.engine.log(
                "감지 조건이 없습니다. [조건부 실행] 탭에서 먼저 만들어 주세요."
            )
        self._after_change(item, select=_cid(gi, len(group.conditions) - 1))

    def _delete_selected(self) -> None:
        item = self.selected()
        node = self._selected_node()
        if item is None or node is None:
            return
        kind, idx = node
        try:
            if kind == "g":
                name = item.groups[idx[0]].name
                del item.groups[idx[0]]
                self.engine.log(f"'{item.name}': 그룹 '{name}' 삭제")
                select = _gid(min(idx[0], len(item.groups) - 1)) if item.groups else None
            elif kind == "s":
                del item.groups[idx[0]].steps[idx[1]]
                select = _gid(idx[0])
            else:
                del item.groups[idx[0]].conditions[idx[1]]
                select = _gid(idx[0])
        except IndexError:
            return
        self._after_change(item, select=select)

    def _move(self, delta: int) -> None:
        item = self.selected()
        node = self._selected_node()
        if item is None or node is None:
            return
        kind, idx = node
        try:
            if kind == "g":
                target = self._swap(item.groups, idx[0], delta)
                select = _gid(target) if target is not None else None
            elif kind == "s":
                target = self._swap(item.groups[idx[0]].steps, idx[1], delta)
                select = _sid(idx[0], target) if target is not None else None
            else:
                target = self._swap(item.groups[idx[0]].conditions, idx[1], delta)
                select = _cid(idx[0], target) if target is not None else None
        except IndexError:
            return
        if select is None:
            return
        self._after_change(item, select=select)

    @staticmethod
    def _swap(items: list, index: int, delta: int) -> int | None:
        target = index + delta
        if not (0 <= index < len(items)) or not (0 <= target < len(items)):
            return None
        items[index], items[target] = items[target], items[index]
        return target

    # ------------------------------------------------------------------
    # 다른 기능들을 여는 도구 창
    #
    # 시나리오만 돌리게 되므로 설정도 여기서 다 끝나야 한다. 각 기능의 편집
    # 화면을 새로 만들지 않고, 이미 있는 탭 위젯을 그대로 창에 담아 띄운다.
    # 화면이 한 벌만 존재하니 고칠 일이 생겨도 한 곳만 고치면 된다.
    # ------------------------------------------------------------------
    def _open_tool(self, key: str, title: str, factory, size: str = "980x680"):
        existing = self._tools.get(key)
        if existing is not None and existing[0].winfo_exists():
            existing[0].deiconify()
            existing[0].lift()
            return existing[1]

        window = tk.Toplevel(self.winfo_toplevel())
        window.title(title)
        window.geometry(theme.scale_geometry(size, window))
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PALETTE["bg"])

        widget = factory(window)
        widget.pack(fill="both", expand=True)

        def _close() -> None:
            if hasattr(widget, "commit"):
                widget.commit()
            self._tools.pop(key, None)
            window.destroy()
            # 다른 곳에서 만든 항목이 이 화면에도 바로 보이도록.
            self._reload()

        window.protocol("WM_DELETE_WINDOW", _close)
        self._tools[key] = (window, widget)
        return widget

    def force_reload(self) -> None:
        """[↻ 새로고침] — 지금 보이는 것을 전부 다시 읽어 온다.

        평소에는 알아서 따라가지만(sync_flow), 눌러서 확실히 하고 싶을 때가
        있다. 고르고 있던 자리는 그대로 두고 내용만 다시 그린다.
        """
        node = self.flow.selection()
        item = self.selected()
        self.refresh(select_name=item.name if item else None)
        self.refresh_sources()
        self.refresh_tools()
        item = self.selected()
        if item is not None:
            self._fill_flow(item, select=node[0] if node else None)
        missing = self._missing_targets(item) if item else []
        if missing:
            self.engine.log(
                "새로고침 완료 — 찾지 못한 항목: " + ", ".join(missing)
            )
        else:
            self.engine.log("새로고침 완료 — 모든 항목이 최신입니다.")

    def _missing_targets(self, item: Scenario) -> list[str]:
        """단계가 가리키는데 실제로는 없는 항목들."""
        out = []
        for group in item.groups:
            for step in group.steps:
                if step.kind == "wait" or not step.target:
                    continue
                if self._source_stamp(step) is None:
                    out.append(f"{STEP_LABELS.get(step.kind, step.kind)} '{step.target}'")
        return out

    def _reload(self) -> None:
        item = self.selected()
        if item is not None:
            self._fill_flow(item)
        self.refresh_sources()
        self.refresh_tools()

    def refresh_tools(self) -> None:
        """열려 있는 설정 창들을 최신 상태로 맞춘다.

        프리셋이나 관찰 학습으로 항목이 늘어나도, 창을 열어 둔 채면 목록이 예전
        상태로 남아 있다. 프로필이 바뀌었을 때 같이 불러 준다.
        """
        for key, (window, widget) in list(self._tools.items()):
            if not window.winfo_exists():
                self._tools.pop(key, None)
                continue
            if hasattr(widget, "refresh"):
                try:
                    widget.refresh()
                except Exception as exc:  # noqa: BLE001
                    self.engine.log(f"설정 창 '{key}' 갱신 실패: {exc!r}")

    def close_tools(self) -> None:
        for window, _widget in list(self._tools.values()):
            if window.winfo_exists():
                window.destroy()
        self._tools.clear()

    def open_moves_tool(self):
        from .tab_moves import MovesTab

        return self._open_tool(
            "moves", "대기 중 움직임",
            lambda parent: MovesTab(parent, self.engine),
        )

    def open_repeat_tool(self):
        from .tab_repeat import RepeatTab

        return self._open_tool(
            "repeat", "연타 · 홀드 설정",
            lambda parent: RepeatTab(parent, self.engine),
        )

    def open_path_tool(self):
        from .tab_path import PathTab

        return self._open_tool(
            "path", "이동 경로 설정", lambda parent: PathTab(parent, self.engine)
        )

    def open_macro_tool(self):
        from .tab_macros import MacroTab

        return self._open_tool(
            "macro", "매크로 편집", lambda parent: MacroTab(parent, self.engine),
            size="1040x760",
        )

    def open_rule_tool(self):
        from .tab_pixel import PixelTab

        return self._open_tool(
            "rule", "감지 조건 설정", lambda parent: PixelTab(parent, self.engine)
        )

    def open_buff_tool(self):
        from .tab_buffs import BuffTab

        return self._open_tool(
            "buff", "버프 아이템 설정", lambda parent: BuffTab(parent, self.engine)
        )

    def open_schedule_tool(self):
        from .tab_schedule import ScheduleTab

        return self._open_tool(
            "schedule", "시간 예약 설정",
            lambda parent: ScheduleTab(parent, self.engine),
        )

    def open_observe_tool(self):
        from .tab_observe import ObserveTab

        return self._open_tool(
            "observe", "관찰 학습",
            lambda parent: ObserveTab(parent, self.engine, self._reload),
        )

    def open_preset_tool(self):
        from .tab_presets import PresetTab

        return self._open_tool(
            "preset", "생활 콘텐츠 프리셋",
            lambda parent: PresetTab(parent, self.engine, self._reload),
        )

    def _apply_flow_fonts(self) -> None:
        """흐름 목록의 태그 글꼴. 태그는 스타일을 안 보므로 직접 걸어 준다."""
        self.flow.tag_configure("group", font=theme.BOLD_FONT)

    def refresh_fonts(self) -> None:
        """화면 배율이 바뀌었을 때 스타일로는 안 따라오는 것들을 다시 맞춘다."""
        self._apply_flow_fonts()

    def request_observe_toggle(self) -> None:
        """관찰 핫키 — 창이 닫혀 있으면 열고 나서 토글한다."""
        def _go() -> None:
            tool = self.open_observe_tool()
            tool.toggle_observe()

        self.after(0, _go)

    # ------------------------------------------------------------------
    # 매크로 목록 창 (팝업)
    # ------------------------------------------------------------------
    def open_palette(self) -> None:
        if self.palette is not None and self.palette.winfo_exists():
            self.palette.deiconify()
            self.palette.lift()
            self.palette.refresh()
            return
        self.palette = MacroPalette(self)
        self.palette.refresh()

    def close_palette(self) -> None:
        if self.palette is not None and self.palette.winfo_exists():
            self.palette.destroy()
        self.palette = None

    def refresh_sources(self) -> None:
        if self.palette is not None and self.palette.winfo_exists():
            self.palette.refresh()

    def add_macros(
        self, names: list[str], group_index: int | None = None,
        insert_at: int | None = None, kind: str = "macro",
    ) -> None:
        item = self.selected()
        if item is None or not names:
            return
        if not item.groups:
            item.groups.append(ScenarioGroup(name="그룹 1"))

        gi = group_index if group_index is not None else self._target_group()
        if gi is None or not (0 <= gi < len(item.groups)):
            gi = len(item.groups) - 1
        group = item.groups[gi]

        if insert_at is None:
            node = self._selected_node()
            if node and node[0] == "s" and node[1][0] == gi:
                insert_at = node[1][1] + 1
            else:
                insert_at = len(group.steps)
        insert_at = max(0, min(insert_at, len(group.steps)))

        for offset, name in enumerate(names):
            group.steps.insert(
                insert_at + offset, ScenarioStep(kind=kind, target=name)
            )
        self.engine.log(
            f"'{item.name}' [{group.name}]: {STEP_LABELS.get(kind, kind)} "
            f"{len(names)}개를 {insert_at + 1}번 자리에 담았습니다."
        )
        self._after_change(item, select=_sid(gi, insert_at + len(names) - 1))

    def _add_wait(self) -> None:
        """고른 단계 바로 뒤에 대기 단계를 하나 넣는다."""
        self._insert_bare(
            ScenarioStep(kind="wait", wait_ms=DEFAULT_WAIT_MS),
            f"{DEFAULT_WAIT_MS}ms 대기",
        )

    def _add_fishing(self) -> None:
        """낚시 단계를 하나 넣는다.

        낚시도 대기처럼 담아 둘 항목이 없다 — 설정이 [낚시] 탭에 한 벌뿐이라
        고를 것이 없기 때문이다. 그래서 팔레트가 아니라 버튼으로 만든다.
        """
        self._insert_bare(
            ScenarioStep(kind="fishing", limit_mode=LIMIT_COUNT, repeat_count=10),
            "낚시 10판",
        )

    def _insert_bare(self, step: ScenarioStep, what: str) -> None:
        """담아 둘 항목이 없는 단계(대기·낚시)를 고른 자리 뒤에 넣는다.

        저장해 두는 항목이 아니라서 [매크로 담기] 팔레트에 뜰 것이 없다.
        그래서 버튼으로 바로 만든다.
        """
        item = self.selected()
        if item is None:
            return
        if not item.groups:
            item.groups.append(ScenarioGroup(name="그룹 1"))

        gi = self._target_group()
        if gi is None or not (0 <= gi < len(item.groups)):
            gi = len(item.groups) - 1
        group = item.groups[gi]

        node = self._selected_node()
        if node and node[0] == "s" and node[1][0] == gi:
            at = node[1][1] + 1
        else:
            at = len(group.steps)

        group.steps.insert(at, step)
        self.engine.log(
            f"'{item.name}' [{group.name}]: {at + 1}번 자리에 {what}을(를) "
            "넣었습니다."
        )
        self._after_change(item, select=_sid(gi, at))

    # -- 팝업에서 끌어다 놓기 --------------------------------------------
    def drop_target_at(self, x_root: int, y_root: int) -> tuple[int, int] | None:
        """화면 좌표 → (그룹 index, 넣을 자리). 트리 밖이면 None."""
        item = self.selected()
        if item is None or not self.flow.winfo_ismapped():
            return None
        x = x_root - self.flow.winfo_rootx()
        y = y_root - self.flow.winfo_rooty()
        if not (0 <= x < self.flow.winfo_width() and 0 <= y < self.flow.winfo_height()):
            return None

        row = self.flow.identify_row(y)
        if not row:
            # 빈 아래쪽에 놓으면 마지막 그룹 끝에 붙인다.
            if not item.groups:
                return None
            gi = len(item.groups) - 1
            return (gi, len(item.groups[gi].steps))

        node = parse_node(row)
        if node is None:
            return None
        kind, idx = node
        if kind == "g":
            return (idx[0], len(item.groups[idx[0]].steps))
        if kind == "s":
            return (idx[0], idx[1])
        return (idx[0], len(item.groups[idx[0]].steps))

    def hover_drop(self, x_root: int, y_root: int) -> None:
        self._clear_drop_mark()
        target = self.drop_target_at(x_root, y_root)
        if target is None:
            return
        gi, si = target
        iid = _sid(gi, si) if self.flow.exists(_sid(gi, si)) else _gid(gi)
        if self.flow.exists(iid):
            tags = list(self.flow.item(iid, "tags"))
            if "drop" not in tags:
                tags.append("drop")
            self.flow.item(iid, tags=tuple(tags))
            self._drag_over = iid

    def finish_drop(
        self, x_root: int, y_root: int, names: list[str], kind: str = "macro"
    ) -> bool:
        self._clear_drop_mark()
        target = self.drop_target_at(x_root, y_root)
        if target is None:
            return False
        self.add_macros(
            names, group_index=target[0], insert_at=target[1], kind=kind
        )
        return True

    # ------------------------------------------------------------------
    # 단축키
    # ------------------------------------------------------------------
    def _bind_shortcuts(self) -> None:
        tree = self.flow
        tree.bind("<Delete>", self._on_delete_key)
        for sequence in ("<Control-c>", "<Control-C>"):
            tree.bind(sequence, self._on_copy_key)
        for sequence in ("<Control-x>", "<Control-X>"):
            tree.bind(sequence, self._on_cut_key)
        for sequence in ("<Control-v>", "<Control-V>"):
            tree.bind(sequence, self._on_paste_key)

    def _on_delete_key(self, _e: object) -> str:
        self._delete_selected()
        return "break"

    def _on_copy_key(self, _e: object) -> str:
        self._copy_step()
        return "break"

    def _on_cut_key(self, _e: object) -> str:
        if self._copy_step():
            self._delete_selected()
        return "break"

    def _on_paste_key(self, _e: object) -> str:
        if self._clipboard:
            item = self.selected()
            if item is not None and item.groups:
                gi = self._target_group()
                gi = 0 if gi is None else gi
                group = item.groups[min(gi, len(item.groups) - 1)]
                for step in self._clipboard:
                    group.steps.append(copy.deepcopy(step))
                self._after_change(item, select=_sid(gi, len(group.steps) - 1))
        return "break"

    def _copy_step(self) -> bool:
        item = self.selected()
        node = self._selected_node()
        if item is None or node is None or node[0] != "s":
            return False
        gi, si = node[1]
        try:
            self._clipboard = [copy.deepcopy(item.groups[gi].steps[si])]
        except IndexError:
            return False
        self.engine.log(f"단계 '{self._clipboard[0].label}' 복사")
        return True

    # ------------------------------------------------------------------
    # 끌어서 순서 변경 (같은 부모 안에서만)
    # ------------------------------------------------------------------
    def _bind_drag(self) -> None:
        self.flow.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.flow.bind("<B1-Motion>", self._drag_motion, add="+")
        self.flow.bind("<ButtonRelease-1>", self._drag_drop, add="+")

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_from = self.flow.identify_row(event.y)
        self._drag_active = False
        self._drag_origin_y = event.y

    def _drag_motion(self, event: tk.Event) -> str | None:
        if not self._drag_from:
            return None
        if not self._drag_active and abs(event.y - self._drag_origin_y) < 5:
            return None
        self._drag_active = True

        target = self.flow.identify_row(event.y)
        if target != self._drag_over:
            self._clear_drop_mark()
            if target and target != self._drag_from and self._compatible(target):
                tags = list(self.flow.item(target, "tags"))
                if "drop" not in tags:
                    tags.append("drop")
                self.flow.item(target, tags=tuple(tags))
                self._drag_over = target
        return "break"

    def _compatible(self, target: str) -> bool:
        """같은 종류이고 같은 부모여야 자리를 바꿀 수 있다."""
        src = parse_node(self._drag_from)
        dst = parse_node(target)
        if src is None or dst is None or src[0] != dst[0]:
            return False
        if src[0] == "g":
            return True
        return src[1][0] == dst[1][0]

    def _drag_drop(self, event: tk.Event) -> None:
        source, active = self._drag_from, self._drag_active
        self._clear_drop_mark()
        self._drag_from = ""
        self._drag_active = False
        if not active or not source:
            return
        target = self.flow.identify_row(event.y)
        if not target or target == source or not self._compatible_pair(source, target):
            return
        self._reorder(source, target)

    def _compatible_pair(self, source: str, target: str) -> bool:
        saved = self._drag_from
        self._drag_from = source
        try:
            return self._compatible(target)
        finally:
            self._drag_from = saved

    def _reorder(self, source: str, target: str) -> None:
        item = self.selected()
        src = parse_node(source)
        dst = parse_node(target)
        if item is None or src is None or dst is None:
            return
        kind = src[0]
        try:
            if kind == "g":
                moved = item.groups.pop(src[1][0])
                item.groups.insert(dst[1][0], moved)
                select = _gid(dst[1][0])
            elif kind == "s":
                steps = item.groups[src[1][0]].steps
                moved = steps.pop(src[1][1])
                steps.insert(dst[1][1], moved)
                select = _sid(src[1][0], dst[1][1])
            else:
                conditions = item.groups[src[1][0]].conditions
                moved = conditions.pop(src[1][1])
                conditions.insert(dst[1][1], moved)
                select = _cid(src[1][0], dst[1][1])
        except IndexError:
            return
        self._after_change(item, select=select)

    def _clear_drop_mark(self) -> None:
        if not self._drag_over:
            return
        try:
            tags = [t for t in self.flow.item(self._drag_over, "tags") if t != "drop"]
            self.flow.item(self._drag_over, tags=tuple(tags))
        except tk.TclError:
            pass
        self._drag_over = ""


def _times(step: ScenarioStep, times: int) -> str:
    """이 단계가 얼마나 도는지 한 줄로. 직접 지정한 것은 눈에 띄게."""
    if step.timed:
        return f" {step.limit_seconds:.1f}초 동안"
    if times <= 1:
        return ""
    return f" ×{times}" + ("(지정)" if step.custom_repeat else "")


def _describe_action(condition: GroupCondition) -> str:
    if condition.action == "stop":
        return "→ 시나리오 중지"
    if condition.action == "goto":
        return f"→ '{condition.target or '?'}' 그룹으로 이동 (안 돌아옴)"
    if condition.action == "group":
        return f"→ '{condition.target or '?'}' 그룹 1회 실행 후 복귀"
    if condition.action == "click":
        return "→ 찾은 그림 누르기"
    return f"→ 매크로 '{condition.target or '?'}' 실행"


class MacroPalette(tk.Toplevel):
    """만들어 둔 매크로 목록 창.

    시나리오를 편집하는 동안 옆에 띄워 두고 끌어다 놓는 용도라 **모달이 아니다.**
    grab_set을 걸면 본 창을 만질 수 없어 끌어다 놓기 자체가 불가능해진다.
    """

    def __init__(self, tab: ScenarioTab) -> None:
        super().__init__(tab)
        self.tab = tab
        self.title("담을 항목 고르기")
        self.geometry(theme.scale_geometry("360x460", self))
        self.minsize(theme.px(300), theme.px(300))
        self.transient(tab.winfo_toplevel())
        self.configure(background=theme.PALETTE["bg"])
        self.protocol("WM_DELETE_WINDOW", tab.close_palette)

        self._drag_names: list[str] = []
        self._drag_active = False
        self._drag_origin_y = 0

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            style="Muted.TLabel",
            justify="left",
            text="항목을 흐름 트리의 그룹 위로 끌어다 놓으세요.\n"
            "더블클릭하거나 [담기] 버튼을 눌러도 됩니다.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        picker = ttk.Frame(frame)
        picker.grid(row=0, column=0, sticky="e")
        ttk.Label(picker, text="종류").pack(side="left", padx=(0, 6))
        self.kind_var = tk.StringVar(value=STEP_LABELS["macro"])
        kind_box = ttk.Combobox(
            picker, textvariable=self.kind_var,
            values=[STEP_LABELS[k] for k in ("macro", "repeat", "path", "schedule")],
            width=10, state="readonly",
        )
        kind_box.pack(side="left")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        wrap = ttk.Frame(frame)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.tree = ttk.Treeview(
            wrap, columns=("count", "dur"), show="tree headings", selectmode="extended"
        )
        self.tree.heading("#0", text="매크로")
        self.tree.column("#0", width=170, stretch=True)
        self.tree.heading("count", text="내용")
        self.tree.column("count", width=60, anchor="e", stretch=False)
        self.tree.heading("dur", text="크기")
        self.tree.column("dur", width=60, anchor="e", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        bar.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=bar.set)
        theme.stripe(self.tree)

        self.tree.bind("<Double-1>", lambda _e: self._add())
        self.tree.bind("<Return>", lambda _e: self._add())
        self.tree.bind("<ButtonPress-1>", self._press, add="+")
        self.tree.bind("<B1-Motion>", self._motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._release, add="+")

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="담기", style="Accent.TButton", command=self._add).pack(
            side="left"
        )
        ttk.Button(buttons, text="새로고침", command=self.refresh).pack(side="left", padx=6)
        ttk.Button(buttons, text="닫기", command=tab.close_palette).pack(side="right")

        self.status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.status, style="Faint.TLabel").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )

    # ------------------------------------------------------------------
    @property
    def kind(self) -> str:
        return STEP_KIND_BY_LABEL.get(self.kind_var.get(), "macro")

    def _rows(self) -> list[tuple[str, str, str]]:
        """(이름, 가운데 열, 오른쪽 열)"""
        profile = self.tab.engine.profile
        if self.kind == "repeat":
            return [
                (r.name, r.key, f"{r.interval_ms}ms") for r in profile.repeats
            ]
        if self.kind == "path":
            return [
                (p.name, f"{len(p.steps)}단계", f"×{p.repeat}") for p in profile.paths
            ]
        if self.kind == "schedule":
            from ..tasks import describe_schedule

            return [
                (s.name, describe_schedule(s), s.action_target or "-")
                for s in profile.schedules
            ]
        return [
            (m.name, str(len(m.events)), f"{m.duration:.1f}s")
            for m in profile.macros
        ]

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = self._rows()
        for index, (name, middle, right) in enumerate(rows):
            self.tree.insert(
                "", "end", iid=str(index), text=name,
                values=(middle, right), tags=(theme.row_tag(index),),
            )
        label = STEP_LABELS.get(self.kind, self.kind)
        self.status.set(
            f"{label} {len(rows)}개"
            if rows
            else f"만들어 둔 {label}이(가) 없습니다. [설정 열기]에서 먼저 만드세요."
        )

    def _selected_names(self) -> list[str]:
        rows = self._rows()
        names = []
        for iid in sorted(self.tree.selection(), key=int):
            index = int(iid)
            if 0 <= index < len(rows):
                names.append(rows[index][0])
        return names

    def _add(self) -> None:
        names = self._selected_names()
        if names:
            self.tab.add_macros(names, kind=self.kind)

    # -- 끌어다 놓기 -----------------------------------------------------
    def _press(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        self._drag_names = []
        self._drag_active = False
        self._drag_origin_y = event.y
        if row:
            # 아직 선택 안 된 행을 눌렀다면 그 행만 끄는 것으로 본다.
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self._drag_names = self._selected_names()

    def _motion(self, event: tk.Event) -> str | None:
        if not self._drag_names:
            return None
        if not self._drag_active and abs(event.y - self._drag_origin_y) < 5:
            return None
        self._drag_active = True
        self.tree.configure(cursor="hand2")
        self.tab.hover_drop(event.x_root, event.y_root)
        return "break"

    def _release(self, event: tk.Event) -> None:
        names, active = self._drag_names, self._drag_active
        self._drag_names = []
        self._drag_active = False
        self.tree.configure(cursor="")
        if not active or not names:
            return
        if not self.tab.finish_drop(
            event.x_root, event.y_root, names, kind=self.kind
        ):
            self.status.set("흐름 트리의 그룹 위에 놓아야 담깁니다.")
