"""탭 2 — 단일 키 반복 (연타 / 홀드)."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk

from ..keys import KEY_CHOICES
from ..model import RepeatTask
from .base import ListEditorTab
from .widgets import HotkeyField, get_int, int_entry

MODE_LABELS = {"tap": "연타 (반복해서 눌렀다 뗌)", "hold": "홀드 (계속 누르고 있기)"}
MODE_BY_LABEL = {v: k for k, v in MODE_LABELS.items()}


class RepeatTab(ListEditorTab):
    kind = "repeat"
    noun = "연타"

    def items(self) -> list[RepeatTask]:
        return self.engine.profile.repeats

    def columns(self) -> list[tuple[str, str, int]]:
        return [
            ("name", "이름", 130),
            ("key", "키", 60),
            ("mode", "모드", 55),
            ("hotkey", "핫키", 100),
        ]

    def row_values(self, item: RepeatTask) -> tuple:
        mode = "연타" if item.mode == "tap" else "홀드"
        return (item.name, item.key, mode, item.hotkey or "-")

    def new_item(self) -> RepeatTask:
        return RepeatTask(name="새 연타")

    def copy_item(self, item: RepeatTask) -> RepeatTask:
        return copy.deepcopy(item)

    # ------------------------------------------------------------------
    def build_form(self, parent: ttk.Frame) -> None:
        self.name_var = tk.StringVar()
        self.key_var = tk.StringVar(value="Z")
        self.mode_var = tk.StringVar(value=MODE_LABELS["tap"])
        self.interval_var = tk.StringVar(value="100")
        self.hold_var = tk.StringVar(value="30")
        self.jitter_var = tk.StringVar(value="0")
        self.duration_var = tk.StringVar(value="0")

        row = 0
        ttk.Label(parent, text="이름").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(parent, textvariable=self.name_var, width=26).grid(
            row=row, column=1, sticky="w", pady=5
        )

        row += 1
        ttk.Label(parent, text="반복할 키").grid(row=row, column=0, sticky="w", pady=5)
        ttk.Combobox(
            parent, textvariable=self.key_var, values=KEY_CHOICES, width=12, height=20
        ).grid(row=row, column=1, sticky="w", pady=5)

        row += 1
        ttk.Label(parent, text="모드").grid(row=row, column=0, sticky="w", pady=5)
        mode_box = ttk.Combobox(
            parent,
            textvariable=self.mode_var,
            values=list(MODE_LABELS.values()),
            width=26,
            state="readonly",
        )
        mode_box.grid(row=row, column=1, sticky="w", pady=5)
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_mode())

        row += 1
        self.interval_label = ttk.Label(parent, text="누름 간격 (ms)")
        self.interval_label.grid(row=row, column=0, sticky="w", pady=5)
        self.interval_entry = int_entry(parent, self.interval_var)
        self.interval_entry.grid(row=row, column=1, sticky="w", pady=5)

        row += 1
        self.hold_label = ttk.Label(parent, text="한 번 누름 유지 (ms)")
        self.hold_label.grid(row=row, column=0, sticky="w", pady=5)
        self.hold_entry = int_entry(parent, self.hold_var)
        self.hold_entry.grid(row=row, column=1, sticky="w", pady=5)

        row += 1
        self.jitter_label = ttk.Label(parent, text="간격 편차 ± (ms)")
        self.jitter_label.grid(row=row, column=0, sticky="w", pady=5)
        self.jitter_entry = int_entry(parent, self.jitter_var)
        self.jitter_entry.grid(row=row, column=1, sticky="w", pady=5)

        row += 1
        ttk.Label(parent, text="자동 종료 (초, 0=무제한)").grid(
            row=row, column=0, sticky="w", pady=5
        )
        int_entry(parent, self.duration_var).grid(row=row, column=1, sticky="w", pady=5)

        row += 1
        ttk.Label(parent, text="토글 핫키").grid(row=row, column=0, sticky="w", pady=5)
        self.hotkey_field = HotkeyField(parent)
        self.hotkey_field.grid(row=row, column=1, sticky="w", pady=5)

        row += 1
        ttk.Label(
            parent,
            text=(
                "· 누름 간격은 '누르기 시작' 사이의 간격입니다.\n"
                "· 간격이 유지 시간보다 짧으면 자동으로 늘어납니다.\n"
                "· 홀드 모드는 정지할 때까지 키를 계속 누르고 있습니다."
            ),
            style="Muted.TLabel",
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(14, 0))

    # ------------------------------------------------------------------
    def _sync_mode(self) -> None:
        hold_mode = MODE_BY_LABEL.get(self.mode_var.get(), "tap") == "hold"
        state = "disabled" if hold_mode else "normal"
        for widget in (self.interval_entry, self.hold_entry, self.jitter_entry):
            widget.configure(state=state)
        color = "#999" if hold_mode else ""
        for label in (self.interval_label, self.hold_label, self.jitter_label):
            label.configure(foreground=color)

    def load_form(self, item: RepeatTask) -> None:
        self.name_var.set(item.name)
        self.key_var.set(item.key)
        self.mode_var.set(MODE_LABELS.get(item.mode, MODE_LABELS["tap"]))
        self.interval_var.set(str(item.interval_ms))
        self.hold_var.set(str(item.hold_ms))
        self.jitter_var.set(str(item.jitter_ms))
        self.duration_var.set(str(item.duration_s))
        self.hotkey_field.set(item.hotkey)
        self._sync_mode()

    def save_form(self, item: RepeatTask) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.key = self.key_var.get().strip() or item.key
        item.mode = MODE_BY_LABEL.get(self.mode_var.get(), "tap")
        item.interval_ms = max(get_int(self.interval_var, 100), 1)
        item.hold_ms = max(get_int(self.hold_var, 30), 0)
        item.jitter_ms = max(get_int(self.jitter_var, 0), 0)
        item.duration_s = max(get_int(self.duration_var, 0), 0)
        if item.hotkey != self.hotkey_field.get():
            item.hotkey = self.hotkey_field.get()
            self.engine.rebind_hotkeys()
        if renamed:
            self.refresh(select_name=item.name)
