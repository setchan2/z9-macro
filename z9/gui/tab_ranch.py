"""[목장] 탭 — 시나리오를 옮겨 와 한 바퀴씩 돌리고, 바퀴마다 피로도를 본다.

돌아가는 차례는 z9/ranch.py 에 적혀 있다. 여기서는 그 차례에 필요한 것들을
정한다: 가져올 시나리오, 8 · 9번 버프(이름 · 재사용 대기), 피로도 조건과 매크로.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import theme
from .widgets import ScrollFrame, get_float

# 목장 탭을 처음 열 때 설정이 비어 있으면 이 시나리오를 가져온다.
DEFAULT_SCENARIO = "[Verson 1.0] 투목"


class RanchTab(ScrollFrame):
    INTRO = (
        "시나리오 편집기에서 짜 둔 시나리오를 그대로 옮겨 와 돌립니다.\n"
        "⓪ 처음에 게임(지구별) 창을 앞으로  →  ① 버프 (재사용 대기가 끝난 것만, "
        "[Esc] → 버프 키 → [Esc])  →  ② 그룹 한 바퀴  →  ③ 피로도 확인 — 가득이면 "
        "정해 둔 매크로 한 번  →  다시 ①"
    )

    def __init__(self, master: tk.Misc, engine) -> None:
        super().__init__(master)
        self.engine = engine
        self._loading = False
        inner = self.inner
        inner.columnconfigure(0, weight=1)

        self.pick_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.escgap_var = tk.StringVar()
        self.bgap_var = tk.StringVar()
        self.fon_var = tk.BooleanVar(value=True)
        self.frule_var = tk.StringVar()
        self.fmacro_var = tk.StringVar()
        self.fover_var = tk.StringVar()
        self.eon_var = tk.BooleanVar(value=False)
        self.en_var = tk.StringVar()
        self.emacro_var = tk.StringVar()
        self.ready_var = tk.StringVar()

        row = 0
        ttk.Label(inner, text="목장", style="Title.TLabel").grid(
            row=row, column=0, sticky="w")
        row += 1
        ttk.Label(inner, style="Faint.TLabel", justify="left",
                  wraplength=theme.px(760), text=self.INTRO).grid(
            row=row, column=0, sticky="w", pady=(4, 10))

        # -- ① 시나리오 ----------------------------------------------------
        row += 1
        flow = ttk.LabelFrame(inner, text="시나리오 (한 바퀴)", padding=theme.pad(8))
        flow.grid(row=row, column=0, sticky="ew")
        line = ttk.Frame(flow)
        line.grid(row=0, column=0, sticky="w")
        ttk.Label(line, text="가져올 시나리오").pack(side="left", padx=(0, 6))
        self.pick_box = ttk.Combobox(
            line, textvariable=self.pick_var, width=30, state="readonly",
            postcommand=lambda: self.pick_box.configure(
                values=[s.name for s in self.engine.profile.scenarios]))
        self.pick_box.pack(side="left")
        ttk.Button(line, text="가져오기", style="Small.TButton",
                   command=self._take).pack(side="left", padx=(8, 0))
        ttk.Label(flow, textvariable=self.source_var, justify="left",
                  wraplength=theme.px(730)).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            flow, style="Faint.TLabel", justify="left", wraplength=theme.px(730),
            text=("복사해 두는 것이라 시나리오 편집기에서 원본을 고쳐도 여기는 "
                  "그대로입니다. 고친 것을 쓰려면 [가져오기]를 다시 누르세요.\n"
                  "그룹의 반복 횟수만큼 돌면 한 바퀴입니다 (무한이면 한 번). "
                  "조건부 그룹은 쓰지 않습니다.")
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

        # -- ② 버프 --------------------------------------------------------
        row += 1
        buffs = ttk.LabelFrame(inner, text="버프 (시작 전)", padding=theme.pad(8))
        buffs.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            buffs, style="Faint.TLabel", justify="left", wraplength=theme.px(730),
            text=("바퀴를 시작하기 전에, 재사용 대기가 끝난 버프만 씁니다. "
                  "버프마다 [Esc] → 버프 키 → [Esc]로 누릅니다.\n"
                  "처음 시작할 때는 바로 쓰고, 그 뒤로는 재사용 대기(분)마다 "
                  "씁니다. 껐다 켜도 남은 시간이 이어집니다.")
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        for col, text in enumerate(("켬", "키", "이름", "재사용 대기(분)",
                                    "다음 사용")):
            ttk.Label(buffs, text=text, style="Faint.TLabel").grid(
                row=1, column=col, sticky="w", padx=(0, 8))
        self.buff_rows = [self._buff_row(buffs, i + 2, i)
                          for i in range(len(self.engine.profile.ranch.buffs))]
        gaps = ttk.Frame(buffs)
        gaps.grid(row=2 + len(self.buff_rows), column=0, columnspan=6,
                  sticky="w", pady=(8, 0))
        ttk.Label(gaps, text="[Esc] ↔ 버프 키 간격").pack(side="left", padx=(0, 4))
        ttk.Entry(gaps, textvariable=self.escgap_var, width=5).pack(side="left")
        ttk.Label(gaps, text="초 · 버프 사이").pack(side="left", padx=(3, 4))
        ttk.Entry(gaps, textvariable=self.bgap_var, width=5).pack(side="left")
        ttk.Label(gaps, text="초").pack(side="left", padx=(3, 12))
        ttk.Button(gaps, text="버프만 해보기", style="Small.TButton",
                   command=lambda: self._try("buffs")).pack(side="left")

        # -- ③ 피로도 ------------------------------------------------------
        row += 1
        tired = ttk.LabelFrame(inner, text="피로도 (바퀴마다)", padding=theme.pad(8))
        tired.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(tired, text="한 바퀴 끝날 때마다 피로도 확인하기",
                        variable=self.fon_var, command=self._save).grid(
            row=0, column=0, sticky="w")
        line = ttk.Frame(tired)
        line.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(line, text="피로도 조건").pack(side="left", padx=(0, 4))
        rule_box = ttk.Combobox(
            line, textvariable=self.frule_var, width=20, state="readonly",
            postcommand=lambda: rule_box.configure(
                values=[r.name for r in self.engine.profile.rules]))
        rule_box.pack(side="left")
        rule_box.bind("<<ComboboxSelected>>", lambda _e: self._save())
        ttk.Label(line, text="→ 가득이면 매크로").pack(side="left", padx=(8, 4))
        macro_box = ttk.Combobox(
            line, textvariable=self.fmacro_var, width=30, state="readonly",
            postcommand=lambda: macro_box.configure(
                values=[m.name for m in self.engine.profile.macros]))
        macro_box.pack(side="left")
        macro_box.bind("<<ComboboxSelected>>", lambda _e: self._save())
        ttk.Label(line, text="한 번 → 다시 목장").pack(side="left", padx=(4, 0))
        line = ttk.Frame(tired)
        line.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(line, text="기준값 (앞 값이 이 수 이상이면)").pack(
            side="left", padx=(0, 4))
        ttk.Entry(line, textvariable=self.fover_var, width=10).pack(side="left")
        ttk.Label(line, style="Faint.TLabel",
                  text="   0 = 가득 찰 때").pack(side="left", padx=(0, 12))
        ttk.Button(line, text="피로도만 해보기", style="Small.TButton",
                   command=lambda: self._try("fatigue")).pack(side="left")
        ttk.Label(
            tired, style="Faint.TLabel", justify="left", wraplength=theme.px(730),
            text=("조건은 [조건] 탭의 숫자 조건입니다 (낚시에서 쓰는 '피로도 확인'과 "
                  "같은 것). [피로도만 해보기]는 읽기만 하고, 가득이면 매크로까지 "
                  "돌립니다.")
        ).grid(row=3, column=0, sticky="w", pady=(6, 0))

        # -- ④ N바퀴마다 ---------------------------------------------------
        row += 1
        every = ttk.LabelFrame(inner, text="N바퀴마다 매크로", padding=theme.pad(8))
        every.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        line = ttk.Frame(every)
        line.grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(line, text="켜기", variable=self.eon_var,
                        command=self._save).pack(side="left", padx=(0, 12))
        ttk.Label(line, text="시나리오").pack(side="left", padx=(0, 4))
        ttk.Entry(line, textvariable=self.en_var, width=6).pack(side="left")
        ttk.Label(line, text="바퀴마다 매크로").pack(side="left", padx=(4, 4))
        every_box = ttk.Combobox(
            line, textvariable=self.emacro_var, width=30, state="readonly",
            postcommand=lambda: every_box.configure(
                values=[m.name for m in self.engine.profile.macros]))
        every_box.pack(side="left")
        every_box.bind("<<ComboboxSelected>>", lambda _e: self._save())
        ttk.Label(line, text="한 번 → 다시 시나리오").pack(side="left", padx=(4, 0))
        ttk.Label(
            every, style="Faint.TLabel", justify="left", wraplength=theme.px(730),
            text=("켜 두면 시나리오를 정한 바퀴 수만큼 돌 때마다(피로도 확인 뒤) "
                  "이 매크로를 한 번 돌리고 다음 바퀴로 넘어갑니다. 끄면 안 돌립니다.")
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        # -- 실행 ----------------------------------------------------------
        row += 1
        ttk.Label(inner, textvariable=self.ready_var, style="Muted.TLabel",
                  justify="left", wraplength=theme.px(760)).grid(
            row=row, column=0, sticky="w", pady=(12, 0))
        row += 1
        runs = ttk.Frame(inner)
        runs.grid(row=row, column=0, sticky="w", pady=(10, 0))
        ttk.Button(runs, text="▶ 목장 시작", style="Accent.TButton",
                   command=self._start).pack(side="left")
        ttk.Button(runs, text="■ 정지", command=self.engine.stop_all).pack(
            side="left", padx=6)
        ttk.Button(runs, text="한 바퀴만 돌려보기", style="Small.TButton",
                   command=lambda: self._try("one")).pack(side="left", padx=(16, 4))

        for var in (self.escgap_var, self.bgap_var, self.fover_var, self.en_var):
            var.trace_add("write", lambda *_a: self._save())
        self.refresh()
        self._tick()   # 버프 남은 시간을 1초마다 새로 적는다

    # ------------------------------------------------------------------
    def _buff_row(self, parent, row: int, index: int) -> dict:
        """버프 한 줄 — 켬 · 키(고정) · 이름 · 재사용 대기 · 남은 시간 · [지금]."""
        on = tk.BooleanVar()
        name = tk.StringVar()
        period = tk.StringVar()
        left = tk.StringVar()
        key = self.engine.profile.ranch.buffs[index].key
        ttk.Checkbutton(parent, variable=on, command=self._save).grid(
            row=row, column=0, sticky="w")
        ttk.Label(parent, text=f"[{key}]").grid(
            row=row, column=1, sticky="w", padx=(0, 8))
        ttk.Entry(parent, textvariable=name, width=14).grid(
            row=row, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(parent, textvariable=period, width=8).grid(
            row=row, column=3, sticky="w", padx=(0, 8))
        ttk.Label(parent, textvariable=left, width=16).grid(
            row=row, column=4, sticky="w", padx=(0, 8))
        ttk.Button(parent, text="다음에 바로", style="Small.TButton",
                   command=lambda i=index: self._buff_now(i)).grid(
            row=row, column=5, sticky="w")
        for var in (name, period):
            var.trace_add("write", lambda *_a: self._save())
        return {"on": on, "name": name, "period": period, "left": left}

    def _buff_now(self, index: int) -> None:
        """다음 바퀴에 바로 쓰게 한다 (남은 시간 0)."""
        self.engine.profile.ranch.buffs[index].due_at = 0.0
        self.engine.save()
        self._sync_buffs()

    def _sync_buffs(self) -> None:
        import time

        now = time.time()
        self._loading = True
        for row, buff in zip(self.buff_rows, self.engine.profile.ranch.buffs):
            if row["on"].get() != buff.on:
                row["on"].set(buff.on)
            if row["name"].get() != buff.name:
                row["name"].set(buff.name)
            if get_float(row["period"], -1) != buff.period_min:
                row["period"].set(f"{buff.period_min:g}")
            row["left"].set(buff.describe(now))
        self._loading = False

    def _tick(self) -> None:
        try:
            if self.winfo_exists():
                self._sync_buffs()
        finally:
            self.after(1000, self._tick)

    # ------------------------------------------------------------------
    def _take(self) -> None:
        name = self.pick_var.get().strip()
        scenario = self.engine.find_scenario(name) if name else None
        if scenario is None:
            messagebox.showinfo("목장", "가져올 시나리오를 골라 주세요.", parent=self)
            return
        setup = self.engine.profile.ranch
        if setup.groups and not messagebox.askyesno(
                "목장", f"지금 들고 있는 '{setup.source}'을(를) "
                        f"'{scenario.name}'(으)로 바꿀까요?", parent=self):
            return
        setup.take(scenario)
        self.engine.save()
        self.engine.log(f"목장: 시나리오 '{scenario.name}'을(를) 가져왔습니다.")
        self._sync_source()

    def _adopt_defaults(self) -> None:
        """비어 있으면 알맞은 것을 채워 둔다 — 시나리오와 피로도 조건."""
        setup = self.engine.profile.ranch
        changed = False
        if not setup.groups:
            scenario = self.engine.find_scenario(DEFAULT_SCENARIO)
            if scenario is not None:
                setup.take(scenario)
                self.engine.log(f"목장: 시나리오 '{scenario.name}'을(를) "
                                "가져왔습니다.")
                changed = True
        if not setup.fatigue_rule:
            # 낚시에서 이미 쓰는 피로도 조건이 있으면 그대로 쓴다.
            rule = self.engine.profile.fishing.fatigue_rule
            if rule and self.engine.find_rule(rule) is not None:
                setup.fatigue_rule = rule
                changed = True
        if changed:
            self.engine.save()

    def _sync_source(self) -> None:
        setup = self.engine.profile.ranch
        if not setup.groups:
            self.source_var.set("아직 가져온 시나리오가 없습니다.")
        else:
            lines = [f"'{setup.source}'에서 가져옴"]
            for group in setup.groups:
                if group.conditional:
                    lines.append(f"  [{group.name}] 조건부 그룹 — 쓰지 않음")
                    continue
                times = f"{group.repeat}회" if group.repeat > 0 else "무한 → 1회"
                lines.append(f"  [{group.name}] {times} · 단계 사이 "
                             f"{group.interval_ms}ms")
                for i, step in enumerate(group.steps, start=1):
                    lines.append(f"     {i}. {step.label}")
            self.source_var.set("\n".join(lines))
            if not self.pick_var.get():
                self.pick_var.set(setup.source)
        self._sync_ready()

    def _sync_ready(self) -> None:
        setup = self.engine.profile.ranch
        problems = list(setup.problems())
        if setup.fatigue_on and setup.fatigue_rule and \
                self.engine.find_rule(setup.fatigue_rule) is None:
            problems.append(f"피로도 조건 '{setup.fatigue_rule}'이(가) 없습니다")
        if setup.fatigue_on and setup.fatigue_macro and \
                self.engine.find_macro(setup.fatigue_macro) is None:
            problems.append(f"매크로 '{setup.fatigue_macro}'이(가) 없습니다")
        if setup.every_on and setup.every_macro and \
                self.engine.find_macro(setup.every_macro) is None:
            problems.append(f"매크로 '{setup.every_macro}'이(가) 없습니다")
        if problems:
            self.ready_var.set("아직 못 정한 것: " + " · ".join(problems))
        else:
            goal = (f"앞 값이 {setup.fatigue_over:g} 이상"
                    if setup.fatigue_over > 0 else "가득")
            tired = (f"바퀴마다 '{setup.fatigue_rule}' → {goal}이면 "
                     f"'{setup.fatigue_macro}'" if setup.fatigue_on
                     else "피로도 안 봄")
            every = (f" · {setup.every_n}바퀴마다 '{setup.every_macro}'"
                     if setup.every_on else "")
            self.ready_var.set(f"준비됐습니다 — {tired}{every} · 여태 "
                               f"{setup.rounds}바퀴 · 피로도 매크로 "
                               f"{setup.fatigue_runs}번")

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._adopt_defaults()
        setup = self.engine.profile.ranch
        self._loading = True
        self.escgap_var.set(f"{setup.esc_gap_s:g}")
        self.bgap_var.set(f"{setup.buff_gap_s:g}")
        self.fon_var.set(bool(setup.fatigue_on))
        self.frule_var.set(setup.fatigue_rule)
        self.fmacro_var.set(setup.fatigue_macro)
        self.fover_var.set(f"{setup.fatigue_over:g}")
        self.eon_var.set(bool(setup.every_on))
        self.en_var.set(str(setup.every_n))
        self.emacro_var.set(setup.every_macro)
        self._loading = False
        self._sync_buffs()
        self._sync_source()

    def _save(self) -> None:
        if self._loading:
            return
        setup = self.engine.profile.ranch
        for row, buff in zip(self.buff_rows, setup.buffs):
            buff.on = bool(row["on"].get())
            buff.name = row["name"].get().strip()
            buff.period_min = max(0.0, min(10080.0, get_float(row["period"], 0)))
        setup.esc_gap_s = max(0.03, min(2.0, get_float(self.escgap_var, 0.1)))
        setup.buff_gap_s = max(0.1, min(30.0, get_float(self.bgap_var, 1.0)))
        setup.fatigue_on = bool(self.fon_var.get())
        setup.fatigue_rule = self.frule_var.get().strip()
        setup.fatigue_macro = self.fmacro_var.get().strip()
        setup.fatigue_over = max(0.0, get_float(self.fover_var, 0.0))
        setup.every_on = bool(self.eon_var.get())
        setup.every_n = max(1, min(100000, int(get_float(self.en_var, 10))))
        setup.every_macro = self.emacro_var.get().strip()
        self.engine.save()
        self._sync_ready()

    def _start(self) -> None:
        problems = self.engine.profile.ranch.problems()
        if problems:
            messagebox.showwarning(
                "목장", "먼저 정해 주세요:\n\n· " + "\n· ".join(problems),
                parent=self)
            return
        self.engine.run("ranch", "목장")

    def _try(self, what: str) -> None:
        labels = {"buffs": "목장 · 버프만", "fatigue": "목장 · 피로도만",
                  "one": "목장 · 한 바퀴만"}
        self.engine.run(f"ranch:{what}", labels[what])
