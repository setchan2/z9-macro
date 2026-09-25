"""실행 상태 창.

"내 시나리오가 실제로 어떻게 흘러가는가"를 보는 창이다. 로그는 지나간 일을
줄줄이 적지만, 여기서는 **지금 어디쯤이고 다음에 무엇이 나가는지**를 한눈에
보여준다.

그리는 쪽은 Tk 스레드뿐이다. 작업 스레드가 적어 둔 게시판(progress.Board)을
주기적으로 읽어 갈 뿐이라, 여기서 하는 일이 재생 타이밍에 영향을 주지 않는다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..progress import REGISTRY
from . import theme

# 새로고침 주기. 사람 눈에는 충분하고, 촘촘한 매크로도 흐름을 놓치지 않는다.
REFRESH_MS = 120

# 상태 줄을 보여줄 순서. 게시판에 없는 줄은 건너뛴다.
# 낚시 · 낚음 · 판 은 낚시가 채운다 (낚음은 빨간 글씨 — 무엇을 보고 낚았다고 했나).
FIELD_ORDER = ("시나리오", "그룹", "단계", "매크로", "경로", "연타", "낚시", "낚음",
               "판", "다음")

# 낚음을 알아보고 누른 입력의 글자색
CATCH_RED = "#e53935"

# 흐름 목록에 한 번에 띄울 최대 줄 수.
TRAIL_VIEW = 200


class StatusWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self.title("실행 상태")
        self.geometry(theme.scale_geometry("620x560", self))
        self.minsize(theme.px(420), theme.px(360))
        self.configure(background=theme.PALETTE["bg"])
        self.protocol("WM_DELETE_WINDOW", self.hide)

        self._selected_key = None
        # 화면에 이미 옮겨 놓은 입력이 몇 개인지. 게시판의 기록은 상한이 있어
        # 오래된 것부터 버려지므로, 목록 길이가 아니라 **누적 개수**로 센다.
        self._shown_total = 0
        self._job: str | None = None

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)

        # -- 돌고 있는 작업 -------------------------------------------------
        top = ttk.LabelFrame(frame, text="실행 중", padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.jobs = ttk.Treeview(
            top, columns=("elapsed", "sent"), show="tree headings",
            selectmode="browse", height=3,
        )
        self.jobs.heading("#0", text="작업")
        self.jobs.column("#0", width=300, stretch=True)
        self.jobs.heading("elapsed", text="경과")
        self.jobs.column("elapsed", width=80, anchor="e", stretch=False)
        self.jobs.heading("sent", text="보낸 입력")
        self.jobs.column("sent", width=90, anchor="e", stretch=False)
        self.jobs.grid(row=0, column=0, sticky="ew")
        self.jobs.bind("<<TreeviewSelect>>", self._on_pick)
        theme.stripe(self.jobs)

        # -- 지금 어디쯤 ----------------------------------------------------
        mid = ttk.LabelFrame(frame, text="진행 상황", padding=8)
        mid.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        mid.columnconfigure(1, weight=1)
        self._rows: dict[str, tuple[ttk.Label, ttk.Label]] = {}
        for row, field in enumerate(FIELD_ORDER):
            name = ttk.Label(mid, text=field, style="Faint.TLabel", width=7)
            value = ttk.Label(
                mid, text="", style="TLabel" if field == "다음" else "Muted.TLabel",
                anchor="w", justify="left",
            )
            name.grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=1)
            value.grid(row=row, column=1, sticky="ew", pady=1)
            self._rows[field] = (name, value)

        self.empty = ttk.Label(
            frame, style="Faint.TLabel",
            text="아직 실행한 것이 없습니다. 시나리오나 매크로를 실행하면 "
            "여기에 진행 상황이 나타납니다.",
        )
        self.empty.grid(row=2, column=0, sticky="w", pady=(8, 0))

        # -- 실제로 나간 입력 ------------------------------------------------
        bottom = ttk.LabelFrame(frame, text="보낸 입력 (최근 순)", padding=8)
        bottom.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(0, weight=1)
        wrap = ttk.Frame(bottom)
        wrap.grid(row=0, column=0, sticky="nsew")
        self.trail = ttk.Treeview(
            wrap, columns=("at", "what", "from"), show="headings", selectmode="none"
        )
        self.trail.heading("at", text="시각")
        self.trail.column("at", width=80, anchor="e", stretch=False)
        self.trail.heading("what", text="입력")
        self.trail.column("what", width=240, anchor="w", stretch=True)
        self.trail.heading("from", text="어디서")
        self.trail.column("from", width=150, anchor="w", stretch=False)
        self.trail.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.trail.yview)
        bar.pack(side="left", fill="y")
        self.trail.configure(yscrollcommand=bar.set)
        theme.stripe(self.trail)
        self._style_trail()

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.follow = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text="새 입력 따라가기", variable=self.follow).pack(
            side="left"
        )
        ttk.Button(actions, text="닫기", command=self.hide).pack(side="right")

        self._tick()

    def _style_trail(self) -> None:
        """드문 입력은 굵게, 낚음을 알아보고 누른 것은 빨갛게.

        줄무늬 태그보다 **나중에** 만들어야 이긴다(Treeview는 나중 태그가 우선).
        """
        base = tkfont.nametofont("TkDefaultFont")
        bold = base.copy()
        bold.configure(weight="bold")
        self._bold = bold  # 붙잡아 두지 않으면 글꼴이 사라진다
        accent = theme.PALETTE.get("accent", "#2f6fdf")
        self.trail.tag_configure("rare", font=bold, foreground=accent)
        self.trail.tag_configure("catch", font=bold, foreground=CATCH_RED)
        # 진행 상황의 '낚음' 줄도 빨갛게
        name, value = self._rows["낚음"]
        value.configure(foreground=CATCH_RED, font=bold)

    # ------------------------------------------------------------------
    def show(self) -> None:
        self.deiconify()
        self.lift()

    def hide(self) -> None:
        self.withdraw()

    def _on_pick(self, _event: object = None) -> None:
        picked = self.jobs.selection()
        key = picked[0] if picked else None
        # _draw가 자동으로 골라 준 것도 이 이벤트를 일으킨다. 그때까지 흐름을
        # 다시 그리면 이미 옮겨 놓은 줄이 통째로 한 번 더 붙는다.
        if key == self._selected_key:
            return
        self._selected_key = key
        self._reset_trail()

    def _reset_trail(self) -> None:
        self.trail.delete(*self.trail.get_children())
        self._shown_total = 0

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        try:
            self._draw()
        finally:
            self._job = self.after(REFRESH_MS, self._tick)

    def _draw(self) -> None:
        entries = REGISTRY.boards()
        entries.reverse()  # 최근 것이 위로

        ids = [str(i) for i in range(len(entries))]
        if list(self.jobs.get_children()) != ids:
            self.jobs.delete(*self.jobs.get_children())
            for i in ids:
                self.jobs.insert("", "end", iid=i, tags=(theme.row_tag(int(i)),))
            # 번호가 밀렸을 수 있으니 흐름은 처음부터 다시 옮긴다.
            self._reset_trail()

        for i, (_key, board) in enumerate(entries):
            mark = "▶" if board.running else "■"
            note = "" if board.running else f"  ({board.note})"
            self.jobs.item(
                str(i),
                text=f"{mark} {board.title}{note}",
                values=(f"{board.elapsed:.1f}초", str(board.sent_count)),
            )

        if not entries:
            self._selected_key = None
            self._show_fields({})
            self._reset_trail()
            self.empty.grid()
            return
        self.empty.grid_remove()

        # 고른 게 없으면 돌고 있는 것 중 가장 최근 것을 자동으로 따라간다.
        if self._selected_key is None or not self.jobs.exists(self._selected_key):
            pick = next(
                (str(i) for i, (_k, b) in enumerate(entries) if b.running), "0"
            )
            self._selected_key = pick
            self.jobs.selection_set(pick)

        index = int(self._selected_key)
        if not (0 <= index < len(entries)):
            return
        board = entries[index][1]
        _revision, state, trail = board.snapshot()
        self._show_fields(state)
        self._show_trail(board, trail)

    def _show_fields(self, state: dict) -> None:
        for field in FIELD_ORDER:
            name, value = self._rows[field]
            text = state.get(field, "")
            if text:
                name.grid()
                value.grid()
                if value.cget("text") != text:
                    value.configure(text=text)
            else:
                name.grid_remove()
                value.grid_remove()

    def _show_trail(self, board, trail: list) -> None:
        # 통째로 다시 그리면 촘촘한 매크로에서 화면이 깜빡인다. 늘어난 만큼만 붙인다.
        total = board.sent_count
        if total < self._shown_total:
            self._reset_trail()

        # 게시판 기록은 상한이 있어 오래된 것부터 버려진다. 목록 길이로 세면
        # 상한에 닿는 순간부터 새 입력이 영영 안 붙으므로 누적 개수로 센다.
        fresh = min(total - self._shown_total, len(trail))
        self._shown_total = total
        if fresh <= 0:
            return
        rows = trail[len(trail) - fresh :]
        for offset, row in enumerate(rows):
            at, text, tag = row[:3]
            style = row[3] if len(row) > 3 else ""
            tags = [theme.row_tag(total - fresh + offset)]
            if style in ("catch", "rare"):
                tags.append(style)   # 빨간 글씨(낚음) · 굵은 글씨(드문 입력)
            self.trail.insert(
                "", 0, values=(f"{at:.2f}s", text, tag), tags=tuple(tags),
            )

        extra = len(self.trail.get_children()) - TRAIL_VIEW
        if extra > 0:
            for iid in self.trail.get_children()[-extra:]:
                self.trail.delete(iid)
        if self.follow.get():
            children = self.trail.get_children()
            if children:
                self.trail.see(children[0])

    def destroy(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        super().destroy()
