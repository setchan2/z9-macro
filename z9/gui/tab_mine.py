"""[채광] 탭 — 화면을 누르고 [Ctrl]을 꾹 누른 채 피로도가 찰 때까지 캔다.

돌아가는 차례는 z9/mine.py 에 적혀 있다. 여기서는 6 · 7 · 8번 버프(이름 ·
재사용 대기), 피로도 조건, 확인 간격을 정한다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import theme
from .widgets import ScrollFrame, get_float


class MineTab(ScrollFrame):
    INTRO = (
        "게임 창을 앞으로 세우고 화면을 한 번 누른 뒤 [Ctrl]을 꾹 누릅니다. "
        "피로도가 다 찰 때까지 그대로 캡니다.\n"
        "[Ctrl]을 누른 채로 정한 간격마다 피로도를 확인하고, 버프 재사용 대기가 "
        "끝나면 [Ctrl]을 잠깐 떼고 [Esc] → 버프 키 → [Esc] 뒤 다시 [Ctrl]을 누릅니다."
    )

    def __init__(self, master: tk.Misc, engine) -> None:
        super().__init__(master)
        self.engine = engine
        self._loading = False
        inner = self.inner
        inner.columnconfigure(0, weight=1)

        self.escgap_var = tk.StringVar()
        self.bgap_var = tk.StringVar()
        self.frule_var = tk.StringVar()
        self.fover_var = tk.StringVar()
        self.check_var = tk.StringVar()
        self.ready_var = tk.StringVar()

        row = 0
        ttk.Label(inner, text="채광", style="Title.TLabel").grid(
            row=row, column=0, sticky="w")
        row += 1
        ttk.Label(inner, style="Faint.TLabel", justify="left",
                  wraplength=theme.px(760), text=self.INTRO).grid(
            row=row, column=0, sticky="w", pady=(4, 10))

        # -- 버프 ----------------------------------------------------------
        row += 1
        buffs = ttk.LabelFrame(inner, text="버프", padding=theme.pad(8))
        buffs.grid(row=row, column=0, sticky="ew")
        ttk.Label(
            buffs, style="Faint.TLabel", justify="left", wraplength=theme.px(730),
            text=("처음 시작할 때 바로 쓰고, 그 뒤로는 재사용 대기(분)마다 씁니다. "
                  "대기가 0이면 안 씁니다. 껐다 켜도 남은 시간이 이어집니다.")
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        for col, text in enumerate(("켬", "키", "이름", "재사용 대기(분)",
                                    "다음 사용")):
            ttk.Label(buffs, text=text, style="Faint.TLabel").grid(
                row=1, column=col, sticky="w", padx=(0, 8))
        self.buff_rows = [self._buff_row(buffs, i + 2, i)
                          for i in range(len(self.engine.profile.mine.buffs))]
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

        # -- 피로도 --------------------------------------------------------
        row += 1
        tired = ttk.LabelFrame(inner, text="피로도", padding=theme.pad(8))
        tired.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        line = ttk.Frame(tired)
        line.grid(row=0, column=0, sticky="w")
        ttk.Label(line, text="피로도 조건").pack(side="left", padx=(0, 4))
        rule_box = ttk.Combobox(
            line, textvariable=self.frule_var, width=20, state="readonly",
            postcommand=lambda: rule_box.configure(
                values=[r.name for r in self.engine.profile.rules]))
        rule_box.pack(side="left")
        rule_box.bind("<<ComboboxSelected>>", lambda _e: self._save())
        ttk.Label(line, text="  [Ctrl]을 누른 채").pack(side="left", padx=(8, 4))
        ttk.Entry(line, textvariable=self.check_var, width=6).pack(side="left")
        ttk.Label(line, text="초마다 확인").pack(side="left", padx=(3, 0))
        line = ttk.Frame(tired)
        line.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(line, text="기준값 (앞 값이 이 수 이상이면)").pack(
            side="left", padx=(0, 4))
        ttk.Entry(line, textvariable=self.fover_var, width=10).pack(side="left")
        ttk.Label(line, style="Faint.TLabel",
                  text="   0 = 가득 찰 때").pack(side="left", padx=(0, 12))
        ttk.Button(line, text="피로도만 읽어보기", style="Small.TButton",
                   command=lambda: self._try("fatigue")).pack(side="left")
        ttk.Label(
            tired, style="Faint.TLabel", justify="left", wraplength=theme.px(730),
            text="피로도가 가득(또는 기준값 이상)이 되면 [Ctrl]을 떼고 멈춥니다."
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

        # -- 실행 ----------------------------------------------------------
        row += 1
        ttk.Label(inner, textvariable=self.ready_var, style="Muted.TLabel",
                  justify="left", wraplength=theme.px(760)).grid(
            row=row, column=0, sticky="w", pady=(12, 0))
        row += 1
        runs = ttk.Frame(inner)
        runs.grid(row=row, column=0, sticky="w", pady=(10, 0))
        ttk.Button(runs, text="▶ 채광 시작", style="Accent.TButton",
                   command=self._start).pack(side="left")
        ttk.Button(runs, text="■ 정지", command=self.engine.stop_all).pack(
            side="left", padx=6)

        for var in (self.escgap_var, self.bgap_var, self.fover_var,
                    self.check_var):
            var.trace_add("write", lambda *_a: self._save())
        self.refresh()
        self._tick()

    # ------------------------------------------------------------------
    def _buff_row(self, parent, row: int, index: int) -> dict:
        on = tk.BooleanVar()
        name = tk.StringVar()
        period = tk.StringVar()
        left = tk.StringVar()
        key = self.engine.profile.mine.buffs[index].key
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
        self.engine.profile.mine.buffs[index].due_at = 0.0
        self.engine.save()
        self._sync_buffs()

    def _sync_buffs(self) -> None:
        import time

        now = time.time()
        self._loading = True
        for row, buff in zip(self.buff_rows, self.engine.profile.mine.buffs):
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

    def _sync_ready(self) -> None:
        setup = self.engine.profile.mine
        problems = list(setup.problems())
        if setup.fatigue_rule and self.engine.find_rule(setup.fatigue_rule) is None:
            problems.append(f"피로도 조건 '{setup.fatigue_rule}'이(가) 없습니다")
        if problems:
            self.ready_var.set("아직 못 정한 것: " + " · ".join(problems))
            return
        goal = (f"앞 값이 {setup.fatigue_over:g} 이상"
                if setup.fatigue_over > 0 else "가득")
        spent = int(setup.mined_s)
        self.ready_var.set(
            f"준비됐습니다 — {setup.check_s:g}초마다 '{setup.fatigue_rule}' 확인, "
            f"{goal}이면 끝 · 여태 {spent // 3600}시간 {spent % 3600 // 60}분 캠")

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        setup = self.engine.profile.mine
        if not setup.fatigue_rule:
            # 낚시에서 이미 쓰는 피로도 조건이 있으면 그대로 쓴다.
            rule = self.engine.profile.fishing.fatigue_rule
            if rule and self.engine.find_rule(rule) is not None:
                setup.fatigue_rule = rule
                self.engine.save()
        self._loading = True
        self.escgap_var.set(f"{setup.esc_gap_s:g}")
        self.bgap_var.set(f"{setup.buff_gap_s:g}")
        self.frule_var.set(setup.fatigue_rule)
        self.fover_var.set(f"{setup.fatigue_over:g}")
        self.check_var.set(f"{setup.check_s:g}")
        self._loading = False
        self._sync_buffs()
        self._sync_ready()

    def _save(self) -> None:
        if self._loading:
            return
        setup = self.engine.profile.mine
        for row, buff in zip(self.buff_rows, setup.buffs):
            buff.on = bool(row["on"].get())
            buff.name = row["name"].get().strip()
            buff.period_min = max(0.0, min(10080.0, get_float(row["period"], 0)))
        setup.esc_gap_s = max(0.03, min(2.0, get_float(self.escgap_var, 0.1)))
        setup.buff_gap_s = max(0.1, min(30.0, get_float(self.bgap_var, 1.0)))
        setup.fatigue_rule = self.frule_var.get().strip()
        setup.fatigue_over = max(0.0, get_float(self.fover_var, 0.0))
        setup.check_s = max(5.0, min(3600.0, get_float(self.check_var, 60.0)))
        self.engine.save()
        self._sync_ready()

    def _start(self) -> None:
        problems = self.engine.profile.mine.problems()
        if problems:
            messagebox.showwarning(
                "채광", "먼저 정해 주세요:\n\n· " + "\n· ".join(problems),
                parent=self)
            return
        self.engine.run("mine", "채광")

    def _try(self, what: str) -> None:
        labels = {"buffs": "채광 · 버프만", "fatigue": "채광 · 피로도만"}
        self.engine.run(f"mine:{what}", labels[what])
