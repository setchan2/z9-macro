"""대기 중 움직임 — 짧은 방향키 이동 10칸.

긴 대기에 캐릭터가 못 박힌 듯 서 있는 것을 줄이려고, 미리 녹화해 둔 짧은
이동 중 하나를 그 틈에 재생한다. 여기서는 그 10칸을 녹화하고 켜고 끈다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..engine import Engine
from ..keys import name_of
from ..moves import MAX_SECONDS, MOVE_KEYS
from . import theme
from .widgets import get_float, get_int

# 녹화가 3초를 넘기면 어차피 잘린다. 남은 시간을 세어 보여 준다.
TICK_MS = 100


class MovesTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine: Engine) -> None:
        super().__init__(parent, padding=12)
        self.engine = engine
        self.engine.ensure_moves()
        self._tick_job: str | None = None
        self._auto_stop: str | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ttk.Label(
            self,
            style="Muted.TLabel",
            justify="left",
            text=(
                "매크로 안에 긴 대기가 있으면 그 틈에 이 중 하나를 재생합니다. "
                f"방향키({' · '.join(MOVE_KEYS)})만 기록되고 {MAX_SECONDS:.0f}초에서 "
                "잘립니다.\n"
                "쓰려면 [녹화 · 재생]에서 그 매크로의 [대기 중 움직임 넣기]도 켜야 합니다."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        # -- 언제 넣을지 ----------------------------------------------------
        rule = ttk.LabelFrame(self, text="언제 넣을지", padding=10)
        rule.grid(row=1, column=0, sticky="ew")

        settings = engine.settings
        self.min_gap = tk.StringVar(value=f"{settings.move_min_gap_s:.1f}")
        self.lead = tk.StringVar(value=f"{settings.move_lead_s:.1f}")
        self.tail = tk.StringVar(value=f"{settings.move_tail_s:.1f}")
        self.chance = tk.StringVar(value=str(settings.move_chance))

        row = ttk.Frame(rule)
        row.pack(fill="x")
        for text, var, unit in (
            ("대기가 최소", self.min_gap, "초 이상일 때"),
            ("대기 시작 후", self.lead, "초는 그대로 두고"),
            ("끝나고", self.tail, "초 여유를 남긴다"),
        ):
            ttk.Label(row, text=text).pack(side="left", padx=(0, 4))
            spin = ttk.Spinbox(
                row, textvariable=var, from_=0.0, to=60.0, increment=0.1,
                format="%.1f", width=6, command=self._save_rule,
            )
            spin.pack(side="left")
            spin.bind("<KeyRelease>", lambda _e: self._save_rule())
            ttk.Label(row, text=unit, style="Faint.TLabel").pack(side="left", padx=(4, 14))

        row2 = ttk.Frame(rule)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="넣을 확률").pack(side="left", padx=(0, 4))
        chance_spin = ttk.Spinbox(
            row2, textvariable=self.chance, from_=0, to=100, increment=5,
            width=6, command=self._save_rule,
        )
        chance_spin.pack(side="left")
        chance_spin.bind("<KeyRelease>", lambda _e: self._save_rule())
        ttk.Label(
            row2, style="Faint.TLabel",
            text="%   조건을 만족해도 늘 넣지는 않습니다 — 항상 움직이면 그것대로 "
            "규칙적입니다.",
        ).pack(side="left", padx=(4, 0))

        self.rule_hint = ttk.Label(rule, style="Faint.TLabel", text="", wraplength=700)
        self.rule_hint.pack(anchor="w", pady=(8, 0))

        # -- 10칸 -----------------------------------------------------------
        box = ttk.LabelFrame(self, text="움직임 10칸", padding=8)
        box.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)

        wrap = ttk.Frame(box)
        wrap.grid(row=0, column=0, sticky="nsew")
        self.tree = ttk.Treeview(
            wrap, columns=("use", "len", "keys"), show="tree headings",
            selectmode="browse", height=10,
        )
        self.tree.heading("#0", text="이름")
        self.tree.column("#0", width=150, stretch=True)
        self.tree.heading("use", text="사용")
        self.tree.column("use", width=60, anchor="center", stretch=False)
        self.tree.heading("len", text="길이")
        self.tree.column("len", width=70, anchor="e", stretch=False)
        self.tree.heading("keys", text="내용")
        self.tree.column("keys", width=320, anchor="w", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        bar.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=bar.set)
        theme.stripe(self.tree)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_buttons())
        self.tree.bind("<space>", lambda _e: self._toggle())
        self.tree.bind("<Double-1>", lambda _e: self._toggle())

        # -- 버튼 -----------------------------------------------------------
        buttons = ttk.Frame(box)
        buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.record_button = ttk.Button(
            buttons, text="● 이 칸에 녹화", style="Accent.TButton",
            command=self._toggle_record,
        )
        self.record_button.pack(side="left")
        ttk.Button(buttons, text="사용 켜기/끄기", command=self._toggle).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="이름 바꾸기", command=self._rename).pack(side="left")
        ttk.Button(
            buttons, text="비우기", style="SmallDanger.TButton", command=self._clear
        ).pack(side="left", padx=6)
        ttk.Button(buttons, text="시험 재생", command=self._preview).pack(side="right")

        self.status = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.status, style="Faint.TLabel").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )

        self.refresh()
        self._sync_rule_hint()

    # ------------------------------------------------------------------
    def refresh(self, select_name: str | None = None) -> None:
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for index, move in enumerate(self.engine.ensure_moves()):
            keys = " ".join(
                f"{name_of(e['vk'])}{'↓' if e.get('down') else '↑'}"
                for e in move.events[:10]
            )
            if len(move.events) > 10:
                keys += " …"
            self.tree.insert(
                "", "end", iid=str(index), text=move.name,
                values=(
                    "O" if move.enabled and move.events else "",
                    f"{move.duration:.1f}초" if move.events else "비어 있음",
                    keys,
                ),
                tags=(theme.row_tag(index),),
            )
        target = keep[0] if keep and self.tree.exists(keep[0]) else "0"
        if self.tree.exists(target):
            self.tree.selection_set(target)
        self._sync_buttons()

    def _index(self) -> int | None:
        picked = self.tree.selection()
        return int(picked[0]) if picked else None

    def _sync_buttons(self) -> None:
        slot = self.engine.recording_move
        if slot is not None:
            moves = self.engine.ensure_moves()
            self.record_button.configure(text="■ 녹화 정지")
            self.status.set(f"[{moves[slot].name}] 녹화 중 — 방향키를 눌러 움직여 보세요.")
        else:
            self.record_button.configure(text="● 이 칸에 녹화")

    def _sync_rule_hint(self) -> None:
        settings = self.engine.settings
        room = settings.move_min_gap_s - settings.move_lead_s - settings.move_tail_s
        if room <= 0:
            self.rule_hint.configure(
                text="⚠ 리드인과 꼬리 여유를 합치면 최소 대기보다 길어서, "
                "어떤 움직임도 들어갈 자리가 없습니다."
            )
            return
        usable = [
            m for m in self.engine.ensure_moves()
            if m.enabled and m.events and m.duration <= room
        ]
        self.rule_hint.configure(
            text=f"{settings.move_min_gap_s:.1f}초 대기에는 "
            f"{room:.1f}초짜리까지 들어갑니다. 지금 조건에 맞는 움직임 "
            f"{len(usable)}개."
        )

    def _save_rule(self) -> None:
        settings = self.engine.settings
        settings.move_min_gap_s = max(get_float(self.min_gap, 5.0), 0.1)
        settings.move_lead_s = max(get_float(self.lead, 1.5), 0.0)
        settings.move_tail_s = max(get_float(self.tail, 0.5), 0.0)
        settings.move_chance = min(max(get_int(self.chance, 60), 0), 100)
        self._sync_rule_hint()

    # ------------------------------------------------------------------
    def _toggle_record(self) -> None:
        if self.engine.recording_move is not None:
            self._finish_record()
            return
        index = self._index()
        if index is None:
            return
        if not self.engine.start_move_recording(index):
            return
        self._sync_buttons()
        self._deadline = MAX_SECONDS
        # 3초를 넘기면 어차피 잘린다. 손으로 멈추지 않아도 알아서 끝낸다.
        self._auto_stop = self.after(int(MAX_SECONDS * 1000), self._finish_record)
        self._tick()

    def _tick(self) -> None:
        if self.engine.recording_move is None:
            return
        self._deadline = max(self._deadline - TICK_MS / 1000.0, 0.0)
        moves = self.engine.ensure_moves()
        slot = self.engine.recording_move
        self.status.set(
            f"[{moves[slot].name}] 녹화 중 — {self._deadline:.1f}초 남음 "
            f"(방향키만 기록됩니다)"
        )
        self._tick_job = self.after(TICK_MS, self._tick)

    def _finish_record(self) -> None:
        if self._auto_stop is not None:
            try:
                self.after_cancel(self._auto_stop)
            except tk.TclError:
                pass
            self._auto_stop = None
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except tk.TclError:
                pass
            self._tick_job = None
        move = self.engine.stop_move_recording()
        self.refresh()
        self._sync_rule_hint()
        if move is not None:
            self.status.set(
                f"[{move.name}] {move.duration:.1f}초 · 이벤트 {len(move.events)}개"
                if move.events
                else f"[{move.name}] 방향키 입력이 없어 비어 있습니다."
            )

    def _toggle(self) -> None:
        index = self._index()
        if index is None:
            return
        move = self.engine.ensure_moves()[index]
        if not move.events:
            self.status.set(f"[{move.name}] 비어 있습니다. 먼저 녹화하세요.")
            return
        move.enabled = not move.enabled
        self.refresh()
        self._sync_rule_hint()

    def _rename(self) -> None:
        index = self._index()
        if index is None:
            return
        move = self.engine.ensure_moves()[index]
        dialog = tk.Toplevel(self)
        dialog.title("이름 바꾸기")
        dialog.transient(self.winfo_toplevel())
        dialog.configure(background=theme.PALETTE["bg"])
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        var = tk.StringVar(value=move.name)
        ttk.Label(frame, text="이름").pack(anchor="w")
        entry = ttk.Entry(frame, textvariable=var, width=28)
        entry.pack(pady=(4, 10))
        entry.focus_set()
        entry.select_range(0, "end")

        def apply() -> None:
            move.name = var.get().strip() or move.name
            dialog.destroy()
            self.refresh()

        ttk.Button(frame, text="확인", style="Accent.TButton", command=apply).pack(
            side="left"
        )
        ttk.Button(frame, text="취소", command=dialog.destroy).pack(side="left", padx=6)
        entry.bind("<Return>", lambda _e: apply())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    def _clear(self) -> None:
        index = self._index()
        if index is None:
            return
        move = self.engine.ensure_moves()[index]
        move.events = []
        self.engine.log(f"[{move.name}] 비웠습니다.")
        self.refresh()
        self._sync_rule_hint()

    def _preview(self) -> None:
        index = self._index()
        if index is None:
            return
        move = self.engine.ensure_moves()[index]
        if not move.events:
            self.status.set(f"[{move.name}] 비어 있어 재생할 것이 없습니다.")
            return
        self.engine.run_movement(index)
