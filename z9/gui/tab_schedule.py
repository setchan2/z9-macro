"""탭 — 시간 예약.

`조건부 실행`이 화면을 보고 반응한다면, 여기는 **시계를 보고** 실행한다.
매시 정각처럼 정해진 시각이 오면 지정한 것을 한 번 돌린다.

핵심은 "겹치지 않게"다. 돌아가는 매크로 한복판에 끼어들면 입력이 뒤섞이므로,
시각이 되어도 바로 쏘지 않고 **입력이 비는 순간**을 기다렸다가 실행한다.
"""

from __future__ import annotations

import copy
import time
import tkinter as tk
from tkinter import ttk

from ..arbiter import ARBITER
from ..model import ScheduledTask
from ..tasks import describe_schedule, next_fire_time
from .base import ListEditorTab
from .widgets import HotkeyField, get_int, int_entry

MODE_LABELS = {"hourly": "매시 정해진 분", "interval": "일정 주기마다"}
MODE_BY_LABEL = {v: k for k, v in MODE_LABELS.items()}

ACTION_LABELS = {"macro": "녹화 매크로", "path": "이동 경로", "scenario": "시나리오"}
ACTION_BY_LABEL = {v: k for k, v in ACTION_LABELS.items()}


class ScheduleTab(ListEditorTab):
    kind = "schedule"
    noun = "예약"

    # ------------------------------------------------------------------
    def items(self) -> list[ScheduledTask]:
        return self.engine.profile.schedules

    def columns(self) -> list[tuple[str, str, int]]:
        return [("name", "이름", 130), ("when", "시각", 100), ("what", "실행", 120)]

    def row_values(self, item: ScheduledTask) -> tuple:
        return (item.name, describe_schedule(item), item.action_target or "-")

    def new_item(self) -> ScheduledTask:
        return ScheduledTask(name="새 예약")

    def copy_item(self, item: ScheduledTask) -> ScheduledTask:
        return copy.deepcopy(item)

    # ------------------------------------------------------------------
    def build_form(self, parent: ttk.Frame) -> None:
        self.name_var = tk.StringVar()
        self.mode_var = tk.StringVar(value=MODE_LABELS["hourly"])
        self.minute_var = tk.StringVar(value="0")
        self.every_var = tk.StringVar(value="30")
        self.action_kind_var = tk.StringVar(value=ACTION_LABELS["macro"])
        self.action_target_var = tk.StringVar()
        self.gap_var = tk.StringVar(value="60")
        self.quiet_var = tk.StringVar(value="150")

        row = 0
        ttk.Label(parent, text="이름").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=self.name_var, width=26).grid(
            row=row, column=1, columnspan=2, sticky="w", pady=5
        )

        # -- 언제 -------------------------------------------------------
        row += 1
        when = ttk.LabelFrame(parent, text="언제", padding=10)
        when.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        mode_box = ttk.Combobox(
            when, textvariable=self.mode_var, values=list(MODE_LABELS.values()),
            width=18, state="readonly",
        )
        mode_box.grid(row=0, column=0, sticky="w")
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_mode())

        self.minute_label = ttk.Label(when, text="매시")
        self.minute_label.grid(row=0, column=1, sticky="w", padx=(14, 4))
        self.minute_entry = int_entry(when, self.minute_var, width=5)
        self.minute_entry.grid(row=0, column=2, sticky="w")
        self.minute_suffix = ttk.Label(when, text="분 (0 = 정각)")
        self.minute_suffix.grid(row=0, column=3, sticky="w", padx=(4, 0))

        self.every_label = ttk.Label(when, text="주기")
        self.every_label.grid(row=1, column=1, sticky="w", padx=(14, 4), pady=(8, 0))
        self.every_entry = int_entry(when, self.every_var, width=5)
        self.every_entry.grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.every_suffix = ttk.Label(when, text="분마다")
        self.every_suffix.grid(row=1, column=3, sticky="w", padx=(4, 0), pady=(8, 0))

        self.next_var = tk.StringVar(value="")
        ttk.Label(when, textvariable=self.next_var, style="Accent.TLabel").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(10, 0)
        )

        # -- 무엇을 -----------------------------------------------------
        row += 1
        what = ttk.LabelFrame(parent, text="무엇을", padding=10)
        what.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        ttk.Label(what, text="종류").grid(row=0, column=0, sticky="w", padx=(0, 6))
        kind_box = ttk.Combobox(
            what, textvariable=self.action_kind_var,
            values=list(ACTION_LABELS.values()), width=14, state="readonly",
        )
        kind_box.grid(row=0, column=1, sticky="w")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_targets())

        ttk.Label(what, text="대상").grid(row=0, column=2, sticky="w", padx=(14, 6))
        self.target_box = ttk.Combobox(
            what, textvariable=self.action_target_var, width=26, state="readonly"
        )
        self.target_box.grid(row=0, column=3, sticky="w")

        # -- 겹침 방지 ---------------------------------------------------
        row += 1
        safe = ttk.LabelFrame(parent, text="겹침 방지", padding=10)
        safe.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        ttk.Label(safe, text="입력이 빌 때까지 최대").grid(row=0, column=0, sticky="w")
        int_entry(safe, self.gap_var, width=6).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(safe, text="초 대기").grid(row=0, column=2, sticky="w")

        ttk.Label(safe, text="이만큼 조용하면 '비었다'").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        int_entry(safe, self.quiet_var, width=6).grid(
            row=1, column=1, sticky="w", padx=4, pady=(8, 0)
        )
        ttk.Label(safe, text="ms").grid(row=1, column=2, sticky="w", pady=(8, 0))

        ttk.Label(
            safe,
            style="Faint.TLabel",
            justify="left",
            text="시각이 되어도 다른 매크로가 입력 중이면 기다립니다. 눌려 있는 키가\n"
            "하나도 없고 지정한 시간만큼 조용해야 실행합니다. 제한 시간 안에 그런\n"
            "순간이 오지 않으면 이번 회차는 건너뜁니다 — 억지로 끼어드는 것보다\n"
            "한 번 거르는 편이 안전합니다.",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))

        # -- 핫키 -------------------------------------------------------
        row += 1
        hot = ttk.Frame(parent)
        hot.grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 0))
        ttk.Label(hot, text="감시 시작/정지 핫키").pack(side="left", padx=(0, 8))
        self.hotkey_field = HotkeyField(hot)
        self.hotkey_field.pack(side="left")

        row += 1
        self.state_var = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.state_var, style="Muted.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )

        self._sync_mode()
        self.after(1000, self._tick)

    # ------------------------------------------------------------------
    def _sync_mode(self) -> None:
        hourly = MODE_BY_LABEL.get(self.mode_var.get(), "hourly") == "hourly"
        for widget in (self.minute_label, self.minute_suffix):
            widget.configure(style="TLabel" if hourly else "Faint.TLabel")
        for widget in (self.every_label, self.every_suffix):
            widget.configure(style="Faint.TLabel" if hourly else "TLabel")
        self.minute_entry.configure(state="normal" if hourly else "disabled")
        self.every_entry.configure(state="disabled" if hourly else "normal")
        self._refresh_next()

    def _sync_targets(self) -> None:
        kind = ACTION_BY_LABEL.get(self.action_kind_var.get(), "macro")
        if kind == "macro":
            names = [m.name for m in self.engine.profile.macros]
        elif kind == "path":
            names = [p.name for p in self.engine.profile.paths]
        else:
            names = [s.name for s in self.engine.profile.scenarios]
        self.target_box.configure(values=names, state="readonly" if names else "disabled")

    def _preview(self) -> ScheduledTask:
        """지금 화면 값으로 만든 임시 예약 — 다음 실행 시각 미리보기용."""
        return ScheduledTask(
            mode=MODE_BY_LABEL.get(self.mode_var.get(), "hourly"),
            minute=min(max(get_int(self.minute_var, 0), 0), 59),
            every_minutes=max(get_int(self.every_var, 30), 1),
        )

    def _refresh_next(self) -> None:
        task = self._preview()
        target = next_fire_time(task)
        left = target - time.time()
        self.next_var.set(
            f"다음 실행: {time.strftime('%H:%M:%S', time.localtime(target))} "
            f"({left / 60:.1f}분 뒤) · {describe_schedule(task)}"
        )

    def _tick(self) -> None:
        if self.winfo_exists():
            self._refresh_next()
            item = self.selected()
            if item is not None:
                running = self.engine.is_running(self.kind, item.name)
                held = ARBITER.held
                self.state_var.set(
                    ("● 감시 중" if running else "○ 꺼짐")
                    + f" · 현재 눌려 있는 입력 {held}개"
                    + ("  (지금은 비어 있음)" if held == 0 else "  (실행 중인 동작 있음)")
                )
            self.after(1000, self._tick)

    # ------------------------------------------------------------------
    def load_form(self, item: ScheduledTask) -> None:
        self.name_var.set(item.name)
        self.mode_var.set(MODE_LABELS.get(item.mode, MODE_LABELS["hourly"]))
        self.minute_var.set(str(item.minute))
        self.every_var.set(str(item.every_minutes))
        self.action_kind_var.set(ACTION_LABELS.get(item.action_kind, ACTION_LABELS["macro"]))
        self._sync_targets()
        self.action_target_var.set(item.action_target)
        self.gap_var.set(str(item.gap_wait_s))
        self.quiet_var.set(str(item.quiet_ms))
        self.hotkey_field.set(item.hotkey)
        self._sync_mode()

    def save_form(self, item: ScheduledTask) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.mode = MODE_BY_LABEL.get(self.mode_var.get(), "hourly")
        item.minute = min(max(get_int(self.minute_var, 0), 0), 59)
        item.every_minutes = max(get_int(self.every_var, 30), 1)
        item.action_kind = ACTION_BY_LABEL.get(self.action_kind_var.get(), "macro")
        item.action_target = self.action_target_var.get().strip()
        item.gap_wait_s = max(get_int(self.gap_var, 60), 0)
        item.quiet_ms = max(get_int(self.quiet_var, 150), 0)
        if item.hotkey != self.hotkey_field.get():
            item.hotkey = self.hotkey_field.get()
            self.engine.rebind_hotkeys()
        if renamed:
            self.refresh(select_name=item.name)
