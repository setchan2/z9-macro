"""[벌목] 탭 — 가르치고, 그대로 돌린다.

나무가 같은 간격으로 늘어선 벌목장이라 자리를 화면에서 알아볼 까닭이 없다.
한 번 **가르쳐 주면**(걸으며 자리마다 벌목 키) 그 시간 간격으로 돈다(z9/lumber.py).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from . import theme
from .widgets import ScrollFrame, get_float, int_entry


class LumberTab(ScrollFrame):
    def __init__(self, master: tk.Misc, engine) -> None:
        super().__init__(master)
        self.engine = engine
        inner = self.inner
        inner.columnconfigure(0, weight=1)

        self.walk_var = tk.StringVar()
        self.home_var = tk.StringVar()
        self.chop_var = tk.StringVar()
        self.teach_var = tk.BooleanVar(value=True)
        self.try_var = tk.StringVar()
        self.quiet_var = tk.StringVar()
        self.max_var = tk.StringVar()
        self.after_var = tk.StringVar()
        self.learned_var = tk.StringVar(value="")

        row = 0
        ttk.Label(inner, text="벌목", style="Title.TLabel").grid(
            row=row, column=0, sticky="w")

        row += 1
        ttk.Label(
            inner, style="Faint.TLabel", justify="left", wraplength=theme.px(760),
            text=("나무가 같은 간격으로 늘어선 벌목장용입니다. 자리를 화면에서 "
                  "알아보지 않고 걷는 시간으로 셈합니다.\n"
                  "① 가르치기 — 제가 방향키를 잡고 있겠습니다. 포탈 앞에서 시작해 "
                  "나무 자리에 닿을 때마다 벌목 키를 눌러 주세요. 누르는 동안은 "
                  "걸음을 멈추니 그 자리에서 실제로 베셔도 됩니다.\n"
                  "② 벌목 — 배운 시간만큼 걷고 멈춰서 벱니다. 데미지가 안 뜨면 "
                  "(남이 있거나 아직 안 자란 자리) 곧장 다음 자리로 갑니다."),
        ).grid(row=row, column=0, sticky="w", pady=(4, 10))

        row += 1
        keys = ttk.LabelFrame(inner, text="① 키", padding=theme.pad(8))
        keys.grid(row=row, column=0, sticky="ew")
        line = ttk.Frame(keys)
        line.pack(anchor="w")
        ttk.Label(line, text="훑어 가는 쪽").pack(side="left", padx=(0, 4))
        ttk.Entry(line, textvariable=self.walk_var, width=8).pack(side="left")
        ttk.Label(line, text="되돌아오는 쪽").pack(side="left", padx=(14, 4))
        ttk.Entry(line, textvariable=self.home_var, width=8).pack(side="left")
        ttk.Label(line, text="벌목").pack(side="left", padx=(14, 4))
        ttk.Entry(line, textvariable=self.chop_var, width=8).pack(side="left")
        ttk.Label(
            keys, style="Faint.TLabel", justify="left",
            text="포탈이 오른쪽이면 훑어 가는 쪽은 Left, 되돌아오는 쪽은 Right입니다.",
        ).pack(anchor="w", pady=(6, 0))

        row += 1
        teach = ttk.LabelFrame(inner, text="② 가르치기", padding=theme.pad(8))
        teach.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        ttk.Checkbutton(
            teach,
            text="[벌목 시작]을 누르면 가르치기로 돕니다 (자리를 다 찍었으면 끄세요)",
            variable=self.teach_var, command=self._save,
        ).pack(anchor="w")
        ttk.Label(
            teach, style="Faint.TLabel", justify="left", wraplength=theme.px(740),
            text=("포탈 앞에 서서 [벌목 시작]을 누르세요. 제가 게임 창을 앞으로 "
                  "가져오고 방향키를 잡습니다. 자리마다 벌목 키를 눌러 주시면 그 "
                  "사이 시간을 적습니다. 끝나면 [정지]를 누르세요."),
        ).pack(anchor="w", pady=(4, 0))

        row += 1
        times = ttk.LabelFrame(inner, text="③ 시간", padding=theme.pad(8))
        times.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        grid = ttk.Frame(times)
        grid.pack(anchor="w")
        self._time_row(grid, 0, "데미지를 기다리는 시간", self.try_var,
                       "이 시간 안에 데미지가 안 뜨면 그 자리는 건너뜁니다")
        self._time_row(grid, 1, "데미지가 멎었다고 볼 시간", self.quiet_var,
                       "이만큼 데미지가 안 뜨면 다 벤 것으로 봅니다")
        self._time_row(grid, 2, "한 자리 최대 시간", self.max_var,
                       "아무리 오래 걸려도 이 시간이 지나면 놓습니다")
        self._time_row(grid, 3, "벤 뒤 기다림", self.after_var,
                       "떨어진 물건이 가라앉기를 기다립니다")

        row += 1
        ttk.Label(inner, textvariable=self.learned_var, style="Muted.TLabel",
                  justify="left", wraplength=theme.px(760)).grid(
            row=row, column=0, sticky="w", pady=(12, 0))

        row += 1
        runs = ttk.Frame(inner)
        runs.grid(row=row, column=0, sticky="w", pady=(12, 0))
        ttk.Button(runs, text="▶ 벌목 시작", style="Accent.TButton",
                   command=self._start).pack(side="left")
        ttk.Button(runs, text="■ 정지", command=self.engine.stop_all).pack(
            side="left", padx=6)
        ttk.Button(runs, text="배운 것 지우기", command=self._forget).pack(
            side="left", padx=6)

        for var in (self.walk_var, self.home_var, self.chop_var, self.try_var,
                    self.quiet_var, self.max_var, self.after_var):
            var.trace_add("write", lambda *_a: self._save())
        self.refresh()

    def _time_row(self, grid, row: int, label: str, var, hint: str) -> None:
        ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", pady=2)
        int_entry(grid, var, width=6).grid(row=row, column=1, padx=(8, 4))
        ttk.Label(grid, text="초").grid(row=row, column=2, sticky="w")
        ttk.Label(grid, text=hint, style="Faint.TLabel").grid(
            row=row, column=3, sticky="w", padx=(12, 0))

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        setup = self.engine.profile.lumber
        self._loading = True
        self.walk_var.set(setup.walk_key)
        self.home_var.set(setup.home_key)
        self.chop_var.set(setup.chop_key)
        self.teach_var.set(bool(setup.teaching))
        self.try_var.set(f"{setup.try_s:g}")
        self.quiet_var.set(f"{setup.quiet_s:g}")
        self.max_var.set(f"{setup.chop_max_s:g}")
        self.after_var.set(f"{setup.after_s:g}")
        self._loading = False
        self._sync_learned()

    def _sync_learned(self) -> None:
        setup = self.engine.profile.lumber
        if not setup.taught:
            self.learned_var.set(
                "배운 것: 아직 없음 — [가르치기]를 켜고 한 바퀴 찍어 주세요.")
            return
        bits = [f"자리 {setup.spots_n}곳",
                f"첫 자리까지 {setup.first_s:g}초",
                f"자리 사이 {setup.gap_s:g}초"]
        if setup.gaps:
            bits.append(f"간격 {min(setup.gaps):g}~{max(setup.gaps):g}초")
        if setup.damage_px:
            bits.append(f"데미지 기준 {setup.damage_px}칸")
        if setup.chopped:
            bits.append(f"여태 {setup.chopped}그루")
        self.learned_var.set("배운 것: " + " · ".join(bits))

    def _save(self) -> None:
        if getattr(self, "_loading", False):
            return
        setup = self.engine.profile.lumber
        setup.walk_key = self.walk_var.get().strip() or "Left"
        setup.home_key = self.home_var.get().strip() or "Right"
        setup.chop_key = self.chop_var.get().strip() or "Ctrl"
        setup.teaching = bool(self.teach_var.get())
        setup.try_s = max(0.4, min(10.0, get_float(self.try_var, 1.6)))
        setup.quiet_s = max(0.3, min(10.0, get_float(self.quiet_var, 1.3)))
        setup.chop_max_s = max(2.0, min(60.0, get_float(self.max_var, 15.0)))
        setup.after_s = max(0.0, min(10.0, get_float(self.after_var, 1.2)))
        self.engine.save()

    def _forget(self) -> None:
        setup = self.engine.profile.lumber
        if not setup.taught:
            return
        if not messagebox.askyesno(
                "배운 것 지우기",
                f"자리 {setup.spots_n}곳과 걸음 시간을 지울까요?\n\n"
                "다시 가르치면 새로 배웁니다.", parent=self):
            return
        setup.first_s = setup.gap_s = 0.0
        setup.gaps = []
        setup.spots_n = 0
        setup.teaching = True
        self.engine.save()
        self.refresh()
        self.engine.log("벌목: 배운 자리를 지웠습니다.")

    def _start(self) -> None:
        setup = self.engine.profile.lumber
        problems = setup.problems()
        if problems:
            messagebox.showwarning(
                "벌목", "먼저 고쳐 주세요:\n\n· " + "\n· ".join(problems), parent=self)
            return
        self.engine.run("lumber", "벌목")
