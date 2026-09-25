"""탭 — 업적.

일일업적을 매일 자동으로 깨는 것이 목적이다. 화면이 하는 일은 셋이다.

1. **무엇이 있는지 보여 준다** — 일일 · 주간 · 월간 · 특별 카탈로그
2. **무엇으로 깰지 정하게 한다** — 업적마다 매크로 · 시나리오 · 경로 · 연타를 붙인다
3. **단계가 어떻게 늘어나는지 쌓는다** — 실제로 본 값을 적어 두면 다음 단계를 어림한다

**실행은 여기서 하지 않는다.** 붙여 둔 것들로 시나리오 하나를 만들어 주고, 돌리는
일은 시나리오 편집기가 맡는다. 실행 엔진을 두 벌 만들 이유가 없고, 그래야 조건 ·
버프 · 자동 교정 같은 것들이 업적에도 그대로 걸린다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import achievements as ach
from ..model import Scenario, ScenarioGroup, ScenarioStep
from ..model import LIMIT_COUNT as STEP_LIMIT_COUNT
from ..model import LIMIT_ITEM as STEP_LIMIT_ITEM
from ..model import LIMIT_TIME as STEP_LIMIT_TIME
from . import theme
from .widgets import ScrollFrame, get_float, get_int, int_entry

# 만들어 주는 시나리오 이름. 다시 만들면 이 이름의 것을 갈아 끼운다.
SCENARIO_NAME = "일일업적"

AUTO_MARKS = {
    ach.AUTO_YES: "",
    ach.AUTO_LOGIN: "접속 시 자동",
    ach.AUTO_CASH: "현금 결제",
    ach.AUTO_DERIVED: "저절로 오름",
}

# 가이드에 없는 줄임을 표에서 바로 알아보게 한다.
SEEN_MARK = "※"


class AchievementTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine) -> None:
        super().__init__(parent, padding=10)
        self.engine = engine
        self._period = ach.DAILY
        self._plan: ach.Plan | None = None
        self._loading = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # -- 위: 요약 -------------------------------------------------------
        head = ttk.Frame(self)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.summary_var = tk.StringVar(value="")
        ttk.Label(head, textvariable=self.summary_var, style="Heading.TLabel").pack(
            side="left"
        )
        ttk.Button(
            head, text="↻ 새로고침", style="Small.TButton", command=self.refresh
        ).pack(side="right")
        ttk.Button(
            head, text="＋ 시나리오로 만들기", style="Accent.TButton",
            command=self._build_scenario,
        ).pack(side="right", padx=6)
        ttk.Button(
            head, text="오늘 기록 초기화", style="Small.TButton",
            command=self._clear_today,
        ).pack(side="right")

        # -- 가운데: 목록 / 설정 ---------------------------------------------
        # 목록과 설정 칸 사이를 끌어서 조절할 수 있게 한다. 업적이 스물두 개라
        # 목록을 크게 보고 싶을 때와, 단계 기록을 채울 때 원하는 비율이 다르다.
        self.split = ttk.PanedWindow(self, orient="vertical")
        self.split.grid(row=1, column=0, sticky="nsew")
        self._sash_placed = False
        self.split.bind("<Configure>", self._place_sash, add="+")

        self.book = ttk.Notebook(self.split)
        self.book.bind("<<NotebookTabChanged>>", self._on_period_change)

        self.trees: dict[str, ttk.Treeview] = {}
        for period in ach.PERIODS:
            page = ttk.Frame(self.book, padding=8)
            self.book.add(page, text=f"  {ach.PERIOD_LABELS[period]}  ")
            self._build_page(page, period)

        # -- 아래: 고른 업적 설정 --------------------------------------------
        self.editor = ttk.LabelFrame(self.split, text="고른 업적 설정", padding=8)
        self._build_editor(self.editor)

        self.split.add(self.book, weight=3)
        self.split.add(self.editor, weight=2)

        self.refresh()

    # ------------------------------------------------------------------
    def _place_sash(self, _event: object = None) -> None:
        if self._sash_placed:
            return
        height = self.split.winfo_height()
        if height < theme.px(400):
            return
        self._sash_placed = True
        try:
            self.split.sashpos(0, max(theme.px(220), height // 2))
        except tk.TclError:
            pass

    def sash_value(self) -> int:
        if not self._sash_placed:
            return 0
        try:
            return int(self.split.sashpos(0))
        except tk.TclError:
            return 0

    def reset_sash(self) -> None:
        self._sash_placed = False
        self._place_sash()

    # ------------------------------------------------------------------
    def _build_page(self, page: ttk.Frame, period: str) -> None:
        page.rowconfigure(1, weight=1)
        page.columnconfigure(0, weight=1)

        note = {
            ach.DAILY: "매일 새벽 4시에 초기화됩니다. 아래에서 업적마다 무엇으로 깰지 "
                       "정하고, 위 [시나리오로 만들기]를 누르면 순서대로 도는 "
                       "시나리오가 생깁니다.",
            ach.WEEKLY: "매주 월요일에 초기화됩니다. 주간업적은 대부분 일일업적을 "
                        "하다 보면 저절로 오릅니다.",
            ach.MONTHLY: "매월 1일에 초기화됩니다. 일일·주간을 꾸준히 하면 따라옵니다.",
            ach.SPECIAL: "기간 제한이 없습니다. 반복 업적은 보상을 받으면 초기화됩니다. "
                         "공식 가이드에 표가 없어, 화면에서 본 것만 담아 두었습니다.",
        }[period]
        ttk.Label(
            page, style="Faint.TLabel", justify="left", wraplength=900, text=note
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        wrap = ttk.Frame(page)
        wrap.grid(row=1, column=0, sticky="nsew")

        columns = ("use", "rp", "title", "stage", "need", "run", "reward")
        tree = ttk.Treeview(
            wrap, columns=columns, show="headings", selectmode="browse", height=12
        )
        for cid, text, width, anchor in (
            ("use", "자동", 44, "center"),
            ("rp", "RP", 44, "e"),
            ("title", "업적", 210, "w"),
            ("stage", "단계", 56, "center"),
            ("need", "전부 깨려면", 84, "e"),
            ("run", "무엇으로 깨나", 200, "w"),
            ("reward", "보상", 200, "w"),
        ):
            tree.heading(cid, text=text, anchor=anchor)
            tree.column(cid, width=theme.px(width), anchor=anchor,
                        stretch=cid in ("title", "run", "reward"))
        tree.grid(row=0, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=bar.set)
        theme.stripe(tree)
        tree.tag_configure("off", foreground=theme.PALETTE["faint"])
        tree.tag_configure("on", foreground=theme.PALETTE["accent"])
        tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        # 자동 칸을 눌러 바로 켜고 끌 수 있게 한다. 스무 개를 하나씩 열어
        # 체크하는 것보다 목록에서 바로 누르는 편이 빠르다.
        tree.bind("<Button-1>", self._on_click, add="+")
        self.trees[period] = tree

    # ------------------------------------------------------------------
    def _build_editor(self, box: ttk.Frame) -> None:
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        scroller = ScrollFrame(box)
        scroller.grid(row=0, column=0, sticky="nsew")
        body = scroller.inner
        body.columnconfigure(1, weight=1)
        self._editor_body = body

        self.title_var = tk.StringVar(value="업적을 고르세요")
        ttk.Label(body, textvariable=self.title_var, style="Title.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        self.spec_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.spec_var, style="Muted.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(2, 8)
        )

        # -- 자동화 --------------------------------------------------------
        self.enabled_var = tk.BooleanVar(value=False)
        self.enable_box = ttk.Checkbutton(
            body, text="오늘 이 업적을 자동으로 깬다", variable=self.enabled_var,
            command=self._apply,
        )
        self.enable_box.grid(row=2, column=0, columnspan=4, sticky="w")

        run = ttk.Frame(body)
        run.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(run, text="무엇으로").pack(side="left", padx=(0, 6))
        self.kind_var = tk.StringVar(value=ach.RUN_LABELS["macro"])
        kind_box = ttk.Combobox(
            run, textvariable=self.kind_var, values=list(ach.RUN_LABELS.values()),
            width=10, state="readonly",
        )
        kind_box.pack(side="left")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._on_kind_change())

        self.target_var = tk.StringVar(value="")
        self.target_box = ttk.Combobox(
            run, textvariable=self.target_var, width=28, state="readonly"
        )
        self.target_box.pack(side="left", padx=(8, 0))
        self.target_box.bind("<<ComboboxSelected>>", lambda _e: self._apply())

        limit = ttk.Frame(body)
        limit.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(limit, text="얼마나").pack(side="left", padx=(0, 6))
        self.limit_var = tk.StringVar(value=ach.LIMIT_LABELS[ach.LIMIT_ALL])
        limit_box = ttk.Combobox(
            limit, textvariable=self.limit_var,
            values=list(ach.LIMIT_LABELS.values()), width=24, state="readonly",
        )
        limit_box.pack(side="left")
        limit_box.bind("<<ComboboxSelected>>", lambda _e: self._on_limit_change())

        self.count_var = tk.StringVar(value="1")
        self.count_entry = int_entry(limit, self.count_var, width=7)
        self.count_entry.pack(side="left", padx=(8, 2))
        self.count_unit = ttk.Label(limit, text="회")
        self.count_unit.pack(side="left")

        self.minutes_var = tk.StringVar(value="5")
        self.minutes_entry = ttk.Entry(limit, textvariable=self.minutes_var, width=7)
        self.minutes_entry.pack(side="left", padx=(8, 2))
        ttk.Label(limit, text="분").pack(side="left")

        self.limit_hint = ttk.Label(
            body, style="Faint.TLabel", justify="left", wraplength=900
        )
        self.limit_hint.grid(row=5, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # -- 단계 기록 ------------------------------------------------------
        stages = ttk.LabelFrame(body, text="단계 기록", padding=8)
        stages.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        stages.columnconfigure(1, weight=1)

        ttk.Label(
            stages,
            style="Faint.TLabel",
            justify="left",
            wraplength=880,
            text="필요 수는 누적입니다 — 농작물 수확은 1단계 35, 5단계 550인데 "
            "550을 채우면 다섯 단계가 전부 깨집니다. 그래서 마지막 단계 값 하나만 "
            "알면 자동화가 됩니다. 아래 값은 공식 가이드의 표에서 가져온 것이라 "
            "보통은 그대로 두면 됩니다. 게임이 바뀌어 숫자가 다르면, 화면에 보이는 "
            "값을 여기에 적어 주세요 — 적어 둔 값이 가이드 값보다 먼저입니다.",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        table = ttk.Frame(stages)
        table.grid(row=1, column=0, sticky="w")
        self.stage_tree = ttk.Treeview(
            table, columns=("stage", "rp", "need", "delta", "day"), show="headings",
            selectmode="browse", height=6,
        )
        for cid, text, width, anchor in (
            ("stage", "단계", 60, "center"),
            ("rp", "RP", 55, "e"),
            ("need", "누적 필요", 85, "e"),
            ("delta", "이 단계에서 더", 105, "e"),
            ("day", "적은 날", 105, "center"),
        ):
            self.stage_tree.heading(cid, text=text, anchor=anchor)
            self.stage_tree.column(cid, width=theme.px(width), anchor=anchor)
        self.stage_tree.pack(side="left")
        self.stage_tree.tag_configure("guess", foreground=theme.PALETTE["muted"])
        self.stage_tree.tag_configure("unknown", foreground=theme.PALETTE["faint"])

        add = ttk.Frame(stages)
        add.grid(row=1, column=1, sticky="nw", padx=(14, 0))
        ttk.Label(add, text="화면에 보이는 값을 적으세요", style="Muted.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6)
        )
        ttk.Label(add, text="단계").grid(row=1, column=0, sticky="w", padx=(0, 4))
        self.s_stage = tk.StringVar(value="1")
        int_entry(add, self.s_stage, width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(add, text="RP").grid(row=1, column=2, sticky="w", padx=(10, 4))
        self.s_rp = tk.StringVar(value="10")
        int_entry(add, self.s_rp, width=5).grid(row=1, column=3, sticky="w")
        ttk.Label(add, text="누적 필요").grid(row=1, column=4, sticky="w", padx=(10, 4))
        self.s_need = tk.StringVar(value="70")
        int_entry(add, self.s_need, width=7).grid(row=1, column=5, sticky="w")

        buttons = ttk.Frame(add)
        buttons.grid(row=2, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(
            buttons, text="기록", style="Small.TButton", command=self._record_stage
        ).pack(side="left")
        ttk.Button(
            buttons, text="고른 단계 삭제", style="Small.TButton",
            command=self._delete_stage,
        ).pack(side="left", padx=6)

        self.stage_hint = ttk.Label(
            stages, style="Muted.TLabel", justify="left", wraplength=880
        )
        self.stage_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # -- 오늘 상태 / 메모 ------------------------------------------------
        bottom = ttk.Frame(body)
        bottom.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Label(bottom, text="지금 단계").pack(side="left", padx=(0, 6))
        self.now_stage_var = tk.StringVar(value="1")
        entry = int_entry(bottom, self.now_stage_var, width=5)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _e: self._apply())
        ttk.Label(
            bottom, style="Faint.TLabel",
            text="화면의 (1/5)에서 앞의 숫자입니다. 오늘 어디까지 올렸는지 적어 두면 "
                 "필요 수를 그 단계 값으로 보여 줍니다.",
        ).pack(side="left", padx=(8, 0))

        memo = ttk.Frame(body)
        memo.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(memo, text="메모").pack(side="left", padx=(0, 6))
        self.note_var = tk.StringVar(value="")
        note_entry = ttk.Entry(memo, textvariable=self.note_var, width=60)
        note_entry.pack(side="left", fill="x", expand=True)
        note_entry.bind("<KeyRelease>", lambda _e: self._apply())

        self.done_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.done_var, style="Ok.TLabel").grid(
            row=9, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )

    # ------------------------------------------------------------------
    # 목록
    # ------------------------------------------------------------------
    def _plans(self) -> list[ach.Plan]:
        return self.engine.profile.achievements

    def _on_period_change(self, _event: object = None) -> None:
        index = self.book.index(self.book.select())
        self._period = ach.PERIODS[index] if index < len(ach.PERIODS) else ach.DAILY
        self._fill(self._period)
        self._show(None)

    def refresh(self) -> None:
        for period in ach.PERIODS:
            self._fill(period)
        self._sync_summary()
        self._show(self._plan)

    def _sync_summary(self) -> None:
        info = ach.summarize(self._plans(), self._period)
        left = ach.describe_remaining(ach.period_seconds_to_reset(self._period))
        text = (
            f"{ach.PERIOD_LABELS[self._period]} {info['total']}개 · "
            f"자동화 가능 {info['automatable']}개 · 지정함 {info['picked']}개"
        )
        if info["goal"]:
            text += f" · 계획 RP {info['rp']}/{info['goal']}"
        if self._period != ach.SPECIAL:
            text += f"   ({ach.PERIOD_RESETS[self._period]} · 남은 시간 {left})"
        if info["unknown"]:
            text += f"   ⚠ 단계 값을 모르는 곳 {info['unknown']}군데"
        if any(s.source != ach.SRC_GUIDE for s in ach.CATALOG[self._period]):
            text += f"   ({SEEN_MARK} 표시는 공식 가이드에 없는 업적)"
        self.summary_var.set(text)

    def _fill(self, period: str) -> None:
        tree = self.trees[period]
        keep = tree.selection()
        tree.delete(*tree.get_children())
        plans = self._plans()
        for index, spec in enumerate(ach.CATALOG[period]):
            plan = ach.find_plan(plans, period, spec.title)
            if plan is None:
                plan = ach.Plan(period=period, title=spec.title)
            stage = max(1, plan.stage)
            rp, _cum, _real = plan.effective(stage, spec)
            # 필요 수는 누적이라, 목록에는 '전부 깨는 데 필요한 양'을 보여 준다.
            # 그 숫자 하나면 자동화가 되고, 중간 단계는 몰라도 상관없다.
            need = plan.total_needed(spec)

            saved = ach.find_plan(plans, period, spec.title)
            plan = saved if saved is not None else plan
            mark = AUTO_MARKS[spec.auto]
            if spec.auto != ach.AUTO_YES:
                use = "—"
                run = mark
                tags = ("off",)
            elif saved is not None and saved.ready():
                use = "☑"
                run = f"{ach.RUN_LABELS[plan.kind]}: {plan.target_name}"
                tags = ("on",)
            elif saved is not None and saved.enabled:
                use = "☑"
                run = "⚠ 무엇으로 깰지 안 정했습니다"
                tags = ("off",)
            else:
                use = "☐"
                run = ""
                tags = ()

            if saved is not None and saved.done_today():
                use = "✔"
                run = (run + "  · 오늘 완료").strip()

            tree.insert(
                "", "end", iid=str(index),
                values=(
                    use,
                    rp or "-",
                    (SEEN_MARK + " " if spec.source != ach.SRC_GUIDE else "") + spec.title,
                    f"{stage}/{spec.stages}" if spec.staged else "-",
                    f"{need:,}" if need else "?",
                    run,
                    spec.reward,
                ),
                tags=tags + (theme.row_tag(index),),
            )
        for iid in keep:
            if tree.exists(iid):
                tree.selection_set(iid)

    def _selected_spec(self) -> ach.Spec | None:
        tree = self.trees[self._period]
        selection = tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        specs = ach.CATALOG[self._period]
        return specs[index] if 0 <= index < len(specs) else None

    def _on_click(self, event: tk.Event) -> None:
        """자동 칸을 누르면 바로 켜고 끈다."""
        tree = self.trees[self._period]
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) != "#1":
            return
        row = tree.identify_row(event.y)
        if not row:
            return
        specs = ach.CATALOG[self._period]
        index = int(row)
        if not (0 <= index < len(specs)):
            return
        spec = specs[index]
        if spec.auto != ach.AUTO_YES:
            self.engine.log(f"'{spec.title}'은 {AUTO_MARKS[spec.auto]}라 자동화 대상이 아닙니다.")
            return
        plan = ach.ensure_plan(self._plans(), self._period, spec.title)
        plan.enabled = not plan.enabled
        tree.selection_set(row)
        self._fill(self._period)
        self._sync_summary()
        self._show(plan)

    def _on_select(self) -> None:
        spec = self._selected_spec()
        if spec is None:
            self._show(None)
            return
        plan = ach.find_plan(self._plans(), self._period, spec.title)
        if plan is None:
            plan = ach.Plan(period=self._period, title=spec.title)
        self._show(plan)

    # ------------------------------------------------------------------
    # 설정 칸
    # ------------------------------------------------------------------
    def _show(self, plan: ach.Plan | None) -> None:
        self._plan = plan
        spec = ach.spec_for(plan.period, plan.title) if plan else None
        self._loading = True
        try:
            if plan is None or spec is None:
                self.title_var.set("업적을 고르세요")
                self.spec_var.set("")
                self.done_var.set("")
                self.stage_hint.configure(text="")
                self.limit_hint.configure(text="")
                self.stage_tree.delete(*self.stage_tree.get_children())
                self._set_editor_state(False)
                return

            self.title_var.set(f"[{ach.PERIOD_LABELS[plan.period][:2]}] {spec.title}")
            parts = [f"보상 {spec.reward}"]
            if spec.staged:
                parts.append(f"{spec.stages}단계")
            parts.append(f"1단계 {spec.how_at(1)} · RP {spec.rp}")
            whole = plan.total_needed(spec)
            parts.append(
                f"전부 깨려면 누적 {whole:,} (RP {spec.total_rp})"
                if whole else "전부 깨는 데 필요한 양은 아직 모름"
            )
            if spec.source != ach.SRC_GUIDE:
                parts.append("공식 가이드에 없음")
            if spec.note:
                parts.append(spec.note)
            self.spec_var.set("  ·  ".join(parts))

            usable = spec.auto == ach.AUTO_YES
            self._set_editor_state(usable)
            self.enabled_var.set(bool(plan.enabled))
            self.kind_var.set(ach.RUN_LABELS.get(plan.kind, ach.RUN_LABELS["macro"]))
            self._refresh_targets(plan.kind)
            self.target_var.set(plan.target_name)
            self.limit_var.set(ach.LIMIT_LABELS.get(plan.limit_mode,
                                                    ach.LIMIT_LABELS[ach.LIMIT_ALL]))
            self.count_var.set(str(max(1, plan.repeat_count)))
            self.minutes_var.set(f"{max(0.1, plan.minutes):g}")
            self.now_stage_var.set(str(max(1, plan.stage)))
            self.note_var.set(plan.note)
            self.done_var.set(
                "오늘 이미 끝냈습니다 — [오늘 기록 초기화]를 누르면 다시 돌립니다."
                if plan.done_today() else ""
            )
            self._fill_stages(plan, spec)
            self._sync_limit(plan, spec)
        finally:
            self._loading = False

    def _set_editor_state(self, on: bool) -> None:
        state = "normal" if on else "disabled"
        self.enable_box.configure(state=state)
        for widget in (self.count_entry, self.minutes_entry):
            widget.configure(state=state)
        self.target_box.configure(state="readonly" if on else "disabled")

    def _refresh_targets(self, kind: str) -> None:
        profile = self.engine.profile
        names = {
            "macro": [m.name for m in profile.macros],
            "scenario": [s.name for s in profile.scenarios if s.name != SCENARIO_NAME],
            "path": [p.name for p in profile.paths],
            "repeat": [r.name for r in profile.repeats],
        }.get(kind, [])
        self.target_box.configure(values=names)

    def _on_kind_change(self) -> None:
        kind = _key_of(ach.RUN_LABELS, self.kind_var.get(), "macro")
        self._refresh_targets(kind)
        self.target_var.set("")
        self._apply()

    def _on_limit_change(self) -> None:
        self._apply()
        if self._plan is not None:
            self._sync_limit(self._plan, ach.spec_for(self._plan.period, self._plan.title))

    def _sync_limit(self, plan: ach.Plan, spec: ach.Spec | None) -> None:
        mode = plan.limit_mode
        self.count_entry.configure(state="normal" if mode == ach.LIMIT_COUNT else "disabled")
        self.minutes_entry.configure(state="normal" if mode == ach.LIMIT_TIME else "disabled")
        if mode == ach.LIMIT_ALL:
            need = plan.total_needed(spec)
            if need:
                self.limit_hint.configure(
                    text=f"마지막 단계의 누적 필요 수는 {need}입니다. 필요 수는 "
                         "누적이라 이만큼 채우면 아래 단계도 함께 깨집니다 — "
                         "한 번 돌 때 1씩 오른다고 볼 때의 이야기이고, 한 번에 여러 개 "
                         "오르는 업적이면 [정한 횟수만큼]으로 바꾸세요."
                )
            else:
                self.limit_hint.configure(
                    text="⚠ 마지막 단계의 누적 필요 수를 모릅니다. 아래 [단계 기록]에 "
                         "그 값만 적어 두면 됩니다 (중간 단계는 몰라도 됩니다)."
                )
        elif mode == ach.LIMIT_STAGE:
            delta = plan.increment(max(1, plan.stage), spec)
            if delta is not None:
                self.limit_hint.configure(
                    text=f"{plan.stage}단계 하나를 올리는 데 {delta}가 더 필요합니다 "
                         "(그 단계 누적값 − 앞 단계 누적값)."
                )
            else:
                self.limit_hint.configure(
                    text="⚠ 앞 단계의 누적값을 몰라 '더 해야 하는 양'을 낼 수 없습니다. "
                         "[전부 깨는 데 필요한 만큼]을 쓰거나 앞 단계를 기록하세요."
                )
        elif mode == ach.LIMIT_COUNT:
            self.limit_hint.configure(
                text="붙여 둔 것을 이 횟수만큼 돌립니다. 한 번에 여러 개가 오르는 "
                     "업적(사냥 매크로 한 바퀴에 여러 마리)에 알맞습니다."
            )
        else:
            self.limit_hint.configure(
                text="정한 시간 동안 돌리고 넘어갑니다. 몇 번 도는지 셀 수 없는 "
                     "것(낚시처럼 대기가 긴 것)에 알맞습니다."
            )

    def _fill_stages(self, plan: ach.Plan, spec: ach.Spec) -> None:
        self.stage_tree.delete(*self.stage_tree.get_children())
        total = spec.stages if spec.staged else 1
        got = plan.points(spec)
        for stage in range(1, total + 1):
            if stage in got:
                rp, need, real = got[stage]
                record = plan.known(stage)
                if record is not None:
                    day, tag = (record.day or "-"), ""
                else:
                    day, tag = "카탈로그", "guess"
                delta = plan.increment(stage, spec)
                self.stage_tree.insert(
                    "", "end", iid=str(stage),
                    values=(f"{stage}/{total}", rp or "?", need,
                            delta if delta is not None else "?", day),
                    tags=(tag,) if tag else (),
                )
                continue
            rp, need = plan.predict(stage, spec)
            tag, day = ("guess", "어림") if need is not None else ("unknown", "모름")
            self.stage_tree.insert(
                "", "end", iid=str(stage),
                values=(f"{stage}/{total}", rp if rp is not None else "?",
                        need if need is not None else "?", "?", day),
                tags=(tag,),
            )

        missing = plan.missing_stages(spec)
        whole = plan.total_needed(spec)
        if whole:
            head = f"전부 깨려면 누적 {whole}. 이 숫자 하나면 자동화가 됩니다."
        else:
            head = (
                f"⚠ 마지막 단계({total}단계)의 누적 필요 수를 모릅니다. "
                "그 값만 적어 두면 전부 깨기가 가능합니다."
            )
        if not missing:
            self.stage_hint.configure(text=f"✔ 모든 단계를 기록했습니다. {head}")
            return
        highest = max(got, default=0)
        rp, need = plan.predict(highest + 1, spec)
        guess = ""
        if need is not None:
            guess = (
                f"  기록으로 미루어 {highest + 1}단계는 RP {rp}, "
                f"누적 {need}쯤으로 보입니다."
            )
        self.stage_hint.configure(
            text=f"{head}\n아직 모르는 단계: {', '.join(str(s) for s in missing)}."
                 f" 게임에서 그 단계에 올랐을 때 값을 적어 주세요.{guess}"
        )

    # ------------------------------------------------------------------
    def _apply(self) -> None:
        if self._loading or self._plan is None:
            return
        spec = ach.spec_for(self._plan.period, self._plan.title)
        if spec is None or spec.auto != ach.AUTO_YES:
            return
        # 손을 댄 순간 프로필에 붙인다. 그 전까지는 임시 객체였다.
        plan = ach.ensure_plan(self._plans(), self._plan.period, self._plan.title)
        self._plan = plan
        plan.enabled = bool(self.enabled_var.get())
        plan.kind = _key_of(ach.RUN_LABELS, self.kind_var.get(), "macro")
        plan.target_name = self.target_var.get().strip()
        plan.limit_mode = _key_of(ach.LIMIT_LABELS, self.limit_var.get(),
                                  ach.LIMIT_ALL)
        plan.repeat_count = max(1, get_int(self.count_var, 1))
        plan.minutes = max(0.1, get_float(self.minutes_var, 5.0))
        plan.stage = max(1, get_int(self.now_stage_var, 1))
        plan.note = self.note_var.get().strip()
        self._fill(self._period)
        self._sync_summary()
        self._sync_limit(plan, spec)

    def _record_stage(self) -> None:
        if self._plan is None:
            return
        spec = ach.spec_for(self._plan.period, self._plan.title)
        if spec is None:
            return
        stage = max(1, get_int(self.s_stage, 1))
        if spec.staged and stage > spec.stages:
            messagebox.showwarning(
                "단계 범위",
                f"'{spec.title}'은 {spec.stages}단계까지입니다.",
                parent=self,
            )
            return
        plan = ach.ensure_plan(self._plans(), self._plan.period, self._plan.title)
        self._plan = plan
        plan.record(stage, max(0, get_int(self.s_rp, 0)), max(0, get_int(self.s_need, 0)))
        self.engine.log(
            f"업적 '{plan.title}' {stage}단계 기록: RP {self.s_rp.get()} · "
            f"필요 {self.s_need.get()}"
        )
        self._fill_stages(plan, spec)
        self._fill(self._period)
        self._sync_summary()
        self._sync_limit(plan, spec)

    def _delete_stage(self) -> None:
        if self._plan is None:
            return
        selection = self.stage_tree.selection()
        if not selection:
            return
        stage = int(selection[0])
        before = len(self._plan.stages)
        self._plan.stages = [s for s in self._plan.stages if s.stage != stage]
        if len(self._plan.stages) != before:
            spec = ach.spec_for(self._plan.period, self._plan.title)
            self._fill_stages(self._plan, spec)
            self._fill(self._period)
            self._sync_summary()

    def _clear_today(self) -> None:
        cleared = 0
        for plan in self._plans():
            if plan.done_day:
                plan.done_day = ""
                cleared += 1
        self.engine.log(f"업적 오늘 기록 {cleared}개를 지웠습니다.")
        self.refresh()

    # ------------------------------------------------------------------
    # 시나리오 만들기
    # ------------------------------------------------------------------
    def _build_scenario(self) -> None:
        """켜 둔 일일업적으로 시나리오 하나를 만든다.

        업적마다 그룹 하나다. 그래야 시나리오 편집기에서 순서를 바꾸거나 특정
        업적만 빼는 것을 손으로 할 수 있고, 그룹마다 버프·조건도 따로 걸 수 있다.
        """
        plans = ach.daily_queue(self._plans())
        if not plans:
            messagebox.showinfo(
                "만들 것이 없습니다",
                "자동으로 깰 일일업적을 먼저 고르고, 무엇으로 깰지 정해 주세요.\n\n"
                "목록의 [자동] 칸을 눌러 켜면 됩니다.",
                parent=self,
            )
            return

        groups: list[ScenarioGroup] = []
        skipped: list[str] = []
        for plan in plans:
            spec = ach.spec_for(ach.DAILY, plan.title)
            step = ScenarioStep(kind=plan.kind, target=plan.target_name, delay_ms=-1)
            if plan.limit_mode == ach.LIMIT_COUNT:
                step.limit_mode = STEP_LIMIT_COUNT
                step.repeat_count = plan.repeat_count
            elif plan.limit_mode == ach.LIMIT_TIME:
                step.limit_mode = STEP_LIMIT_TIME
                step.limit_seconds = max(0.1, plan.minutes * 60.0)
            elif plan.limit_mode == ach.LIMIT_STAGE:
                need = plan.increment(max(1, plan.stage), spec)
                if not need:
                    skipped.append(plan.title)
                    continue
                step.limit_mode = STEP_LIMIT_COUNT
                step.repeat_count = int(need)
            else:
                # 누적이므로 마지막 단계 값 하나면 전부 깨진다.
                need = plan.total_needed(spec)
                if not need:
                    skipped.append(plan.title)
                    continue
                step.limit_mode = STEP_LIMIT_COUNT
                step.repeat_count = int(need)
            groups.append(
                ScenarioGroup(name=plan.title, repeat=1, interval_ms=500, steps=[step])
            )

        if not groups:
            messagebox.showwarning(
                "만들 수 없습니다",
                "고른 업적 모두 필요 수를 알 수 없습니다.\n"
                "[단계 기록]에 값을 적거나 [정한 횟수만큼]으로 바꿔 주세요.",
                parent=self,
            )
            return

        scenarios = self.engine.profile.scenarios
        existing = next((s for s in scenarios if s.name == SCENARIO_NAME), None)
        if existing is not None:
            if not messagebox.askyesno(
                "다시 만들기",
                f"시나리오 '{SCENARIO_NAME}'이(가) 이미 있습니다.\n"
                "지금 설정으로 새로 만들까요? 기존 내용은 사라집니다.",
                parent=self,
            ):
                return
            # 조건·버프처럼 손으로 붙여 둔 것이 있으면 첫 그룹에 옮겨 살린다.
            keep = existing.groups[0] if existing.groups else None
            if keep is not None and (keep.buffs or keep.conditions):
                groups[0].buffs = list(keep.buffs)
                groups[0].conditions = list(keep.conditions)
                groups[0].buff_margin_s = keep.buff_margin_s
            scenarios.remove(existing)

        scenario = Scenario(name=SCENARIO_NAME, repeat=1, interval_ms=1000)
        scenario.groups = groups
        scenarios.append(scenario)
        self.engine.rebind_hotkeys()

        message = f"시나리오 '{SCENARIO_NAME}'을(를) 만들었습니다 — 그룹 {len(groups)}개."
        if skipped:
            message += f"\n\n필요 수를 몰라 뺀 것: {', '.join(skipped)}"
        self.engine.log(message.replace("\n\n", " / "))
        messagebox.showinfo(
            "만들었습니다",
            message + "\n\n[시나리오 편집기] 탭에서 순서를 다듬고 실행하세요.",
            parent=self,
        )
        # 편집기가 새 시나리오를 바로 보도록 알린다.
        top = self.winfo_toplevel()
        if hasattr(top, "_refresh_all"):
            top._refresh_all()


def _key_of(labels: dict, value: str, fallback: str) -> str:
    for key, text in labels.items():
        if text == value:
            return key
    return fallback
