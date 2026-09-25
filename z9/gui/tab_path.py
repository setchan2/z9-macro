"""탭 3 — 이동 경로 매크로 (단계 시퀀스)."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk

from ..keys import KEY_CHOICES
from ..model import PathMacro, PathStep
from .base import ListEditorTab
from .widgets import HotkeyField, capture_click_point, get_int, int_entry

STEP_LABELS = {
    "key": "키 누르고 있기",
    "click": "클릭",
    "move": "커서 이동",
    "wait": "대기",
}
STEP_BY_LABEL = {v: k for k, v in STEP_LABELS.items()}


class PathTab(ListEditorTab):
    kind = "path"
    noun = "경로"

    def items(self) -> list[PathMacro]:
        return self.engine.profile.paths

    def columns(self) -> list[tuple[str, str, int]]:
        return [("name", "이름", 150), ("steps", "단계", 50), ("hotkey", "핫키", 100)]

    def row_values(self, item: PathMacro) -> tuple:
        return (item.name, len(item.steps), item.hotkey or "-")

    def new_item(self) -> PathMacro:
        return PathMacro(name="새 경로")

    def copy_item(self, item: PathMacro) -> PathMacro:
        return copy.deepcopy(item)

    # ------------------------------------------------------------------
    def build_form(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        self.name_var = tk.StringVar()
        self.repeat_var = tk.StringVar(value="1")
        self.interval_var = tk.StringVar(value="200")
        self.scale_var = tk.BooleanVar(value=True)

        head = ttk.Frame(parent)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")

        ttk.Label(head, text="이름").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(head, textvariable=self.name_var, width=22).grid(row=0, column=1, sticky="w")
        ttk.Label(head, text="반복 (0=무한)").grid(row=0, column=2, sticky="w", padx=(16, 8))
        int_entry(head, self.repeat_var, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(head, text="반복 간 대기(ms)").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        int_entry(head, self.interval_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(head, text="핫키").grid(row=1, column=2, sticky="w", padx=(16, 8))
        self.hotkey_field = HotkeyField(head, width=13)
        self.hotkey_field.grid(row=1, column=3, sticky="w")

        ttk.Checkbutton(
            head, text="창 크기 변화 시 좌표 비례 보정", variable=self.scale_var
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # -- 단계 목록 -------------------------------------------------------
        ttk.Label(parent, text="단계").grid(row=1, column=0, columnspan=2, sticky="w", pady=(14, 4))

        wrap = ttk.Frame(parent)
        wrap.grid(row=2, column=0, columnspan=2, sticky="nsew")
        parent.rowconfigure(2, weight=1)

        self.steps_tree = ttk.Treeview(
            wrap, columns=("n", "desc"), show="headings", selectmode="browse", height=10
        )
        self.steps_tree.heading("n", text="#")
        self.steps_tree.column("n", width=36, anchor="e", stretch=False)
        self.steps_tree.heading("desc", text="동작")
        self.steps_tree.column("desc", width=320, anchor="w")
        self.steps_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.steps_tree.yview)
        bar.pack(side="left", fill="y")
        self.steps_tree.configure(yscrollcommand=bar.set)
        self.steps_tree.bind("<<TreeviewSelect>>", self._on_step_select)

        order = ttk.Frame(parent)
        order.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(order, text="▲ 위로", width=8, command=lambda: self._move(-1)).pack(side="left")
        ttk.Button(order, text="▼ 아래로", width=9, command=lambda: self._move(1)).pack(
            side="left", padx=4
        )
        ttk.Button(order, text="단계 삭제", command=self._delete_step).pack(side="left", padx=4)

        # -- 단계 편집기 ------------------------------------------------------
        editor = ttk.LabelFrame(parent, text="단계 편집", padding=8)
        editor.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        self.step_kind = tk.StringVar(value=STEP_LABELS["key"])
        self.step_key = tk.StringVar(value="Right")
        self.step_dur = tk.StringVar(value="300")
        self.step_x = tk.StringVar(value="0")
        self.step_y = tk.StringVar(value="0")
        self.step_btn = tk.StringVar(value="left")

        ttk.Label(editor, text="종류").grid(row=0, column=0, sticky="w", padx=(0, 6))
        kind_box = ttk.Combobox(
            editor,
            textvariable=self.step_kind,
            values=list(STEP_LABELS.values()),
            width=16,
            state="readonly",
        )
        kind_box.grid(row=0, column=1, sticky="w")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_step_kind())

        ttk.Label(editor, text="키").grid(row=0, column=2, sticky="w", padx=(12, 6))
        self.key_box = ttk.Combobox(
            editor, textvariable=self.step_key, values=KEY_CHOICES, width=10, height=20
        )
        self.key_box.grid(row=0, column=3, sticky="w")

        ttk.Label(editor, text="시간(ms)").grid(row=0, column=4, sticky="w", padx=(12, 6))
        self.dur_entry = int_entry(editor, self.step_dur, width=7)
        self.dur_entry.grid(row=0, column=5, sticky="w")

        ttk.Label(editor, text="X").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 6))
        self.x_entry = int_entry(editor, self.step_x, width=7)
        self.x_entry.grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(editor, text="Y").grid(row=1, column=2, sticky="w", pady=(8, 0), padx=(12, 6))
        self.y_entry = int_entry(editor, self.step_y, width=7)
        self.y_entry.grid(row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Label(editor, text="버튼").grid(row=1, column=4, sticky="w", pady=(8, 0), padx=(12, 6))
        self.btn_box = ttk.Combobox(
            editor,
            textvariable=self.step_btn,
            values=["left", "right", "middle"],
            width=8,
            state="readonly",
        )
        self.btn_box.grid(row=1, column=5, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(editor)
        buttons.grid(row=2, column=0, columnspan=6, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text="＋ 단계 추가", command=self._add_step).pack(side="left")
        ttk.Button(buttons, text="선택 단계에 적용", command=self._apply_step).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="🎯 좌표 캡처", command=self._capture_coord).pack(side="left")

        self._sync_step_kind()

    # ------------------------------------------------------------------
    def load_form(self, item: PathMacro) -> None:
        self.name_var.set(item.name)
        self.repeat_var.set(str(item.repeat))
        self.interval_var.set(str(item.interval_ms))
        self.scale_var.set(item.scale_to_window)
        self.hotkey_field.set(item.hotkey)
        self._fill_steps(item)

    def save_form(self, item: PathMacro) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.repeat = max(get_int(self.repeat_var, 1), 0)
        item.interval_ms = max(get_int(self.interval_var, 200), 0)
        item.scale_to_window = bool(self.scale_var.get())
        if item.hotkey != self.hotkey_field.get():
            item.hotkey = self.hotkey_field.get()
            self.engine.rebind_hotkeys()
        if renamed:
            self.refresh(select_name=item.name)

    def _fill_steps(self, item: PathMacro, select: int | None = None) -> None:
        self.steps_tree.delete(*self.steps_tree.get_children())
        for index, step in enumerate(item.steps):
            self.steps_tree.insert("", "end", iid=str(index), values=(index + 1, step.label()))
        if select is not None and 0 <= select < len(item.steps):
            self.steps_tree.selection_set(str(select))
            self.steps_tree.see(str(select))

    # ------------------------------------------------------------------
    def _sync_step_kind(self) -> None:
        kind = STEP_BY_LABEL.get(self.step_kind.get(), "key")
        self.key_box.configure(state="normal" if kind == "key" else "disabled")
        self.dur_entry.configure(state="normal" if kind in ("key", "wait", "click") else "disabled")
        coord_state = "normal" if kind in ("click", "move") else "disabled"
        self.x_entry.configure(state=coord_state)
        self.y_entry.configure(state=coord_state)
        self.btn_box.configure(state="readonly" if kind == "click" else "disabled")

    def _selected_step_index(self) -> int | None:
        selection = self.steps_tree.selection()
        return int(selection[0]) if selection else None

    def _on_step_select(self, _event: object = None) -> None:
        item = self.selected()
        index = self._selected_step_index()
        if item is None or index is None or index >= len(item.steps):
            return
        step = item.steps[index]
        self.step_kind.set(STEP_LABELS.get(step.kind, STEP_LABELS["key"]))
        self.step_key.set(step.key)
        self.step_dur.set(str(step.duration_ms))
        self.step_x.set(str(step.x))
        self.step_y.set(str(step.y))
        self.step_btn.set(step.button)
        self._sync_step_kind()

    def _step_from_form(self) -> PathStep:
        return PathStep(
            kind=STEP_BY_LABEL.get(self.step_kind.get(), "key"),
            key=self.step_key.get().strip() or "Right",
            duration_ms=max(get_int(self.step_dur, 300), 0),
            x=get_int(self.step_x, 0),
            y=get_int(self.step_y, 0),
            button=self.step_btn.get() or "left",
        )

    def _add_step(self) -> None:
        item = self.selected()
        if item is None:
            return
        index = self._selected_step_index()
        step = self._step_from_form()
        insert_at = len(item.steps) if index is None else index + 1
        item.steps.insert(insert_at, step)
        self._fill_steps(item, select=insert_at)
        self.refresh(select_name=item.name)

    def _apply_step(self) -> None:
        item = self.selected()
        index = self._selected_step_index()
        if item is None or index is None or index >= len(item.steps):
            return
        item.steps[index] = self._step_from_form()
        self._fill_steps(item, select=index)

    def _delete_step(self) -> None:
        item = self.selected()
        index = self._selected_step_index()
        if item is None or index is None or index >= len(item.steps):
            return
        del item.steps[index]
        self._fill_steps(item, select=min(index, len(item.steps) - 1))
        self.refresh(select_name=item.name)

    def _move(self, delta: int) -> None:
        item = self.selected()
        index = self._selected_step_index()
        if item is None or index is None:
            return
        target = index + delta
        if not (0 <= target < len(item.steps)):
            return
        item.steps[index], item.steps[target] = item.steps[target], item.steps[index]
        self._fill_steps(item, select=target)

    def _capture_coord(self) -> None:
        item = self.selected()
        if item is None:
            return
        window = self.engine.window()
        result = capture_click_point(self.winfo_toplevel(), window)
        if result is None:
            return
        cx, cy, _color = result
        self.step_x.set(str(cx))
        self.step_y.set(str(cy))
        if window is not None:
            item.client_w, item.client_h = window.client_size()
        self.engine.log(f"좌표 캡처: ({cx}, {cy})")
